#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║         COLD REACHOUT HUNTER — by Pratap Gurav       ║
║   LinkedIn → Email Finder → AI Email → Gmail Send    ║
╚══════════════════════════════════════════════════════╝

Usage:
  python cold_outreach.py hunt   --company "Google"
  python cold_outreach.py send   --url "https://linkedin.com/in/someone"
  python cold_outreach.py send   --company "Siemens Energy" --auto-hunt
  python cold_outreach.py status
  python cold_outreach.py followup

Examples:
  python cold_outreach.py hunt --company "McKinsey"
  python cold_outreach.py send --url "https://linkedin.com/in/jane-doe-123" --type internship
  python cold_outreach.py send --company "Shell" --auto-hunt --type internship
  python cold_outreach.py status
"""

import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from modules.linkedin_scraper import LinkedInScraper, LinkedInProfile
from modules.email_finder import find_email, get_company_domain_from_hunter
from modules.email_generator import generate_cold_email, preview_email, EMAIL_TYPES
from modules.email_sender import EmailSender
from modules.tracker import OutreachTracker


# ─── Colors ──────────────────────────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"

def banner():
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════════════════╗
║         COLD REACHOUT HUNTER — Pratap Gurav          ║
║   Fall 2026 Internship Campaign | NYU MOT            ║
╚══════════════════════════════════════════════════════╝
{C.RESET}""")

def ok(msg):  print(f"{C.GREEN}✅ {msg}{C.RESET}")
def warn(msg): print(f"{C.YELLOW}⚠️  {msg}{C.RESET}")
def info(msg): print(f"{C.BLUE}ℹ️  {msg}{C.RESET}")
def err(msg):  print(f"{C.RED}❌ {msg}{C.RESET}")
def step(msg): print(f"\n{C.CYAN}→ {msg}{C.RESET}")


# ─── CONFIG ───────────────────────────────────────────────────────────────────
def get_config() -> dict:
    return {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "hunter_api_key": os.getenv("HUNTER_API_KEY"),
        "gmail_app_password": os.getenv("GMAIL_APP_PASSWORD"),
    }

def check_config():
    cfg = get_config()
    print(f"\n{C.BOLD}Config check:{C.RESET}")
    print(f"  Anthropic API  : {'✅' if cfg['anthropic_api_key'] else '❌ Missing — add to .env'}")
    print(f"  Hunter.io API  : {'✅' if cfg['hunter_api_key'] else '⚠️  Optional (email guessing only)'}")
    print(f"  Gmail Password : {'✅' if cfg['gmail_app_password'] else '⚠️  Needed to send emails'}")

    resume = Path(__file__).parent / "Pratap_Gurav_Resume.pdf"
    print(f"  Resume PDF     : {'✅' if resume.exists() else '❌ Missing — place Pratap_Gurav_Resume.pdf in project root'}")

    if not cfg["anthropic_api_key"]:
        err("ANTHROPIC_API_KEY is required. Add it to .env file.")
        sys.exit(1)


# ─── HUNT COMMAND ─────────────────────────────────────────────────────────────
def cmd_hunt(args):
    """Find the right people to reach out to at a company."""
    check_config()
    cfg = get_config()

    company = args.company
    if not company:
        company = input("Enter company name: ").strip()

    step(f"Hunting targets at {C.BOLD}{company}{C.RESET}{C.CYAN}...")

    scraper = LinkedInScraper(headless=False)
    people = scraper.search_people_at_company(company, max_results=args.max or 10)

    if not people:
        warn(f"No results found for {company}. LinkedIn may have limited results.")
        return

    print(f"\n{C.BOLD}Found {len(people)} people at {company}:{C.RESET}")
    print(f"\n{'#':<4} {'NAME':<25} {'TITLE':<40} {'RELEVANCE'}")
    print("─" * 80)

    for i, p in enumerate(people, 1):
        stars = "★" * min(p["relevance_score"], 5) + "☆" * (5 - min(p["relevance_score"], 5))
        print(f"{i:<4} {p['name']:<25} {p['title'][:38]:<40} {stars}")

    print(f"\n{C.DIM}Tip: To send an outreach to one of these people, run:{C.RESET}")
    print(f'{C.DIM}  python cold_outreach.py send --url "<their LinkedIn URL>" --type internship{C.RESET}')

    # Save to JSON for reference
    output_file = Path(f"hunt_{company.replace(' ', '_').lower()}.json")
    with open(output_file, "w") as f:
        json.dump(people, f, indent=2)
    ok(f"Results saved to {output_file}")

    return people


