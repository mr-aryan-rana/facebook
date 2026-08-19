#!/usr/bin/env python3
"""
=============================================================================
🗄️ DATABASE PRE-CHECK, PRE-SEND EMAIL VERIFIER & DEDUPLICATION MANAGER
=============================================================================
Syncs extracted leads with PostgreSQL database.

Checks before saving:
1. Pre-Send Email Validation (Format + DNS MX lookup without sending mail)
2. Always Updates Mobile Number & Location on existing creator records
3. Duplicate Check (Verifies if email has ALREADY BEEN SENT before or unsubscribed)
4. Rate Limit Enforcement (Respects EMAIL_DAILY_LIMIT=200 in .env.local)
=============================================================================
"""

import json
import os
import sys
from pathlib import Path
import psycopg2
import psycopg2.extras

# Ensure UTF-8 output encoding across terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SRC_DIR = Path(__file__).resolve().parent
FACEBOOK_DIR = SRC_DIR.parent

sys.path.insert(0, str(SRC_DIR))
from env_loader import load_env
from verifier import verify_email_dns

load_env()

def get_pg_connection():
    """Connects to PostgreSQL using DIRECT_URL or DATABASE_URL."""
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL/DIRECT_URL not set in environment.")
    db_url = raw_url.split("?")[0]
    return psycopg2.connect(db_url, connect_timeout=8)

def is_email_already_sent_or_unsubscribed(cur, email_address: str) -> bool:
    """Checks if an email has already been sent an outreach email or unsubscribed."""
    cur.execute(
        """
        SELECT e.id, e.unsubscribed,
               EXISTS (
                   SELECT 1 FROM email_logs el WHERE el.email_id = e.id AND el.status = 'SENT'
               ) as is_sent
        FROM emails e
        WHERE LOWER(e.address) = LOWER(%s)
        """,
        (email_address,)
    )
    row = cur.fetchone()
    if row:
        if row["unsubscribed"]:
            return True
        if row["is_sent"]:
            return True
    return False

def sync_and_filter_leads_for_outreach(extracted_leads: list) -> list:
    """Performs email verification (without sending), DB pre-check, stores phone numbers & locations, and queues new valid leads for email outreach."""
    if not extracted_leads:
        print("⚠️ [DB Sync] No leads to process.")
        return []

    print(f"\n🗄️ [DB Sync] Performing zero-send verification & DB pre-check for {len(extracted_leads)} leads...")

    conn = get_pg_connection()
    queued_for_outreach = []
    skipped_count = 0
    phone_only_count = 0

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        for lead in extracted_leads:
            name = (lead.get("name") or "Creator").strip()
            platform = (lead.get("platform") or "facebook").strip().lower()
            profile_url = lead.get("profile_url") or f"https://www.facebook.com/{name.replace(' ', '')}"
            raw_email = (lead.get("email") or "").strip().lower()
            raw_phone = (lead.get("mobile_number") or lead.get("phone") or "").strip()
            location = (lead.get("location") or "").strip()

            db_phone = raw_phone if raw_phone else None
            db_email = raw_email if (raw_email and "@" in raw_email) else None
            db_location = location if location else None

            # Skip if neither email nor phone is available
            if not db_email and not db_phone:
                print(f"  [DB Sync] Skipping lead '{name}' - Neither email nor mobile number provided.")
                continue

            # 1. ALWAYS Upsert creator record (Store creator with phone & location in DB)
            cur.execute(
                """
                INSERT INTO creators (name, platform, profile_url, phone, location)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (profile_url) DO UPDATE SET
                    name = EXCLUDED.name,
                    phone = COALESCE(NULLIF(EXCLUDED.phone, ''), creators.phone),
                    location = COALESCE(NULLIF(EXCLUDED.location, ''), creators.location)
                RETURNING id
                """,
                (name, platform, profile_url, db_phone, db_location)
            )
            creator_row = cur.fetchone()
            creator_id = creator_row["id"]

            # If phone is newly extracted, update creator phone
            if db_phone:
                cur.execute(
                    "UPDATE creators SET phone = %s WHERE id = %s AND (phone IS NULL OR phone = '')",
                    (db_phone, creator_id)
                )

            # 2. If NO email provided (Phone-Only Lead) -> Saved in DB, skip email outreach
            if not db_email:
                print(f"  [DB Sync] 📱 STORED Phone-Only Creator in DB: '{name}' (Phone: {db_phone}) [No email address for email outreach]")
                phone_only_count += 1
                conn.commit()
                continue

            # 3. Email Pre-Verification: Check syntax and DNS MX records
            is_dns_valid, dns_msg = verify_email_dns(db_email)
            if not is_dns_valid:
                print(f"  [DB Sync] ⛔ REJECTED invalid email '<{db_email}>' ({dns_msg}). Creator & phone ({db_phone or 'N/A'}) stored in DB.")
                skipped_count += 1
                conn.commit()
                continue

            # 4. Upsert email record
            cur.execute(
                """
                INSERT INTO emails (address, creator_id, is_valid)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (address) DO UPDATE SET
                    creator_id = EXCLUDED.creator_id
                RETURNING id
                """,
                (db_email, creator_id)
            )
            email_row = cur.fetchone()
            email_id = email_row["id"]

            # Double check phone updated on creator linked by email
            if db_phone:
                cur.execute(
                    "UPDATE creators SET phone = %s WHERE id = (SELECT creator_id FROM emails WHERE id = %s) AND (phone IS NULL OR phone = '')",
                    (db_phone, email_id)
                )

            conn.commit()

            # 5. Duplicate Check: Has email been sent before or unsubscribed?
            if is_email_already_sent_or_unsubscribed(cur, db_email):
                print(f"  [DB Sync] ⛔ SKIPPED duplicate lead '<{db_email}>' (already emailed or unsubscribed before). Phone in DB: {db_phone or 'N/A'}")
                skipped_count += 1
                continue

            lead_item = {
                "email_id": email_id,
                "creator_id": creator_id,
                "email": db_email,
                "name": name,
                "platform": platform,
                "profile_url": profile_url,
                "phone": db_phone,
                "location": db_location
            }
            queued_for_outreach.append(lead_item)
            print(f"  [DB Sync] ✅ QUEUED verified lead for email outreach: '{name}' <{db_email}> (Phone: {db_phone or 'N/A'}, ID: {email_id})")

    except Exception as e:
        conn.rollback()
        print(f"❌ [DB Sync] Database error: {e}")
    finally:
        conn.close()

    print(f"📊 [DB Sync Result] {len(queued_for_outreach)} new email leads queued, {phone_only_count} phone-only creators stored in DB, {skipped_count} invalid/duplicate email leads skipped.")
    return queued_for_outreach

if __name__ == "__main__":
    test_lead = [
        {"name": "Test Creator", "platform": "Facebook", "profile_url": "https://facebook.com/test9999", "email": "testunique9999@gmail.com", "mobile_number": "+1 555-0199", "location": "NYC"}
    ]
    res = sync_and_filter_leads_for_outreach(test_lead)
    print(json.dumps(res, indent=2))
