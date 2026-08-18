#!/usr/bin/env python3
"""Re-verifies Facebook-sourced emails in the DB at the SMTP mailbox level
(RCPT TO probe), not just DNS/MX domain-level. DNS verification only proves
a domain accepts mail; it says nothing about whether a specific address has
an inbox. Confirmed-rejected mailboxes are downgraded to is_valid=FALSE so
the sender never targets them; inconclusive probes are left untouched
(a blocked/timed-out probe is not evidence the address is fake).

Usage: python verify_mailboxes.py [--limit N]
"""

import argparse
import os
import random
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_loader import load_env
from verifier import verify_smtp_mailbox

load_env()


def _pg_conn():
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    return psycopg2.connect(raw_url.split("?")[0], connect_timeout=8)


def verify_mailboxes(limit: int = 500) -> dict:
    conn = _pg_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT e.id, e.address
            FROM emails e
            LEFT JOIN creators c ON c.id = e.creator_id
            WHERE e.is_valid IS TRUE
              AND COALESCE(c.platform, '') ILIKE %s
              AND e.id NOT IN (SELECT email_id FROM validations WHERE smtp_check IS NOT NULL)
            ORDER BY e.id
            LIMIT %s
            """,
            ("%facebook%", limit),
        )
        targets = cur.fetchall()

        confirmed, rejected, inconclusive = 0, 0, 0
        delay_min = float(os.environ.get("SMTP_VERIFY_DELAY_MIN_SEC", "1.0"))
        delay_max = float(os.environ.get("SMTP_VERIFY_DELAY_MAX_SEC", "2.5"))

        for i, row in enumerate(targets):
            is_confirmed, reason = verify_smtp_mailbox(row["address"])

            if is_confirmed is True:
                confirmed += 1
                smtp_check_val = True
            elif is_confirmed is False:
                rejected += 1
                smtp_check_val = False
                cur.execute("UPDATE emails SET is_valid = FALSE WHERE id = %s", (row["id"],))
            else:
                inconclusive += 1
                smtp_check_val = None

            cur.execute(
                "INSERT INTO validations (email_id, smtp_check, syntax_check, reason) VALUES (%s, %s, TRUE, %s)",
                (row["id"], smtp_check_val, reason),
            )
            conn.commit()

            print(f"[{i + 1}/{len(targets)}] {row['address']} -> {is_confirmed} ({reason})")

            if i < len(targets) - 1:
                time.sleep(random.uniform(delay_min, delay_max))

        return {"checked": len(targets), "confirmed": confirmed, "rejected": rejected, "inconclusive": inconclusive}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    print(verify_mailboxes(args.limit))
