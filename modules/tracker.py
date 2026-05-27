"""
Outreach Tracker Module — Database Version
-------------------------------------------
All reads/writes go through SQLAlchemy (OutreachLog model).
Pass user_id to every method so data is always scoped per user.
"""

from datetime import datetime, timedelta
from typing import Optional


class OutreachTracker:
    """
    Thin wrapper around OutreachLog DB queries.
    user_id must be passed to every method.
    """

    def log_outreach(
        self,
        target_name: str,
        target_email: str,
        user_id: int,
        target_title: str = "",
        target_company: str = "",
        linkedin_url: str = "",
        email_type: str = "internship",
        subject: str = "",
        status: str = "sent",
        notes: str = "",
        follow_up_days: int = 7,
        message_id: str = "",
    ) -> dict:
        from models import db, OutreachLog

        follow_up_date = (datetime.utcnow() + timedelta(days=follow_up_days)).strftime("%Y-%m-%d")

        entry = OutreachLog(
            user_id        = user_id,
            date_sent      = datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            target_name    = target_name,
            target_title   = target_title,
            target_company = target_company,
            target_email   = target_email,
            linkedin_url   = linkedin_url,
            email_type     = email_type,
            subject        = subject,
            status         = status,
            notes          = notes,
            follow_up_date = follow_up_date,
            message_id     = message_id,
        )
        db.session.add(entry)
        db.session.commit()
        return entry.to_dict()

    def already_contacted(
        self,
        user_id: int,
        target_email: str = "",
        linkedin_url: str = "",
    ) -> Optional[dict]:
        from models import OutreachLog

        if target_email:
            row = OutreachLog.query.filter_by(
                user_id=user_id, target_email=target_email.lower()
            ).first()
            if row:
                return row.to_dict()

        if linkedin_url:
            rows = OutreachLog.query.filter_by(user_id=user_id).all()
            for row in rows:
                if row.linkedin_url and row.linkedin_url.rstrip("/") == linkedin_url.rstrip("/"):
                    return row.to_dict()

        return None

    def update_status(
        self,
        user_id: int,
        target_email: str,
        new_status: str,
        notes: str = "",
    ) -> bool:
        from models import db, OutreachLog

        rows = OutreachLog.query.filter_by(
            user_id=user_id, target_email=target_email.lower()
        ).all()
        if not rows:
            return False

        for row in rows:
            row.status = new_status
            if notes:
                row.notes = notes
            if new_status == "replied":
                row.response_received = datetime.utcnow().strftime("%Y-%m-%d")

        db.session.commit()
        return True

    def get_follow_ups_due(self, user_id: int) -> list:
        from models import OutreachLog

        today = datetime.utcnow().strftime("%Y-%m-%d")
        rows = OutreachLog.query.filter(
            OutreachLog.user_id == user_id,
            OutreachLog.status.in_(["sent", "draft"]),
            OutreachLog.response_received == "",
            OutreachLog.follow_up_date <= today,
        ).all()
        return [r.to_dict() for r in rows]

    def get_all(self, user_id: int) -> list:
        from models import OutreachLog
        rows = OutreachLog.query.filter_by(user_id=user_id)\
                                .order_by(OutreachLog.created_at.desc()).all()
        return [r.to_dict() for r in rows]

    def get_stats(self, user_id: int) -> dict:
        from models import OutreachLog

        rows = OutreachLog.query.filter_by(user_id=user_id).all()
        total    = len(rows)
        sent     = sum(1 for r in rows if r.status in ("sent", "draft"))
        replied  = sum(1 for r in rows if r.status == "replied")
        interview= sum(1 for r in rows if r.status == "interview_scheduled")

        today = datetime.utcnow().strftime("%Y-%m-%d")
        followups_due = sum(
            1 for r in rows
            if r.status in ("sent", "draft")
            and not r.response_received
            and r.follow_up_date <= today
        )

        return {
            "total":               total,
            "sent":                sent,
            "replied":             replied,
            "interview_scheduled": interview,
            "followups_due":       followups_due,
        }

    def get_recent(self, user_id: int, n: int = 10) -> list:
        from models import OutreachLog
        rows = OutreachLog.query.filter_by(user_id=user_id)\
                                .order_by(OutreachLog.created_at.desc())\
                                .limit(n).all()
        return [r.to_dict() for r in rows]

    def get_entry_by_email(self, user_id: int, target_email: str) -> Optional[dict]:
        from models import OutreachLog
        row = OutreachLog.query.filter_by(
            user_id=user_id, target_email=target_email
        ).order_by(OutreachLog.created_at.desc()).first()
        return row.to_dict() if row else None
