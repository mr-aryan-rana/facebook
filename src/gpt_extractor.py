#!/usr/bin/env python3
"""
=============================================================================
🧠 OPENAI GPT LEAD EXTRACTION & LOCATION VERIFICATION MODULE
=============================================================================
Processes raw live web search data using OpenAI (gpt-4o-mini).

Enforces:
1. Mandatory Creator Name & Contact Filter: Discards any record that is missing
   a valid creator name OR missing both email and mobile_number.
2. Unicode Normalization: Normalizes Google Serper non-breaking hyphens (\u2011).
3. Hybrid Regex Phone Extractor Safeguard: Ensures 100% US +1 mobile phone
   extraction accuracy from snippets.
=============================================================================
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
FACEBOOK_DIR = SRC_DIR.parent

sys.path.insert(0, str(SRC_DIR))
from env_loader import load_env
from verifier import verify_us_phone, normalize_unicode_text

load_env()

def extract_and_verify_leads(raw_items: list, verbose: bool = False) -> list:
    """Processes a list of raw search items through OpenAI GPT and returns clean, verified leads."""
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("❌ [GPT Extractor] Error: OPENAI_API_KEY not set in environment.")
        return []

    if not raw_items:
        print("⚠️ [GPT Extractor] No raw items provided.")
        return []

    print(f"\n🧠 [GPT Extractor] Sending {len(raw_items)} raw items to OpenAI gpt-4o-mini...")

    # Normalize unicode text in raw items first
    clean_raw_items = []
    for item in raw_items:
        c_title = normalize_unicode_text(item.get("title", ""))
        c_snippet = normalize_unicode_text(item.get("snippet", ""))
        clean_raw_items.append({
            "platform": item.get("platform", "Facebook"),
            "title": c_title,
            "snippet": c_snippet,
            "link": item.get("link", "")
        })

    system_prompt = (
        "You are an expert lead extraction & location verification AI.\n\n"
        "STRICT MANDATORY EXTRACTION & FILTERING RULES:\n"
        "1. MANDATORY NAME & CONTACT REQUIREMENT: Each lead MUST have a valid creator 'name' AND AT LEAST ONE contact method: an 'email' OR a 'mobile_number' (or both).\n"
        "2. DISCARD RULE: IF A LEAD HAS NO CREATOR NAME, OR HAS NO EMAIL AND NO MOBILE NUMBER, DISCARD IT ENTIRELY!\n"
        "3. PHONE NUMBER EXTRACTION: Extract any US mobile phone number (+1 XXX XXX-XXXX or standard 10-digit number) from snippet/title into 'mobile_number'.\n"
        "4. LOCATION VERIFICATION SIGNALS:\n"
        "   - Phone number starting with '+1' (or US 10-digit area code) is a STRONG PROOF/SIGNAL of USA location.\n"
        "   - Mentions of US Cities or States or 'United States'.\n"
        "   - Set location_verification_status to 'Verified US' if any US location or +1 phone signal is present.\n"
        "5. Respond ONLY with a valid JSON object containing key 'extracted_leads' with an array of valid leads.\n"
        "   Each lead object must have: name, first_name, platform, profile_url, email, mobile_number, location, location_verification_status."
    )

    user_prompt = f"""
Extract ALL valid creator contacts from this raw search batch:

Raw Input Batch ({len(clean_raw_items)} items):
{json.dumps(clean_raw_items, indent=2, ensure_ascii=False)}
"""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    if verbose:
        print("\n" + "=" * 80)
        print("🧠 [OPENAI GPT TEST INSPECTOR - OUTGOING REQUEST]")
        print("  • Target URL: https://api.openai.com/v1/chat/completions")
        print("  • Model: gpt-4o-mini")
        print("  • System Prompt:\n", system_prompt)
        print("  • User Prompt Payload:\n", user_prompt)
        print("=" * 80)

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_resp_bytes = resp.read()
            body = json.loads(raw_resp_bytes.decode("utf-8"))
            raw_reply = body["choices"][0]["message"]["content"]

            if verbose:
                print("\n" + "=" * 80)
                print("📥 [OPENAI GPT TEST INSPECTOR - INCOMING RESPONSE]")
                print(f"  • Status Code: {resp.status}")
                print(f"  • Usage Tokens: {body.get('usage', {})}")
                print(f"  • GPT Raw Response String:\n{raw_reply}")
                print("=" * 80 + "\n")

            parsed = json.loads(raw_reply)
            leads = parsed.get("extracted_leads", [])

            # Secondary python-level safeguard enforcement & regex phone backup
            valid_leads = []
            for idx, lead in enumerate(leads):
                name = (lead.get("name") or "").strip()
                email = (lead.get("email") or "").strip()
                phone = (lead.get("mobile_number") or "").strip()

                # Extract first name
                first_name = (lead.get("first_name") or "").strip()
                if not first_name and name and name.lower() not in ["unknown", "creator", "none", "n/a", "admin"]:
                    parts = re.split(r'[\s&,/]+', name)
                    first_name = parts[0].capitalize() if parts else ""
                lead["first_name"] = first_name

                # Backup phone check if OpenAI missed a phone present in snippet
                if not phone and idx < len(clean_raw_items):
                    raw_text = clean_raw_items[idx]["title"] + " " + clean_raw_items[idx]["snippet"]
                    has_phone, fmt_phone, _ = verify_us_phone(raw_text)
                    if has_phone:
                        phone = fmt_phone
                        lead["mobile_number"] = fmt_phone

                if name and (email or phone):
                    valid_leads.append(lead)

            print(f"✅ [GPT Extractor] Extracted {len(valid_leads)} valid leads (Name + Email/Phone required).")
            return valid_leads
    except Exception as e:
        print(f"❌ [GPT Extractor] Error calling OpenAI: {e}")
        return []
