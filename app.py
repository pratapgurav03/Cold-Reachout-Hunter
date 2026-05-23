#!/usr/bin/env python3
"""
Cold Reachout Hunter — Flask Web Backend
Runs on http://localhost:5050
"""

import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from modules.linkedin_scraper import LinkedInScraper, LinkedInProfile
from modules.email_finder import find_email
from modules.email_generator import generate_cold_email, EMAIL_TYPES
from modules.email_sender import EmailSender, save_draft_file
from modules.tracker import OutreachTracker

app = Flask(__name__)
CORS(app)

# Global state for long-running scrape jobs
_scrape_jobs = {}  # job_id -> {status, result, error}
_scrape_lock = threading.Lock()

tracker = OutreachTracker()
sender = EmailSender(app_password=os.getenv("GMAIL_APP_PASSWORD"))


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── Config ───────────────────────────────────────────────────────────────────

@app.route("/api/config")
def api_config():
    resume = Path(__file__).parent / "Pratap_Gurav_Resume.pdf"
    return jsonify({
        "anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "hunter_key": bool(os.getenv("HUNTER_API_KEY")),
        "gmail_password": bool(os.getenv("GMAIL_APP_PASSWORD")),
        "resume_found": resume.exists(),
        "sender_email": "pratap.gurav03@gmail.com"
    })


