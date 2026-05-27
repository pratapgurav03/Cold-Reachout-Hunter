"""
Database Models — Cold Reachout Hunter
--------------------------------------
SQLAlchemy models for multi-user support.
Uses SQLite locally; swap to PostgreSQL via DATABASE_URL env var.
"""

import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ─── USER ─────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name          = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    outreach_logs      = db.relationship("OutreachLog",      back_populates="user", cascade="all, delete-orphan")
    resumes            = db.relationship("Resume",           back_populates="user", cascade="all, delete-orphan")
    resume_assignments = db.relationship("ResumeAssignment", back_populates="user", cascade="all, delete-orphan")
    sender_config      = db.relationship("SenderConfig",     back_populates="user", uselist=False, cascade="all, delete-orphan")
    gmail_token        = db.relationship("GmailToken",       back_populates="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


# ─── OUTREACH LOG ─────────────────────────────────────────────────────────────

class OutreachLog(db.Model):
    __tablename__ = "outreach_logs"

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date_sent        = db.Column(db.String(32),  default=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    target_name      = db.Column(db.String(255), default="")
    target_title     = db.Column(db.String(255), default="")
    target_company   = db.Column(db.String(255), default="")
    target_email     = db.Column(db.String(255), default="")
    linkedin_url     = db.Column(db.String(512), default="")
    email_type       = db.Column(db.String(64),  default="internship")
    subject          = db.Column(db.String(512), default="")
    status           = db.Column(db.String(64),  default="sent")   # sent/draft/replied/bounced/interview_scheduled/no_response
    notes            = db.Column(db.Text,        default="")
    follow_up_date   = db.Column(db.String(16),  default="")
    response_received= db.Column(db.String(16),  default="")
    message_id       = db.Column(db.String(512), default="")
    created_at       = db.Column(db.DateTime,    default=datetime.utcnow)

    user = db.relationship("User", back_populates="outreach_logs")

    def to_dict(self):
        return {
            "id":               self.id,
            "date_sent":        self.date_sent,
            "target_name":      self.target_name,
            "target_title":     self.target_title,
            "target_company":   self.target_company,
            "target_email":     self.target_email,
            "linkedin_url":     self.linkedin_url,
            "email_type":       self.email_type,
            "subject":          self.subject,
            "status":           self.status,
            "notes":            self.notes,
            "follow_up_date":   self.follow_up_date,
            "response_received":self.response_received,
            "message_id":       self.message_id,
        }

    def __repr__(self):
        return f"<OutreachLog {self.target_name} @ {self.target_company}>"


# ─── RESUME ───────────────────────────────────────────────────────────────────

class Resume(db.Model):
    __tablename__ = "resumes"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename    = db.Column(db.String(255), nullable=False)
    is_default  = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="resumes")

    def filepath(self, base_dir: str) -> str:
        """Absolute path to this resume file."""
        return os.path.join(base_dir, str(self.user_id), self.filename)

    def to_dict(self):
        return {
            "filename":    self.filename,
            "is_default":  self.is_default,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else "",
        }


# ─── RESUME ASSIGNMENT ────────────────────────────────────────────────────────

class ResumeAssignment(db.Model):
    __tablename__ = "resume_assignments"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    email_type      = db.Column(db.String(64),  nullable=False)
    resume_filename = db.Column(db.String(255), nullable=False)

    user = db.relationship("User", back_populates="resume_assignments")

    __table_args__ = (
        db.UniqueConstraint("user_id", "email_type", name="uq_user_email_type"),
    )


# ─── SENDER CONFIG ────────────────────────────────────────────────────────────

class SenderConfig(db.Model):
    __tablename__ = "sender_configs"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    sender_email = db.Column(db.String(255), nullable=False)
    sender_name  = db.Column(db.String(255), nullable=False, default="")
    app_password = db.Column(db.String(512), default="")   # stored as-is; use HTTPS + server-side only
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="sender_config")


# ─── GMAIL OAUTH TOKEN ────────────────────────────────────────────────────────

class GmailToken(db.Model):
    __tablename__ = "gmail_tokens"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    token_json  = db.Column(db.Text, nullable=False)   # full OAuth credentials JSON
    gmail_email = db.Column(db.String(255), default="")  # the Gmail address that was authorized
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="gmail_token")
