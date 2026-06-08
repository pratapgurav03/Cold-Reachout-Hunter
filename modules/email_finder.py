"""
Email Finder Module
--------------------
Finds email addresses for LinkedIn contacts using:
1. Hunter.io API (most accurate, free tier: 25/month)
2. Common corporate email pattern guessing + MX record verification

Get your free Hunter.io key at: https://hunter.io/users/sign_up
Add it to your .env file as HUNTER_API_KEY=your_key_here
"""

import re
import socket
import smtplib
import requests
from typing import Optional


# Common email patterns used by companies
EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}{last}@{domain}",
    "{first}@{domain}",
    "{first}_{last}@{domain}",
    "{last}.{first}@{domain}",
    "{first}-{last}@{domain}",
]


def _clean_name(name: str) -> tuple[str, str, str]:
    """Extract first, last, and first initial from full name."""
    parts = name.strip().split()
    first = parts[0].lower() if parts else ""
    last = parts[-1].lower() if len(parts) > 1 else ""
    # Remove non-alpha chars
    first = re.sub(r"[^a-z]", "", first)
    last = re.sub(r"[^a-z]", "", last)
    f = first[0] if first else ""
    return first, last, f


def _get_company_domain(company_name: str) -> Optional[str]:
    """
    Try to guess the primary domain for a company.
    Uses a few heuristics + a fallback web lookup.
    """
    raw = company_name.strip().lower()

    # If company_name already looks like a domain (e.g. "Google.org", "github.io"),
    # try it directly before falling back to name-munging.
    domain_re = re.compile(r'^[a-z0-9][a-z0-9\-]*\.[a-z]{2,}$')
    raw_nodot = raw.replace(' ', '')
    if domain_re.match(raw_nodot):
        try:
            socket.gethostbyname(raw_nodot)
            return raw_nodot
        except (socket.gaierror, UnicodeError):
            pass

    # Clean company name — strip stop-words and non-alphanumeric chars
    clean = raw
    clean = re.sub(r"\b(inc|llc|ltd|corp|co|company|the|&|and)\b", "", clean)
    clean = re.sub(r"[^a-z0-9]", "", clean.strip())

    # Guard: domain label must be 1-63 chars and non-empty
    if not clean or len(clean) > 63:
        return None

    candidates = [
        f"{clean}.com",
        f"{clean}.io",
        f"{clean}.net",
        f"{clean}.co",
    ]

    for domain in candidates:
        try:
            # Validate domain format before DNS lookup
            if not re.match(r'^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]\.[a-z]{2,}$', domain):
                continue
            socket.gethostbyname(domain)
            return domain
        except (socket.gaierror, UnicodeError):
            continue

    return None


def _verify_email_format(email: str) -> bool:
    """Basic format check."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def _check_mx_record(domain: str) -> bool:
    """Check if domain has MX records (accepts email)."""
    try:
        import dns.resolver
        records = dns.resolver.resolve(domain, "MX")
        return len(records) > 0
    except Exception:
        # Fall back to basic socket check
        try:
            socket.gethostbyname(domain)
            return True
        except Exception:
            return False


def find_email_hunter(
    first_name: str,
    last_name: str,
    domain: str,
    api_key: str
) -> Optional[dict]:
    """
    Use Hunter.io API to find a verified email.
    Returns dict with {email, score, sources} or None.
    """
    url = "https://api.hunter.io/v2/email-finder"
    params = {
        "domain": domain,
        "first_name": first_name,
        "last_name": last_name,
        "api_key": api_key
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json().get("data", {})
            if data.get("email"):
                return {
                    "email": data["email"],
                    "score": data.get("score", 0),
                    "sources": data.get("sources", []),
                    "method": "hunter.io"
                }
    except Exception as e:
        print(f"  Hunter.io error: {e}")
    return None


def find_email_pattern(
    first_name: str,
    last_name: str,
    domain: str
) -> list[dict]:
    """
    Generate candidate emails using common patterns.
    Returns list sorted by likelihood.
    """
    first, last, f = _clean_name(f"{first_name} {last_name}")
    if not domain:
        return []

    candidates = []
    for pattern in EMAIL_PATTERNS:
        try:
            email = pattern.format(
                first=first, last=last, f=f, domain=domain
            )
            if _verify_email_format(email):
                candidates.append({
                    "email": email,
                    "score": 50,  # unknown confidence
                    "method": "pattern_guess"
                })
        except KeyError:
            continue

    return candidates


def find_domain_pattern(company_name: str, hunter_api_key: Optional[str] = None) -> Optional[str]:
    """
    Use Hunter.io domain search to find the company's email pattern.
    Falls back to guessing.
    """
    if hunter_api_key:
        url = "https://api.hunter.io/v2/domain-search"
        # First try to get the domain from company name
        domain = _get_company_domain(company_name)
        if domain:
            params = {"domain": domain, "api_key": hunter_api_key, "limit": 1}
            try:
                r = requests.get(url, params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json().get("data", {})
                    return data.get("pattern")  # e.g. "{first}.{last}"
            except Exception:
                pass
    return None


def find_email(
    full_name: str,
    company_name: str,
    domain: Optional[str] = None,
    hunter_api_key: Optional[str] = None
) -> dict:
    """
    Main email finder function.
    Returns best guess: {email, confidence, method, alternatives}
    """
    first, last, f = _clean_name(full_name)

    # Step 1: Get company domain if not provided
    if not domain:
        domain = _get_company_domain(company_name)
        if not domain:
            return {
                "email": None,
                "confidence": 0,
                "method": "none",
                "alternatives": [],
                "error": f"Could not find domain for {company_name}"
            }

    # Step 2: Try Hunter.io first (most accurate)
    if hunter_api_key and first and last:
        hunter_result = find_email_hunter(first, last, domain, hunter_api_key)
        if hunter_result and hunter_result["score"] > 30:
            return {
                "email": hunter_result["email"],
                "confidence": hunter_result["score"],
                "method": "hunter.io",
                "alternatives": find_email_pattern(first, last, domain)[:3],
                "domain": domain
            }

    # Step 3: Pattern guessing
    candidates = find_email_pattern(first, last, domain)
    if candidates:
        return {
            "email": candidates[0]["email"],  # most common pattern: first.last@domain
            "confidence": 40,  # low confidence for guesses
            "method": "pattern_guess",
            "alternatives": candidates[1:4],
            "domain": domain,
            "note": "Pattern guess — verify before sending, or use Hunter.io for accuracy"
        }

    return {
        "email": None,
        "confidence": 0,
        "method": "none",
        "alternatives": [],
        "error": "Could not determine email"
    }


def get_company_domain_from_hunter(company_name: str, api_key: str) -> Optional[str]:
    """Use Hunter.io company search to find the official domain."""
    url = "https://api.hunter.io/v2/domain-search"
    params = {
        "company": company_name,
        "api_key": api_key,
        "limit": 1
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", {})
            return data.get("domain")
    except Exception:
        pass
    return None


if __name__ == "__main__":
    # Quick test
    result = find_email("John Smith", "Google", hunter_api_key=None)
    print(result)
