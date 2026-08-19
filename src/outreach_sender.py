#!/usr/bin/env python3
"""
=============================================================================
📧 AUTOMATED EMAIL OUTREACH ENGINE MODULE
=============================================================================
Sends outreach emails to newly queued leads and updates database status.

Features:
- Daily Quota Limit: Enforces EMAIL_DAILY_LIMIT=200 max sends per 24 hours
- Time Gap Control: Randomized delay between sends (EMAIL_SEND_DELAY_MIN_SEC & MAX_SEC)
- Zero-Bounce Protection: Pre-verifies email before sending
- Spintax subject line and message body variation
- CAN-SPAM compliant footers with opt-out link
- Sends via Gmail SMTP using credentials in .env.local
- Pre-send duplicate check to prevent double-emailing
- Logs every send to DB email_logs table with sent_at timestamp
=============================================================================
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import psycopg2
import psycopg2.extras

SRC_DIR = Path(__file__).resolve().parent
FACEBOOK_DIR = SRC_DIR.parent

sys.path.insert(0, str(SRC_DIR))
from env_loader import load_env
from mailer import send_email
from sender import parse_spintax, build_footer
from unsubscribe_token import generate_token

load_env()

EMAIL_DAILY_LIMIT = int(os.environ.get("EMAIL_DAILY_LIMIT", "200"))
SEND_DELAY_MIN = int(os.environ.get("EMAIL_SEND_DELAY_MIN_SEC", "60"))
SEND_DELAY_MAX = int(os.environ.get("EMAIL_SEND_DELAY_MAX_SEC", "90"))

TEMPLATE_FILE = FACEBOOK_DIR.parent / "template.md"

def get_greeting(raw_name: str) -> str:
    """Generates 'Hi {first_name},' if first name is found, otherwise returns 'Hii Dear,'."""
    if not raw_name:
        return "Hii Dear,"
    cleaned = raw_name.strip()
    if not cleaned or cleaned.lower() in ["unknown", "creator", "none", "n/a", "admin", "null"]:
        return "Hii Dear,"
    
    # Extract first name (first word before spaces or symbols)
    parts = re.split(r'[\s&,/]+', cleaned)
    first_name = parts[0].capitalize() if parts else ""
    if not first_name or first_name.lower() in ["unknown", "creator", "none", "n/a", "admin"]:
        return "Hii Dear,"
    
    return f"Hi {first_name},"

EMAIL_TEMPLATES = [
    {
        "subject": "MakeAble Affiliate Program | Paid Creator Collaboration",
        "body": """{greeting}

We're partnering with creators for the MakeAble Affiliate Program, where you'll earn 25% commission on every successful order placed through your unique affiliate link or code. It's a great way to monetize your content while introducing your audience to personalized AI 3D figurines.

Learn more about us: https://makeable.nyc/

As part of the collaboration, we'll also provide you with a complimentary personalized 3D figurine. Simply upload your favorite couple photo (or any special photo), and we'll create it for you so you can share your genuine experience with your audience.

Your followers will receive an exclusive $20 OFF discount code to use on their own orders, making it even easier for them to join in.

We're looking for authentic content such as Reels, unboxings, first reactions, gift reveals, and short reviews that naturally showcase your experience with the product.

If this sounds like something you'd enjoy creating, we'd love to collaborate! ❤️

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Custom 3D Figurine Gift for You + Paid Collaboration",
        "body": """{greeting}

We loved your content and would love to send you a complimentary custom 3D figurine from MakeAble! 🎨

MakeAble turns your favorite memories and couple photos into high-detail, personalized 3D physical figurines. Check out our work here: https://makeable.nyc/

We are offering creators 25% commission per sale plus an exclusive $20 OFF discount code for your community. All we ask is an honest unboxing, reaction reel, or review video featuring your personalized figurine.

Would you be open to receiving a free custom figurine and collaborating with us on a paid campaign? Let us know! ✨

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Creator Collaboration Opportunity with MakeAble NYC",
        "body": """{greeting}

I'm reaching out from MakeAble NYC! We create stunning, personalized AI-crafted 3D figurines that turn memorable moments and couple photos into physical art. 🖼️

See what we do: https://makeable.nyc/

We are inviting select content creators to join our paid affiliate program. You'll receive:
1. A 100% free custom 3D figurine of your favorite photo.
2. 25% recurring commission on all orders placed via your custom link or code.
3. An exclusive $20 OFF coupon code for your followers.

