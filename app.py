#!/usr/bin/env python3
"""
Cold Reachout Hunter — Multi-User Flask Backend
"""

import os
import sys
import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from models import db, User, OutreachLog, Resume, ResumeAssignment, SenderConfig, GmailToken
from modules.linkedin_scraper import LinkedInScraper, LinkedInProfile
from modules.email_finder import find_email
from modules.email_generator import generate_cold_email, EMAIL_TYPES, generate_followup_email
from modules.email_sender import (
    save_draft_file, save_draft_to_gmail,
    save_draft_via_gmail_oauth, send_via_gmail_oauth,
)
from modules.tracker import OutreachTracker

# ─── App setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# DB: use DATABASE_URL (PostgreSQL on Render/Supabase) or local SQLite
database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url or f"sqlite:///{Path(__file__).parent / 'cold_reachout.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "auth_page"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

tracker = OutreachTracker()
_scrape_jobs = {}
_scrape_lock = threading.Lock()

# ─── Resume dirs (per user) ────────────────────────────────────────────────────

RESUMES_BASE = Path(__file__).parent / "resumes"

def _user_resumes_dir(user_id: int) -> Path:
    d = RESUMES_BASE / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Sender config helpers (DB-backed, per user) ─────────────────────────────

def _get_sender_config(user_id: int) -> dict:
    cfg = SenderConfig.query.filter_by(user_id=user_id).first()
    if cfg:
        return {
            "sender_email": cfg.sender_email,
            "sender_name":  cfg.sender_name,
            "app_password": cfg.app_password or os.getenv("GMAIL_APP_PASSWORD", ""),
        }
    # First-time fallback: use env vars
    return {
        "sender_email": os.getenv("SENDER_EMAIL", ""),
        "sender_name":  os.getenv("SENDER_NAME",  ""),
        "app_password": os.getenv("GMAIL_APP_PASSWORD", ""),
    }

def _save_sender_config(user_id: int, sender_email: str, sender_name: str, app_password: str = ""):
    cfg = SenderConfig.query.filter_by(user_id=user_id).first()
    if cfg:
        cfg.sender_email = sender_email
        cfg.sender_name  = sender_name
        if app_password:
            cfg.app_password = app_password
    else:
        cfg = SenderConfig(
            user_id=user_id,
            sender_email=sender_email,
            sender_name=sender_name,
            app_password=app_password,
        )
        db.session.add(cfg)
    db.session.commit()


# ─── Gmail OAuth helpers ──────────────────────────────────────────────────────

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

def _gmail_flow():
    """Build a Google OAuth Flow from env vars."""
    from google_auth_oauthlib.flow import Flow
    client_id     = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/auth/gmail/callback")
    return Flow.from_client_config(
        {"web": {
            "client_id":      client_id,
            "client_secret":  client_secret,
            "auth_uri":       "https://accounts.google.com/o/oauth2/auth",
            "token_uri":      "https://oauth2.googleapis.com/token",
            "redirect_uris":  [redirect_uri],
        }},
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )

def _get_gmail_token(user_id: int) -> Optional[str]:
    """Return stored OAuth token JSON for user, or None."""
    row = GmailToken.query.filter_by(user_id=user_id).first()
    return row.token_json if row else None


# ─── Resume helpers (DB-backed, per user) ─────────────────────────────────────

def _get_resume_for_type(user_id: int, email_type: str) -> Optional[Path]:
    # Check assignment
    assignment = ResumeAssignment.query.filter_by(user_id=user_id, email_type=email_type).first()
    filename = assignment.resume_filename if assignment else None

    # Fall back to default resume
    if not filename:
        default = Resume.query.filter_by(user_id=user_id, is_default=True).first()
        filename = default.filename if default else None

    if filename:
        path = _user_resumes_dir(user_id) / filename
        if path.exists():
            return path

    return None


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user)

@app.route("/auth")
def auth_page():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("auth.html")


# ─── Auth API ─────────────────────────────────────────────────────────────────

