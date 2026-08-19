import base64
import html
import random
import re
import time
from typing import Dict, Any, List, Optional
from urllib.parse import quote
from curl_cffi import requests
from verifier import verify_email_dns, verify_us_phone, EMAIL_REGEX, PHONE_REGEX
from us_locations import AREA_CODE_TO_STATE, MAJOR_US_CITIES

import os
from pathlib import Path

FB_SEARCH_DORKS = [
    'site:facebook.com "Digital Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Content Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "UGC Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Video Creator" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Media Studio" "gmail.com" OR "yahoo.com" OR "hotmail.com"',
    'site:facebook.com "Production Studio" "gmail.com" OR "yahoo.com" OR "hotmail.com"'
]

EXCLUDED_NEWS_GOV_KEYWORDS = [
    # News & Media Outlets
    "news", "channel", "tv", "newspaper", "press", "journal", "gazette", "broadcasting",
    "broadcaster", "media network", "news network", "news channel", "herald", "tribune",
    "breaking news", "daily news", "post news", "times", "chronicle", "reporter",
    "fox", "cnn", "nbc", "cbs", "abc", "msnbc", "bbc", "reuters", "associated press",

    # Government & Municipal Service Pages
    ".gov", "government", "gov", "city of ", "town of ", "county of ", "village of ",
    "dept of", "department of", "dept. of", "department of", "municipal", "police department",
    "sheriff", "fire department", "fire & rescue", "emergency management", "public safety",
    "school district", "city hall", "mayor", "governor", "senate", "embassy", "consulate",
    "ministry", "state of ", "bureau of", "health department", "transit authority"
]

SEARCH_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

INSTA_CACHE: Dict[str, str] = {}

# Location confirmation. Previously extract_lead_from_snippet hardcoded
# "location": "United States" on every lead regardless of what the page
# actually said -- these patterns are the real signal this was ported
# from run_creator_us_harvest.py, which had it but wasn't wired into the
# shared extractor every harvester actually uses.
US_STATE_ABBR = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    "NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
# Facebook page titles commonly render as "Page Name | City ST" (pipe
# delimiter, no comma) rather than the "City, ST" comma form -- match both.
CITY_STATE_RE = re.compile(r"[,|]\s*([A-Z][a-zA-Z.\s]{2,25}?)[,\s]+(" + US_STATE_ABBR + r")\b")
US_TEXT_RE = re.compile(r"\b(usa|u\.s\.a\.|united states)\b", re.IGNORECASE)

NON_US_LOCATION_KEYWORDS = [
    "nigeria", "lagos", "ogbomoso", "kenya", "ruiru", "cape town", "mafikeng",
    "south africa", "ghana", "accra", "trinidad", "philippines", "manila",
    "india", "pakistan", "bangladesh", "indonesia", "malaysia", "vietnam",
    "united kingdom", " uk ", "london", "canada", "toronto", "ontario",
    "australia", "sydney", "brazil", "mexico", "dubai", "uae", "egypt",
    "johannesburg", "tripoli", "kampala",
]


def detect_location(text: str, area_code: str = "") -> str:
    """Best-effort location confirmation, checked in order of reliability:
      1. Explicit "City, ST" / "City | ST" pattern in the text
      2. Phone area code (already regex-matched AND verified by
         verify_us_phone) cross-referenced against the real NANP
         area-code-to-state table -- more reliable than free-text
         matching since it's tied to a verified phone number, not a
         string that happens to appear on the page
      3. A curated, state-qualified list of major US cities with no
         well-known non-US namesake (see us_locations.py for why a full
         "all cities" list would hurt rather than help here)
      4. A generic USA/United States text mention
    Returns "Non-US" when a known non-US country/city is named, or
    "Unconfirmed" when there's no real signal either way -- never
    silently defaults to "United States"."""
    low = text.lower()
    if any(k in low for k in NON_US_LOCATION_KEYWORDS):
        return "Non-US"

    m = CITY_STATE_RE.search(text)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"

    if area_code and area_code in AREA_CODE_TO_STATE:
        return f"United States ({AREA_CODE_TO_STATE[area_code]}, via phone area code)"

    for city_name, state in MAJOR_US_CITIES.items():
        if city_name in low:
            return f"{city_name.title()}, {state}"

    if US_TEXT_RE.search(text):
        return "United States"
    return "Unconfirmed"

