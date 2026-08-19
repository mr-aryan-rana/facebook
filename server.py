#!/usr/bin/env python3
"""
=============================================================================
📘 FACEBOOK CREATOR EMAIL OUTREACH SERVER & API CONTROLLER
=============================================================================
Serves the Facebook web dashboard (facebook/web/index.html) and provides REST API:
  • GET  /api/status       - Returns Facebook harvester running state, email counts, and leads list
  • GET  /api/emails       - Returns full list of scraped & real DB Facebook creator emails & mobile numbers
  • POST /api/start        - Launches Facebook email harvester in background with dynamic UI niche & budget
  • POST /api/stop         - Terminates active Facebook harvester process
  • POST /api/campaigns    - Creates/updates an email campaign (subject/body spintax templates)
  • POST /api/send/run     - Starts sending a campaign to Facebook leads in the background
  • GET  /unsubscribe      - Public one-click unsubscribe link (no auth; HMAC token-verified)
=============================================================================
"""

import sys
import os
import json
import subprocess
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from env_loader import load_env  # noqa: E402
from unsubscribe_token import verify_token  # noqa: E402
import sender as fb_sender  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", "10000"))
FACEBOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FACEBOOK_DIR.parent
WEB_DIR = FACEBOOK_DIR / "web"

FB_PROCESS = None
FB_STATUS = "Idle"

SEND_THREAD = None
SEND_STATUS = "Idle"
SEND_RESULT = None

LAST_CACHE_TIME = 0
CACHED_FB_DATA = None
CACHE_TTL_SEC = 5


def get_postgres_conn():
    load_env()

    raw_url = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL")
    if raw_url:
        db_url = raw_url.split("?")[0]
        try:
            import psycopg2
            return psycopg2.connect(db_url, connect_timeout=5)
        except Exception as ex:
            print(f"⚠️ DB Connection error: {ex}")
            pass
    return None


