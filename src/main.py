#!/usr/bin/env python3
"""
=============================================================================
📘 PURE LIVE FACEBOOK PAGE SCRAPER & PROFILE VERIFIER
=============================================================================
Scrapes ONLY 100% REAL, LIVE, CLICKABLE Facebook Pages from search engine index.
Verifies each page URL live before saving:
  • Ensures page_url returns HTTP 200 (Active Live Page)
  • Extracts real page title, username, verified US phone (+1), and email
  • Cross-checks Instagram presence live
Outputs: facebook/Data/real_live_facebook_pages.json & .csv
=============================================================================
"""

import sys
import re
import json
import random
import time
import csv
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extractor import FB_SEARCH_DORKS, FacebookExtractor

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Number of new leads between incremental disk saves. Saving on every single
# lead rewrites the whole JSON+CSV each time (O(n^2) I/O for large targets);
# batching keeps crash-resilience while avoiding that blowup.
SAVE_INTERVAL = 5

# If this many consecutive full passes over all search dorks produce zero new
# leads, stop instead of spinning forever against a blocked/exhausted search source.
MAX_EMPTY_ROUNDS = 5


def save_leads_to_disk(leads: list, data_dir: Path, output_filename: str):
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / f"{output_filename}.json"
    csv_path = data_dir / f"{output_filename}.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2, ensure_ascii=False)

    fieldnames = [
        "username", "name", "platform", "mobile_number", "phone_verified",
        "email", "email_dns_verified", "area_code", "location", "page_url", "status"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)


def main():
    parser = argparse.ArgumentParser(description="Pure Live Facebook Page Harvester")
    parser.add_argument("--target", type=int, default=50, help="Target number of verified live Facebook Page leads")
    parser.add_argument("--output", type=str, default="pure_live_facebook_verified_leads", help="Output filename prefix")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy server URL (e.g. 'http://us-proxy-ip:port')")

    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    facebook_root = src_dir.parent
    data_dir = facebook_root / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("🚀 PURE LIVE FACEBOOK PAGE SCRAPER & LIVE URL VERIFIER")
    print("=" * 80)
    print(f"📊 Target Live Verified Leads: {args.target}")
    print(f"📁 JSON Output Path: {data_dir / f'{args.output}.json'}")
    print(f"📊 CSV Output Path:  {data_dir / f'{args.output}.csv'}")
    if args.proxy:
        print(f"🌐 Proxy Server:     {args.proxy}")
    print("-" * 80)

    extractor = FacebookExtractor(proxy_server=args.proxy)

    leads = []
    seen_urls = set()
    leads_saved = 0
    consecutive_failures = 0
    empty_rounds = 0

    dork_index = 0
    while len(leads) < args.target:
        round_start_lead_count = len(leads)
        current_dork = FB_SEARCH_DORKS[dork_index % len(FB_SEARCH_DORKS)]
        dork_index += 1

        print(f"\n🔍 [Query {dork_index}] Searching Live Web: '{current_dork}'...")

        for page in range(0, 7):
            if len(leads) >= args.target:
                break

            results = extractor.fetch_search_results(current_dork, page)
            if not results:
                consecutive_failures += 1
                backoff = min(1.5 * (2 ** min(consecutive_failures, 5)), 60)
                print(f"  ⚠️  Search request failed/rate-limited, backing off {backoff:.1f}s...")
                time.sleep(backoff + random.uniform(0.5, 2.0))
                continue
            consecutive_failures = 0

            for result in results:
                if len(leads) >= args.target:
                    break

                raw_url = result["url"]
                title_html = result["title_html"]
                snippet_html = result["snippet_html"]

                # Strict Facebook domain & non-page route check
                if "facebook.com" not in raw_url or "instagram.com" in raw_url:
                    continue
                low_raw = raw_url.lower()
                if any(x in low_raw for x in ["/groups/", "/events/", "/posts/", "profile.php", "/p/", "/stories/"]):
                    continue

                # Clean Facebook page URL
                clean_url = raw_url.split("?")[0].split("#")[0].rstrip("/")
                if clean_url in seen_urls:
                    continue

                seen_urls.add(clean_url)

                # Verify page URL is LIVE HTTP 200 (and not a login wall),
                # and keep the fetched HTML -- phone/email extraction checks
                # it first since it's the actual page content, not just the
                # search-result snippet.
                page_html = extractor.fetch_page_html(clean_url)
                if page_html is None:
                    continue

                lead = extractor.extract_lead_from_snippet(clean_url, title_html, snippet_html, page_html=page_html)
                if lead is None:
                    # No verifiable US phone found on the page — skip rather
                    # than fabricate a placeholder number.
                    continue
                lead["status"] = "Verified Real Live FB Page"

                leads.append(lead)
                if len(leads) - leads_saved >= SAVE_INTERVAL:
                    save_leads_to_disk(leads, data_dir, args.output)
                    leads_saved = len(leads)

                print(f"  ✅ VERIFIED LIVE FB PAGE [{len(leads)}/{args.target}]")
                print(f"      👉 Page Name:       {lead['name']}")
                print(f"      👤 Username:       @{lead['username']}")
                print(f"      📱 Mobile Phone:    {lead['mobile_number']} (Verified US)")
                print(f"      📧 Email:           {lead['email']} [{lead['email_dns_verified']}]")
                print(f"      🔗 Live FB URL:     {lead['page_url']}")

                # Jittered human-like pacing between per-lead live verification
                # requests (each lead triggers 2-3 live HTTP calls: FB page,
                # Instagram check). A fixed sleep is a fingerprint; random
                # pacing is not.
                time.sleep(random.uniform(0.8, 2.2))

            time.sleep(random.uniform(1.5, 3.5))

        if len(leads) == round_start_lead_count:
            empty_rounds += 1
        else:
            empty_rounds = 0

        if empty_rounds >= MAX_EMPTY_ROUNDS:
            print(f"\n⚠️  No new leads found in {MAX_EMPTY_ROUNDS} consecutive passes over all "
                  f"search dorks — stopping early with {len(leads)}/{args.target} leads.")
            break

    if len(leads) != leads_saved:
        save_leads_to_disk(leads, data_dir, args.output)

    print("\n" + "=" * 80)
    print("🎉 LIVE HARVEST COMPLETE!")
    print(f"✨ Successfully Collected: {len(leads)} 100% Live Clickable Facebook Page Leads")
    print(f"📁 JSON File: {data_dir / f'{args.output}.json'}")
    print(f"📊 CSV File:  {data_dir / f'{args.output}.csv'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
