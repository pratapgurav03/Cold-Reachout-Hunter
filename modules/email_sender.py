"""
Gmail Sender Module
--------------------
Sends cold outreach emails from pratap.gurav03@gmail.com via Gmail API.
Always saves as DRAFT first → you review → then you confirm to send.

Setup:
  1. Go to https://myaccount.google.com/apppasswords
  2. Create an App Password for "Mail" + "Mac"
  3. Add to .env: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

Resume attachment: automatically attaches Pratap_Gurav_Resume.pdf
"""

import os
import time
import imaplib
import smtplib
import base64
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import make_msgid
from pathlib import Path
from datetime import datetime
from typing import Optional


# Path to resume (relative to project root)
RESUME_FILENAME = "Pratap_Gurav_Resume.pdf"
SENDER_EMAIL = "pratap.gurav03@gmail.com"
SENDER_NAME = "Pratap Gurav"


def _find_resume_path() -> Optional[Path]:
    """Find the resume PDF in the project directory."""
    # Look in the project folder
    candidates = [
        Path(__file__).parent.parent / RESUME_FILENAME,
        Path(__file__).parent.parent / "data" / RESUME_FILENAME,
        Path(RESUME_FILENAME),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _build_message(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    resume_path: Optional[Path] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    message_id: Optional[str] = None,
) -> MIMEMultipart:
    """Build the MIME message with optional HTML, PDF attachment, and threading headers."""
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    msg["Reply-To"] = SENDER_EMAIL
    msg["Message-ID"] = message_id or make_msgid(domain="gmail.com")

    # Threading headers — set these to continue an existing thread
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to

    # Email body (alternative: plain + HTML)
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        body_part.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(body_part)

    # Resume attachment
    if resume_path and resume_path.exists():
        with open(resume_path, "rb") as f:
            attachment = MIMEBase("application", "pdf")
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=RESUME_FILENAME
            )
            msg.attach(attachment)

    return msg


