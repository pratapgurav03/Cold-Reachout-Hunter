"""
AI Email Generator Module
--------------------------
Uses Claude API to generate hyper-personalized cold emails based on:
- Target's LinkedIn profile
- Their company context
- Pratap's resume highlights
- The specific ask (internship / informational / referral)

Requires ANTHROPIC_API_KEY in your .env file.
"""

import anthropic
from typing import Optional

from modules.linkedin_scraper import LinkedInProfile


# ─── Pratap's profile context ──────────────────────────────────────────────────
SENDER_PROFILE = """
Name: Pratap Gurav
Email: pratap.gurav03@gmail.com
LinkedIn: linkedin.com/in/pratapgurav
Phone: +1 (929) 757-0479
Location: New York, NY (open to relocation across the U.S.)
Education: NYU - Master's in Management of Technology (Aug 2025 – May 2027)
           Institute of Chemical Technology, Mumbai - Integrated Master's in Chemical Engineering

Professional Summary:
Technical Project Manager with 2+ years leading cross-functional programs delivering $1.7M+ in
cost savings. Engineer by training, Manager by design. Experience spans energy, industrial, and
technology sectors. Currently at NYU studying Management of Technology.

Key Experience:
- Henkel (Jan 2024 – Jul 2025): Managed 10+ concurrent projects across $1.5M+ annual cost reduction
  portfolio, Power BI dashboards, ISO 9001 compliance across 6 countries, 2000+ internal customers.
- IVP Ltd (Sep–Dec 2023): Led Foundry Adhesives initiative, $200K+ cost reductions, 40% ahead of schedule.
- Technip Energies (Jul–Oct 2022): Process Engineering Intern, heat exchanger optimization, P&IDs.
- LeaseGuard AI (April 2026): Built multilingual AI voice agent at GDG NYC Hackathon (NYU Tandon).

Key Skills: Python, Power BI, Agile, Waterfall, Jira, Aspen Plus, ISO 9001/14001/45001,
Should-Cost Modeling, BOM Analysis, Stakeholder Management, AI Workflow Design.

Target: Fall 2026 internship in project management, technical operations, or cross-functional execution.
Sectors: Energy, Industrial, Technology, Consulting.
"""

# ─── Email type templates / tone guides ────────────────────────────────────────
EMAIL_TYPES = {
    "internship": {
        "goal": "Ask about Fall 2026 internship opportunities (PM, TPM, operations, or strategy roles)",
        "tone": "Professional but personable. Show genuine interest in their work. Be specific about the role fit.",
        "cta": "Ask for a 15-minute chat or to be considered for any open Fall 2026 intern roles",
        "subject_style": "Specific, references their company + Fall 2026 interest"
    },
    "informational": {
        "goal": "Request a 15-minute informational conversation about their career path / company",
        "tone": "Curious and respectful. Frame it as learning from their experience, not asking for a job.",
        "cta": "Ask for 15 minutes at their convenience",
        "subject_style": "Mentions common ground (NYU, engineering background, etc.)"
    },
    "referral": {
        "goal": "Ask if they'd be willing to refer you for open PM/TPM roles at their company",
        "tone": "Direct and confident. Show you've done research on the company.",
        "cta": "Ask if they can share your resume internally or make an intro to the hiring team",
        "subject_style": "Specific role title + mutual connection if any"
    },
    "networking": {
        "goal": "Build a genuine professional connection without a specific immediate ask",
        "tone": "Warm and curious. Lead with something specific you admire about their work.",
        "cta": "Suggest a virtual coffee chat",
        "subject_style": "Reference something specific from their profile or recent post"
    }
}


