#!/usr/bin/env python3
"""
=============================================================================
📘 FACEBOOK CREATOR EMAIL OUTREACH SERVER & API CONTROLLER
=============================================================================
Serves the Facebook web dashboard (facebook/web/index.html) and provides REST API:
  • GET  /api/status       - Returns Facebook harvester running state, email counts, and leads list
  • GET  /api/emails       - Returns full list of scraped & real DB Facebook creator emails
  • POST /api/start        - Launches Facebook email harvester in background
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

PORT = 5001
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
                    el.sent_at
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
                email_id, email, name, platform, profile_url, is_valid, reason, log_status, sent_at = r
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
                    "dns_status": dns_str,
                    "page_url": profile_url or f"https://www.facebook.com/{uname}",
                    "location": "United States",
                    "status": status_str,
                    "sent_at": sent_at.isoformat() if sent_at else None
                }
        except Exception as ex:
            print(f"⚠️ Error querying real database: {ex}")

    # 2. Merge local Facebook lead JSON files from facebook/Data
    fb_data_dir = FACEBOOK_DIR / "Data"
    if fb_data_dir.exists():
        for fpath in fb_data_dir.glob("*.json"):
            if fpath.name.startswith("SYNTHETIC_"):
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
                                if email not in leads_dict:
                                    leads_dict[email] = {
                                        "name": item.get("name", uname),
                                        "username": uname,
                                        "email": email,
                                        "dns_status": item.get("email_dns_verified", "Valid (DNS Verified)"),
                                        "page_url": item.get("page_url") or f"https://www.facebook.com/{uname}",
                                        "location": item.get("location", "United States"),
                                        "status": item.get("status", "Verified FB Creator"),
                                        "sent_at": None
                                    }
            except Exception:
                pass

    email_list = list(leads_dict.values())
    email_list.sort(key=lambda x: (0 if x["sent_at"] else 1, x["email"]))

    sent_count = sum(1 for e in email_list if e.get("sent_at") or "Sent" in str(e.get("status")))
    dns_verified_count = sum(1 for e in email_list if "Valid" in str(e.get("dns_status")) or "Verified" in str(e.get("dns_status")))

    CACHED_FB_DATA = {
        "total_emails": len(email_list),
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
        if clean_path.endswith("/") and len(clean_path) > 1:
            clean_path = clean_path[:-1]

        print(f"DEBUG do_GET path={self.path!r} clean_path={clean_path!r}")

        is_running = FB_PROCESS is not None and FB_PROCESS.poll() is None
        if not is_running and FB_PROCESS is not None:
            FB_PROCESS = None
            FB_STATUS = "Idle"

        if clean_path == "/unsubscribe":
            qs = parse_qs(parsed.query)
            try:
                email_id = int(qs.get("email_id", [""])[0])
            except ValueError:
                email_id = None
            token = qs.get("token", [""])[0]

            if email_id is None or not verify_token(email_id, token):
                self._send_html("<p>Invalid or expired unsubscribe link.</p>", status=400)
                return

            fb_sender.unsubscribe(email_id)
            self._send_html("<p>You have been unsubscribed and will not receive further emails.</p>")
            return

        if clean_path in ("/api/send/status", "/api/facebook/send/status"):
            self._send_json({
                "running": SEND_THREAD is not None and SEND_THREAD.is_alive(),
                "statusText": SEND_STATUS,
                "lastResult": SEND_RESULT,
            })
            return

        if clean_path in ("/api/status", "/api/facebook/status"):
            fb_data = load_facebook_emails()
            self._send_json({
                "running": is_running,
                "statusText": FB_STATUS if is_running else "System Idle",
                "totalEmails": fb_data["total_emails"],
                "totalSent": fb_data["total_sent"],
                "dnsVerified": fb_data["dns_verified"]
            })
            return

        elif clean_path in ("/api/emails", "/api/facebook/emails"):
            fb_data = load_facebook_emails()
            self._send_json({
                "running": is_running,
                "statusText": FB_STATUS if is_running else "System Idle",
                "totalEmails": fb_data["total_emails"],
                "totalSent": fb_data["total_sent"],
                "dnsVerified": fb_data["dns_verified"],
                "emails": fb_data["emails"]
            })
            return

        super().do_GET()

    def do_POST(self):
        global FB_PROCESS, FB_STATUS
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        payload = {}

        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass

        if self.path in ("/api/start", "/api/facebook/start"):
            if FB_PROCESS is not None and FB_PROCESS.poll() is None:
                self._send_json({"error": "Facebook Harvester is already running"}, status=400)
                return

            req_budget = payload.get("requests", 100)
            cmd = [
                sys.executable,
                str(FACEBOOK_DIR / "src" / "run_credit_capped_harvest.py"),
                "--requests", str(req_budget),
                "--output", "facebook_100credit_email_leads"
            ]

            print(f"\n📘 [API Facebook Start] Executing Command: {' '.join(cmd)}")
            FB_PROCESS = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
            FB_STATUS = "Facebook Email Harvester Active"

            self._send_json({
                "success": True,
                "message": "Facebook Email Harvester started successfully",
                "pid": FB_PROCESS.pid
            })
            return

        elif self.path in ("/api/stop", "/api/facebook/stop"):
            if FB_PROCESS is not None:
                print("\n⏹️ [API Facebook Stop] Terminating Facebook harvester process...")
                try:
                    FB_PROCESS.terminate()
                    time.sleep(1)
                    if FB_PROCESS.poll() is None:
                        FB_PROCESS.kill()
                except Exception as ex:
                    print(f"Error terminating process: {ex}")
                FB_PROCESS = None
                FB_STATUS = "Stopped by User"

            self._send_json({"success": True, "message": "Facebook harvester stopped"})
            return

        elif self.path in ("/api/campaigns", "/api/facebook/campaigns"):
            name = payload.get("name")
            subject_template = payload.get("subject_template")
            body_template = payload.get("body_template")
            if not (name and subject_template and body_template):
                self._send_json({"error": "name, subject_template and body_template are required"}, status=400)
                return

            campaign_id = fb_sender.create_campaign(name, subject_template, body_template)
            self._send_json({"success": True, "id": campaign_id, "name": name})
            return

        elif self.path in ("/api/send/run", "/api/facebook/send/run"):
            global SEND_THREAD, SEND_STATUS, SEND_RESULT

            if SEND_THREAD is not None and SEND_THREAD.is_alive():
                self._send_json({"error": "A send is already running"}, status=400)
                return

            campaign_id = payload.get("campaign_id")
            if not campaign_id:
                self._send_json({"error": "campaign_id is required"}, status=400)
                return
            requests_limit = payload.get("limit")

            def _run():
                global SEND_STATUS, SEND_RESULT
                SEND_STATUS = "Sending"
                try:
                    SEND_RESULT = fb_sender.send_campaign(campaign_id, requests_limit)
                except Exception as ex:
                    print(f"⚠️ [Facebook Send] Error during send: {ex}")
                    SEND_RESULT = {"error": str(ex)}
                SEND_STATUS = "Idle"

            SEND_THREAD = threading.Thread(target=_run, daemon=True)
            SEND_THREAD.start()

            self._send_json({"success": True, "message": "Facebook campaign send started", "campaign_id": campaign_id})
            return

        self._send_json({"error": "Endpoint not found"}, status=404)


def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, FacebookAPIHandler)
    print("=" * 80)
    print(f"📘 FACEBOOK EMAIL OUTREACH DASHBOARD SERVER RUNNING AT: http://localhost:{PORT}")
    print("=" * 80)
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