# ─── SEND COMMAND ─────────────────────────────────────────────────────────────
def cmd_send(args):
    """Full pipeline: scrape → find email → generate → draft → review → send."""
    check_config()
    cfg = get_config()

    tracker = OutreachTracker()
    sender = EmailSender(app_password=cfg["gmail_app_password"])

    # ── STEP 1: Get LinkedIn profile ──────────────────────────────────────────
    profile = None
    linkedin_url = args.url or ""

    if linkedin_url:
        step(f"Scraping LinkedIn profile: {linkedin_url}")

        # Check if already contacted
        existing = tracker.already_contacted(linkedin_url=linkedin_url)
        if existing:
            warn(f"Already contacted {existing['target_name']} on {existing['date_sent'][:10]}!")
            choice = input("Send again anyway? [y/N]: ").strip().lower()
            if choice != "y":
                info("Skipped.")
                return

        scraper = LinkedInScraper(headless=False)
        profile = scraper.scrape_profile(linkedin_url)

    elif args.company and args.auto_hunt:
        step(f"Auto-hunting targets at {args.company}...")
        scraper = LinkedInScraper(headless=False)
        people = scraper.search_people_at_company(args.company, max_results=8)

        if not people:
            err("No people found.")
            return

        print(f"\n{C.BOLD}Top targets at {args.company}:{C.RESET}")
        for i, p in enumerate(people[:5], 1):
            print(f"  {i}. {p['name']} — {p['title']}")

        choice = input("\nPick a number to reach out to (or 'q' to quit): ").strip()
        if choice.lower() == "q":
            return
        try:
            idx = int(choice) - 1
            selected = people[idx]
            linkedin_url = selected["url"]
        except (ValueError, IndexError):
            err("Invalid selection.")
            return

        # Scrape the selected profile
        step(f"Scraping profile for {selected['name']}...")
        profile = scraper.scrape_profile(linkedin_url)

    else:
        # Manual entry
        print("\nNo LinkedIn URL provided. Enter details manually:")
        name = input("Target name: ").strip()
        title = input("Their title: ").strip()
        company = input("Their company: ").strip()
        linkedin_url = input("LinkedIn URL (optional): ").strip()
        about = input("Brief about them (optional): ").strip()

        profile = LinkedInProfile(
            name=name,
            title=title,
            company=company,
            profile_url=linkedin_url,
            about=about
        )

    if not profile or not profile.name:
        err("Could not get profile info. Try with a direct LinkedIn URL.")
        return

    ok(f"Profile loaded: {profile.name} — {profile.title or profile.headline}")

    # ── STEP 2: Find email ────────────────────────────────────────────────────
    step(f"Finding email for {profile.name}...")

    email_result = find_email(
        full_name=profile.name,
        company_name=profile.company or args.company or "",
        hunter_api_key=cfg["hunter_api_key"]
    )

    target_email = ""

    if email_result.get("email"):
        confidence = email_result["confidence"]
        method = email_result["method"]
        suggested = email_result["email"]

        if confidence >= 80:
            ok(f"Email found (high confidence): {suggested}")
            target_email = suggested
        else:
            warn(f"Email guess ({method}, {confidence}% confidence): {suggested}")
            if email_result.get("alternatives"):
                print("  Alternatives:")
                for i, alt in enumerate(email_result["alternatives"][:3], 1):
                    print(f"    {i}. {alt['email']}")
            print(f"\n  [1] Use {suggested}")
            print(f"  [2] Enter email manually")
            choice = input("Choice [1]: ").strip()
            if choice == "2":
                target_email = input("Enter email address: ").strip()
            else:
                target_email = suggested
    else:
        warn("Couldn't find email automatically.")
        target_email = input("Enter their email address manually: ").strip()

    if not target_email:
        err("No email address. Can't send.")
        return

    # ── STEP 3: Generate email ────────────────────────────────────────────────
    email_type = args.type or "internship"
    step(f"Generating personalized {email_type} email for {profile.name}...")

    custom_context = args.context or ""
    if not custom_context and not args.no_prompt:
        print(f"\n  {C.DIM}Optional: Add any extra context for this email (company initiative, mutual connection, etc.)")
        print(f"  Press ENTER to skip.{C.RESET}")
        custom_context = input("  Extra context: ").strip()

    email_data = generate_cold_email(
        target_profile=profile,
        email_type=email_type,
        custom_context=custom_context or None,
        anthropic_api_key=cfg["anthropic_api_key"]
    )

    ok("Email generated!")

    if email_data.get("personalization_notes"):
        info("Personalization used:")
        for note in email_data["personalization_notes"]:
            print(f"    • {note}")

    # ── STEP 4: Draft & Review ────────────────────────────────────────────────
    step("Saving draft for your review...")

    draft_info = sender.draft_and_review(
        to_email=target_email,
        to_name=profile.name,
        subject=email_data["subject"],
        body_text=email_data["body_text"],
        body_html=email_data["body_html"]
    )

    # ── STEP 5: Confirm & Send ────────────────────────────────────────────────
    sent = sender.confirm_and_send(draft_info)

    # ── STEP 6: Log to tracker ────────────────────────────────────────────────
    status = "sent" if sent else "draft"
    tracker.log_outreach(
        target_name=profile.name,
        target_email=target_email,
        target_title=profile.title or profile.headline,
        target_company=profile.company or args.company or "",
        linkedin_url=linkedin_url,
        email_type=email_type,
        subject=email_data["subject"],
        status=status,
        notes=custom_context[:100] if custom_context else ""
    )

    ok(f"Logged to outreach tracker (status: {status})")

    # Show follow-up reminder
    reminder = tracker.get_follow_up_reminder()
    if reminder:
        print(reminder)