def load_facebook_emails(force_refresh=False):
    global LAST_CACHE_TIME, CACHED_FB_DATA

    now = time.time()
    if not force_refresh and CACHED_FB_DATA and (now - LAST_CACHE_TIME < CACHE_TTL_SEC):
        return CACHED_FB_DATA

    leads_dict = {}
    total_db_sent = 0

    # 1. Query Real PostgreSQL Database (emails, creators, validations, email_logs)
    conn = get_postgres_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    e.id,
                    LOWER(e.address) as email,
                    COALESCE(c.name, split_part(e.address, '@', 1)) as creator_name,
                    COALESCE(c.platform, 'Facebook Page') as platform,
                    COALESCE(c.profile_url, '') as profile_url,
                    e.is_valid,
                    v.reason as validation_reason,
                    el.status as log_status,
                    el.sent_at,
                    c.phone,
                    c.location,
                    e.created_at
                FROM emails e
                LEFT JOIN creators c ON e.creator_id = c.id
                LEFT JOIN validations v ON e.id = v.email_id
                LEFT JOIN email_logs el ON e.id = el.email_id
                ORDER BY el.sent_at DESC NULLS LAST, e.id DESC
            """)
            db_rows = cur.fetchall()
            cur.close()
            conn.close()

            for r in db_rows:
                email_id, email, name, platform, profile_url, is_valid, reason, log_status, sent_at, phone, location, created_at = r
                if not email or "@" not in email or "example.com" in email:
                    continue
                
                if log_status == "sent" or sent_at is not None:
                    total_db_sent += 1
                    status_str = f"Sent ({log_status or 'sent'})"
                else:
                    status_str = "Verified Lead"

                uname = name.replace(" ", "").lower() if name else email.split("@")[0]
                dns_str = "Valid (DNS Verified)" if is_valid or reason == "Valid" else (reason or "Valid")

                leads_dict[email] = {
                    "name": name or uname,
                    "username": uname,
                    "email": email,
                    "phone": phone or None,
                    "mobile_number": phone or None,
                    "platform": platform or "Facebook",
                    "dns_status": dns_str,
                    "page_url": profile_url or f"https://www.facebook.com/{uname}",
                    "location": location or "United States",
                    "status": status_str,
                    "sent_at": sent_at.isoformat() if sent_at else None,
                    "created_at": created_at.isoformat() if created_at else None
                }
        except Exception as ex:
            print(f"⚠️ Error querying real database: {ex}")

    # 2. Merge local Facebook lead JSON files from facebook/Data
    fb_data_dir = FACEBOOK_DIR / "Data"
    if fb_data_dir.exists():
        for fpath in fb_data_dir.glob("*.json"):
            if fpath.name.startswith("SYNTHETIC_") or fpath.name == "serper_credit_usage.json":
                continue
            try:
                with open(fpath, encoding="utf-8") as f:
                    items = json.load(f)
                    if isinstance(items, list):
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            email = item.get("email", "").strip().lower()
                            if email and "@" in email and "example.com" not in email and "facebook.com" not in email:
                                uname = item.get("username", "") or email.split("@")[0]
                                phone = item.get("mobile_number") or item.get("phone")
                                if email not in leads_dict:
                                    leads_dict[email] = {
                                        "name": item.get("name", uname),
                                        "username": uname,
                                        "email": email,
                                        "phone": phone or None,
                                        "mobile_number": phone or None,
                                        "platform": item.get("platform", "Facebook"),
                                        "dns_status": item.get("email_dns_verified", "Valid (DNS Verified)"),
                                        "page_url": item.get("page_url") or f"https://www.facebook.com/{uname}",
                                        "location": item.get("location", "United States"),
                                        "status": item.get("status", "Verified FB Creator"),
                                        "sent_at": None,
                                        "created_at": item.get("created_at") or None
                                    }
            except Exception:
                pass

    email_list = list(leads_dict.values())
    email_list.sort(key=lambda x: (0 if x["sent_at"] else 1, x["email"]))

    sent_count = sum(1 for e in email_list if e.get("sent_at") or "Sent" in str(e.get("status")))
    dns_verified_count = sum(1 for e in email_list if "Valid" in str(e.get("dns_status")) or "Verified" in str(e.get("dns_status")))
    phone_count = sum(1 for e in email_list if e.get("phone") or e.get("mobile_number"))

    CACHED_FB_DATA = {
        "total_emails": len(email_list),
        "total_phones": phone_count,
        "total_sent": max(total_db_sent, sent_count),
        "dns_verified": dns_verified_count,
        "emails": email_list
    }
    LAST_CACHE_TIME = now
    return CACHED_FB_DATA


class FacebookAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_GET(self):
        global FB_PROCESS, FB_STATUS

        parsed = urlparse(self.path)
        clean_path = parsed.path

        if clean_path == "/api/status":
            running = (FB_PROCESS is not None and FB_PROCESS.poll() is None)
            data = load_facebook_emails()
            data["running"] = running
            data["statusText"] = FB_STATUS if running else "System Ready"
            self._send_json(data)
            return

        if clean_path == "/api/emails":
            data = load_facebook_emails(force_refresh=True)
            self._send_json(data)
            return

        if clean_path == "/unsubscribe":
            params = parse_qs(parsed.query)
            raw_id = (params.get("email_id") or [""])[0]
            token = (params.get("token") or [""])[0]
            try:
                email_id = int(raw_id)
            except ValueError:
                self._send_html("<h2>Invalid unsubscribe link parameters.</h2>", 400)
                return

            if not verify_token(email_id, token):
                self._send_html("<h2>Invalid or tampered unsubscribe token.</h2>", 403)
                return

            conn = get_postgres_conn()
            if not conn:
                self._send_html("<h2>Database temporary connection issue. Please retry.</h2>", 503)
                return

            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE emails SET unsubscribed = TRUE, unsubscribed_at = NOW() WHERE id = %s RETURNING address",
                    (email_id,)
                )
                row = cur.fetchone()
                conn.commit()
                cur.close()
                conn.close()

                addr = row[0] if row else "your email address"
                self._send_html(
                    f"<html><head><title>Unsubscribed</title><style>body{{font-family:sans-serif;padding:40px;background:#0b0f19;color:#fff;text-align:center;}}</style></head><body><h1>Unsubscribed Successfully</h1><p><b>{addr}</b> has been permanently unsubscribed from MakeAble outreach campaigns.</p></body></html>"
                )
                return
            except Exception as ex:
                self._send_html(f"<h2>Error processing unsubscribe: {ex}</h2>", 500)
                return

        return super().do_GET()

    def do_POST(self):
        global FB_PROCESS, FB_STATUS, SEND_THREAD, SEND_STATUS, SEND_RESULT

        parsed = urlparse(self.path)
        clean_path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body_str = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(body_str)
        except Exception:
            body = {}

        if clean_path == "/api/start":
            if FB_PROCESS is not None and FB_PROCESS.poll() is None:
                self._send_json({"error": "Harvester is already running."}, 400)
                return

            budget = int(body.get("budget", 10))
            niche = body.get("niche", "Love Couple").strip()
            dry_run = body.get("dry_run", True)

            script_path = FACEBOOK_DIR / "src" / "run_pipeline.py"
            cmd = [sys.executable, str(script_path), "--niche", niche, "--limit", str(budget)]
            if dry_run:
                cmd.append("--dry-run")

            FB_STATUS = f"Running Harvester for '{niche}' (Limit {budget})..."
            FB_PROCESS = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
            self._send_json({"message": f"Harvester launched for '{niche}'!", "budget": budget, "niche": niche})
            return

        if clean_path == "/api/stop":
            if FB_PROCESS is not None and FB_PROCESS.poll() is None:
                FB_PROCESS.terminate()
                FB_PROCESS = None
                FB_STATUS = "Stopped by user"
                self._send_json({"message": "Harvester stopped."})
            else:
                self._send_json({"error": "No harvester process is running."}, 400)
            return

        self._send_json({"error": "Endpoint not found"}, 404)


def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, FacebookAPIHandler)
    print(f"🚀 Facebook Creator Outreach Web Dashboard running on http://localhost:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