@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    data = request.json or {}
    email    = data.get("email", "").strip().lower()
    name     = data.get("name", "").strip()
    password = data.get("password", "")

    if not email or not name or not password:
        return jsonify({"error": "Email, name and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    # Auto-create sender config from their email
    _save_sender_config(user.id, sender_email=email, sender_name=name)

    login_user(user, remember=True)
    return jsonify({"ok": True, "name": user.name, "email": user.email})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json or {}
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(user, remember=True)
    return jsonify({"ok": True, "name": user.name, "email": user.email})


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/auth/me")
@login_required
def api_me():
    return jsonify({"name": current_user.name, "email": current_user.email})


# ─── Gmail OAuth routes ───────────────────────────────────────────────────────

@app.route("/auth/gmail")
@login_required
def gmail_oauth_start():
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        return "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set in .env", 500
    from flask import session
    flow = _gmail_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",   # always ask so we always get a refresh_token
    )
    session["oauth_state"]   = state
    session["oauth_user_id"] = current_user.id
    return redirect(auth_url)


@app.route("/auth/gmail/callback")
def gmail_oauth_callback():
    from flask import session
    user_id = session.get("oauth_user_id")
    if not user_id:
        return redirect(url_for("auth_page"))

    try:
        flow = _gmail_flow()
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
    except Exception as e:
        return f"OAuth error: {e}", 400

    # Get the email address that was authorized
    gmail_email = ""
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=creds)
        gmail_email = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception:
        pass

    # Save / update token
    row = GmailToken.query.filter_by(user_id=user_id).first()
    if row:
        row.token_json  = creds.to_json()
        row.gmail_email = gmail_email
    else:
        row = GmailToken(user_id=user_id, token_json=creds.to_json(), gmail_email=gmail_email)
        db.session.add(row)

    # Sync the authorized Gmail address into SenderConfig if not already set
    cfg = SenderConfig.query.filter_by(user_id=user_id).first()
    if cfg and not cfg.sender_email and gmail_email:
        cfg.sender_email = gmail_email
    db.session.commit()

    return redirect("/?gmail_connected=1")


@app.route("/api/gmail-status")
@login_required
def api_gmail_status():
    row = GmailToken.query.filter_by(user_id=current_user.id).first()
    return jsonify({"connected": bool(row), "gmail_email": row.gmail_email if row else ""})


