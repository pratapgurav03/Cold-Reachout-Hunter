# Deploy to Replit — Step by Step

## What you need first (get these before starting)

| Key | Where to get it | Cost |
|-----|----------------|------|
| `ANTHROPIC_API_KEY` | console.anthropic.com | Pay per use (~$0.001/email) |
| `PROXYCURL_API_KEY` | nubela.co/proxycurl | Free: 10 credits, then $0.01/profile |
| `GMAIL_APP_PASSWORD` | myaccount.google.com/apppasswords | Free |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | developers.google.com/custom-search | Free: 100 searches/day |
| `HUNTER_API_KEY` | hunter.io | Optional — free: 25/month |

---

## Step 1 — Get your API keys

### Proxycurl (LinkedIn data)
1. Go to https://nubela.co/proxycurl
2. Sign up → Dashboard → copy your API key
3. Free tier gives 10 credits (= 10 profile scrapes). $9 buys 900 more.

### Google Custom Search (for Hunt feature)
1. Go to https://developers.google.com/custom-search/v1/introduction
2. Click "Get a Key" → create a project → copy the API key
3. Go to https://cse.google.com/cse/create/new
4. Set "Search the entire web" → Create
5. Click on your engine → copy the Search Engine ID (cx)

### Gmail App Password
1. Make sure 2-Step Verification is ON at myaccount.google.com/security
2. Go to myaccount.google.com/apppasswords
3. Name it "Cold Reachout" → Generate → copy the 16-char password

---

## Step 2 — Create a Replit account and new Repl

1. Go to https://replit.com and sign up (free)
2. Click **+ Create Repl**
3. Choose **Import from GitHub** if your code is on GitHub, OR choose **Python** template

---

## Step 3 — Upload your files to Replit

**Option A — GitHub (recommended)**
1. Push your project folder to a GitHub repo
2. On Replit: Create Repl → Import from GitHub → paste your repo URL

**Option B — Upload manually**
1. Create a Python repl
2. Use Replit's file uploader to upload all files:
   - `app.py`
   - `modules/` folder (all 5 files)
   - `templates/index.html`
   - `requirements.txt`
   - `.replit`
   - `Pratap_Gurav_Resume.pdf`

---

## Step 4 — Set your secrets (API keys) in Replit

**Never paste API keys in code files.** Use Replit Secrets instead:

1. In your Repl, click the **lock icon** (🔒 Secrets) in the left sidebar
2. Add each key:

| Secret Name | Value |
|-------------|-------|
| `ANTHROPIC_API_KEY` | sk-ant-... |
| `PROXYCURL_API_KEY` | your proxycurl key |
| `GMAIL_APP_PASSWORD` | xxxx xxxx xxxx xxxx |
| `GOOGLE_API_KEY` | AIza... |
| `GOOGLE_CSE_ID` | your CSE ID |
| `HUNTER_API_KEY` | (optional) |

---

## Step 5 — Run it

1. Click the **Run** button (▶) in Replit
2. Replit installs packages automatically from `requirements.txt`
3. Your app URL appears at the top — looks like:
   `https://cold-reachout-hunter.yourusername.repl.co`
4. Open that URL — your dashboard loads

---

## Step 6 — Keep it alive (free tier limitation)

Replit free tier **sleeps after 30 min of inactivity**. Two options:

**Option A — UptimeRobot (free)**
1. Go to https://uptimerobot.com → sign up free
2. Add monitor → HTTP(S) → paste your Replit URL
3. Set interval: every 5 minutes
4. Your app stays awake 24/7

**Option B — Replit Hacker plan ($7/month)**
- "Always On" feature keeps it running permanently

---

## How it works differently from local

| Feature | Local (Playwright) | Cloud (Proxycurl) |
|---------|-------------------|-------------------|
| LinkedIn scraping | Opens Chrome on your Mac | API call — no browser |
| Company hunt | Browser search | Google Custom Search API |
| LinkedIn login required | Yes | No |
| Works 24/7 | Only when Mac is on | Always |
| Credit cost | Free | $0.01/profile after free tier |

---

## Troubleshooting

**"Module not found"** → Click Shell in Replit, run: `pip install -r requirements.txt`

**"Proxycurl 401 error"** → Check your PROXYCURL_API_KEY in Secrets

**"Google Search not working"** → Make sure both GOOGLE_API_KEY and GOOGLE_CSE_ID are set

**"Gmail send failed"** → Double-check GMAIL_APP_PASSWORD — use the App Password, not your regular Gmail password

**App goes to sleep** → Set up UptimeRobot (Step 6 above)
