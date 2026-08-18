#!/usr/bin/env python3
"""
Credit-capped Facebook harvester scoped to individual content creators
(excludes media companies, production studios, news outlets, and
government pages). US location is inferred from text signals (city/state
name, state abbreviation, or "USA"/"United States" mention) rather than
requiring a verified phone number, which is optional here.
"""
import sys
import re
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

from extractor import FacebookExtractor

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

# Individual-creator niches only — deliberately excludes "Media Studio",
# "Production Studio", "News" dorks from the original FB_SEARCH_DORKS list,
# since those skew toward companies/outlets rather than individual creators.
CREATOR_DORKS = [
    'site:facebook.com "Digital Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Content Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "UGC Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Video Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Lifestyle Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Fashion Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Beauty Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Fitness Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Travel Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Food Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Comedy Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Music Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Photography Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Influencer" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Blogger" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Vlogger" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
]

US_STATE_ABBR = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    "NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
CITY_STATE_RE = re.compile(r",\s*(" + US_STATE_ABBR + r")\b")
US_TEXT_RE = re.compile(r"\b(usa|u\.s\.a\.|united states)\b", re.IGNORECASE)

NON_US_KEYWORDS = [
    "nigeria", "lagos", "ogbomoso", "kenya", "ruiru", "cape town", "mafikeng",
    "south africa", "ghana", "accra", "trinidad", "philippines", "manila",
    "india", "pakistan", "bangladesh", "indonesia", "malaysia", "vietnam",
    "united kingdom", " uk ", "london", "canada", "toronto", "ontario",
    "australia", "sydney", "brazil", "mexico", "dubai", "uae", "egypt",
]

MEDIA_GOV_EXCLUDE = [
    "media studio", "production studio", "news network", "news channel",
    ".gov", "government", "city of ", "county of ", "dept. of", "department of",
    "municipal", "police department", "fire department", "school district",
]

NON_US_LOCALE_HOSTS_OK = ("www.facebook.com", "m.facebook.com", "facebook.com")


def is_us_based(name: str, snippet: str, page_url: str) -> bool:
    text = f"{name} {snippet}".lower()
    if any(k in text for k in NON_US_KEYWORDS):
        return False
    from urllib.parse import urlparse
    host = urlparse(page_url).netloc.lower()
    if host not in NON_US_LOCALE_HOSTS_OK:
        return False
    if CITY_STATE_RE.search(name) or CITY_STATE_RE.search(snippet):
        return True
    if US_TEXT_RE.search(name) or US_TEXT_RE.search(snippet):
        return True
    return False


def is_excluded_media_or_gov(name: str, snippet: str) -> bool:
    text = f"{name} {snippet}".lower()
    return any(k in text for k in MEDIA_GOV_EXCLUDE)


def save_outputs(leads, data_dir: Path, output_filename: str):
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / f"{output_filename}.json"
    xlsx_path = data_dir / f"{output_filename}.xlsx"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2, ensure_ascii=False)

    if Workbook is not None:
        wb = Workbook()
        ws = wb.active
        ws.title = "US Creators"
        ws.append(["Name", "Email"])
        for lead in leads:
            ws.append([lead["name"], lead["email"]])
        ws.column_dimensions["A"].width = 45
        ws.column_dimensions["B"].width = 35
        wb.save(xlsx_path)

    return json_path, xlsx_path


def main():
    parser = argparse.ArgumentParser(description="US content-creator email harvester (credit-capped)")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--output", type=str, default="facebook_us_creators_batch2")
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    data_dir = src_dir.parent / "Data"

    print("=" * 80)
    print(f"US CONTENT-CREATOR EMAIL HARVEST — {args.requests} requests")
    print("=" * 80)

    extractor = FacebookExtractor()

    leads = []
    seen_usernames = set()
    seen_urls = set()
    requests_used = 0
    dork_index = 0
    page = 0

    while requests_used < args.requests:
        current_dork = CREATOR_DORKS[dork_index % len(CREATOR_DORKS)]

        requests_used += 1
        print(f"\n[Request {requests_used}/{args.requests}] dork='{current_dork}' page={page}")
        results = extractor.fetch_search_results(current_dork, page)
        print(f"  -> {len(results)} raw results")

        dork_index += 1
        if dork_index % len(CREATOR_DORKS) == 0:
            page += 1

        if not results:
            time.sleep(random.uniform(0.5, 1.2))
            continue

        for r in results:
            raw_url = r["url"]
            if "facebook.com" not in raw_url or "instagram.com" in raw_url:
                continue
            if any(x in raw_url.lower() for x in ["/groups/", "/events/", "profile.php", "/p/", "/stories/"]):
                continue

            clean_url = raw_url.split("?")[0].split("#")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            name_guess = r["title_html"]
            snippet = r["snippet_html"]

            if is_excluded_media_or_gov(name_guess, snippet):
                continue
            if not is_us_based(name_guess, snippet, clean_url):
                continue

            page_html = extractor.fetch_page_html(clean_url)
            if page_html is None:
                continue

            lead = extractor.extract_lead_from_snippet(clean_url, r["title_html"], r["snippet_html"], page_html=page_html)
            if lead is None:
                continue
            if is_excluded_media_or_gov(lead["name"], snippet):
                continue

            uname = lead["username"].lower()
            if uname in seen_usernames:
                continue
            seen_usernames.add(uname)

            leads.append(lead)
            print(f"  [+] LEAD #{len(leads)}: {lead['name']} <{lead['email']}>")

            time.sleep(random.uniform(0.4, 1.0))

        time.sleep(random.uniform(0.7, 1.5))

    json_path, xlsx_path = save_outputs(leads, data_dir, args.output)

    print("\n" + "=" * 80)
    print("HARVEST COMPLETE")
    print(f"Search requests used: {requests_used}")
    print(f"US content-creator emails collected: {len(leads)}")
    print(f"JSON:  {json_path}")
    print(f"Excel: {xlsx_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