@app.route("/api/gmail-disconnect", methods=["POST"])
@login_required
def api_gmail_disconnect():
    row = GmailToken.query.filter_by(user_id=current_user.id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


# ─── Config ───────────────────────────────────────────────────────────────────

@app.route("/api/config")
@login_required
def api_config():
    cfg      = _get_sender_config(current_user.id)
    has_pw   = bool(cfg.get("app_password"))
    resumes  = Resume.query.filter_by(user_id=current_user.id).all()
    gtoken   = GmailToken.query.filter_by(user_id=current_user.id).first()
    return jsonify({
        "anthropic_key":   bool(os.getenv("ANTHROPIC_API_KEY")),
        "hunter_key":      bool(os.getenv("HUNTER_API_KEY")),
        "gmail_connected": bool(gtoken),
        "gmail_password":  has_pw,
        "resume_found":    len(resumes) > 0,
        "sender_email":    cfg.get("sender_email", ""),
        "sender_name":     cfg.get("sender_name", ""),
        "gmail_email":     gtoken.gmail_email if gtoken else "",
    })


@app.route("/api/sender-config", methods=["GET"])
@login_required
def api_get_sender_config():
    cfg = _get_sender_config(current_user.id)
    return jsonify({
        "sender_email": cfg.get("sender_email", ""),
        "sender_name":  cfg.get("sender_name", ""),
        "has_password": bool(cfg.get("app_password")),
    })


@app.route("/api/sender-config", methods=["POST"])
@login_required
def api_save_sender_config():
    data = request.json or {}
    email = data.get("sender_email", "").strip()
    name  = data.get("sender_name", "").strip()
    pw    = data.get("app_password", "").strip()
    if not email:
        return jsonify({"error": "Email required"}), 400
    _save_sender_config(current_user.id, email, name, pw)
    return jsonify({"ok": True, "sender_email": email, "sender_name": name})


# ─── Dashboard / Stats ────────────────────────────────────────────────────────

@app.route("/api/stats")
@login_required
def api_stats():
    stats    = tracker.get_stats(current_user.id)
    followups= tracker.get_follow_ups_due(current_user.id)
    recent   = tracker.get_recent(current_user.id, n=8)
    return jsonify({
        **stats,
        "followups": followups[:5],
        "recent":    recent,
    })


# ─── Hunt ─────────────────────────────────────────────────────────────────────

@app.route("/api/hunt", methods=["POST"])
@login_required
def api_hunt():
    data = request.json or {}
    company     = data.get("company", "").strip()
    max_results = int(data.get("max_results", 10))
    if not company:
        return jsonify({"error": "Company name required"}), 400
    try:
        scraper = LinkedInScraper(headless=False)
        people  = scraper.search_people_at_company(company, max_results=max_results)
        return jsonify({"company": company, "results": people})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Profile Scrape ───────────────────────────────────────────────────────────

@app.route("/api/scrape", methods=["POST"])
@login_required
def api_scrape():
    data = request.json or {}
    linkedin_url = data.get("url", "").strip()
    if not linkedin_url:
        return jsonify({"error": "LinkedIn URL required"}), 400
    try:
        scraper = LinkedInScraper(headless=False)
        profile = scraper.scrape_profile(linkedin_url)
        return jsonify({
            "name": profile.name, "title": profile.title,
            "company": profile.company, "headline": profile.headline,
            "location": profile.location, "about": profile.about,
            "experience": profile.experience, "education": profile.education,
            "recent_posts": profile.recent_posts, "profile_url": profile.profile_url,
            "summary": profile.summary_for_ai()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Email Finder ─────────────────────────────────────────────────────────────

@app.route("/api/find-email", methods=["POST"])
@login_required
def api_find_email():
    data    = request.json or {}
    full_name = data.get("name", "").strip()
    company   = data.get("company", "").strip()
    if not full_name or not company:
        return jsonify({"error": "Name and company required"}), 400
    result = find_email(full_name=full_name, company_name=company,
                        hunter_api_key=os.getenv("HUNTER_API_KEY"))
    return jsonify(result)


# ─── Generate Email ───────────────────────────────────────────────────────────

@app.route("/api/generate-email", methods=["POST"])
@login_required
def api_generate_email():
    data         = request.json or {}
    profile_data = data.get("profile", {})
    email_type   = data.get("email_type", "internship")
    custom_ctx   = data.get("custom_context", "")
    api_key      = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500
    profile = LinkedInProfile(
        name=profile_data.get("name",""), title=profile_data.get("title",""),
        company=profile_data.get("company",""), headline=profile_data.get("headline",""),
        location=profile_data.get("location",""), about=profile_data.get("about",""),
        experience=profile_data.get("experience",[]), education=profile_data.get("education",[]),
        recent_posts=profile_data.get("recent_posts",[]), profile_url=profile_data.get("profile_url","")
    )
    try:
        result = generate_cold_email(target_profile=profile, email_type=email_type,
                                     custom_context=custom_ctx or None, anthropic_api_key=api_key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Save Draft ───────────────────────────────────────────────────────────────

@app.route("/api/save-draft", methods=["POST"])
@login_required
def api_save_draft():
    data           = request.json or {}
    to_email       = data.get("to_email", "")
    to_name        = data.get("to_name", "")
    subject        = data.get("subject", "")
    body           = data.get("body", "")
    target_title   = data.get("target_title", "")
    target_company = data.get("target_company", "")
    linkedin_url   = data.get("linkedin_url", "")
    email_type     = data.get("email_type", "internship")

    scfg         = _get_sender_config(current_user.id)
    app_password = scfg.get("app_password")
    gmail_token  = _get_gmail_token(current_user.id)
    resume_override = data.get("resume_filename")
    resume_path = (
        _user_resumes_dir(current_user.id) / resume_override
        if resume_override else _get_resume_for_type(current_user.id, email_type)
    )
    rp = resume_path if resume_path and resume_path.exists() else None

    # Priority: OAuth → SMTP App Password → local fallback
    message_id = None
    method_note = ""

    if gmail_token:
        message_id  = save_draft_via_gmail_oauth(
            token_json=gmail_token,
            to_email=to_email, to_name=to_name, subject=subject, body_text=body,
            resume_path=rp,
            from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
        )
        method_note = "Saved to Gmail Drafts via OAuth ✓"
    elif app_password:
        message_id  = save_draft_to_gmail(
            to_email=to_email, to_name=to_name, subject=subject, body_text=body,
            app_password=app_password, resume_path=rp,
            from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
        )
        method_note = "Saved to Gmail Drafts ✓"

    if message_id:
        tracker.log_outreach(
            target_name=to_name, target_email=to_email, user_id=current_user.id,
            target_title=target_title, target_company=target_company,
            linkedin_url=linkedin_url, email_type=email_type,
            subject=subject, status="draft", notes=method_note, message_id=message_id
        )
        return jsonify({"saved": True, "message_id": message_id,
                        "message": f"{method_note} (with resume attached)"})

    # Fallback: local draft file
    drafts_folder = str(Path(__file__).parent / "drafts")
    draft_file = save_draft_file(to_email, to_name, subject, body, drafts_folder)
    return jsonify({"saved": True, "draft_file": draft_file,
                    "message": f"Draft saved locally: {Path(draft_file).name}"})


# ─── Send Email ───────────────────────────────────────────────────────────────

@app.route("/api/send", methods=["POST"])
@login_required
def api_send():
    data           = request.json or {}
    to_email       = data.get("to_email", "")
    to_name        = data.get("to_name", "")
    subject        = data.get("subject", "")
    body_text      = data.get("body_text", "")
    body_html      = data.get("body_html", "")
    email_type     = data.get("email_type", "internship")
    linkedin_url   = data.get("linkedin_url", "")
    target_title   = data.get("target_title", "")
    target_company = data.get("target_company", "")
    notes          = data.get("notes", "")

    if not to_email or not subject or not body_text:
        return jsonify({"error": "Missing required fields"}), 400

    scfg        = _get_sender_config(current_user.id)
    pw          = scfg.get("app_password")
    gmail_token = _get_gmail_token(current_user.id)

    if not gmail_token and not pw:
        return jsonify({"error": "Gmail not connected. Click your email in the nav to connect Gmail."}), 500

    try:
        from modules.email_sender import send_via_smtp
        resume_path = _get_resume_for_type(current_user.id, email_type)
        rp = resume_path if resume_path and resume_path.exists() else None

        if gmail_token:
            message_id = send_via_gmail_oauth(
                token_json=gmail_token,
                to_email=to_email, to_name=to_name, subject=subject,
                body_text=body_text, body_html=body_html or None,
                resume_path=rp,
                from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
            )
        else:
            message_id = send_via_smtp(
                to_email=to_email, to_name=to_name, subject=subject,
                body_text=body_text, body_html=body_html or None,
                resume_path=rp, app_password=pw,
                from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
            )
        success = bool(message_id)
        tracker.log_outreach(
            target_name=to_name, target_email=to_email, user_id=current_user.id,
            target_title=target_title, target_company=target_company,
            linkedin_url=linkedin_url, email_type=email_type,
            subject=subject, status="sent" if success else "failed",
            notes=notes, message_id=message_id or ""
        )
        return jsonify({"success": success, "status": "sent" if success else "failed",
                        "message": f"Email {'sent to' if success else 'failed for'} {to_name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Bulk Draft ───────────────────────────────────────────────────────────────

@app.route("/api/bulk-draft", methods=["POST"])
@login_required
def api_bulk_draft():
    data         = request.json or {}
    people       = data.get("people", [])
    email_type   = data.get("email_type", "internship")
    custom_ctx   = data.get("custom_context", "")

    if not people:
        return jsonify({"error": "No people provided"}), 400

    api_key      = os.getenv("ANTHROPIC_API_KEY")
    scfg         = _get_sender_config(current_user.id)
    app_password = scfg.get("app_password")
    gmail_token  = _get_gmail_token(current_user.id)
    uid          = current_user.id

    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    scraper = LinkedInScraper(headless=False)
    results = []

    for person in people:
        name    = person.get("name", "")
        url     = person.get("url", "")
        company = person.get("company", "")
        result  = {"name": name, "url": url, "status": "pending", "email": "", "subject": ""}
        try:
            profile = scraper.scrape_profile(url) if url else LinkedInProfile(
                name=name, title=person.get("title",""), company=company)
            email_result = find_email(full_name=profile.name or name,
                                      company_name=profile.company or company,
                                      hunter_api_key=os.getenv("HUNTER_API_KEY"))
            found_email = email_result.get("email") or ""
            result["email"] = found_email
            result["email_confidence"] = email_result.get("confidence", 0)
            if not found_email:
                result["status"] = "no_email"
                result["note"]   = "Email not found — enter manually in Compose"
                results.append(result); continue

            email_gen = generate_cold_email(target_profile=profile, email_type=email_type,
                                            custom_context=custom_ctx or None, anthropic_api_key=api_key)
            subject = email_gen.get("subject", f"Quick question about opportunities at {company}")
            body    = email_gen.get("body_text", "") or email_gen.get("body", "")
            result["subject"] = subject

            draft_message_id = None
            bulk_resume = _get_resume_for_type(uid, email_type)
            rp = bulk_resume if bulk_resume and bulk_resume.exists() else None

            if found_email and (gmail_token or app_password):
                if gmail_token:
                    draft_message_id = save_draft_via_gmail_oauth(
                        token_json=gmail_token,
                        to_email=found_email, to_name=profile.name or name,
                        subject=subject, body_text=body, resume_path=rp,
                        from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
                    )
                else:
                    draft_message_id = save_draft_to_gmail(
                        to_email=found_email, to_name=profile.name or name,
                        subject=subject, body_text=body, app_password=app_password,
                        resume_path=rp,
                        from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
                    )
                result["status"] = "drafted" if draft_message_id else "draft_failed"
            else:
                result["status"] = "generated"
                result["body"]   = body

            tracker.log_outreach(
                target_name=profile.name or name, target_email=found_email, user_id=uid,
                target_title=profile.title or person.get("title",""),
                target_company=profile.company or company,
                linkedin_url=url, email_type=email_type, subject=subject,
                status="draft", notes="Bulk drafted", message_id=draft_message_id or ""
            )
        except Exception as e:
            result["status"] = "error"; result["note"] = str(e)
        results.append(result)

    drafted  = sum(1 for r in results if r["status"] == "drafted")
    no_email = sum(1 for r in results if r["status"] == "no_email")
    errors   = sum(1 for r in results if r["status"] == "error")
    return jsonify({"total": len(results), "drafted": drafted, "no_email": no_email,
                    "errors": errors, "results": results,
                    "message": f"✓ {drafted} drafts saved · {no_email} missing email · {errors} errors"})


# ─── Follow-up Engine ─────────────────────────────────────────────────────────

@app.route("/api/followup-due")
@login_required
def api_followup_due():
    due = tracker.get_follow_ups_due(current_user.id)
    return jsonify({"due": due, "count": len(due)})


@app.route("/api/followup-draft", methods=["POST"])
@login_required
def api_followup_draft():
    data         = request.json or {}
    target_email = data.get("target_email")
    api_key      = os.getenv("ANTHROPIC_API_KEY")
    scfg         = _get_sender_config(current_user.id)
    app_password = scfg.get("app_password")
    uid          = current_user.id

    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    due = [e for e in tracker.get_follow_ups_due(uid) if e.get("target_email") == target_email] \
          if target_email else tracker.get_follow_ups_due(uid)

    if not due:
        return jsonify({"message": "No follow-ups due right now.", "drafted": 0, "results": []})

    results = []
    for entry in due:
        name    = entry.get("target_name","")
        email   = entry.get("target_email","")
        result  = {"name": name, "email": email, "status": "pending"}
        try:
            try:
                sent_dt  = datetime.strptime(entry.get("date_sent","")[:16], "%Y-%m-%d %H:%M")
                days_ago = (datetime.utcnow() - sent_dt).days
            except Exception:
                days_ago = 7

            fu = generate_followup_email(
                target_name=name, target_email=email,
                target_title=entry.get("target_title",""),
                target_company=entry.get("target_company",""),
                original_subject=entry.get("subject",""),
                days_since_sent=days_ago, anthropic_api_key=api_key
            )
            result["subject"] = fu["subject"]
            original_mid = entry.get("message_id") or None

            if app_password and email:
                fu_mid = save_draft_to_gmail(
                    to_email=email, to_name=name, subject=fu["subject"],
                    body_text=fu["body_text"], app_password=app_password,
                    in_reply_to=original_mid, references=original_mid,
                    from_email=scfg.get("sender_email"), from_name=scfg.get("sender_name"),
                )
                result["status"]   = "drafted" if fu_mid else "draft_failed"
                result["threaded"] = bool(original_mid)
            else:
                result["status"]   = "generated"
                result["body"]     = fu["body_text"]
                result["threaded"] = bool(original_mid)
        except Exception as e:
            result["status"] = "error"; result["note"] = str(e)
        results.append(result)

    drafted = sum(1 for r in results if r["status"] == "drafted")
    return jsonify({"drafted": drafted, "total": len(results), "results": results,
                    "message": f"✓ {drafted} follow-up drafts saved to Gmail"})


# ─── Tracker ──────────────────────────────────────────────────────────────────

@app.route("/api/tracker")
@login_required
def api_tracker():
    entries = tracker.get_all(current_user.id)
    return jsonify({"entries": entries})


@app.route("/api/tracker/update", methods=["POST"])
@login_required
def api_tracker_update():
    data       = request.json or {}
    email      = data.get("email","")
    new_status = data.get("status","")
    notes      = data.get("notes","")
    valid = ["sent","draft","replied","bounced","interview_scheduled","no_response"]
    if new_status not in valid:
        return jsonify({"error": f"Invalid status. Use: {', '.join(valid)}"}), 400
    success = tracker.update_status(current_user.id, email, new_status, notes)
    return jsonify({"updated": success})


@app.route("/api/tracker/log-draft", methods=["POST"])
@login_required
def api_log_draft():
    data = request.json or {}
    tracker.log_outreach(
        target_name=data.get("to_name",""), target_email=data.get("to_email",""),
        user_id=current_user.id,
        target_title=data.get("target_title",""), target_company=data.get("target_company",""),
        linkedin_url=data.get("linkedin_url",""), email_type=data.get("email_type","internship"),
        subject=data.get("subject",""), status="draft",
        notes=data.get("notes",""), message_id=data.get("message_id","")
    )
    return jsonify({"logged": True})


# ─── Resume Manager ───────────────────────────────────────────────────────────

@app.route("/api/resumes")
@login_required
def api_list_resumes():
    uid     = current_user.id
    resumes = Resume.query.filter_by(user_id=uid).order_by(Resume.uploaded_at).all()
    assigns = ResumeAssignment.query.filter_by(user_id=uid).all()
    assignments = {a.email_type: a.resume_filename for a in assigns}
    default_res = Resume.query.filter_by(user_id=uid, is_default=True).first()
    return jsonify({
        "resumes": [r.to_dict() for r in resumes],
        "config": {"default": default_res.filename if default_res else "", "assignments": assignments}
    })


@app.route("/api/resumes/upload", methods=["POST"])
@login_required
def api_upload_resume():
    uid = current_user.id
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files accepted"}), 400

    dest = _user_resumes_dir(uid) / f.filename
    f.save(str(dest))

    # Add to DB if not already there
    existing = Resume.query.filter_by(user_id=uid, filename=f.filename).first()
    if not existing:
        is_first = Resume.query.filter_by(user_id=uid).count() == 0
        resume = Resume(user_id=uid, filename=f.filename, is_default=is_first)
        db.session.add(resume)
        db.session.commit()

    return jsonify({"uploaded": True, "filename": f.filename})


@app.route("/api/resumes/delete", methods=["POST"])
@login_required
def api_delete_resume():
    uid      = current_user.id
    filename = (request.json or {}).get("filename","")
    if not filename:
        return jsonify({"error": "Filename required"}), 400

    path = _user_resumes_dir(uid) / filename
    if path.exists():
        path.unlink()

    row = Resume.query.filter_by(user_id=uid, filename=filename).first()
    if row:
        was_default = row.is_default
        db.session.delete(row)
        db.session.commit()
        if was_default:
            next_r = Resume.query.filter_by(user_id=uid).first()
            if next_r:
                next_r.is_default = True
                db.session.commit()

    ResumeAssignment.query.filter_by(user_id=uid, resume_filename=filename).delete()
    db.session.commit()
    return jsonify({"deleted": True})


@app.route("/api/resumes/rename", methods=["POST"])
@login_required
def api_rename_resume():
    uid      = current_user.id
    data     = request.json or {}
    old_name = data.get("old_name","")
    new_name = data.get("new_name","").strip()
    if not old_name or not new_name:
        return jsonify({"error": "Both old_name and new_name required"}), 400
    if not new_name.lower().endswith(".pdf"):
        new_name += ".pdf"

    old_path = _user_resumes_dir(uid) / old_name
    new_path = _user_resumes_dir(uid) / new_name
    if old_path.exists():
        old_path.rename(new_path)

    row = Resume.query.filter_by(user_id=uid, filename=old_name).first()
    if row:
        row.filename = new_name
        db.session.commit()

    assigns = ResumeAssignment.query.filter_by(user_id=uid, resume_filename=old_name).all()
    for a in assigns:
        a.resume_filename = new_name
    db.session.commit()
    return jsonify({"renamed": True, "new_name": new_name})


@app.route("/api/resumes/file/<int:uid>/<path:filename>")
@login_required
def api_serve_resume(uid, filename):
    if uid != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    return send_from_directory(str(_user_resumes_dir(uid)), filename, mimetype="application/pdf")


@app.route("/api/resumes/config", methods=["GET", "POST"])
@login_required
def api_resume_config():
    uid = current_user.id
    if request.method == "GET":
        assigns  = ResumeAssignment.query.filter_by(user_id=uid).all()
        default_r = Resume.query.filter_by(user_id=uid, is_default=True).first()
        return jsonify({"default": default_r.filename if default_r else "",
                        "assignments": {a.email_type: a.resume_filename for a in assigns}})

    data = request.json or {}
    if "default" in data:
        Resume.query.filter_by(user_id=uid).update({"is_default": False})
        row = Resume.query.filter_by(user_id=uid, filename=data["default"]).first()
        if row:
            row.is_default = True
        db.session.commit()

    if "assignments" in data:
        for email_type, filename in data["assignments"].items():
            existing = ResumeAssignment.query.filter_by(user_id=uid, email_type=email_type).first()
            if existing:
                existing.resume_filename = filename
            else:
                db.session.add(ResumeAssignment(user_id=uid, email_type=email_type, resume_filename=filename))
        db.session.commit()

    return jsonify({"saved": True})


# ─── Email types ──────────────────────────────────────────────────────────────

@app.route("/api/email-types")
@login_required
def api_email_types():
    return jsonify({k: v["goal"] for k, v in EMAIL_TYPES.items()})


# ─── DB Init + Run ────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"""
╔══════════════════════════════════════════════════╗
║       COLD REACHOUT HUNTER  — Multi-User         ║
║   Open: http://localhost:{port}                     ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