def generate_cold_email(
    target_profile: LinkedInProfile,
    email_type: str = "internship",
    custom_context: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    model: str = "claude-haiku-4-5-20251001"
) -> dict:
    """
    Generate a personalized cold email.

    Returns:
        {
            "subject": str,
            "body_text": str,       # plain text version
            "body_html": str,       # HTML version
            "personalization_notes": list[str],  # what was personalized
        }
    """
    if not anthropic_api_key:
        import os
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Add it to your .env file.")

    email_config = EMAIL_TYPES.get(email_type, EMAIL_TYPES["internship"])

    # Build context for the AI
    profile_summary = target_profile.summary_for_ai()
    if not profile_summary.strip():
        profile_summary = f"Name: {target_profile.name}\nCompany: {target_profile.company}\nTitle: {target_profile.title}"

    prompt = f"""You are writing a cold outreach email on behalf of Pratap Gurav.

## SENDER PROFILE
{SENDER_PROFILE}

## TARGET PERSON'S LINKEDIN PROFILE
{profile_summary}

## EMAIL TYPE
Goal: {email_config['goal']}
Tone: {email_config['tone']}
CTA: {email_config['cta']}
Subject style: {email_config['subject_style']}

{f"## ADDITIONAL CONTEXT FROM USER{chr(10)}{custom_context}" if custom_context else ""}

## INSTRUCTIONS
1. Write a compelling cold email that feels HUMAN and NOT like a template.
2. Reference something SPECIFIC from their profile (their role, company initiatives, a post they made, their background).
3. Keep it SHORT — under 200 words for the body. Busy people don't read long emails.
4. Don't use buzzwords like "leverage", "synergy", "game-changer", "transformative".
5. Don't start with "I hope this email finds you well" or generic openers.
6. Connect Pratap's specific experience to something relevant to them or their company.
7. One clear ask at the end. Not multiple asks.
8. Sign off as: Pratap Gurav | NYU Management of Technology | linkedin.com/in/pratapgurav

## OUTPUT FORMAT
Respond with exactly this JSON structure (no markdown, no extra text):
{{
  "subject": "the email subject line",
  "body": "the full email body in plain text",
  "personalization_used": ["list", "of", "specific", "things", "you", "referenced", "from", "their", "profile"]
}}
"""

    client = anthropic.Anthropic(api_key=anthropic_api_key)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    raw = response.content[0].text.strip()

    # Handle case where model wraps in markdown code blocks
    if raw.startswith("```"):
        raw = re.sub(r"```(?:json)?\n?", "", raw).strip("` \n")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract manually
        data = {
            "subject": "Fall 2026 Internship Opportunity Inquiry",
            "body": raw,
            "personalization_used": []
        }

    # Build HTML version
    body_text = data.get("body", "")
    body_html = _text_to_html(body_text)

    return {
        "subject": data.get("subject", ""),
        "body_text": body_text,
        "body_html": body_html,
        "personalization_notes": data.get("personalization_used", [])
    }


def _text_to_html(text: str) -> str:
    """Convert plain text email to simple HTML."""
    lines = text.split("\n")
    html_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            html_lines.append(f"<p style='margin:0 0 12px 0;font-family:Arial,sans-serif;font-size:14px;color:#333;'>{stripped}</p>")
        else:
            html_lines.append("<br>")

    return f"""<!DOCTYPE html>
<html>
<body style='max-width:600px;margin:20px auto;padding:0 20px;'>
{"".join(html_lines)}
</body>
</html>"""


def preview_email(email_data: dict, target_name: str, target_email: str) -> None:
    """Pretty-print the generated email for review."""
    print("\n" + "═" * 60)
    print("📧  EMAIL PREVIEW")
    print("═" * 60)
    print(f"To:      {target_name} <{target_email}>")
    print(f"From:    Pratap Gurav <pratap.gurav03@gmail.com>")
    print(f"Subject: {email_data['subject']}")
    print("─" * 60)
    print(email_data['body_text'])
    print("─" * 60)
    if email_data.get('personalization_notes'):
        print("🎯 Personalization used:")
        for note in email_data['personalization_notes']:
            print(f"   • {note}")
    print("═" * 60)


import re  # needed for text processing above


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # Quick test with a mock profile
    mock_profile = LinkedInProfile(
        name="Sarah Chen",
        title="Senior Technical Program Manager",
        company="Google",
        headline="TPM @ Google | Building infrastructure at scale",
        location="San Francisco, CA",
        about="Leading large-scale technical programs at Google Cloud...",
        experience=[
            {"title": "Senior TPM", "company": "Google", "duration": "3 yrs"},
            {"title": "PM", "company": "Microsoft", "duration": "2 yrs"},
        ]
    )

    result = generate_cold_email(
        target_profile=mock_profile,
        email_type="internship",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
    )
    preview_email(result, "Sarah Chen", "sarah.chen@google.com")