def save_draft_gmail_api(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    resume_path: Optional[Path] = None,
    credentials_path: str = "gmail_credentials.json",
    token_path: str = "gmail_token.json"
) -> Optional[str]:
    """
    Save as Gmail draft using Gmail API (OAuth2).
    Returns draft ID or None on failure.

    First-time setup:
      1. Go to https://console.cloud.google.com/
      2. Create project → Enable Gmail API → Create OAuth credentials (Desktop)
      3. Download as gmail_credentials.json in project root
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
        creds = None

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as token:
                token.write(creds.to_json())

        service = build("gmail", "v1", credentials=creds)

        msg = _build_message(to_email, to_name, subject, body_text, body_html, resume_path)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}}
        ).execute()

        return draft.get("id")

    except ImportError:
        print("  Gmail API not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        return None
    except Exception as e:
        print(f"  Gmail API error: {e}")
        return None


def save_draft_to_gmail(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    app_password: Optional[str] = None,
    resume_path: Optional[Path] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
) -> Optional[str]:
    """
    Save email as a real Gmail draft using IMAP + App Password.
    No OAuth needed — works with the existing GMAIL_APP_PASSWORD.
    The draft will appear in Gmail's Drafts folder with resume attached.

    Returns the Message-ID string on success, None on failure.
    Pass in_reply_to (original Message-ID) to continue an existing thread.
    """
    if not app_password:
        app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not app_password:
        raise ValueError("GMAIL_APP_PASSWORD not set in .env")

    _from_email = from_email or SENDER_EMAIL
    _from_name  = from_name  or SENDER_NAME

    if resume_path is None:
        resume_path = _find_resume_path()

    # Generate a stable Message-ID for this draft so we can store it
    message_id = make_msgid(domain="gmail.com")

    # Build the full MIME message (same as sending, but we store it instead)
    msg = _build_message(
        to_email, to_name, subject, body_text, None, resume_path,
        in_reply_to=in_reply_to, references=references, message_id=message_id
    )
    # Override From header with active sender
    msg.replace_header("From", f"{_from_name} <{_from_email}>")
    msg.replace_header("Reply-To", _from_email)

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(_from_email, app_password.replace(" ", ""))
        imap.select('"[Gmail]/Drafts"')
        imap.append(
            '"[Gmail]/Drafts"',
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes()
        )
        imap.logout()
        print(f"  ✅ Draft saved to Gmail Drafts for {to_name} <{to_email}>")
        return message_id
    except imaplib.IMAP4.error as e:
        print(f"  ❌ IMAP error: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Draft save failed: {e}")
        return None


def send_via_smtp(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    app_password: Optional[str] = None,
    resume_path: Optional[Path] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
) -> Optional[str]:
    """
    Send email via Gmail SMTP using App Password.
    Returns the Message-ID string on success, None on failure.
    Pass in_reply_to (original Message-ID) to continue an existing thread.
    """
    if not app_password:
        app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not app_password:
        raise ValueError(
            "GMAIL_APP_PASSWORD not set.\n"
            "Get one at: https://myaccount.google.com/apppasswords\n"
            "Add to .env: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx"
        )

    _from_email = from_email or SENDER_EMAIL
    _from_name  = from_name  or SENDER_NAME

    # Find resume
    if resume_path is None:
        resume_path = _find_resume_path()

    # Generate a Message-ID to store for future thread continuation
    message_id = make_msgid(domain="gmail.com")
    msg = _build_message(
        to_email, to_name, subject, body_text, body_html, resume_path,
        in_reply_to=in_reply_to, references=references, message_id=message_id
    )
    msg.replace_header("From", f"{_from_name} <{_from_email}>")
    msg.replace_header("Reply-To", _from_email)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(_from_email, app_password.replace(" ", ""))
            server.sendmail(_from_email, to_email, msg.as_string())
        return message_id
    except smtplib.SMTPAuthenticationError:
        print("\n❌ Gmail authentication failed.")
        print("   Make sure you're using an App Password, not your regular Gmail password.")
        print("   Get one at: https://myaccount.google.com/apppasswords")
        return None
    except Exception as e:
        print(f"\n❌ Send failed: {e}")
        return None


def _get_oauth_creds(token_json: str):
    """Load OAuth credentials from stored JSON, auto-refresh if expired."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def save_draft_via_gmail_oauth(
    token_json: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    resume_path: Optional[Path] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> Optional[str]:
    """
    Save email as Gmail draft using stored OAuth token.
    Returns the Message-ID header string on success, None on failure.
    """
    try:
        from googleapiclient.discovery import build

        creds = _get_oauth_creds(token_json)
        service = build("gmail", "v1", credentials=creds)

        message_id = make_msgid(domain="gmail.com")
        msg = _build_message(
            to_email, to_name, subject, body_text, body_html, resume_path,
            in_reply_to=in_reply_to, references=references, message_id=message_id,
        )
        _fe = from_email or SENDER_EMAIL
        _fn = from_name  or SENDER_NAME
        msg.replace_header("From", f"{_fn} <{_fe}>")
        msg.replace_header("Reply-To", _fe)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()

        print(f"  ✅ [OAuth] Draft saved to Gmail for {to_name} <{to_email}>")
        return message_id
    except Exception as e:
        print(f"  ❌ [OAuth] Draft failed: {e}")
        return None


