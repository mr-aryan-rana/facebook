#!/usr/bin/env python3
"""
Runs the Facebook live harvester for a fixed number of search requests
(credit budget) instead of a fixed lead target, and exports Name + Email
to an Excel file alongside the usual JSON/CSV.

Each call to extractor.fetch_search_results() counts as one request,
regardless of which underlying search engine served it (Serper is tried
first and is the one that consumes paid API credits; free engines are
only used as a fallback if Serper returns nothing).
"""
import sys
import time
import random
import json
import csv
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from extractor import FB_SEARCH_DORKS, FacebookExtractor

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


def save_outputs(leads, data_dir: Path, output_filename: str):
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / f"{output_filename}.json"
    csv_path = data_dir / f"{output_filename}.csv"
    xlsx_path = data_dir / f"{output_filename}.xlsx"

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

    if Workbook is not None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Leads"
        ws.append(["Name", "Email", "Facebook URL", "Location"])
        for lead in leads:
            ws.append([lead["name"], lead["email"], lead["page_url"], lead["location"]])
        for col, width in zip("ABCD", (35, 35, 55, 15)):
            ws.column_dimensions[col].width = width
        wb.save(xlsx_path)

    return json_path, csv_path, xlsx_path


def main():
    parser = argparse.ArgumentParser(description="Credit-capped Facebook email harvester")
    parser.add_argument("--requests", type=int, default=100, help="Max search requests (credit budget)")
    parser.add_argument("--output", type=str, default="facebook_100credit_email_leads", help="Output filename prefix")
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    facebook_root = src_dir.parent
    data_dir = facebook_root / "Data"

    print("=" * 80)
    print(f"FACEBOOK EMAIL HARVEST — CREDIT-CAPPED RUN ({args.requests} requests)")
    print("=" * 80)

    extractor = FacebookExtractor()

    leads = []
    seen_urls = set()
    requests_used = 0
    dork_index = 0
    page = 0

    while requests_used < args.requests:
        current_dork = FB_SEARCH_DORKS[dork_index % len(FB_SEARCH_DORKS)]

        requests_used += 1
        print(f"\n[Request {requests_used}/{args.requests}] dork='{current_dork}' page={page}")
        results = extractor.fetch_search_results(current_dork, page)
        print(f"  -> {len(results)} raw results")

        # Advance to next (dork, page) combo: cycle all 7 dorks at page N
        # before moving to page N+1, so early requests stay high-yield.
        dork_index += 1
        if dork_index % len(FB_SEARCH_DORKS) == 0:
            page += 1

        if not results:
            time.sleep(random.uniform(0.5, 1.2))
            continue

        for r in results:
            raw_url = r["url"]
            if "facebook.com" not in raw_url or "instagram.com" in raw_url:
                continue
            if any(x in raw_url.lower() for x in ["/groups/", "/events/", "/posts/", "profile.php", "/p/", "/stories/"]):
                continue

            clean_url = raw_url.split("?")[0].split("#")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            page_html = extractor.fetch_page_html(clean_url)
            if page_html is None:
                continue

            lead = extractor.extract_lead_from_snippet(clean_url, r["title_html"], r["snippet_html"], page_html=page_html)
            if lead is None:
                continue

            leads.append(lead)
            print(f"  [+] LEAD #{len(leads)}: {lead['name']} <{lead['email']}>")

            time.sleep(random.uniform(0.5, 1.2))

        time.sleep(random.uniform(0.8, 1.8))

    json_path, csv_path, xlsx_path = save_outputs(leads, data_dir, args.output)

    print("\n" + "=" * 80)
    print("HARVEST COMPLETE")
    print(f"Search requests used: {requests_used}")
    print(f"Emails collected: {len(leads)}")
    print(f"JSON:  {json_path}")
    print(f"CSV:   {csv_path}")
    print(f"Excel: {xlsx_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
