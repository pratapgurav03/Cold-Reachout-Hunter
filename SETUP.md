# Cold Reachout Hunter — Setup Guide

## What this does
1. Hunts LinkedIn for the right people at target companies (hiring managers, TPMs, Chiefs of Staff, etc.)
2. Scrapes their profile to personalize your email
3. Finds their email via Hunter.io or smart pattern guessing
4. Generates a short, human-sounding cold email using Claude AI
5. Shows you the draft → you approve → sends from pratap.gurav03@gmail.com with your resume attached

---

## One-time setup (takes ~10 minutes)

### Step 1 — Install Python packages
```bash
cd "COLD REACHOUT HUNTER"
pip3 install -r requirements.txt
playwright install chromium
```

### Step 2 — Set up your .env file
```bash
cp .env.example .env
```
Open `.env` and fill in:

**ANTHROPIC_API_KEY** (required)
- Go to https://console.anthropic.com/ → API Keys → Create key
- Paste it in .env

**GMAIL_APP_PASSWORD** (required for sending)
- Your Gmail must have 2-Factor Authentication enabled
- Go to https://myaccount.google.com/apppasswords
- Select "Mail" + "Mac" → click Generate
- Copy the 16-character password into .env

**HUNTER_API_KEY** (optional, free tier = 25/month)
- Go to https://hunter.io/users/sign_up
- Copy your API key into .env
- Without this, the tool guesses emails using common patterns (first.last@company.com etc.)

### Step 3 — Verify setup
```bash
python3 cold_outreach.py config
```
All four items should show ✅.

---

## How to use it

### Hunt — find who to target at a company
```bash
python3 cold_outreach.py hunt --company "Siemens Energy"
python3 cold_outreach.py hunt --company "McKinsey" --max 15
```
This opens LinkedIn in Chrome, finds relevant people, and ranks them by title relevance.
**You must be logged into LinkedIn in that browser window.**

---

### Send — full pipeline to one person
```bash
# From a LinkedIn URL directly:
python3 cold_outreach.py send --url "https://linkedin.com/in/their-profile"

# Let the tool find the best person at a company automatically:
python3 cold_outreach.py send --company "Google" --auto-hunt

# Change email type (default is internship):
python3 cold_outreach.py send --url "https://..." --type informational
python3 cold_outreach.py send --url "https://..." --type networking
python3 cold_outreach.py send --url "https://..." --type referral

# Skip the extra context prompt (non-interactive):
python3 cold_outreach.py send --url "https://..." --no-prompt
```

**The send flow:**
1. Scrapes their LinkedIn profile
2. Finds their email (Hunter.io or pattern guess)
3. Generates a personalized email using Claude AI
4. Shows you the full draft with personalization notes
5. Asks: Send now / Edit first / Save to Gmail drafts / Skip
6. Logs the outreach to outreach_log.csv

Your resume (`Pratap_Gurav_Resume.pdf`) is **always attached**.

---

### Status — see your outreach dashboard
```bash
python3 cold_outreach.py status
python3 cold_outreach.py status --n 20
```

### Follow-ups — see who you should follow up with
```bash
python3 cold_outreach.py followup
```
Shows everyone you emailed 7+ days ago with no response.

### Update status — when someone replies
```bash
python3 cold_outreach.py update --email jane@google.com --status replied
python3 cold_outreach.py update --email john@siemens.com --status interview_scheduled
```

---

## Email types

| Type | When to use |
|------|-------------|
| `internship` | Asking about Fall 2026 intern roles (default) |
| `informational` | Requesting a 15-min chat, no job ask |
| `networking` | Building a connection, leading with their work |
| `referral` | Asking them to refer you internally |

---

## Target companies by sector (your sweet spot)

**Energy & Industrial**
- Siemens Energy, GE Vernova, Honeywell, Exxon, Shell, Schlumberger, Baker Hughes, Technip Energies

**Big Tech (PM/TPM tracks)**
- Google (TPM), Microsoft (PM), Amazon (PgM), Meta, Apple

**Startups & Scale-ups**
- Look for Series B/C companies on TechCrunch, LinkedIn Jobs, Y Combinator

**Consulting**
- McKinsey Operations, BCG Platinion, Accenture Tech Consulting, Deloitte Tech

---

## Tips
- Start with `hunt` to find the right person before committing to a full send
- Use `--type informational` for senior people — less aggressive, higher response rate
- Always review the draft before sending — AI is good but not perfect
- Follow up after 7 days if no response (the tool will remind you)
- Don't spam the same company — track your outreach in outreach_log.csv

---

## Files
```
COLD REACHOUT HUNTER/
├── cold_outreach.py          ← Main CLI (start here)
├── Pratap_Gurav_Resume.pdf   ← Auto-attached to every email
├── outreach_log.csv          ← Auto-created, tracks all outreach
├── drafts/                   ← Auto-created, saved draft emails
├── modules/
│   ├── linkedin_scraper.py   ← LinkedIn browser automation
│   ├── email_finder.py       ← Hunter.io + pattern guessing
│   ├── email_generator.py    ← Claude AI email writer
│   ├── email_sender.py       ← Gmail SMTP sender
│   └── tracker.py            ← Outreach log management
├── .env                      ← Your API keys (never commit this)
├── .env.example              ← Template
└── requirements.txt          ← Python dependencies
```
