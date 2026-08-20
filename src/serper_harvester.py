#!/usr/bin/env python3
"""
=============================================================================
📘 SERPER LIVE HARVESTER MODULE (WITH 60 CREDITS/DAY QUOTA PROTECTION)
=============================================================================
Harvests real-time live raw web search results across Facebook, TikTok, and
Instagram using Serper Google Search API.

Enforces:
- SERPER_DAILY_CREDIT_LIMIT=60 (max 60 search API calls per rolling 24 hours)
- Explicit "+1 " US phone number signal in Google search dorks
- Exclusions against government pages (.gov, dept of) and news/media outlets.
=============================================================================
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output encoding across terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SRC_DIR = Path(__file__).resolve().parent
FACEBOOK_DIR = SRC_DIR.parent
DATA_DIR = FACEBOOK_DIR / "Data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TRACKER_FILE = DATA_DIR / "serper_credit_usage.json"

# Import env loader
sys.path.insert(0, str(SRC_DIR))
from env_loader import load_env

load_env()

SERPER_KEY = os.environ.get("SERPER_KEY", "")
SERPER_DAILY_CREDIT_LIMIT = int(os.environ.get("SERPER_DAILY_CREDIT_LIMIT", "60"))

EXCLUDED_KEYWORDS = [
    "news", "channel", "tv", "newspaper", "press", "journal", "gazette", "broadcasting",
    "herald", "tribune", "fox", "cnn", "nbc", "cbs", "abc", "msnbc", "bbc", "reuters",
    ".gov", "government", "gov", "city of ", "town of ", "police department", "fire department",
    "school district", "city hall", "embassy", "consulate", "ministry", "state of "
]

def get_db_conn():
    raw_url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if raw_url:
        try:
            import psycopg2
            return psycopg2.connect(raw_url.split("?")[0], connect_timeout=5)
        except Exception:
            pass
    return None

def init_serper_db(conn):
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
            cur.close()
        except Exception:
            pass

def load_credit_log() -> list:
    """Loads past Serper credit usage timestamps from local fallback."""
    if not TRACKER_FILE.exists():
        return []
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("timestamps", [])
    except Exception:
        return []

def save_credit_log(timestamps: list):
    """Saves updated Serper credit usage timestamps to local fallback."""
    try:
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamps": timestamps}, f, indent=2)
    except Exception:
        pass

def get_credits_used_in_24h() -> tuple:
    """Returns (count_used, valid_recent_timestamps) for rolling last 24 hours."""
    db_count = 0
    conn = get_db_conn()
    if conn:
        try:
            init_serper_db(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM serper_logs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            row = cur.fetchone()
            db_count = row[0] if row else 0
            cur.close()
            conn.close()
        except Exception:
            pass

    now = time.time()
    twenty_four_hours_ago = now - (24 * 3600)
    timestamps = load_credit_log()
    valid_stamps = [t for t in timestamps if t >= twenty_four_hours_ago]
    json_count = len(valid_stamps)

    total_used = max(db_count, json_count)
    return total_used, valid_stamps

def record_credit_used(query: str = ""):
    """Records 1 Serper credit consumption in PostgreSQL database."""
    conn = get_db_conn()
    if conn:
        try:
            init_serper_db(conn)
            cur = conn.cursor()
            cur.execute("INSERT INTO serper_logs (query) VALUES (%s)", (query[:500],))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    count, valid_stamps = get_credits_used_in_24h()
    valid_stamps.append(time.time())
    save_credit_log(valid_stamps)

def fetch_serper(query: str, num: int = 10, verbose: bool = False) -> list:
    """Fetches real-time search results via Serper API with 60 credits/day quota check."""
    used_24h, valid_stamps = get_credits_used_in_24h()
    
    if used_24h >= SERPER_DAILY_CREDIT_LIMIT:
        print(f"🛑 [Serper Quota Exceeded] Daily credit limit of {SERPER_DAILY_CREDIT_LIMIT} calls/24h reached ({used_24h} used). Halting Serper search.")
        return []

    url = "https://google.serper.dev/search"
    payload_dict = {"q": query, "num": num}
    payload = json.dumps(payload_dict).encode("utf-8")
    headers = {
        "X-API-KEY": SERPER_KEY,
        "Content-Type": "application/json"
    }

    if verbose:
        print("\n" + "=" * 80)
        print("🌐 [SERPER TEST INSPECTOR - OUTGOING REQUEST]")
        print(f"  • Target URL: {url}")
        print(f"  • Request Payload: {json.dumps(payload_dict)}")
        print("=" * 80)

    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            record_credit_used()
            new_used = used_24h + 1
            print(f"  🔒 [Serper Credit Usage] ({new_used}/{SERPER_DAILY_CREDIT_LIMIT} credits/24h used) Query: '{query}'")
            raw_body = resp.read().decode("utf-8")
            data = json.loads(raw_body)

            if verbose:
                print("\n" + "=" * 80)
                print("📥 [SERPER TEST INSPECTOR - INCOMING RESPONSE]")
                print(f"  • Status Code: {resp.status}")
                print(f"  • Organic Results Count: {len(data.get('organic', []))}")
                print(f"  • Serper Raw Response JSON:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
                print("=" * 80 + "\n")

            return data.get("organic", [])
    except Exception as e:
        print(f"Serper error for query '{query}': {e}")
        return []

def harvest_live_niche_data(niche: str = "Love Couple", max_per_platform: int = 10, verbose: bool = False) -> dict:
    """Harvests raw search results for a given niche across Facebook, TikTok, and Instagram."""
    used_24h, _ = get_credits_used_in_24h()
    print(f"\n🔍 [Serper Live Harvester] Searching live web for Niche: '{niche}'...")
    print(f"🔒 [Serper Daily Quota] {used_24h} / {SERPER_DAILY_CREDIT_LIMIT} credits consumed in last 24h.")

    if used_24h >= SERPER_DAILY_CREDIT_LIMIT:
        print(f"🛑 [Serper Quota Exceeded] Daily credit limit of {SERPER_DAILY_CREDIT_LIMIT} calls/24h reached. Serper harvesting deferred to next window.")
        return {"niche": niche, "facebook_results": [], "tiktok_results": [], "instagram_results": [], "all_results": []}

    # Build exact queries with "+1 " for each platform
    fb_query = f'site:facebook.com "{niche}" "gmail.com" OR "yahoo.com" "+1 "'
    tiktok_query = f'site:tiktok.com "{niche}" "gmail.com" OR "yahoo.com" "+1 "'
    ig_query = f'site:instagram.com "{niche}" "gmail.com" OR "yahoo.com" "+1 "'

    fb_raw = fetch_serper(fb_query, num=max_per_platform, verbose=verbose)
    tiktok_raw = fetch_serper(tiktok_query, num=max_per_platform, verbose=verbose)
    ig_raw = fetch_serper(ig_query, num=max_per_platform, verbose=verbose)

    def filter_exclusions(results, platform):
        filtered = []
        seen_links = set()
        for r in results:
            link = r.get("link", "")
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            text = (title + " " + snippet + " " + link).lower()

            if link in seen_links:
                continue
            seen_links.add(link)

            if any(k in text for k in EXCLUDED_KEYWORDS):
                continue

            filtered.append({
                "platform": platform,
                "title": title,
                "snippet": snippet,
                "link": link
            })
        return filtered

    clean_fb = filter_exclusions(fb_raw, "Facebook")
    clean_tiktok = filter_exclusions(tiktok_raw, "TikTok")
    clean_ig = filter_exclusions(ig_raw, "Instagram")

    total = len(clean_fb) + len(clean_tiktok) + len(clean_ig)
    print(f"✅ [Serper Harvester] Collected {total} live raw search items (FB: {len(clean_fb)}, TikTok: {len(clean_tiktok)}, IG: {len(clean_ig)})")

    return {
        "niche": niche,
        "facebook_results": clean_fb,
        "tiktok_results": clean_tiktok,
        "instagram_results": clean_ig,
        "all_results": clean_fb + clean_tiktok + clean_ig
    }

if __name__ == "__main__":
    data = harvest_live_niche_data("Love Couple", max_per_platform=5)
    print(json.dumps(data, indent=2, ensure_ascii=False))
