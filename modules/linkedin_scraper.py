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
    SCRAPIN_BASE = "https://api.scrapin.io/enrichment"

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
        self.scrapin_key = os.getenv("SCRAPIN_API_KEY")
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID")

    # ── Profile Scraping ──────────────────────────────────────────────────────

    def scrape_profile(self, profile_url: str) -> LinkedInProfile:
        """Fetch a LinkedIn profile via Scrapin.io API."""
        if not self.scrapin_key:
            raise ValueError(
                "SCRAPIN_API_KEY not set. "
                "Get 100 free credits/month at https://scrapin.io"
            )

        print(f"  Fetching profile via Scrapin.io: {profile_url}")
        response = requests.get(
            f"{self.SCRAPIN_BASE}/profile",
            params={
                "apikey": self.scrapin_key,
                "linkedInUrl": profile_url,
            },
            timeout=20
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

        # Scrapin wraps data in a "person" key
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

    def search_people_at_company(
        self,
        company_name: str,
        max_results: int = 10
    ) -> list[dict]:
        """
        Find people to target at a company.
        Uses Google Custom Search to find LinkedIn profiles.
        """
        if self.google_api_key and self.google_cse_id:
            return self._hunt_via_google(company_name, max_results)
        else:
            raise ValueError(
                "Set GOOGLE_API_KEY + GOOGLE_CSE_ID (free, 100/day) to use the hunt feature. "
                "Get them at https://developers.google.com/custom-search/v1/introduction "
                "and https://cse.google.com"
            )

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
