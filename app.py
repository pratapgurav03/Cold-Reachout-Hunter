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
from typing import Optional
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from modules.linkedin_scraper import LinkedInScraper, LinkedInProfile
from modules.email_finder import find_email
from modules.email_generator import generate_cold_email, EMAIL_TYPES, generate_followup_email
from modules.email_sender import EmailSender, save_draft_file, save_draft_to_gmail
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
    # Optional tracker fields passed from the compose panel
    target_title = data.get("target_title", "")
    target_company = data.get("target_company", "")
    linkedin_url = data.get("linkedin_url", "")
    email_type = data.get("email_type", "internship")

    app_password = os.getenv("GMAIL_APP_PASSWORD")

    # Try saving to Gmail Drafts via IMAP first
    resume_override = data.get("resume_filename")  # optional manual override from compose panel
    resume_path = (RESUMES_DIR / resume_override) if resume_override else _get_resume_for_type(email_type)

    if app_password:
        message_id = save_draft_to_gmail(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_text=body,
            app_password=app_password,
            resume_path=resume_path if resume_path and resume_path.exists() else None
        )
        if message_id:
            # Log to tracker so follow-up engine can find the Message-ID later
            tracker.log_outreach(
                target_name=to_name,
                target_email=to_email,
                target_title=target_title,
                target_company=target_company,
                linkedin_url=linkedin_url,
                email_type=email_type,
                subject=subject,
                status="draft",
                notes="Saved to Gmail Drafts",
                message_id=message_id
            )
            return jsonify({
                "saved": True,
                "message_id": message_id,
                "message": "Draft saved to Gmail Drafts ✓ (with resume attached)"
            })

    # Fallback: save locally
    drafts_folder = str(Path(__file__).parent / "drafts")
    draft_file = save_draft_file(to_email, to_name, subject, body, drafts_folder)
    return jsonify({
        "saved": True,
        "draft_file": draft_file,
        "message": f"Draft saved locally: {Path(draft_file).name}"
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
        resume_path = _get_resume_for_type(email_type)
        message_id = send_via_smtp(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html or None,
            resume_path=resume_path
        )

        success = bool(message_id)
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
            notes=notes,
            message_id=message_id or ""
        )

        return jsonify({
            "success": success,
            "status": status,
            "message": f"Email {'sent to' if success else 'failed for'} {to_name}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Bulk Draft ───────────────────────────────────────────────────────────────

@app.route("/api/bulk-draft", methods=["POST"])
def api_bulk_draft():
    """
    For each person in the list:
      1. Scrape LinkedIn profile snippet (SerpAPI)
      2. Find email (Hunter.io)
      3. Generate personalized email (Claude AI)
      4. Save to Gmail Drafts (IMAP)
    Returns a progress stream via SSE or final summary.
    """
    data = request.json or {}
    people = data.get("people", [])        # [{name, url, title, company}, ...]
    email_type = data.get("email_type", "internship")
    custom_context = data.get("custom_context", "")

    if not people:
        return jsonify({"error": "No people provided"}), 400

    api_key = os.getenv("ANTHROPIC_API_KEY")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    scraper = LinkedInScraper(headless=False)
    results = []

    for person in people:
        name = person.get("name", "")
        url = person.get("url", "")
        company = person.get("company", "")
        result = {"name": name, "url": url, "status": "pending", "email": "", "subject": ""}

        try:
            # Step 1: scrape profile
            profile = scraper.scrape_profile(url) if url else LinkedInProfile(
                name=name,
                title=person.get("title", ""),
                company=company
            )

            # Step 2: find email
            email_result = find_email(
                full_name=profile.name or name,
                company_name=profile.company or company,
                hunter_api_key=os.getenv("HUNTER_API_KEY")
            )
            found_email = email_result.get("email") or ""
            result["email"] = found_email
            result["email_confidence"] = email_result.get("confidence", 0)

            if not found_email:
                result["status"] = "no_email"
                result["note"] = "Email not found — enter manually in Compose"
                results.append(result)
                continue

            # Step 3: generate email
            email_gen = generate_cold_email(
                target_profile=profile,
                email_type=email_type,
                custom_context=custom_context or None,
                anthropic_api_key=api_key
            )
            subject = email_gen.get("subject", f"Quick question about opportunities at {company}")
            body = email_gen.get("body_text", "") or email_gen.get("body", "")
            result["subject"] = subject

            # Step 4: save to Gmail Drafts
            draft_message_id = None
            bulk_resume = _get_resume_for_type(email_type)
            if app_password and found_email:
                draft_message_id = save_draft_to_gmail(
                    to_email=found_email,
                    to_name=profile.name or name,
                    subject=subject,
                    body_text=body,
                    app_password=app_password,
                    resume_path=bulk_resume if bulk_resume and bulk_resume.exists() else None
                )
                result["status"] = "drafted" if draft_message_id else "draft_failed"
            else:
                result["status"] = "generated"
                result["body"] = body

            # Log to tracker — store Message-ID so follow-up engine can thread replies
            tracker.log_outreach(
                target_name=profile.name or name,
                target_email=found_email,
                target_title=profile.title or person.get("title", ""),
                target_company=profile.company or company,
                linkedin_url=url,
                email_type=email_type,
                subject=subject,
                status="draft",
                notes="Bulk drafted",
                message_id=draft_message_id or ""
            )

        except Exception as e:
            result["status"] = "error"
            result["note"] = str(e)

        results.append(result)

    drafted = sum(1 for r in results if r["status"] == "drafted")
    no_email = sum(1 for r in results if r["status"] == "no_email")
    errors = sum(1 for r in results if r["status"] == "error")

    return jsonify({
        "total": len(results),
        "drafted": drafted,
        "no_email": no_email,
        "errors": errors,
        "results": results,
        "message": f"✓ {drafted} drafts saved to Gmail · {no_email} missing email · {errors} errors"
    })


# ─── Follow-up Engine ─────────────────────────────────────────────────────────

@app.route("/api/followup-due")
def api_followup_due():
    """Return all outreach entries where follow-up is due and no reply received."""
    due = tracker.get_follow_ups_due()
    return jsonify({"due": due, "count": len(due)})


@app.route("/api/followup-draft", methods=["POST"])
def api_followup_draft():
    """
    Generate + save Gmail draft follow-ups for all overdue outreach.
    Or for a specific person if target_email is provided.
    """
    data = request.json or {}
    target_email = data.get("target_email")  # optional — if None, drafts all due

    api_key = os.getenv("ANTHROPIC_API_KEY")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    # Get the list to follow up on
    if target_email:
        due = [e for e in tracker.get_follow_ups_due() if e.get("target_email") == target_email]
    else:
        due = tracker.get_follow_ups_due()

    if not due:
        return jsonify({"message": "No follow-ups due right now.", "drafted": 0, "results": []})

    results = []
    from datetime import datetime

    for entry in due:
        name = entry.get("target_name", "")
        email = entry.get("target_email", "")
        title = entry.get("target_title", "")
        company = entry.get("target_company", "")
        original_subject = entry.get("subject", "")
        date_sent = entry.get("date_sent", "")
        result = {"name": name, "email": email, "status": "pending"}

        try:
            # Calculate days since original email
            try:
                sent_dt = datetime.strptime(date_sent[:16], "%Y-%m-%d %H:%M")
                days_ago = (datetime.now() - sent_dt).days
            except Exception:
                days_ago = 7

            # Generate follow-up
            fu = generate_followup_email(
                target_name=name,
                target_email=email,
                target_title=title,
                target_company=company,
                original_subject=original_subject,
                days_since_sent=days_ago,
                anthropic_api_key=api_key
            )

            result["subject"] = fu["subject"]

            # Retrieve the original Message-ID so follow-up lands in the same thread
            original_message_id = entry.get("message_id", "") or None

            # Save to Gmail Drafts — pass in_reply_to to continue the thread
            if app_password and email:
                fu_message_id = save_draft_to_gmail(
                    to_email=email,
                    to_name=name,
                    subject=fu["subject"],
                    body_text=fu["body_text"],
                    app_password=app_password,
                    in_reply_to=original_message_id,
                    references=original_message_id,
                )
                result["status"] = "drafted" if fu_message_id else "draft_failed"
                result["threaded"] = bool(original_message_id)
            else:
                result["status"] = "generated"
                result["body"] = fu["body_text"]
                result["threaded"] = bool(original_message_id)

        except Exception as e:
            result["status"] = "error"
            result["note"] = str(e)

        results.append(result)

    drafted = sum(1 for r in results if r["status"] == "drafted")
    return jsonify({
        "drafted": drafted,
        "total": len(results),
        "results": results,
        "message": f"✓ {drafted} follow-up drafts saved to Gmail"
    })


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
        notes=data.get("notes", ""),
        message_id=data.get("message_id", "")
    )
    return jsonify({"logged": True})


# ─── Resume Manager ───────────────────────────────────────────────────────────

RESUMES_DIR = Path(__file__).parent / "resumes"
RESUME_CONFIG = RESUMES_DIR / "config.json"

def _load_resume_config() -> dict:
    if RESUME_CONFIG.exists():
        with open(RESUME_CONFIG, "r") as f:
            return json.load(f)
    return {"default": "", "assignments": {}}

def _save_resume_config(config: dict):
    RESUMES_DIR.mkdir(exist_ok=True)
    with open(RESUME_CONFIG, "w") as f:
        json.dump(config, f, indent=2)

def _get_resume_for_type(email_type: str) -> Optional[Path]:
    """Return the correct resume Path for a given email type."""
    config = _load_resume_config()
    filename = config.get("assignments", {}).get(email_type) or config.get("default", "")
    if filename:
        path = RESUMES_DIR / filename
        if path.exists():
            return path
    # Fallback to legacy location
    legacy = Path(__file__).parent / "Pratap_Gurav_Resume.pdf"
    return legacy if legacy.exists() else None


@app.route("/api/resumes")
def api_list_resumes():
    RESUMES_DIR.mkdir(exist_ok=True)
    config = _load_resume_config()
    files = []
    for f in sorted(RESUMES_DIR.iterdir()):
        if f.suffix.lower() == ".pdf":
            files.append({
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "is_default": f.name == config.get("default"),
            })
    return jsonify({
        "resumes": files,
        "config": config
    })


@app.route("/api/resumes/upload", methods=["POST"])
def api_upload_resume():
    from flask import request as freq
    if "file" not in freq.files:
        return jsonify({"error": "No file provided"}), 400
    f = freq.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files accepted"}), 400
    RESUMES_DIR.mkdir(exist_ok=True)
    save_path = RESUMES_DIR / f.filename
    f.save(str(save_path))
    # If it's the first resume, set as default
    config = _load_resume_config()
    if not config.get("default"):
        config["default"] = f.filename
        _save_resume_config(config)
    return jsonify({"uploaded": True, "filename": f.filename})


@app.route("/api/resumes/delete", methods=["POST"])
def api_delete_resume():
    data = request.json or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    path = RESUMES_DIR / filename
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    path.unlink()
    # Clean up config references
    config = _load_resume_config()
    if config.get("default") == filename:
        remaining = [f.name for f in RESUMES_DIR.iterdir() if f.suffix == ".pdf"]
        config["default"] = remaining[0] if remaining else ""
    config["assignments"] = {k: v for k, v in config.get("assignments", {}).items() if v != filename}
    _save_resume_config(config)
    return jsonify({"deleted": True})


@app.route("/api/resumes/rename", methods=["POST"])
def api_rename_resume():
    data = request.json or {}
    old_name = data.get("old_name", "")
    new_name = data.get("new_name", "").strip()
    if not old_name or not new_name:
        return jsonify({"error": "Both old_name and new_name required"}), 400
    if not new_name.lower().endswith(".pdf"):
        new_name += ".pdf"
    old_path = RESUMES_DIR / old_name
    new_path = RESUMES_DIR / new_name
    if not old_path.exists():
        return jsonify({"error": "File not found"}), 404
    old_path.rename(new_path)
    # Update config references
    config = _load_resume_config()
    if config.get("default") == old_name:
        config["default"] = new_name
    config["assignments"] = {
        k: (new_name if v == old_name else v)
        for k, v in config.get("assignments", {}).items()
    }
    _save_resume_config(config)
    return jsonify({"renamed": True, "new_name": new_name})


@app.route("/api/resumes/file/<path:filename>")
def api_serve_resume(filename):
    """Serve a resume PDF for in-browser preview."""
    from flask import send_from_directory
    return send_from_directory(str(RESUMES_DIR), filename, mimetype="application/pdf")


@app.route("/api/resumes/config", methods=["GET", "POST"])
def api_resume_config():
    if request.method == "GET":
        return jsonify(_load_resume_config())
    data = request.json or {}
    config = _load_resume_config()
    if "default" in data:
        config["default"] = data["default"]
    if "assignments" in data:
        config["assignments"].update(data["assignments"])
    _save_resume_config(config)
    return jsonify({"saved": True, "config": config})


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
