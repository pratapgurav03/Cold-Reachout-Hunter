"""
LinkedIn Scraper Module — Cloud Version (Scrapin.io API)
--------------------------------------------------------
Uses Scrapin.io for LinkedIn profile scraping (100 free credits/month).
Uses Google Custom Search API for company hunting (100 free searches/day).

APIs used:
  - Scrapin.io  : Profile scraping  → SCRAPIN_API_KEY in .env
                  Free tier: 100 credits/month
                  Get key: https://scrapin.io → sign up → API keys
  - Google CSE  : Company hunting   → GOOGLE_API_KEY + GOOGLE_CSE_ID in .env
                  Free tier: 100 searches/day
                  Get key: https://developers.google.com/custom-search/v1/introduction
"""

import os
import re
import json
import requests
from typing import Optional
from dataclasses import dataclass, field, asdict


# ─── PROFILE DATA CLASS ───────────────────────────────────────────────────────

@dataclass
class LinkedInProfile:
    name: str = ""
    headline: str = ""
    location: str = ""
    about: str = ""
    profile_url: str = ""
    company: str = ""
    title: str = ""
    experience: list = field(default_factory=list)
    education: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    recent_posts: list = field(default_factory=list)
    email_guess: str = ""

    def to_dict(self):
        return asdict(self)

    def summary_for_ai(self) -> str:
        parts = []
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.title and self.company:
            parts.append(f"Role: {self.title} at {self.company}")
        elif self.headline:
            parts.append(f"Headline: {self.headline}")
        if self.location:
            parts.append(f"Location: {self.location}")
        if self.about:
            parts.append(f"About: {self.about[:600]}")
        if self.experience:
            exp_lines = []
            for exp in self.experience[:4]:
                line = f"  - {exp.get('title','')} at {exp.get('company','')} ({exp.get('duration','')})"
                exp_lines.append(line)
            parts.append("Experience:\n" + "\n".join(exp_lines))
        if self.education:
            edu_lines = []
            for edu in self.education[:2]:
                line = f"  - {edu.get('degree','')} at {edu.get('school','')} ({edu.get('years','')})"
                edu_lines.append(line)
            parts.append("Education:\n" + "\n".join(edu_lines))
        if self.recent_posts:
            parts.append(f"Recent activity: {' | '.join(self.recent_posts[:2])}")
        return "\n".join(parts)


# ─── SCRAPIN.IO SCRAPER ───────────────────────────────────────────────────────

