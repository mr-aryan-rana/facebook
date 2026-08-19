"""Facebook-lead email campaign sender.

Standalone port of app/services/sender.py's logic (Redis-atomic daily
quota, spintax subject/body rotation, jittered inter-send delay,
unsubscribe suppression, CAN-SPAM footer) running against the same shared
Postgres DB via raw SQL instead of the SQLAlchemy models in app/, since
this package doesn't depend on the app/ package.

Deliberately does NOT offer a 5-second send gap: a fixed few-second cadence
across many messages from one Gmail account is a spam-pattern signal (both
to Gmail's own abuse detection and to recipient spam filters), and Gmail's
sending guidelines assume much slower pacing than that. Uses
EMAIL_SEND_DELAY_MIN/MAX_SEC if set, else falls back to the DM_DELAY_MIN/MAX_SEC
already configured in .env.local (60-90s)."""

import os
import random
import re
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import redis

from env_loader import load_env
from mailer import send_email
from unsubscribe_token import generate_token

load_env()


def _pg_conn():
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL/DIRECT_URL not set")
    db_url = raw_url.split("?")[0]
    return psycopg2.connect(db_url, connect_timeout=5)


def _redis_client():
    return redis.from_url(os.environ["REDIS_URL"])


def _daily_limit() -> int:
    return int(os.environ.get("EMAIL_DAILY_LIMIT", "200"))


def _today_key() -> str:
    return f"facebook_outreach:sent_count:{datetime.now(timezone.utc):%Y%m%d}"


def _reserve_send_slot(r) -> bool:
    """Same fail-closed atomic reservation as app/services/sender.py: if
    Redis is unreachable we can't prove the quota isn't exhausted, so we
    refuse to send rather than risk exceeding EMAIL_DAILY_LIMIT."""
    key = _today_key()
    try:
        count = r.incr(key)
        if count == 1:
            r.expire(key, 93600)
    except redis.exceptions.RedisError as e:
        print(f"facebook sender: Redis unavailable, refusing to send (fail-closed): {e}")
        return False
    if count > _daily_limit():
        _release_send_slot(r)
        return False
    return True


def _release_send_slot(r) -> None:
    try:
        r.decr(_today_key())
    except redis.exceptions.RedisError:
        pass