TEL_HREF_REGEX = re.compile(r"tel:([+0-9()\-.\s]{7,20})", re.IGNORECASE)


def _phone_candidates_from_page(page_html: str) -> str:
    """Restricts phone-number scanning of a raw Facebook page to tel: link
    targets only. A blind digit regex over the whole page HTML matches
    Facebook's own internal numeric IDs (app_id, video_id, fbid, timestamps
    embedded in the page's JSON) that happen to fall within valid US phone
    ranges -- confirmed empirically (an app_id of 2392950137 formatted as a
    plausible +1 (239) 295-0137). A tel: href is the only place a 10-digit
    sequence on the page is actually asserting itself as a phone number."""
    if not page_html:
        return ""
    return " ".join(TEL_HREF_REGEX.findall(page_html))


def _load_serper_key() -> str:
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("SERPER_KEY", "")


def _random_search_headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(SEARCH_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _decode_bing_redirect(href: str) -> str:
    # Bing serves the href HTML-entity-escaped (e.g. "&amp;u=..."); without
    # unescaping first, the "[?&]u=" pattern never matches and every result
    # silently falls back to the useless bing.com/ck/a wrapper link.
    href = html.unescape(href)
    m = re.search(r"[?&]u=([A-Za-z0-9_-]+)", href)
    if not m:
        return href
    token = m.group(1)
    if token.startswith("a1"):
        token = token[2:]
    token += "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token).decode("utf-8", "ignore")
    except Exception:
        return href

def check_instagram_profile(username: str, session: requests.Session) -> str:
    if not username or username in ("facebook_page", "pages", "people", "groups", "events"):
        return "N/A"
    
    clean_user = username.lower().strip()
    if clean_user in INSTA_CACHE:
        return INSTA_CACHE[clean_user]

    insta_url = f"https://www.instagram.com/{clean_user}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        resp = session.get(insta_url, headers=headers, timeout=5, allow_redirects=False)
        if resp.status_code == 200:
            INSTA_CACHE[clean_user] = insta_url
            return insta_url
    except Exception:
        pass

    INSTA_CACHE[clean_user] = "N/A"
    return "N/A"

def parse_fb_username(url: str) -> str:
    low_url = url.lower()
    if any(x in low_url for x in ["/groups/", "/events/", "/posts/", "profile.php", "/p/", "/stories/"]):
        return "facebook_page"

    m = re.search(r"facebook\.com/([^/?#]+)", url)
    if m:
        u = m.group(1).replace("pages", "").replace("people", "").strip("/")
        if u and not u.isdigit() and len(u) > 2 and u not in ("home.php", "login", "checkpoint", "help"):
            return u
    return "facebook_page"

def clean_page_title(title_html: str) -> str:
    title = re.sub(r"<[^>]+>", "", title_html)
    title = title.replace(" | Facebook", "").replace(" - Home", "").replace("Home | ", "").strip()
    title = re.sub(r"^\([^)]+\)\s*", "", title)
    return title if title else "Facebook Creator"

class FacebookExtractor:
    def __init__(self, proxy_server: Optional[str] = None):
        self.session = requests.Session(impersonate="chrome124")
        if proxy_server:
            self.session.proxies = {"http": proxy_server, "https": proxy_server}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

    def _get_with_backoff(self, url: str, max_attempts: int = 3) -> Optional[Any]:
        delays = (2.0, 5.0, 12.0)
        for attempt in range(max_attempts):
            try:
                resp = self.session.get(url, headers=_random_search_headers(), timeout=10)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else delays[min(attempt, len(delays) - 1)]
                    time.sleep(wait + random.uniform(0.3, 1.2))
                    continue
                if resp.status_code == 200:
                    return resp
                return None
            except Exception:
                if attempt < max_attempts - 1:
                    time.sleep(delays[min(attempt, len(delays) - 1)] + random.uniform(0.3, 1.2))
        return None

    def _fetch_bing_results(self, dork: str, page: int) -> List[Dict[str, str]]:
        first = page * 10 + 1
        url = f"https://www.bing.com/search?q={quote(dork)}&first={first}"
        resp = self._get_with_backoff(url)
        if resp is None:
            return []

        results = []
        for block in re.findall(r'<li class="b_algo"[^>]*>.*?</li>', resp.text, re.S):
            m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.S)
            if not m:
                continue
            real_url = _decode_bing_redirect(m.group(1))
            results.append({"url": real_url, "title_html": m.group(2), "snippet_html": block})
        return results

    def _fetch_duckduckgo_results(self, dork: str, page: int) -> List[Dict[str, str]]:
        offset = page * 30
        url = f"https://html.duckduckgo.com/html/?q={quote(dork)}&s={offset}"
        resp = self._get_with_backoff(url)
        if resp is None:
            return []

        anchors = list(re.finditer(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text))
        results = []
        for i, m in enumerate(anchors):
            end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(resp.text), m.end() + 2000)
            block = resp.text[m.start():end]
            results.append({"url": m.group(1), "title_html": m.group(2), "snippet_html": block})
        return results

    def _fetch_brave_results(self, dork: str, page: int) -> List[Dict[str, str]]:
        if page > 0:
            return []
        url = f"https://search.brave.com/search?q={quote(dork)}"
        resp = self._get_with_backoff(url)
        if resp is None:
            return []

        text = resp.text
        anchors = list(re.finditer(
            r'<a href="(https?://(?:www\.)?facebook\.com/[^"]+)"[^>]*class="[^"]*"><div class="site-name-wrapper.*?'
            r'<div class="title[^"]*"[^>]*title="([^"]*)"',
            text, re.S
        ))
        results = []
        for i, m in enumerate(anchors):
            end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(text), m.end() + 1500)
            block = text[m.start():end]
            results.append({"url": m.group(1), "title_html": m.group(2), "snippet_html": block})
        return results

    def _fetch_serper_results(self, dork: str, page: int) -> List[Dict[str, str]]:
        api_key = _load_serper_key()
        if not api_key:
            return []
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": dork, "num": 10, "page": page + 1}
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for item in data.get("organic", []):
                link = item.get("link", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                if link:
                    results.append({"url": link, "title_html": title, "snippet_html": snippet})
            return results
        except Exception:
            return []

    def fetch_search_results(self, dork: str, page: int = 0) -> List[Dict[str, str]]:
        for engine in (self._fetch_serper_results, self._fetch_brave_results, self._fetch_duckduckgo_results, self._fetch_bing_results):
            try:
                results = engine(dork, page)
            except Exception:
                results = []
            if results:
                return results
            time.sleep(random.uniform(1.0, 2.0))
        return []

    def fetch_page_html(self, url: str) -> Optional[str]:
        """Fetches the live Facebook page and returns its HTML if the page is
        genuinely live and viewable, else None. Unlike a search-engine
        snippet (a couple hundred characters of result-page text), this is
        the actual page content -- the only place a phone number realistically
        appears, and a far more reliable source for an email too."""
        try:
            resp = self.session.get(url, headers=self.headers, timeout=6, allow_redirects=True)
            if resp.status_code != 200:
                return None

            text = resp.text
            low = text.lower()
            not_available_markers = (
                "this content isn't available",
                "content not found",
                "this page isn't available",
                "owner only shared it with a small group",
                "log into facebook",
                "you must log in to continue"
            )

            if any(marker in low for marker in not_available_markers):
                return None

            return text
        except Exception:
            return None

    def is_live_facebook_page(self, url: str) -> bool:
        return self.fetch_page_html(url) is not None

    def extract_lead_from_snippet(self, page_url: str, title_html: str, full_html: str, page_html: str = "") -> Optional[Dict[str, Any]]:
        # Strictly reject groups, events, posts, p/, profile.php
        low_url = page_url.lower()
        if any(x in low_url for x in ["/groups/", "/events/", "/posts/", "profile.php", "/p/", "/stories/"]):
            return None

        # STRICT EXCLUSION: Never fetch info of News accounts or Government service pages.
        # Deliberately excludes page_html here -- a real Facebook page's full
        # HTML (ads, footer links, unrelated feed content) reliably contains
        # noise words like "news"/"tv"/".gov" regardless of what the page
        # actually is, so scanning it for these keywords produces false
        # positives. The search snippet/title is a targeted enough source
        # for this classification; page_html is only used below for the
        # phone/email regex extraction, where false positives aren't a risk.
        combined_text = f"{page_url} {title_html} {full_html}".lower()
        if any(k in combined_text for k in EXCLUDED_NEWS_GOV_KEYWORDS):
            return None

        username = parse_fb_username(page_url)
        if username in ("facebook_page", "pages", "people", "groups", "events", "profile.php"):
            return None

        real_name = clean_page_title(title_html)
        low_name = real_name.lower()
        junk_patterns = ["hotmail", "yahoo", "log in", "sign up", "customer care", "software, website", "privacy policy"]
        if any(j in low_name for j in junk_patterns):
            return None

        # Strict Phone verification -- check the live page's tel: links first
        # (see _phone_candidates_from_page for why this can't be a blind
        # regex over the whole page), falling back to the search-result
        # snippet/title if no tel: link was present or the page fetch wasn't
        # available.
        has_phone, formatted_phone, area_code = verify_us_phone(_phone_candidates_from_page(page_html))
        if not has_phone:
            has_phone, formatted_phone, area_code = verify_us_phone(full_html)
        if not has_phone:
            has_phone, formatted_phone, area_code = verify_us_phone(title_html)

        # Email extraction & DNS verification
        raw_emails = EMAIL_REGEX.findall(page_html) + EMAIL_REGEX.findall(full_html) + EMAIL_REGEX.findall(title_html)
        verified_email = ""
        dns_status = ""

        for em in raw_emails:
            em_clean = em.lower().strip()
            if not em_clean.endswith(('.png', '.jpg', '.jpeg', '.svg', '.gif', 'facebook.com', 'fb.com')):
                is_valid, status_msg = verify_email_dns(em_clean)
                if is_valid:
                    verified_email = em_clean
                    dns_status = status_msg
                    break

        # STRICT QUALITY CHECK: Require at least ONE authentic contact method (DNS-verified email OR verified phone)
        if not verified_email and not has_phone:
            return None

        phone_val = formatted_phone if has_phone else ""
        email_val = verified_email if verified_email else ""
        dns_status_val = dns_status if verified_email else "N/A"
        # Deliberately excludes page_html here, same reasoning as the news/
        # gov exclusion check above: a real Facebook page's full HTML
        # contains unrelated boilerplate (language-switcher links, friend/
        # page suggestions mentioning other cities) that reliably produces
        # false "Non-US" matches regardless of the page's actual location.
        location_val = detect_location(f"{title_html} {full_html}", area_code=area_code if has_phone else "")

        return {
            "username": username,
            "name": real_name,
            "platform": "Facebook Page",
            "mobile_number": phone_val,
            "phone_verified": True if has_phone else False,
            "email": email_val,
            "email_dns_verified": dns_status_val,
            "area_code": area_code if has_phone else "N/A",
            "location": location_val,
            "page_url": page_url,
            "status": "Verified Real Live FB Page"
        }