# ─── STATUS COMMAND ───────────────────────────────────────────────────────────
def cmd_status(args):
    """Show outreach stats and recent activity."""
    tracker = OutreachTracker()
    tracker.print_stats()
    tracker.list_recent(n=args.n or 10)

    reminder = tracker.get_follow_up_reminder()
    if reminder:
        print(reminder)


# ─── FOLLOWUP COMMAND ─────────────────────────────────────────────────────────
def cmd_followup(args):
    """Show who needs a follow-up and optionally update their status."""
    tracker = OutreachTracker()
    due = tracker.get_follow_ups_due()

    if not due:
        ok("No follow-ups due. You're on top of it! 🎉")
        return

    print(f"\n{C.BOLD}Follow-ups due ({len(due)}):{C.RESET}")
    for i, entry in enumerate(due, 1):
        print(f"\n  {i}. {entry['target_name']} @ {entry['target_company']}")
        print(f"     Sent: {entry['date_sent'][:10]}  |  Follow-up due: {entry['follow_up_date']}")
        print(f"     Email: {entry['target_email']}")

    print(f"\n{C.DIM}To update status, run:{C.RESET}")
    print(f"{C.DIM}  python cold_outreach.py update --email someone@company.com --status replied{C.RESET}")


# ─── UPDATE COMMAND ───────────────────────────────────────────────────────────
def cmd_update(args):
    """Update status of an outreach entry."""
    tracker = OutreachTracker()
    valid_statuses = ["sent", "draft", "replied", "bounced", "interview_scheduled", "no_response"]

    if args.status not in valid_statuses:
        err(f"Invalid status. Choose from: {', '.join(valid_statuses)}")
        return

    success = tracker.update_status(
        target_email=args.email,
        new_status=args.status,
        notes=args.notes or ""
    )

    if success:
        ok(f"Updated {args.email} → {args.status}")
    else:
        warn(f"Could not find entry for {args.email}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    banner()

    parser = argparse.ArgumentParser(
        description="Cold Reachout Hunter — automated LinkedIn-to-email outreach",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command")

    # hunt
    hunt_parser = subparsers.add_parser("hunt", help="Find targets at a company")
    hunt_parser.add_argument("--company", "-c", help="Company name")
    hunt_parser.add_argument("--max", "-m", type=int, default=10, help="Max results (default: 10)")

    # send
    send_parser = subparsers.add_parser("send", help="Full pipeline: scrape → email → send")
    send_parser.add_argument("--url", "-u", help="LinkedIn profile URL")
    send_parser.add_argument("--company", "-c", help="Company name (used with --auto-hunt)")
    send_parser.add_argument("--auto-hunt", action="store_true", help="Auto-find best target at company")
    send_parser.add_argument(
        "--type", "-t",
        choices=list(EMAIL_TYPES.keys()),
        default="internship",
        help="Email type (default: internship)"
    )
    send_parser.add_argument("--context", help="Extra context for email generation")
    send_parser.add_argument("--no-prompt", action="store_true", help="Skip extra context prompt")

    # status
    status_parser = subparsers.add_parser("status", help="Show outreach stats")
    status_parser.add_argument("--n", type=int, default=10, help="Number of recent entries to show")

    # followup
    subparsers.add_parser("followup", help="Show who needs a follow-up")

    # update
    update_parser = subparsers.add_parser("update", help="Update status of an outreach")
    update_parser.add_argument("--email", required=True, help="Target's email address")
    update_parser.add_argument("--status", required=True,
        choices=["sent", "draft", "replied", "bounced", "interview_scheduled", "no_response"])
    update_parser.add_argument("--notes", help="Optional notes")

    # config check
    subparsers.add_parser("config", help="Check your configuration")

    args = parser.parse_args()

    if not args.command or args.command == "config":
        check_config()
        if not args.command:
            parser.print_help()
        return

    dispatch = {
        "hunt": cmd_hunt,
        "send": cmd_send,
        "status": cmd_status,
        "followup": cmd_followup,
        "update": cmd_update,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