# ─── Dashboard / Stats ────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    import csv
    log_path = Path(__file__).parent / "outreach_log.csv"
    if not log_path.exists():
        return jsonify({
            "total": 0, "sent": 0, "replied": 0,
            "interview_scheduled": 0, "followups_due": 0,
            "recent": []
        })

    rows = []
    with open(log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    by_status = {}
    for row in rows:
        s = row.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    followups = tracker.get_follow_ups_due()
    recent = list(reversed(rows[-8:])) if rows else []

    return jsonify({
        "total": len(rows),
        "sent": by_status.get("sent", 0),
        "replied": by_status.get("replied", 0),
        "interview_scheduled": by_status.get("interview_scheduled", 0),
        "draft": by_status.get("draft", 0),
        "followups_due": len(followups),
        "recent": recent,
        "followups": followups[:5]
    })


# ─── Hunt ─────────────────────────────────────────────────────────────────────

@app.route("/api/hunt", methods=["POST"])
def api_hunt():
    data = request.json or {}
    company = data.get("company", "").strip()
    max_results = int(data.get("max_results", 10))

    if not company:
        return jsonify({"error": "Company name required"}), 400

    try:
        scraper = LinkedInScraper(headless=False)
        people = scraper.search_people_at_company(company, max_results=max_results)
        return jsonify({"company": company, "results": people})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Profile Scrape ───────────────────────────────────────────────────────────

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data = request.json or {}
    linkedin_url = data.get("url", "").strip()

    if not linkedin_url:
        return jsonify({"error": "LinkedIn URL required"}), 400

    try:
        scraper = LinkedInScraper(headless=False)
        profile = scraper.scrape_profile(linkedin_url)
        return jsonify({
            "name": profile.name,
            "title": profile.title,
            "company": profile.company,
            "headline": profile.headline,
            "location": profile.location,
            "about": profile.about,
            "experience": profile.experience,
            "education": profile.education,
            "recent_posts": profile.recent_posts,
            "profile_url": profile.profile_url,
            "summary": profile.summary_for_ai()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Email Finder ─────────────────────────────────────────────────────────────

@app.route("/api/find-email", methods=["POST"])
def api_find_email():
    data = request.json or {}
    full_name = data.get("name", "").strip()
    company = data.get("company", "").strip()

    if not full_name or not company:
        return jsonify({"error": "Name and company required"}), 400

    result = find_email(
        full_name=full_name,
        company_name=company,
        hunter_api_key=os.getenv("HUNTER_API_KEY")
    )
    return jsonify(result)


# ─── Generate Email ───────────────────────────────────────────────────────────

@app.route("/api/generate-email", methods=["POST"])
def api_generate_email():
    data = request.json or {}
    profile_data = data.get("profile", {})
    email_type = data.get("email_type", "internship")
    custom_context = data.get("custom_context", "")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    # Rebuild profile object
    profile = LinkedInProfile(
        name=profile_data.get("name", ""),
        title=profile_data.get("title", ""),
        company=profile_data.get("company", ""),
        headline=profile_data.get("headline", ""),
        location=profile_data.get("location", ""),
        about=profile_data.get("about", ""),
        experience=profile_data.get("experience", []),
        education=profile_data.get("education", []),
        recent_posts=profile_data.get("recent_posts", []),
        profile_url=profile_data.get("profile_url", "")
    )

    try:
        result = generate_cold_email(
            target_profile=profile,
            email_type=email_type,
            custom_context=custom_context or None,
            anthropic_api_key=api_key
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Save Draft ───────────────────────────────────────────────────────────────

@app.route("/api/save-draft", methods=["POST"])
def api_save_draft():
    data = request.json or {}
    to_email = data.get("to_email", "")
    to_name = data.get("to_name", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    drafts_folder = str(Path(__file__).parent / "drafts")
    draft_file = save_draft_file(to_email, to_name, subject, body, drafts_folder)

    return jsonify({
        "saved": True,
        "draft_file": draft_file,
        "message": f"Draft saved to {Path(draft_file).name}"
    })


# ─── Send Email ───────────────────────────────────────────────────────────────

@app.route("/api/send", methods=["POST"])
def api_send():
    """
    ONLY called after user explicitly clicks 'Approve & Send' in the UI.
    Logs to tracker regardless of outcome.
    """
    data = request.json or {}
    to_email = data.get("to_email", "")
    to_name = data.get("to_name", "")
    subject = data.get("subject", "")
    body_text = data.get("body_text", "")
    body_html = data.get("body_html", "")
    email_type = data.get("email_type", "internship")
    linkedin_url = data.get("linkedin_url", "")
    target_title = data.get("target_title", "")
    target_company = data.get("target_company", "")
    notes = data.get("notes", "")

    if not to_email or not subject or not body_text:
        return jsonify({"error": "Missing required fields"}), 400

    # Check Gmail config
    if not os.getenv("GMAIL_APP_PASSWORD"):
        return jsonify({
            "error": "GMAIL_APP_PASSWORD not configured. Add it to your .env file."
        }), 500

    try:
        from modules.email_sender import send_via_smtp
        resume_path = Path(__file__).parent / "Pratap_Gurav_Resume.pdf"
        success = send_via_smtp(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html or None,
            resume_path=resume_path if resume_path.exists() else None
        )

        status = "sent" if success else "failed"
        tracker.log_outreach(
            target_name=to_name,
            target_email=to_email,
            target_title=target_title,
            target_company=target_company,
            linkedin_url=linkedin_url,
            email_type=email_type,
            subject=subject,
            status=status,
            notes=notes
        )

        return jsonify({
            "success": success,
            "status": status,
            "message": f"Email {'sent to' if success else 'failed for'} {to_name}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Tracker ──────────────────────────────────────────────────────────────────

@app.route("/api/tracker")
def api_tracker():
    import csv
    log_path = Path(__file__).parent / "outreach_log.csv"
    if not log_path.exists():
        return jsonify({"entries": []})

    with open(log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return jsonify({"entries": list(reversed(rows))})


@app.route("/api/tracker/update", methods=["POST"])
def api_tracker_update():
    data = request.json or {}
    email = data.get("email", "")
    new_status = data.get("status", "")
    notes = data.get("notes", "")

    valid = ["sent", "draft", "replied", "bounced", "interview_scheduled", "no_response"]
    if new_status not in valid:
        return jsonify({"error": f"Invalid status. Use: {', '.join(valid)}"}), 400

    success = tracker.update_status(email, new_status, notes)
    return jsonify({"updated": success})


@app.route("/api/tracker/log-draft", methods=["POST"])
def api_log_draft():
    """Log a draft (saved but not sent yet)."""
    data = request.json or {}
    tracker.log_outreach(
        target_name=data.get("to_name", ""),
        target_email=data.get("to_email", ""),
        target_title=data.get("target_title", ""),
        target_company=data.get("target_company", ""),
        linkedin_url=data.get("linkedin_url", ""),
        email_type=data.get("email_type", "internship"),
        subject=data.get("subject", ""),
        status="draft",
        notes=data.get("notes", "")
    )
    return jsonify({"logged": True})


# ─── Email types list ─────────────────────────────────────────────────────────

@app.route("/api/email-types")
def api_email_types():
    return jsonify({k: v["goal"] for k, v in EMAIL_TYPES.items()})


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Replit sets PORT env var automatically; local default is 5050
    port = int(os.environ.get("PORT", 5050))
    is_replit = bool(os.environ.get("REPL_ID"))

    url = f"https://{os.environ.get('REPL_SLUG','app')}.{os.environ.get('REPL_OWNER','user')}.repl.co" \
          if is_replit else f"http://localhost:{port}"

    print(f"""
╔══════════════════════════════════════════════════════╗
║         COLD REACHOUT HUNTER — Web Server            ║
║   Open: {url:<43}║
╚══════════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
