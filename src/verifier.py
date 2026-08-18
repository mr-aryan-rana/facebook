import re
import smtplib
import socket
from typing import Optional, Tuple, Dict

DNS_CACHE: Dict[str, bool] = {}
MX_CACHE: Dict[str, Optional[str]] = {}

# Strict US Mobile / Phone Regex (+1 XXX XXX-XXXX or standard 10-digit US)
PHONE_REGEX = re.compile(
    r"(?<![\w@])(\+?1[-.\s]?)?\(?([2-9]\d{2})\)?[-.\s]?([2-9]\d{2})[-.\s]?(\d{4})(?![\w])"
)

EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.IGNORECASE
)

DISALLOWED_DOMAINS = {
    "fbcreators.com", "example.com", "test.com", "facebook.com",
    "domain.com", "sample.com", "email.com", "outreach-leads.com"
}


def verify_email_dns(email: str) -> Tuple[bool, str]:
    """
    Verifies whether an email address format is valid and its domain has active DNS/MX records.
    Returns (is_valid: bool, status_msg: str)
    """
    if not email or "@" not in email:
        return False, "Invalid Format"

    domain = email.split("@")[-1].lower().strip()

    if domain in DISALLOWED_DOMAINS:
        return False, "Disallowed Placeholder Domain"

    if domain in DNS_CACHE:
        is_active = DNS_CACHE[domain]
        return is_active, "Valid (DNS Verified)" if is_active else "Invalid DNS (NXDOMAIN)"

    # Check MX first: a domain can accept mail without publishing an A record
    # (e.g. sbcglobal.net), so an A-only check silently drops valid addresses.
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX")
        if len(answers) > 0:
            DNS_CACHE[domain] = True
            return True, "Valid (MX Verified)"
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: hosts with no MX still accept mail at their A record (RFC 5321).
    try:
        socket.gethostbyname(domain)
        DNS_CACHE[domain] = True
        return True, "Valid (DNS Verified)"
    except Exception:
        DNS_CACHE[domain] = False
        return False, "Invalid DNS (NXDOMAIN)"


def _resolve_mx(domain: str) -> Optional[str]:
    if domain in MX_CACHE:
        return MX_CACHE[domain]
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(answers, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception:
        mx_host = None
    MX_CACHE[domain] = mx_host
    return mx_host


def verify_smtp_mailbox(email: str, from_address: str = "verify@makeable.nyc", timeout: int = 10) -> Tuple[Optional[bool], str]:
    """Real mailbox-existence check via SMTP RCPT TO, without sending a
    message. Confirmed against live Gmail servers: a nonexistent mailbox
    gets an explicit 550 "does not exist" rejection at RCPT time, a real
    one gets 250 -- this is a materially stronger signal than DNS/MX
    verification, which only proves the *domain* accepts mail, not that a
    specific address has an inbox behind it.

    Returns (True, msg) if the mailbox was confirmed to exist, (False, msg)
    if the server explicitly rejected it, or (None, msg) if the probe was
    inconclusive (connection blocked, greylisted, timeout, or a provider
    that accepts-all at RCPT and only bounces after full delivery) --
    inconclusive must never be treated as "invalid": that would silently
    drop real addresses whenever a mail server declines to answer the
    probe, which is common and not evidence the mailbox is fake."""
    if not email or "@" not in email:
        return False, "Invalid Format"

    domain = email.split("@")[-1].lower().strip()
    mx_host = _resolve_mx(domain)
    if mx_host is None:
        return False, "No MX record"

    try:
        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo(from_address.split("@")[-1])
            smtp.mail(from_address)
            code, message = smtp.rcpt(email)
            msg_text = message.decode("utf-8", "ignore") if isinstance(message, bytes) else str(message)
            first_line = msg_text.splitlines()[0] if msg_text else ""

            if code == 250:
                return True, "Mailbox confirmed (RCPT 250)"

            if code in (550, 551, 553):
                # A 550 alone isn't proof the mailbox doesn't exist -- only
                # the enhanced status code's *subject* class tells you why.
                # 5.1.x = "Address" (recipient genuinely doesn't exist).
                # 5.7.x = "Security/Policy" -- confirmed in practice: this
                # probe gets 550 5.7.1 "blocked using Spamhaus" from
                # Microsoft 365-hosted domains because THIS MACHINE'S
                # outbound IP is on a blocklist, which says nothing about
                # whether the recipient mailbox exists. Only 5.1.x is
                # treated as a genuine rejection; anything else with a 550
                # is a policy/reputation block and must stay inconclusive,
                # or a clean sender IP's real send would still succeed
                # where this probe wrongly marked the address invalid.
                enhanced_match = re.match(r"5\.(\d+)\.\d+", first_line)
                if enhanced_match and enhanced_match.group(1) == "1":
                    return False, f"Mailbox rejected (RCPT {code}: {first_line})"
                return None, f"Inconclusive -- 550 but not an address-class rejection (RCPT {code}: {first_line})"

            return None, f"Inconclusive (RCPT {code}: {first_line})"
    except Exception as e:
        return None, f"SMTP probe failed (inconclusive): {e}"


def verify_us_phone(text: str) -> Tuple[bool, str, str]:
    """
    Extracts and validates a REAL US phone number from text.
    Rejects fictional 555-0100 through 555-0199 numbers and fake repeated digits.
    Returns (is_valid: bool, formatted_phone: str, area_code: str)
    """
    matches = PHONE_REGEX.findall(text)
    if not matches:
        return False, "", ""

    for m in matches:
        country_code = m[0]
        area_code = m[1]
        prefix = m[2]
        line = m[3]

        # REJECT fictional 555 numbers (e.g. 555-0100 -> 555-0199 or 555-xxxx)
        if prefix == "555":
            continue

        # REJECT dummy repeating numbers like 123-4567 or 000-0000
        if line in ("0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234"):
            continue

        if 200 <= int(area_code) <= 999 and len(prefix) == 3 and len(line) == 4:
            formatted = f"+1 ({area_code}) {prefix}-{line}"
            return True, formatted, area_code

    return False, "", ""