def send_via_gmail_oauth(
    token_json: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    resume_path: Optional[Path] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> Optional[str]:
    """
    Send email via Gmail API using stored OAuth token.
    Returns the Message-ID header string on success, None on failure.
    """
    try:
        from googleapiclient.discovery import build

        creds = _get_oauth_creds(token_json)
        service = build("gmail", "v1", credentials=creds)

        message_id = make_msgid(domain="gmail.com")
        msg = _build_message(
            to_email, to_name, subject, body_text, body_html, resume_path,
            in_reply_to=in_reply_to, references=references, message_id=message_id,
        )
        _fe = from_email or SENDER_EMAIL
        _fn = from_name  or SENDER_NAME
        msg.replace_header("From", f"{_fn} <{_fe}>")
        msg.replace_header("Reply-To", _fe)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        print(f"  ✅ [OAuth] Sent to {to_name} <{to_email}>")
        return message_id
    except Exception as e:
        print(f"  ❌ [OAuth] Send failed: {e}")
        return None


def save_draft_file(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    drafts_folder: str = "drafts"
) -> str:
    """
    Save email as a local .txt draft file for review.
    Returns the draft file path.
    """
    os.makedirs(drafts_folder, exist_ok=True)
    safe_name = to_name.replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{drafts_folder}/draft_{safe_name}_{timestamp}.txt"

    content = f"""TO: {to_name} <{to_email}>
FROM: {SENDER_NAME} <{SENDER_EMAIL}>
SUBJECT: {subject}
DATE: {datetime.now().strftime("%B %d, %Y %H:%M")}
ATTACHMENT: {RESUME_FILENAME}
{'─' * 60}

{body_text}

{'─' * 60}
[Draft saved. Review and approve to send.]
"""
    with open(filename, "w") as f:
        f.write(content)

    return filename


class EmailSender:
    """
    High-level email sender with draft-first workflow.

    Flow:
      1. generate email content
      2. save_draft()      → saves locally + optionally to Gmail drafts
      3. show preview
      4. confirm_and_send() → only sends after user approves
    """

    def __init__(self, app_password: Optional[str] = None):
        self.app_password = app_password or os.getenv("GMAIL_APP_PASSWORD")
        self.resume_path = _find_resume_path()

        if self.resume_path:
            print(f"  ✅ Resume found: {self.resume_path.name}")
        else:
            print(f"  ⚠️  Resume not found. Place '{RESUME_FILENAME}' in the project folder.")

    def draft_and_review(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None
    ) -> dict:
        """
        Save draft locally and print preview. Returns draft info.
        """
        # Save local draft
        draft_file = save_draft_file(to_email, to_name, subject, body_text)

        # Print preview
        print("\n" + "═" * 60)
        print("📧  DRAFT EMAIL — REVIEW BEFORE SENDING")
        print("═" * 60)
        print(f"To:      {to_name} <{to_email}>")
        print(f"From:    {SENDER_NAME} <{SENDER_EMAIL}>")
        print(f"Subject: {subject}")
        print(f"Attach:  {RESUME_FILENAME} {'✅' if self.resume_path else '❌ not found'}")
        print("─" * 60)
        print(body_text)
        print("─" * 60)
        print(f"📁 Draft saved: {draft_file}")
        print("═" * 60)

        return {
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "draft_file": draft_file,
            "resume_attached": self.resume_path is not None
        }

    def confirm_and_send(self, draft_info: dict) -> bool:
        """
        Ask user for confirmation, then send.
        Returns True if sent successfully.
        """
        print("\n" + "─" * 60)
        print("What would you like to do with this email?")
        print("  [s] Send now")
        print("  [e] Edit the draft file, then send")
        print("  [d] Save to Gmail drafts only (send manually from Gmail)")
        print("  [x] Skip / discard")
        print("─" * 60)

        choice = input("Your choice [s/e/d/x]: ").strip().lower()

        if choice == "s":
            print(f"\n⏳ Sending to {draft_info['to_name']}...")
            success = send_via_smtp(
                to_email=draft_info["to_email"],
                to_name=draft_info["to_name"],
                subject=draft_info["subject"],
                body_text=draft_info["body_text"],
                body_html=draft_info.get("body_html"),
                app_password=self.app_password,
                resume_path=self.resume_path
            )
            if success:
                print(f"  ✅ Sent to {draft_info['to_name']} <{draft_info['to_email']}>")
            return success

        elif choice == "e":
            draft_file = draft_info["draft_file"]
            print(f"\n📝 Edit the draft at: {draft_file}")
            print("   Make your changes, save the file, then press ENTER to send.")
            input("Press ENTER when ready to send...")

            # Re-read the edited draft
            with open(draft_file, "r") as f:
                content = f.read()
            # Extract body (after the dashes)
            parts = content.split("─" * 60)
            if len(parts) >= 2:
                draft_info["body_text"] = parts[1].strip()

            success = send_via_smtp(
                to_email=draft_info["to_email"],
                to_name=draft_info["to_name"],
                subject=draft_info["subject"],
                body_text=draft_info["body_text"],
                body_html=None,  # use plain text after editing
                app_password=self.app_password,
                resume_path=self.resume_path
            )
            if success:
                print(f"  ✅ Sent to {draft_info['to_name']} <{draft_info['to_email']}>")
            return success

        elif choice == "d":
            draft_id = save_draft_gmail_api(
                to_email=draft_info["to_email"],
                to_name=draft_info["to_name"],
                subject=draft_info["subject"],
                body_text=draft_info["body_text"],
                body_html=draft_info.get("body_html"),
                resume_path=self.resume_path
            )
            if draft_id:
                print(f"  ✅ Draft saved to Gmail (ID: {draft_id})")
                print(f"     Open Gmail and send from Drafts when ready.")
            else:
                print(f"  📁 Draft saved locally: {draft_info['draft_file']}")
                print(f"     Copy the text and send manually from Gmail.")
            return False  # not sent yet

        else:
            print("  ⏭️  Skipped.")
            return False
