"""
email_helpers.py — SES email sending for magic-link and funnel emails.

When FROM_EMAIL is unset (local dev / unit tests) all sends are logged to
console at INFO level and no SES call is made — same pattern used by
stripe_helpers.py for webhook verification.
"""

import logging
import os
import random
from pathlib import Path

import boto3

log = logging.getLogger(__name__)

FROM_EMAIL          = os.environ.get("FROM_EMAIL", "")
MAGIC_LINK_BASE_URL = os.environ.get("MAGIC_LINK_BASE_URL", "http://localhost:3000/auth/verify")
MAGIC_LINK_EXPIRY_MIN = 15  # used in link text only
UI_BASE_URL         = os.environ.get("UI_BASE_URL", "http://localhost:3001")


def _load_random_line_from_file(file_path: Path) -> str:
    """Return a random non-empty line from a text file, or '' if unavailable."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            return random.choice(lines) if lines else ""
    except FileNotFoundError:
        log.error("Template file not found: %s", file_path)
        return ""


def send_magic_link(email: str, token: str) -> None:
    """Send a magic-link login email via SES.

    When FROM_EMAIL is unset the link is logged to console instead.
    """
    link = f"{MAGIC_LINK_BASE_URL}?token={token}"
    if not FROM_EMAIL:
        log.info("Magic link (FROM_EMAIL unset — not sent via SES): %s", link)
        return
    ses = boto3.client("ses")
    try:
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": "Your login link"},
                "Body": {
                    "Text": {
                        "Data": (
                            f"Click to log in (expires in {MAGIC_LINK_EXPIRY_MIN} minutes):"
                            f"\n\n{link}"
                        )
                    }
                },
            },
        )
    except Exception as exc:
        log.error("SES send_email failed: %s", exc)


def send_funnel_email(
    to_email: str,
    token: str,
    leads: list,
    price: int,
    first_name: str = None,
    last_name: str = None,
    user_id: str = None,
) -> None:
    """Send a marketing funnel email with sample leads and subscribe/unsubscribe links.

    When FROM_EMAIL is unset the email content is logged to console instead.

    Args:
        to_email:   Recipient email address (plain "email@example.com" format).
        token:      Signed funnel JWT (used to build subscribe/unsubscribe links).
        leads:      List of lead dicts with at least grantor, recordedDate, docNumber.
        price:      Offered monthly subscription price in dollars.
        first_name: Optional first name for subject-line personalization.
        last_name:  Optional last name (unused currently, available for templates).
        user_id:    User ID for activity logging after a successful send.
    """
    subscribe_url   = f"{UI_BASE_URL}/signup?token={token}"
    unsubscribe_url = f"{UI_BASE_URL}/unsubscribe?token={token}"

    templates_dir = Path(__file__).parent / "templates"

    # Pick subject line
    if first_name:
        personalized_file = templates_dir / "email_subjects_personalized.txt"
        if personalized_file.exists():
            subject = _load_random_line_from_file(personalized_file)
            subject = subject.replace("{first_name}", first_name)
        else:
            subject = _load_random_line_from_file(templates_dir / "email_subjects.txt")
    else:
        subject = _load_random_line_from_file(templates_dir / "email_subjects.txt")

    from_name = _load_random_line_from_file(templates_dir / "email_from_names.txt")
    preheader  = _load_random_line_from_file(templates_dir / "email_preheaders.txt")

    # Build lead rows
    lead_rows_html = ""
    lead_rows_text = ""
    for lead in leads:
        grantor = lead.get("grantor") or lead.get("Grantor", "")
        date    = lead.get("recordedDate") or lead.get("recorded_date", "")
        doc_num = lead.get("docNumber") or lead.get("doc_number", "")
        lead_rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{grantor}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{date}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{doc_num}</td>"
            f"</tr>"
        )
        lead_rows_text += f"  {grantor}  |  {date}  |  {doc_num}\n"

    # Load HTML template
    template_path = templates_dir / "prospect_email_v1.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
    except FileNotFoundError:
        log.error("Funnel email template not found at %s", template_path)
        raise

    html_body = (
        html_template
        .replace("{lead_rows_html}", lead_rows_html)
        .replace("{price}", str(price))
        .replace("{subscribe_url}", subscribe_url)
        .replace("{unsubscribe_url}", unsubscribe_url)
        .replace("{preheader}", preheader)
    )

    text_body = (
        f"Collin County Probate Leads\n\n"
        f"Here is a sample of recent probate leads:\n\n"
        f"  Grantor  |  Recorded Date  |  Doc Number\n"
        f"  {'─' * 50}\n"
        f"{lead_rows_text}\n"
        f"Subscribe for ${price}/month: {subscribe_url}\n\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )

    if not FROM_EMAIL:
        log.info(
            "Funnel email (FROM_EMAIL unset — not sent via SES) to=%s price=%s subscribe=%s",
            to_email, price, subscribe_url,
        )
        return

    ses = boto3.client("ses")
    source_email = f"{from_name} <{FROM_EMAIL}>" if from_name else FROM_EMAIL
    try:
        ses.send_email(
            Source=source_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": {
                    "Text": {"Data": text_body},
                    "Html": {"Data": html_body},
                },
            },
        )
    except Exception as exc:
        log.error("SES send_email (funnel) failed for %s: %s", to_email, exc)
        raise

    # Log activity only after a confirmed successful send
    if user_id:
        from auth_helpers import log_activity  # local import avoids circular dep at module load
        log_activity(
            user_id=user_id,
            activity_type="email_sent",
            email_template="prospect_email_v1.html",
            from_name=from_name,
            subject_line=subject,
            funnel_token=token,
            metadata={
                "to_email": to_email,
                "price": price,
                "lead_count": len(leads),
                "personalized": bool(first_name),
            },
        )