def parse_spintax(text: str) -> str:
    """Parse spintax like {Option A|Option B|Option C} by randomly choosing one."""
    if not text:
        return text
    pattern = re.compile(r"\{([^{}]*)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        choices = match.group(1).split("|")
        text = text[: match.start()] + random.choice(choices) + text[match.end() :]
    return text


def build_footer(email_id: int) -> str:
    """Appends the sender website and a working opt-out link to every
    outgoing email. NOTE: CAN-SPAM legally requires a valid physical postal
    address in commercial email, not just a website URL -- that requirement
    doesn't go away because this field shows a URL instead. Put a real
    address or PO box in COMPANY_MAILING_ADDRESS (facebook/.env.local) to
    actually satisfy it; until then this footer is not compliant."""
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:5001")
    unsubscribe_url = f"{base_url}/unsubscribe?email_id={email_id}&token={generate_token(email_id)}"
    website = os.environ.get("COMPANY_WEBSITE_URL") or os.environ.get("COMPANY_MAILING_ADDRESS") or "https://makeable.nyc"
    return f"\n\n---\n{website}\nDon't want these emails? Unsubscribe: {unsubscribe_url}"


def _first_name(creator_name: str | None, fallback_address: str) -> str:
    raw = (creator_name or fallback_address.split("@")[0]).replace("@", "")
    parts = re.split(r"[_.\-\s]", raw)
    return parts[0].capitalize() if parts and parts[0] else "Creator"


def create_campaign(name: str, subject_template: str, body_template: str) -> int:
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO campaigns (name, subject_template, body_template)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                subject_template = EXCLUDED.subject_template,
                body_template = EXCLUDED.body_template
            RETURNING id
            """,
            (name, subject_template, body_template),
        )
        campaign_id = cur.fetchone()[0]
        conn.commit()
        return campaign_id
    finally:
        conn.close()


def send_campaign(campaign_id: int, requests_limit: int | None = None) -> dict:
    """Sends to valid, non-unsubscribed, Facebook-sourced emails not yet
    logged against this campaign, one at a time, honoring EMAIL_DAILY_LIMIT."""
    conn = _pg_conn()
    r = _redis_client()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT id, subject_template, body_template FROM campaigns WHERE id = %s", (campaign_id,))
        campaign = cur.fetchone()
        if not campaign:
            return {"error": f"campaign {campaign_id} not found"}

        # Confirmed-US location gate: requires either a specific "City, ST"
        # match (contains a comma) or the phone-area-code cross-reference
        # (contains "via phone area code") from extractor.detect_location().
        # Deliberately excludes bare "United States" -- that string is also
        # what every pre-fix scrape wrote for every single lead regardless
        # of truth, so it isn't trustworthy as a real "confirmed" signal.
        # Set REQUIRE_CONFIRMED_US_LOCATION=false in .env.local to disable.
        location_filter_sql = ""
        if os.environ.get("REQUIRE_CONFIRMED_US_LOCATION", "true").lower() != "false":
            location_filter_sql = "AND (c.location LIKE '%%,%%' OR c.location LIKE '%%via phone area code%%')"

        cur.execute(
            f"""
            SELECT e.id, e.address, c.name AS creator_name
            FROM emails e
            LEFT JOIN creators c ON e.creator_id = c.id
            WHERE e.is_valid IS TRUE
              AND e.unsubscribed IS NOT TRUE
              AND COALESCE(c.platform, '') ILIKE %s
              AND e.id NOT IN (SELECT email_id FROM email_logs WHERE campaign_id = %s)
              {location_filter_sql}
            ORDER BY e.id
            LIMIT %s
            """,
            ("%facebook%", campaign_id, requests_limit or _daily_limit()),
        )
        targets = cur.fetchall()

        delay_min = float(os.environ.get("EMAIL_SEND_DELAY_MIN_SEC", os.environ.get("DM_DELAY_MIN_SEC", "30")))
        delay_max = float(os.environ.get("EMAIL_SEND_DELAY_MAX_SEC", os.environ.get("DM_DELAY_MAX_SEC", "90")))

        sent, failed = 0, 0
        for i, row in enumerate(targets):
            if not _reserve_send_slot(r):
                print("facebook sender: daily send limit reached mid-run")
                break

            subject = parse_spintax(campaign["subject_template"])
            first_name = _first_name(row["creator_name"], row["address"])
            body = (
                parse_spintax(campaign["body_template"])
                .replace("{{email}}", row["address"])
                .replace("{{First Name}}", first_name)
            )
            body += build_footer(row["id"])

            ok, detail = send_email(row["address"], subject, body)
            if not ok:
                _release_send_slot(r)

            cur.execute(
                "INSERT INTO email_logs (email_id, campaign_id, status, sent_at) VALUES (%s, %s, %s, %s)",
                (row["id"], campaign_id, "sent" if ok else "failed", datetime.now(timezone.utc) if ok else None),
            )
            conn.commit()

            if ok:
                sent += 1
                print(f"facebook sender: sent to {row['address']}")
            else:
                failed += 1
                print(f"facebook sender: failed to send to {row['address']}: {detail}")

            if i < len(targets) - 1:
                time.sleep(random.uniform(delay_min, delay_max))

        return {"sent": sent, "failed": failed, "targeted": len(targets)}
    finally:
        conn.close()


def send_single(email_id: int, campaign_id: int) -> dict:
    """Send (or retry) one specific email against one campaign right now --
    used by the dashboard's per-row Send/Retry button."""
    conn = _pg_conn()
    r = _redis_client()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT id, subject_template, body_template FROM campaigns WHERE id = %s", (campaign_id,))
        campaign = cur.fetchone()
        cur.execute("SELECT e.id, e.address, e.unsubscribed, c.name AS creator_name FROM emails e LEFT JOIN creators c ON e.creator_id = c.id WHERE e.id = %s", (email_id,))
        email = cur.fetchone()

        if not campaign or not email:
            return {"ok": False, "detail": "email or campaign not found"}
        if email["unsubscribed"]:
            return {"ok": False, "detail": "recipient has unsubscribed"}
        if not _reserve_send_slot(r):
            return {"ok": False, "detail": "daily send limit reached"}

        subject = parse_spintax(campaign["subject_template"])
        first_name = _first_name(email["creator_name"], email["address"])
        body = (
            parse_spintax(campaign["body_template"])
            .replace("{{email}}", email["address"])
            .replace("{{First Name}}", first_name)
        )
        body += build_footer(email["id"])

        ok, detail = send_email(email["address"], subject, body)
        if not ok:
            _release_send_slot(r)

        cur.execute(
            "INSERT INTO email_logs (email_id, campaign_id, status, sent_at) VALUES (%s, %s, %s, %s)",
            (email["id"], campaign_id, "sent" if ok else "failed", datetime.now(timezone.utc) if ok else None),
        )
        conn.commit()

        return {"ok": ok, "detail": detail}
    finally:
        conn.close()


def unsubscribe(email_id: int) -> bool:
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE emails SET unsubscribed = TRUE, unsubscribed_at = %s WHERE id = %s AND unsubscribed IS NOT TRUE",
            (datetime.now(timezone.utc), email_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