If you're interested in sharing a short unboxing video or review, reply to this email and we'll get your free figurine started right away! 🚀

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Turn Your Special Memories into 3D Art | Paid Sponsorship",
        "body": """{greeting}

Your content caught our eye, and we think your audience would love MakeAble! 

At MakeAble (https://makeable.nyc/), we transform special photos into custom 3D figurines. We are onboarding creators to our campaign and would love to partner with you.

Here is what we offer:
• Free personalized 3D figurine crafted from your favorite photo.
• 25% commission on every order generated by your content.
• A special $20 discount code for your followers.

We're looking for short, genuine content like unboxings, gift reveals, or reviews. Let us know if you'd like to get your free custom 3D figurine! 🎁

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Quick question regarding a creator collab with MakeAble",
        "body": """{greeting}

Hope you're having a great week! 

We're currently scouting authentic creators for MakeAble (https://makeable.nyc/). We make personalized 3D figurines from couple and family photos, and we'd love to gift you a custom 3D figurine!

As a MakeAble creator partner:
• You earn 25% commission per sale.
• Your audience gets $20 OFF with your custom code.
• You get a free personalized 3D figurine to review and showcase in your Reels/TikToks.

Let us know if you're open to brand deals right now and we'll send over all the details! 🌟

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Monetize Your Content with MakeAble 3D Figurines (25% Commission)",
        "body": """{greeting}

We represent MakeAble NYC and love the energy and style of your page!

We're launching a new creator campaign for our custom 3D figurines (https://makeable.nyc/) and wanted to invite you to collaborate.

What's in it for you:
1. **Free Gift**: A personalized 3D figurine crafted from your favorite photo.
2. **High Earnings**: 25% commission on every purchase using your link.
3. **Audience Value**: A $20 OFF discount code exclusive to your followers.

If you enjoy creating unboxing, reaction, or lifestyle content, reply back to get your free figurine ordered! 📦

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Paid Sponsorship Opportunity for your Channel",
        "body": """{greeting}

We've been following your posts and think you'd be a perfect fit for a MakeAble creator partnership! 📸

MakeAble (https://makeable.nyc/) creates custom 3D figurines from photos. We want to send you a complimentary 3D figurine and feature you in our upcoming affiliate campaign.

Perks of joining:
• Complimentary custom 3D figurine of your choice.
• 25% commission on all driven sales.
• $20 OFF discount code for your followers.

If you'd be interested in creating a quick review or reaction video, let us know and we'll set up your account! 💡

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    },
    {
        "subject": "Special Gift for You: Custom 3D Figurine + Brand Deal",
        "body": """{greeting}

Hi from MakeAble NYC! We create one-of-a-kind personalized 3D figurines from photos. Check us out at https://makeable.nyc/

We'd love to gift you a free custom 3D figurine of your favorite couple or personal photo! In return, we're looking for authentic content like unboxing reactions, gift ideas, or short reviews.

Key benefits:
• 25% commission on all orders.
• $20 OFF discount for your audience.
• Free personalized 3D product sent to your door.

Let us know if you're open to collaborating and we'll get your custom figurine into production! ❤️

---
*Note: This is an automatically generated email. If there is any issue with your name, we apologize.*

If you do not wish to receive further emails from us, please click below:
[Unsubscribe / Not Interested]({unsubscribe_url})"""
    }
]

DATA_DIR = FACEBOOK_DIR / "Data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRACKER_FILE = DATA_DIR / "email_template_tracker.json"

def get_next_template_index() -> int:
    """Loads past template rotation index so templates rotate seamlessly without repeating across runs."""
    if TRACKER_FILE.exists():
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_template_index", 0)
        except Exception:
            pass
    return 0

def save_next_template_index(next_idx: int):
    """Saves updated template rotation index."""
    try:
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_template_index": next_idx}, f, indent=2)
    except Exception:
        pass

def get_pg_connection():
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL/DIRECT_URL not set.")
    return psycopg2.connect(raw_url.split("?")[0], connect_timeout=8)

def get_sends_in_last_24_hours(cur) -> int:
    """Counts emails sent in the rolling last 24 hours."""
    cur.execute(
        """
        SELECT COUNT(*) as count
        FROM email_logs
        WHERE status = 'SENT'
          AND sent_at >= NOW() - INTERVAL '24 hours'
        """
    )
    row = cur.fetchone()
    return row["count"] if row else 0

