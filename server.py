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
  • GET  /unsubscribe      - Public one-click unsubscribe link (no auth; HMAC token-verified)

Note: actual outreach sending runs out-of-band via `facebook/src/sender.py`
(invoked by the harvester pipeline / a scheduler), not through this HTTP API.
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

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", "10000"))
FACEBOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FACEBOOK_DIR.parent
WEB_DIR = FACEBOOK_DIR / "web"

PID_FILE = FACEBOOK_DIR / "Data" / "harvester.pid"
LOG_FILE = FACEBOOK_DIR / "Data" / "harvester.log"

FB_PROCESS = None
FB_STATUS = "idle"
SEND_THREAD = None
SEND_STATUS = "idle"
SEND_RESULT = None

LAST_CACHE_TIME = 0
CACHED_FB_DATA = None
CACHE_TTL_SEC = 5

def is_pid_running(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False

def get_running_pid():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if is_pid_running(pid):
                return pid
        except Exception:
            pass
    return None

def save_pid(pid: int):
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(pid))
    except Exception:
        pass

def clear_pid():
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except Exception:
            pass


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


def get_serper_used_24h(conn):
    db_count = 0
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS serper_logs (
                    id SERIAL PRIMARY KEY,
                    query VARCHAR(500),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            conn.commit()
            cur.execute("""
                SELECT COUNT(*) FROM serper_logs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            row = cur.fetchone()
            db_count = row[0] if row else 0
        except Exception:
            pass

    json_count = 0
    usage_file = FACEBOOK_DIR / "Data" / "serper_credit_usage.json"
    if usage_file.exists():
        try:
            with open(usage_file, encoding="utf-8") as f:
                stamps = json.load(f).get("timestamps", [])
                now = time.time()
                recent = [t for t in stamps if t >= (now - 86400)]
                json_count = len(recent)
        except Exception:
            pass

    return max(db_count, json_count)


def get_emails_sent_24h(conn):
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*)
                FROM email_logs
                WHERE sent_at >= NOW() - INTERVAL '24 hours'
                  AND status = 'sent'
            """)
            row = cur.fetchone()
            return row[0] if row else 0
        except Exception:
            pass
    return 0


def load_facebook_emails(force_refresh=False):
    global LAST_CACHE_TIME, CACHED_FB_DATA

    now = time.time()
    if not force_refresh and CACHED_FB_DATA and (now - LAST_CACHE_TIME < CACHE_TTL_SEC):
        return CACHED_FB_DATA

    leads_dict = {}
    total_db_sent = 0
    sent_24h = 0

    # 1. Query Real PostgreSQL Database (emails, creators, validations, email_logs)
    conn = get_postgres_conn()
    if conn:
        sent_24h = get_emails_sent_24h(conn)
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
                LEFT JOIN LATERAL (
                    SELECT status, sent_at FROM email_logs
                    WHERE email_id = e.id
                    ORDER BY sent_at DESC NULLS LAST
                    LIMIT 1
                ) el ON TRUE
                ORDER BY COALESCE(el.sent_at, e.created_at) DESC NULLS LAST, e.id DESC
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
    email_list.sort(key=lambda x: x.get("sent_at") or x.get("created_at") or "", reverse=True)

    sent_count = sum(1 for e in email_list if e.get("sent_at") or "Sent" in str(e.get("status")))
    dns_verified_count = sum(1 for e in email_list if "Valid" in str(e.get("dns_status")) or "Verified" in str(e.get("dns_status")))
    phone_count = sum(1 for e in email_list if e.get("phone") or e.get("mobile_number"))

    CACHED_FB_DATA = {
        "total_emails": len(email_list),
        "total_phones": phone_count,
        "total_sent": max(total_db_sent, sent_count),
        "emails_sent_24h": sent_24h,
        "email_daily_limit": int(os.environ.get("EMAIL_DAILY_LIMIT", "200")),
        "serper_used_24h": get_serper_used_24h(conn),
        "serper_daily_limit": int(os.environ.get("SERPER_DAILY_CREDIT_LIMIT", "60")),
        "dns_verified": dns_verified_count,
        "emails": email_list
    }
    LAST_CACHE_TIME = now
    return CACHED_FB_DATA


def get_last_log_status():
    if LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-20:]):
                line_str = line.strip()
                if line_str and not line_str.startswith("=") and not line_str.startswith("-"):
                    return line_str[:80]
        except Exception:
            pass
    return None


class FacebookAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data, status=200):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self, html, status=200):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_exception(self, exc):
        if not isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            super().log_exception(exc)

    def do_GET(self):
        global FB_PROCESS, FB_STATUS

        parsed = urlparse(self.path)
        clean_path = parsed.path

        if clean_path == "/api/status":
            running_pid = get_running_pid()
            running = (running_pid is not None) or (FB_PROCESS is not None and FB_PROCESS.poll() is None)
            data = load_facebook_emails()
            data["running"] = running
            last_log = get_last_log_status()
            data["statusText"] = last_log if (running and last_log) else (FB_STATUS if running else "System Ready")
            self._send_json(data)
            return

        if clean_path == "/api/logs":
            logs = []
            if LOG_FILE.exists():
                try:
                    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
                    logs = lines[-100:]
                except Exception:
                    pass
            self._send_json({"logs": logs})
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
            running_pid = get_running_pid()
            if (FB_PROCESS is not None and FB_PROCESS.poll() is None) or running_pid:
                self._send_json({"error": "Harvester is already running."}, 400)
                return

            budget = int(body.get("budget", 10))
            niche = body.get("niche", "Love Couple").strip()
            dry_run = body.get("dry_run", False)

            script_path = FACEBOOK_DIR / "src" / "run_pipeline.py"
            cmd = [sys.executable, str(script_path), "--niche", niche, "--limit", str(budget), "--loop", "--inspect"]
            if dry_run:
                cmd.append("--dry-run")

            FB_STATUS = f"Running Harvester for '{niche}' (Limit {budget})..."
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            log_out = open(LOG_FILE, "a", encoding="utf-8")
            FB_PROCESS = subprocess.Popen(cmd, cwd=str(FACEBOOK_DIR), stdout=log_out, stderr=log_out)
            save_pid(FB_PROCESS.pid)
            self._send_json({"message": f"Harvester launched for '{niche}'!", "budget": budget, "niche": niche})
            return

        if clean_path == "/api/stop":
            running_pid = get_running_pid()
            stopped = False
            if FB_PROCESS is not None and FB_PROCESS.poll() is None:
                FB_PROCESS.terminate()
                stopped = True
            if running_pid:
                try:
                    import signal
                    os.kill(running_pid, signal.SIGTERM)
                except Exception:
                    pass
                clear_pid()
                stopped = True

            FB_PROCESS = None
            clear_pid()
            if stopped:
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
