#!/usr/bin/env python3
"""Imports harvested Facebook leads from facebook/Data/*.json into the
shared Postgres DB (creators/emails tables) tagged platform='facebook', so
facebook/src/sender.py can actually find them -- the harvester only ever
wrote to local JSON/CSV files, never to the DB the sender queries.

Idempotent: safe to re-run after every harvest. Creators are upserted on
profile_url, emails on address; existing rows (including is_valid/
unsubscribed flags set later, e.g. by hand or by an unsubscribe click)
are left untouched on re-import.
"""

import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

from env_loader import load_env

FACEBOOK_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = FACEBOOK_DIR / "Data"


def _pg_conn():
    load_env()
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL/DIRECT_URL not set")
    return psycopg2.connect(raw_url.split("?")[0], connect_timeout=8)


def import_leads() -> dict:
    seen_emails = {}
    for fpath in DATA_DIR.glob("*.json"):
        if fpath.name.startswith("SYNTHETIC_"):
            # Confirmed fabricated/placeholder data (mobile_number literally
            # "Public Bio / Direct Message", dead profile URLs, includes
            # real media companies' press inboxes rather than creators) --
            # never treat these as real harvested leads. See conversation
            # from 2026-08-17 for how this was found.
            continue
        try:
            items = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            email = (item.get("email") or "").strip().lower()
            if not email or "@" not in email or "example.com" in email or "facebook.com" in email:
                continue
            uname = item.get("username") or email.split("@")[0]
            seen_emails[email] = {
                "email": email,
                "name": item.get("name") or uname,
                "profile_url": item.get("page_url") or f"https://www.facebook.com/{uname}",
                "phone": item.get("mobile_number") or None,
            }

    inserted_creators, inserted_emails = 0, 0
    conn = _pg_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for lead in seen_emails.values():
            cur.execute(
                """
                INSERT INTO creators (name, platform, profile_url, phone)
                VALUES (%s, 'facebook', %s, %s)
                ON CONFLICT (profile_url) DO UPDATE SET name = EXCLUDED.name
                RETURNING id, (xmax = 0) AS was_inserted
                """,
                (lead["name"], lead["profile_url"], lead["phone"]),
            )
            row = cur.fetchone()
            creator_id = row["id"]
            if row["was_inserted"]:
                inserted_creators += 1

            cur.execute(
                """
                INSERT INTO emails (address, creator_id, is_valid)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (address) DO NOTHING
                RETURNING id
                """,
                (lead["email"], creator_id),
            )
            if cur.fetchone() is not None:
                inserted_emails += 1

        conn.commit()
    finally:
        conn.close()

    return {
        "leads_found_in_files": len(seen_emails),
        "creators_inserted": inserted_creators,
        "emails_inserted": inserted_emails,
    }


if __name__ == "__main__":
    result = import_leads()
    print(result)
