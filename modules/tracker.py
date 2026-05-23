"""
Outreach Tracker Module
------------------------
CSV-based tracker for all cold outreach activity.
Prevents duplicate outreach and tracks status over time.

Log file: outreach_log.csv (created automatically)
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


# CSV columns
COLUMNS = [
    "date_sent",
    "target_name",
    "target_title",
    "target_company",
    "target_email",
    "linkedin_url",
    "email_type",      # internship / informational / referral / networking
    "subject",
    "status",          # draft / sent / bounced / replied / interview_scheduled / no_response
    "notes",
    "follow_up_date",
    "response_received",
]

DEFAULT_LOG_PATH = Path(__file__).parent.parent / "outreach_log.csv"


class OutreachTracker:
    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        self._ensure_log_exists()

    def _ensure_log_exists(self):
        """Create CSV with headers if it doesn't exist."""
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=COLUMNS)
                writer.writeheader()

    def log_outreach(
        self,
        target_name: str,
        target_email: str,
        target_title: str = "",
        target_company: str = "",
        linkedin_url: str = "",
        email_type: str = "internship",
        subject: str = "",
        status: str = "sent",
        notes: str = "",
        follow_up_days: int = 7
    ) -> dict:
        """
        Log a sent or drafted email to the tracker.
        Returns the logged entry.
        """
        from datetime import timedelta
        follow_up_date = (datetime.now() + timedelta(days=follow_up_days)).strftime("%Y-%m-%d")

        entry = {
            "date_sent": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "target_name": target_name,
            "target_title": target_title,
            "target_company": target_company,
            "target_email": target_email,
            "linkedin_url": linkedin_url,
            "email_type": email_type,
            "subject": subject,
            "status": status,
            "notes": notes,
            "follow_up_date": follow_up_date,
            "response_received": "",
        }

        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writerow(entry)

        return entry

    def already_contacted(self, target_email: str = "", linkedin_url: str = "") -> Optional[dict]:
        """
        Check if this person has already been contacted.
        Returns the existing record or None.
        """
        if not self.log_path.exists():
            return None

        with open(self.log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if target_email and row.get("target_email", "").lower() == target_email.lower():
                    return row
                if linkedin_url and row.get("linkedin_url", "").rstrip("/") == linkedin_url.rstrip("/"):
                    return row
        return None

    def update_status(self, target_email: str, new_status: str, notes: str = "") -> bool:
        """Update the status of an existing outreach (e.g., replied, bounced)."""
        if not self.log_path.exists():
            return False

        rows = []
        updated = False

        with open(self.log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("target_email", "").lower() == target_email.lower():
                    row["status"] = new_status
                    if notes:
                        row["notes"] = notes
                    if new_status == "replied":
                        row["response_received"] = datetime.now().strftime("%Y-%m-%d")
                    updated = True
                rows.append(row)

        if updated:
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

        return updated

    def get_follow_ups_due(self) -> list[dict]:
        """Return outreach entries where follow-up date has passed and no response."""
        if not self.log_path.exists():
            return []

        today = datetime.now().strftime("%Y-%m-%d")
        due = []

        with open(self.log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (
                    row.get("status") in ("sent", "draft")
                    and not row.get("response_received")
                    and row.get("follow_up_date", "9999") <= today
                ):
                    due.append(row)

        return due

    def print_stats(self):
        """Print a summary of outreach activity."""
        if not self.log_path.exists():
            print("No outreach logged yet.")
            return

        rows = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("No outreach logged yet.")
            return

        total = len(rows)
        by_status = {}
        by_company = {}

        for row in rows:
            status = row.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
            company = row.get("target_company", "Unknown")
            by_company[company] = by_company.get(company, 0) + 1

        print("\n" + "═" * 50)
        print("📊  OUTREACH STATS")
        print("═" * 50)
        print(f"Total outreach: {total}")
        print("\nBy status:")
        for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
            emoji = {"sent": "📤", "replied": "✅", "bounced": "❌",
                     "interview_scheduled": "🎉", "draft": "📝",
                     "no_response": "⏳"}.get(status, "•")
            print(f"  {emoji} {status}: {count}")
        print("\nTop companies:")
        for company, count in sorted(by_company.items(), key=lambda x: -x[1])[:5]:
            print(f"  • {company}: {count}")
        print("═" * 50)

    def list_recent(self, n: int = 10):
        """Print the N most recent outreach entries."""
        if not self.log_path.exists():
            print("No outreach logged yet.")
            return

        with open(self.log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        recent = rows[-n:][::-1]
        print(f"\n{'DATE':<18} {'NAME':<22} {'COMPANY':<20} {'STATUS':<12}")
        print("─" * 74)
        for row in recent:
            print(
                f"{row.get('date_sent', '')[:16]:<18} "
                f"{row.get('target_name', '')[:20]:<22} "
                f"{row.get('target_company', '')[:18]:<20} "
                f"{row.get('status', ''):<12}"
            )

    def get_follow_up_reminder(self) -> str:
        """Return a formatted reminder string for due follow-ups."""
        due = self.get_follow_ups_due()
        if not due:
            return ""

        lines = [f"\n🔔 FOLLOW-UP REMINDERS ({len(due)} due):"]
        for entry in due:
            lines.append(
                f"  • {entry['target_name']} @ {entry['target_company']} "
                f"(sent {entry['date_sent'][:10]})"
            )
        return "\n".join(lines)