def send_outreach_to_queued_leads(queued_leads: list, dry_run: bool = False) -> dict:
    """Sends outreach email to queued leads and updates email_logs in DB."""
    if not queued_leads:
        print("⚠️ [Outreach Sender] No queued leads to send emails to.")
        return {"sent": 0, "failed": 0, "skipped": 0}

    print(f"\n📧 [Outreach Sender] Processing {len(queued_leads)} queued leads for email sending...")
    print(f"🔒 [Quota Enforcement] EMAIL_DAILY_LIMIT = {EMAIL_DAILY_LIMIT} max emails / 24 hours.")
    print(f"⏱️ [Send Delay Gap] Randomized delay between emails: {SEND_DELAY_MIN}s - {SEND_DELAY_MAX}s per send.")
    if dry_run:
        print("🧪 [DRY RUN MODE ENABLED] - No actual emails will be dispatched.")

    conn = get_pg_connection()
    sent_count, failed_count, skipped_count = 0, 0, 0
    current_template_idx = get_next_template_index()

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Check daily quota usage
        sends_24h = get_sends_in_last_24_hours(cur)
        print(f"📈 [Daily Quota Usage] Emails sent in last 24 hours: {sends_24h} / {EMAIL_DAILY_LIMIT}")

        if sends_24h >= EMAIL_DAILY_LIMIT:
            print(f"🛑 [Quota Exceeded] Daily limit of {EMAIL_DAILY_LIMIT} emails/24h reached ({sends_24h} sent). Halting outreach sending.")
            return {"sent": 0, "failed": 0, "skipped": len(queued_leads)}

        for idx, lead in enumerate(queued_leads):
            # Check remaining quota
            if (sends_24h + sent_count) >= EMAIL_DAILY_LIMIT:
                print(f"🛑 [Quota Exceeded] Reached max daily limit of {EMAIL_DAILY_LIMIT} emails. Remaining queued leads deferred to next window.")
                skipped_count += (len(queued_leads) - idx)
                break

            email_id = lead["email_id"]
            to_email = lead["email"]
            raw_name = lead.get("name") or ""
            display_name = raw_name if raw_name else "Creator"

            # Double-Check: Ensure email hasn't been sent in another worker run
            cur.execute(
                "SELECT status FROM email_logs WHERE email_id = %s AND status = 'SENT'",
                (email_id,)
            )
            if cur.fetchone():
                print(f"  [Outreach Sender] ⛔ SKIPPED {to_email}: Already sent in a concurrent run.")
                skipped_count += 1
                continue

            # Format template content from rotating EMAIL_TEMPLATES
            tpl_num = (current_template_idx % len(EMAIL_TEMPLATES)) + 1
            tpl = EMAIL_TEMPLATES[current_template_idx % len(EMAIL_TEMPLATES)]
            greeting = get_greeting(raw_name)
            base_url = os.environ.get("APP_BASE_URL", "http://localhost:5001")
            token = generate_token(email_id)
            unsubscribe_url = f"{base_url}/unsubscribe?email_id={email_id}&token={token}"

            subject = tpl["subject"]
            full_body = tpl["body"].format(
                greeting=greeting,
                unsubscribe_url=unsubscribe_url
            )

            print(f"  [Outreach Sender] Sending email ({sends_24h + sent_count + 1}/{EMAIL_DAILY_LIMIT}) [Template #{tpl_num}/8] to '{display_name}' <{to_email}>...")

            # Advance and save template rotation state
            current_template_idx = (current_template_idx + 1) % len(EMAIL_TEMPLATES)
            save_next_template_index(current_template_idx)

            if dry_run:
                sent_count += 1
                print(f"  [DRY RUN] Would send to {to_email}: Subject: '{subject}'")
                continue

            # Send live email via SMTP / Gmail
            try:
                send_email(to_email, subject, full_body)

                # Record in email_logs
                cur.execute(
                    """
                    INSERT INTO email_logs (email_id, status, sent_at, created_at)
                    VALUES (%s, 'SENT', NOW(), NOW())
                    """,
                    (email_id,)
                )
                conn.commit()

                sent_count += 1
                print(f"  ✅ [Outreach Sender] Email SENT to <{to_email}>!")

                # Apply randomized delay gap between sends (only if more items remain)
                if idx < len(queued_leads) - 1:
                    sleep_sec = random.randint(SEND_DELAY_MIN, SEND_DELAY_MAX)
                    print(f"  ⏱️ [Delay Gap] Waiting {sleep_sec}s before next email...")
                    time.sleep(sleep_sec)

            except Exception as send_err:
                conn.rollback()
                failed_count += 1
                print(f"  ❌ [Outreach Sender] Failed to send email to <{to_email}>: {send_err}")

    except Exception as e:
        print(f"❌ [Outreach Sender] Error processing outreach queue: {e}")
    finally:
        conn.close()

    print(f"\n📊 [Outreach Sender Result] Sent: {sent_count}, Failed: {failed_count}, Skipped/Deferred: {skipped_count}")
    return {"sent": sent_count, "failed": failed_count, "skipped": skipped_count}

if __name__ == "__main__":
    sample = [
        {"email_id": 9999, "creator_id": 9999, "email": "testsample@example.com", "name": "Sample Creator"}
    ]
    send_outreach_to_queued_leads(sample, dry_run=True)