class LinkedInScraper:
    SCRAPIN_BASE = "https://api.reversecontact.com/enrichment"

    # Titles to prioritize when hunting
    TARGET_TITLES = [
        "hiring manager", "talent acquisition", "recruiter",
        "chief of staff", "vp of engineering", "director of engineering",
        "head of product", "director of product", "product manager",
        "program manager", "technical program manager", "engineering manager",
        "vp engineering", "cto", "operations manager", "director of operations",
        "senior program manager", "people operations"
    ]

    def __init__(self, headless: bool = False):
        # headless param kept for interface compatibility
        self.rapidapi_key = os.getenv("RAPIDAPI_KEY")
        self.apify_key = os.getenv("APIFY_KEY")
        self.scrapin_key = os.getenv("SCRAPIN_API_KEY")
        self.serpapi_key = os.getenv("SERPAPI_KEY")
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID")

    def _normalize_linkedin_url(self, url: str) -> str:
        """Normalize LinkedIn URL: strip country subdomains, query params, trailing slashes."""
        # Convert jp.linkedin.com, uk.linkedin.com, etc. → linkedin.com
        url = re.sub(r'https?://[a-z]{2}\.linkedin\.com', 'https://www.linkedin.com', url)
        # Also handle linkedin.com without www
        url = re.sub(r'https?://linkedin\.com', 'https://www.linkedin.com', url)
        # Strip query params and trailing slash
        url = url.split("?")[0].rstrip("/")
        return url

    # ── Profile Scraping ──────────────────────────────────────────────────────

    def scrape_profile(self, profile_url: str) -> LinkedInProfile:
        """
        Fetch a LinkedIn profile.
        Priority: RapidAPI (if configured) → SerpAPI snippet (free, always available)
        """
        url = self._normalize_linkedin_url(profile_url)

        if self.rapidapi_key:
            return self._scrape_via_rapidapi(url)
        elif self.serpapi_key:
            return self._scrape_via_serpapi_snippet(url)
        else:
            raise ValueError(
                "No scraping API configured. SERPAPI_KEY is already in your .env — "
                "just restart the app."
            )

    def _scrape_via_rapidapi(self, profile_url: str) -> LinkedInProfile:
        """
        Fetch a LinkedIn profile via RapidAPI 'Fresh LinkedIn Profile Data'.
        Sign up at rapidapi.com → search 'Fresh LinkedIn Profile Data' → Subscribe (free tier: 200/month).
        """
        print(f"  Fetching profile via RapidAPI: {profile_url}")
        response = requests.get(
            "https://fresh-linkedin-profile-data.p.rapidapi.com/get-linkedin-profile",
            headers={
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": "fresh-linkedin-profile-data.p.rapidapi.com",
            },
            params={"linkedin_url": profile_url, "include_skills": "true"},
            timeout=30
        )

        if response.status_code == 401 or response.status_code == 403:
            raise ValueError("Invalid RapidAPI key or not subscribed to Fresh LinkedIn Profile Data.")
        if response.status_code == 404:
            raise ValueError(f"LinkedIn profile not found: {profile_url}")
        if response.status_code == 429:
            print("  RapidAPI rate limit hit, falling back to Scrapin.io...")
            if self.scrapin_key:
                return self._scrape_via_scrapin(profile_url)
            raise ValueError("RapidAPI rate limit hit and no fallback configured.")
        if response.status_code != 200:
            print(f"  RapidAPI error {response.status_code}, falling back to Scrapin.io...")
            if self.scrapin_key:
                return self._scrape_via_scrapin(profile_url)
            raise ValueError(f"RapidAPI error {response.status_code}: {response.text[:200]}")

        # Fresh LinkedIn Profile Data wraps response in a "data" key
        body = response.json()
        data = body.get("data") or body
        return self._parse_rapidapi_response(data, profile_url)

    def _parse_rapidapi_response(self, data: dict, profile_url: str) -> LinkedInProfile:
        """Convert Fresh LinkedIn Profile Data response to LinkedInProfile."""
        profile = LinkedInProfile(profile_url=profile_url)

        first = data.get("first_name") or ""
        last = data.get("last_name") or ""
        profile.name = data.get("full_name") or f"{first} {last}".strip()
        profile.headline = data.get("headline") or data.get("occupation") or ""
        profile.about = (data.get("summary") or "")[:1000]

        city = data.get("city") or ""
        state = data.get("state") or ""
        country = data.get("country_full_name") or data.get("country") or ""
        profile.location = ", ".join(filter(None, [city, state, country]))

        # Experience — same structure as Proxycurl
        for exp in (data.get("experiences") or [])[:6]:
            title = exp.get("title") or ""
            company = exp.get("company") or ""
            desc = exp.get("description") or ""
            starts = exp.get("starts_at") or {}
            ends = exp.get("ends_at") or {}
            s_year = starts.get("year", "")
            e_year = ends.get("year", "") if ends else "Present"
            duration = f"{s_year}–{e_year}" if s_year else ""
            profile.experience.append({
                "title": title, "company": company,
                "duration": duration, "description": desc[:200]
            })
            if not profile.title and title:
                profile.title = title
            if not profile.company and company:
                profile.company = company

        # Education
        for edu in (data.get("education") or [])[:3]:
            school = edu.get("school") or ""
            degree = edu.get("degree_name") or ""
            field = edu.get("field_of_study") or ""
            starts = edu.get("starts_at") or {}
            ends = edu.get("ends_at") or {}
            s_year = starts.get("year", "")
            e_year = ends.get("year", "")
            years = f"{s_year}–{e_year}" if s_year else ""
            if school:
                profile.education.append({
                    "school": school,
                    "degree": f"{degree} {field}".strip(),
                    "years": years
                })

        # Skills — can be strings or dicts
        raw_skills = data.get("skills") or []
        profile.skills = [
            (s if isinstance(s, str) else s.get("name", ""))
            for s in raw_skills[:15] if s
        ]

        if not profile.headline and profile.title and profile.company:
            profile.headline = f"{profile.title} at {profile.company}"

        return profile

    def _scrape_via_apify(self, profile_url: str) -> LinkedInProfile:
        """Fetch a LinkedIn profile via Apify LinkedIn Profile Scraper."""
        print(f"  Fetching profile via Apify: {profile_url}")
        try:
            response = requests.post(
                "https://api.apify.com/v2/acts/curious_coder~linkedin-profile-scraper/run-sync-get-dataset-items",
                params={"token": self.apify_key},
                json={"profileUrls": [profile_url]},
                timeout=60
            )
            if response.status_code == 200:
                items = response.json()
                if items and len(items) > 0:
                    return self._parse_apify_response(items[0], profile_url)
            print(f"  Apify returned {response.status_code}, falling back to Scrapin.io")
        except Exception as e:
            print(f"  Apify error: {e}, falling back to Scrapin.io")

        # Fallback to Scrapin.io if Apify fails
        if self.scrapin_key:
            return self._scrape_via_scrapin(profile_url)
        raise ValueError("Profile scraping failed. Try entering details manually.")

    def _parse_apify_response(self, data: dict, profile_url: str) -> LinkedInProfile:
        """Convert Apify LinkedIn scraper response to LinkedInProfile."""
        profile = LinkedInProfile(profile_url=profile_url)
        profile.name = data.get("fullName") or f"{data.get('firstName','')} {data.get('lastName','')}".strip()
        profile.headline = data.get("headline") or ""
        profile.about = (data.get("summary") or data.get("about") or "")[:1000]
        profile.location = data.get("location") or data.get("addressWithCountry") or ""

        # Experience
        for exp in (data.get("experiences") or data.get("positions") or [])[:6]:
            title = exp.get("title") or ""
            company = exp.get("companyName") or exp.get("company") or ""
            duration = exp.get("duration") or exp.get("dateRange") or ""
            desc = exp.get("description") or ""
            profile.experience.append({
                "title": title, "company": company,
                "duration": duration, "description": desc[:200]
            })
            if not profile.title and title:
                profile.title = title
            if not profile.company and company:
                profile.company = company

        # Education
        for edu in (data.get("educations") or data.get("schools") or [])[:3]:
            school = edu.get("schoolName") or edu.get("school") or ""
            degree = edu.get("degreeName") or edu.get("degree") or ""
            field = edu.get("fieldOfStudy") or ""
            years = edu.get("dateRange") or edu.get("years") or ""
            if school:
                profile.education.append({
                    "school": school,
                    "degree": f"{degree} {field}".strip(),
                    "years": years
                })

        # Skills
        profile.skills = [
            s.get("name") or s if isinstance(s, (str, dict)) else ""
            for s in (data.get("skills") or [])[:15]
            if s
        ]

        if not profile.headline and profile.title and profile.company:
            profile.headline = f"{profile.title} at {profile.company}"

        return profile

    def _scrape_via_serpapi_snippet(self, profile_url: str) -> LinkedInProfile:
        """
        FREE fallback: extract basic profile info from Google search snippet via SerpAPI.
        Gets name, title, company, location from the search result description.
        Not as complete as full scraping but good enough for email personalization.
        """
        print(f"  Extracting profile via SerpAPI snippet (free): {profile_url}")

        # Extract the LinkedIn username from URL for a targeted search
        username = profile_url.rstrip("/").split("/in/")[-1].split("/")[0]
        query = f'site:linkedin.com/in/{username}'

        response = requests.get(
            "https://serpapi.com/search",
            params={
                "api_key": self.serpapi_key,
                "engine": "google",
                "q": query,
                "num": 1,
                "gl": "us",
                "hl": "en"
            },
            timeout=25
        )

        profile = LinkedInProfile(profile_url=profile_url)

        if response.status_code != 200:
            print(f"  SerpAPI error {response.status_code}")
            return profile

        results = response.json().get("organic_results", [])
        if not results:
            return profile

        item = results[0]
        title_text = item.get("title", "")
        snippet = item.get("snippet", "")

        # Parse "Name - Title at Company | LinkedIn"
        title_text = re.sub(r'\s*\|\s*LinkedIn.*$', '', title_text, flags=re.IGNORECASE).strip()
        title_text = re.sub(r'\s*[-–]\s*LinkedIn.*$', '', title_text, flags=re.IGNORECASE).strip()

        parts = re.split(r'\s+[-–]\s+', title_text, maxsplit=1)
        profile.name = parts[0].strip() if parts else ""
        role_text = parts[1].strip() if len(parts) > 1 else ""

        # "Senior PM at Google" OR "Senior PM @ Google"
        at_match = re.match(r'^(.+?)\s+(?:at|@)\s+(.+)$', role_text, re.IGNORECASE)
        if at_match:
            profile.title = at_match.group(1).strip()
            profile.company = at_match.group(2).strip()
            profile.headline = role_text
        else:
            profile.headline = role_text
            profile.title = role_text

        # If company still missing, dig into the snippet
        # Snippet format: "Name · Senior Recruiter @ Technip Energies | Headline · ..."
        if not profile.company and snippet:
            comp_match = re.search(
                r'(?:at|@)\s+([A-Z][A-Za-z0-9 &\-\.]{2,50?})(?:\s*[·|]|$)',
                snippet
            )
            if comp_match:
                profile.company = comp_match.group(1).strip()

            # Also try to get title from snippet if missing
            if not profile.title:
                title_match = re.search(
                    r'·\s*([A-Za-z][A-Za-z0-9 &\-]{3,60}?)\s+(?:at|@)',
                    snippet
                )
                if title_match:
                    profile.title = title_match.group(1).strip()

        # Rebuild headline if we got title + company from snippet
        if not profile.headline and profile.title and profile.company:
            profile.headline = f"{profile.title} at {profile.company}"

        # Extract location from snippet (often "City, State · Title · ...")
        loc_match = re.search(r'^([A-Z][^·\n]{3,40}?)·', snippet)
        if loc_match:
            profile.location = loc_match.group(1).strip()

        # Use snippet as brief "about"
        profile.about = snippet[:500] if snippet else ""

        if profile.name:
            print(f"  Found via snippet: {profile.name} — {profile.headline}")
        else:
            print(f"  Could not parse profile from snippet")

        return profile

    def _scrape_via_scrapin(self, profile_url: str) -> LinkedInProfile:
        """Fetch a LinkedIn profile via Scrapin.io API."""
        print(f"  Fetching profile via Scrapin.io: {profile_url}")
        response = requests.get(
            f"{self.SCRAPIN_BASE}/profile",
            params={
                "apikey": self.scrapin_key,
                "linkedInUrl": profile_url,
            },
            timeout=60
        )

        if response.status_code == 401:
            raise ValueError("Invalid Scrapin.io API key.")
        if response.status_code == 404:
            raise ValueError(f"LinkedIn profile not found: {profile_url}")
        if response.status_code == 429:
            raise ValueError("Scrapin.io rate limit hit. Wait a moment and retry.")
        if response.status_code != 200:
            raise ValueError(f"Scrapin.io error {response.status_code}: {response.text[:200]}")

        data = response.json()
        person = data.get("person") or data
        return self._parse_scrapin_response(person, profile_url)

    def _parse_scrapin_response(self, data: dict, profile_url: str) -> LinkedInProfile:
        """Convert Scrapin.io JSON response to LinkedInProfile."""
        profile = LinkedInProfile(profile_url=profile_url)

        first = data.get("firstName") or ""
        last = data.get("lastName") or ""
        profile.name = data.get("fullName") or f"{first} {last}".strip()
        profile.headline = data.get("headline") or ""
        profile.about = (data.get("summary") or "")[:1000]

        # Location
        city = data.get("city") or ""
        state = data.get("state") or ""
        country = data.get("country") or ""
        profile.location = ", ".join(filter(None, [city, state, country]))

        # Experience
        for exp in (data.get("positions") or {}).get("positionHistory", [])[:6]:
            title = exp.get("title") or ""
            company = exp.get("companyName") or ""
            desc = exp.get("description") or ""
            s_year = exp.get("startEndDate", {}).get("start", {}).get("year", "")
            e_year = exp.get("startEndDate", {}).get("end", {}).get("year", "") or "Present"
            duration = f"{s_year}–{e_year}" if s_year else ""

            entry = {
                "title": title,
                "company": company,
                "duration": duration,
                "description": desc[:200]
            }
            profile.experience.append(entry)

            if not profile.title and title:
                profile.title = title
            if not profile.company and company:
                profile.company = company

        # Education
        for edu in (data.get("schools") or {}).get("educationHistory", [])[:3]:
            school = edu.get("schoolName") or ""
            degree = edu.get("degreeName") or ""
            field_of_study = edu.get("fieldOfStudy") or ""
            s_year = edu.get("startEndDate", {}).get("start", {}).get("year", "")
            e_year = edu.get("startEndDate", {}).get("end", {}).get("year", "")
            years = f"{s_year}–{e_year}" if s_year else ""

            if school:
                profile.education.append({
                    "school": school,
                    "degree": f"{degree} {field_of_study}".strip(),
                    "years": years
                })

        # Skills
        profile.skills = [
            s.get("name", "") for s in (data.get("skills") or [])[:15]
            if s.get("name")
        ]

        # If no headline but we have title+company, construct one
        if not profile.headline and profile.title and profile.company:
            profile.headline = f"{profile.title} at {profile.company}"

        return profile

    # ── Company Hunting ───────────────────────────────────────────────────────

    # ── Seen-people registry ─────────────────────────────────────────────────

    _SEEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seen_people.json")

    def _load_seen(self) -> dict:
        """Load the registry of already-seen LinkedIn URLs per company."""
        try:
            with open(self._SEEN_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_seen(self, seen: dict):
        """Persist the registry."""
        with open(self._SEEN_FILE, "w") as f:
            json.dump(seen, f, indent=2)

    def _mark_seen(self, company: str, urls: list[str]):
        """Add URLs to the seen registry for a company."""
        seen = self._load_seen()
        key = company.lower().strip()
        seen.setdefault(key, [])
        for url in urls:
            if url not in seen[key]:
                seen[key].append(url)
        self._save_seen(seen)

    def _filter_seen(self, company: str, results: list[dict]) -> list[dict]:
        """Remove people already seen for this company."""
        seen = self._load_seen()
        key = company.lower().strip()
        seen_urls = set(seen.get(key, []))
        fresh = [r for r in results if r.get("url", "") not in seen_urls]
        return fresh

    # ── Rotating role-term groups ─────────────────────────────────────────────

    # Each search rotates through a different group so we surface different people
    _ROLE_GROUPS = [
        '"program manager" OR "technical program manager" OR "TPM" OR "senior program manager"',
        '"recruiter" OR "talent acquisition" OR "hiring manager" OR "people operations"',
        '"product manager" OR "head of product" OR "director of product" OR "VP product"',
        '"chief of staff" OR "operations manager" OR "director of operations" OR "COO"',
        '"engineering manager" OR "director of engineering" OR "VP engineering" OR "CTO"',
        '"strategy" OR "business development" OR "partnerships" OR "growth"',
    ]

    def search_people_at_company(
        self,
        company_name: str,
        max_results: int = 10
    ) -> list[dict]:
        """
        Find people to target at a company.
        Rotates role groups + SerpAPI pagination to return fresh faces each time.
        Uses SerpAPI (preferred) or Google Custom Search as fallback.
        """
        if self.serpapi_key:
            return self._hunt_via_serpapi(company_name, max_results)
        elif self.google_api_key and self.google_cse_id:
            return self._hunt_via_google(company_name, max_results)
        else:
            raise ValueError(
                "Set SERPAPI_KEY (free, 250 searches at serpapi.com) to use the hunt feature."
            )

    def _hunt_via_serpapi(self, company_name: str, max_results: int) -> list[dict]:
        """Use SerpAPI to find LinkedIn profiles at a company — always fresh faces."""
        print(f"  Searching via SerpAPI for people at {company_name}...")

        # Pick which role group to use based on how many times this company's been searched
        seen = self._load_seen()
        key = company_name.lower().strip()
        search_count = len(seen.get(key, [])) // max(max_results, 1)
        role_terms = self._ROLE_GROUPS[search_count % len(self._ROLE_GROUPS)]

        # Paginate: start further into results each round
        start_offset = (search_count % 5) * 10

        print(f"  Role group #{search_count % len(self._ROLE_GROUPS)}, offset={start_offset}")

        all_results = []

        # Fetch up to 2 pages to get enough fresh results after filtering
        for start in [start_offset, start_offset + 10]:
            response = requests.get(
                "https://serpapi.com/search",
                params={
                    "api_key": self.serpapi_key,
                    "engine": "google",
                    "q": f'site:linkedin.com/in "{company_name}" ({role_terms})',
                    "num": 10,
                    "start": start,
                    "gl": "us",
                    "hl": "en"
                },
                timeout=20
            )

            if response.status_code != 200:
                print(f"  SerpAPI error: {response.status_code}")
                break

            items = response.json().get("organic_results", [])
            if not items:
                break

            for item in items:
                url = item.get("link", "")
                if "linkedin.com/in/" not in url:
                    continue
                title_text = item.get("title", "")
                snippet = item.get("snippet", "")
                name, title = self._parse_google_result(title_text, company_name)
                if not name:
                    continue
                clean_url = url.split("?")[0].rstrip("/")
                all_results.append({
                    "name": name,
                    "title": title,
                    "url": clean_url,
                    "company": company_name,
                    "relevance_score": self._score_title(title),
                    "snippet": snippet[:150]
                })

            if len(all_results) >= max_results * 3:
                break  # Enough candidates, stop fetching

        # Filter out already-seen people
        fresh = self._filter_seen(company_name, all_results)
        print(f"  {len(all_results)} found, {len(fresh)} are fresh (unseen)")

        # If we've seen everyone, reset the seen list for this company and start fresh
        if not fresh and all_results:
            print(f"  All results seen before — resetting seen list for {company_name}")
            seen = self._load_seen()
            seen[company_name.lower().strip()] = []
            self._save_seen(seen)
            fresh = all_results

        # Deduplicate by URL within this batch
        seen_urls = set()
        unique = []
        for r in fresh:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                unique.append(r)

        unique.sort(key=lambda x: x["relevance_score"], reverse=True)
        final = unique[:max_results]

        # Mark these as seen so next search skips them
        self._mark_seen(company_name, [r["url"] for r in final])

        return final

    def _hunt_via_google(self, company_name: str, max_results: int) -> list[dict]:
        """Use Google Custom Search API to find LinkedIn profiles at a company."""
        print(f"  Searching Google for people at {company_name}...")

        role_terms = (
            '"program manager" OR "product manager" OR "technical program manager" '
            'OR "chief of staff" OR "recruiter" OR "talent acquisition" '
            'OR "engineering manager" OR "director" OR "operations"'
        )
        query = f'site:linkedin.com/in "{company_name}" ({role_terms})'

        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self.google_api_key,
                "cx": self.google_cse_id,
                "q": query,
                "num": min(max_results, 10)
            },
            timeout=10
        )

        if response.status_code != 200:
            print(f"  Google Search error: {response.status_code}")
            return []

        items = response.json().get("items", [])
        results = []

        for item in items:
            url = item.get("link", "")
            if "linkedin.com/in/" not in url:
                continue

            title_text = item.get("title", "")
            snippet = item.get("snippet", "")

            name, title = self._parse_google_result(title_text, company_name)
            if not name:
                continue

            clean_url = url.split("?")[0].rstrip("/")

            results.append({
                "name": name,
                "title": title,
                "url": clean_url,
                "company": company_name,
                "relevance_score": self._score_title(title),
                "snippet": snippet[:150]
            })

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:max_results]

    def _parse_google_result(self, title_text: str, company: str) -> tuple[str, str]:
        """
        Parse name and title from a Google search result title.
        e.g. "Jane Smith - Senior TPM at Google | LinkedIn" → ("Jane Smith", "Senior TPM at Google")
        """
        title_text = re.sub(r'\s*\|\s*LinkedIn.*$', '', title_text).strip()
        title_text = re.sub(r'\s*-\s*LinkedIn.*$', '', title_text).strip()

        parts = re.split(r'\s+[-–|]\s+', title_text, maxsplit=1)
        name = parts[0].strip() if parts else ""
        role = parts[1].strip() if len(parts) > 1 else ""

        role_clean = re.sub(rf'\s+at\s+{re.escape(company)}.*$', '', role, flags=re.IGNORECASE).strip()

        if not re.match(r'^[A-Za-z][a-zA-Z\s\-\.\']{2,40}$', name):
            return "", ""

        return name, role_clean or role

    def _score_title(self, title: str) -> int:
        """Score a job title by relevance for PM/TPM outreach."""
        title_lower = title.lower()
        priority_map = {
            "hiring manager": 10, "talent acquisition": 9, "recruiter": 8,
            "chief of staff": 9, "cto": 9, "vp of engineering": 8,
            "director of engineering": 8, "head of product": 8,
            "director of product": 8, "technical program manager": 7,
            "program manager": 7, "product manager": 6,
            "engineering manager": 6, "operations manager": 5,
            "director": 4, "manager": 3,
        }
        score = 0
        for kw, points in priority_map.items():
            if kw in title_lower:
                score = max(score, points)
        return score
