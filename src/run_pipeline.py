#!/usr/bin/env python3
"""
=============================================================================
🚀 UNIFIED MASTER OUTREACH PIPELINE RUNNER
=============================================================================
Runs the complete automated pipeline end-to-end:

1. Live Serper Harvesting across Facebook, TikTok, & Instagram for targeted niches
2. OpenAI GPT Lead Extraction & Location Verification (Name + Email/Phone mandatory)
3. Database Pre-Check & Deduplication (Skips previously emailed contacts in Postgres)
4. Automated Email Outreach via Gmail/SMTP + DB logging

Usage:
  python facebook/src/run_pipeline.py --niche "Love Couple" --limit 10 --dry-run
=============================================================================
"""

import argparse
import json
import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
FACEBOOK_DIR = SRC_DIR.parent

sys.path.insert(0, str(SRC_DIR))

from serper_harvester import harvest_live_niche_data
from gpt_extractor import extract_and_verify_leads
from db_lead_sync import sync_and_filter_leads_for_outreach
from outreach_sender import send_outreach_to_queued_leads

class DualLogger:
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.filepath = filepath

    def write(self, message):
        if self.terminal:
            try:
                self.terminal.write(message)
                self.terminal.flush()
            except Exception:
                pass
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(message)
        except Exception:
            pass

    def flush(self):
        if self.terminal:
            try:
                self.terminal.flush()
            except Exception:
                pass

log_file_path = FACEBOOK_DIR / "Data" / "harvester.log"
sys.stdout = DualLogger(log_file_path)
sys.stderr = sys.stdout

def run_full_pipeline(niche: str, limit_per_platform: int, dry_run: bool = False, verbose: bool = True):
    print("=" * 80)
    print("🚀 UNIFIED LIVE HARVEST, GPT VERIFY, DB CHECK & OUTREACH PIPELINE")
    print("=" * 80)
    print(f"🎯 Target Niche:        '{niche}'")
    print(f"📊 Max Results/Platform: {limit_per_platform}")
    print(f"🧪 Dry Run Mode:         {dry_run}")
    print(f"🔍 Inspector Verbose:    {verbose}")
    print("-" * 80)

    # Step 1: Serper Live Harvesting
    harvest_data = harvest_live_niche_data(niche=niche, max_per_platform=limit_per_platform, verbose=verbose)
    raw_items = harvest_data.get("all_results", [])
    if not raw_items:
        print("❌ Pipeline stopped: No raw search items collected.")
        return

    print("\n" + "=" * 80)
    print(f"🌐 [RAW SEARCH HARVESTER SUMMARY] Collected {len(raw_items)} raw web items:")
    for idx, item in enumerate(raw_items, 1):
        print(f"  [{idx}] Platform: {item.get('platform')} | Title: {item.get('title')[:60]}")
        print(f"      URL: {item.get('link')}")
        print(f"      Snippet: {item.get('snippet')[:100]}")
    print("=" * 80 + "\n")

    # Step 2: OpenAI Lead & Location Extraction
    extracted_leads = extract_and_verify_leads(raw_items, verbose=verbose)
    if not extracted_leads:
        print("❌ Pipeline stopped: No valid contact leads extracted.")
        return

    print("\n" + "=" * 80)
    print(f"🧠 [OPENAI GPT RESPONSE SUMMARY] Extracted {len(extracted_leads)} valid contact leads:")
    for idx, lead in enumerate(extracted_leads, 1):
        name = lead.get("name", "Unknown")
        email = lead.get("email") or "No Email"
        phone = lead.get("mobile_number") or "No Mobile"
        loc = lead.get("location") or "USA"
        status = lead.get("location_verification_status") or "Verified US"
        print(f"  [{idx}] Name: '{name}' | Email: '{email}' | Phone: '{phone}'")
        print(f"      Location: '{loc}' ({status}) | Profile: {lead.get('profile_url')}")
    print("=" * 80 + "\n")

    # Step 3: DB Pre-Check & Deduplication
    queued_leads = sync_and_filter_leads_for_outreach(extracted_leads)
    if not queued_leads:
        print("ℹ️ Pipeline complete: All extracted leads were previously emailed or already exist in DB.")
        return

    print("\n" + "=" * 80)
    print(f"🗄️ [DB OUTREACH QUEUE SUMMARY] {len(queued_leads)} NEW leads queued for email outreach:")
    for idx, ql in enumerate(queued_leads, 1):
        print(f"  [{idx}] To: {ql.get('creator_name')} <{ql.get('address')}>")
    print("=" * 80 + "\n")

    # Step 4: Email Outreach Engine
    send_stats = send_outreach_to_queued_leads(queued_leads, dry_run=dry_run)

    print("\n" + "=" * 80)
    print("🎉 PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
    print(f"  • Raw Results Harvested: {len(raw_items)}")
    print(f"  • GPT Extracted Leads:   {len(extracted_leads)}")
    print(f"  • DB Queued New Leads:   {len(queued_leads)}")
    print(f"  • Emails Sent:           {send_stats.get('sent', 0)}")
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="Master Outreach Pipeline Runner")
    parser.add_argument("--niche", type=str, default="Love Couple", help="Target creator niche (e.g. 'Love Couple', 'Travel', 'Beauty')")
    parser.add_argument("--limit", type=int, default=3, help="Maximum raw search results per platform")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending actual outreach emails")
    parser.add_argument("--inspect", "--verbose", "-v", dest="inspect", action="store_true", help="Inspect raw Serper URL, Serper response JSON, and GPT raw response")
    parser.add_argument("--loop", "--continuous", dest="loop", action="store_true", help="Run continuously in a loop until terminated")
    parser.add_argument("--interval", type=int, default=120, help="Interval in seconds between loop cycles")

    args = parser.parse_args()

    if args.loop:
        import time
        cycle = 1
        base_niche = args.niche
        niche_variations = [
            base_niche,
            f"{base_niche} Vlog",
            f"Travel {base_niche}",
            f"{base_niche} UGC Creator",
            f"Wedding {base_niche}",
            f"{base_niche} Lifestyle"
        ]
        print(f"🔄 Starting Autonomous 24/7 Pipeline Daemon (Loop Interval: {args.interval}s)...")
        while True:
            current_niche = niche_variations[(cycle - 1) % len(niche_variations)]
            print(f"\n" + "=" * 80)
            print(f"🔄 PIPELINE CYCLE #{cycle} | Niche: '{current_niche}'")
            print("=" * 80)
            try:
                run_full_pipeline(niche=current_niche, limit_per_platform=args.limit, dry_run=args.dry_run, verbose=args.inspect)
            except Exception as ex:
                print(f"⚠️ Exception during pipeline cycle #{cycle}: {ex}")
            cycle += 1
            print(f"\n⏱️ Cycle #{cycle-1} complete. Sleeping {args.interval}s before next autonomous run...")
            time.sleep(args.interval)
    else:
        run_full_pipeline(niche=args.niche, limit_per_platform=args.limit, dry_run=args.dry_run, verbose=args.inspect)


if __name__ == "__main__":
    main()
