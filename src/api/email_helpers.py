"""
email_helpers.py — Resend email sending for prospect/marketing emails.

Magic-link (auth) email is in auth_helpers.send_magic_link.

When FROM_EMAIL or RESEND_API_KEY is unset (local dev / unit tests) all sends
are logged to console at INFO level and no API call is made — same pattern used
by stripe_helpers.py for webhook verification.
"""

import logging
import os
import random
from pathlib import Path

log = logging.getLogger(__name__)

FROM_EMAIL      = os.environ.get("FROM_EMAIL", "")
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "")
UI_BASE_URL     = os.environ.get("UI_BASE_URL", "http://localhost:3001")


def _load_random_line_from_file(file_path: Path) -> str:
    """Return a random non-empty line from a text file, or '' if unavailable."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            return random.choice(lines) if lines else ""
    except FileNotFoundError:
        log.error("Template file not found: %s", file_path)
        return ""


def send_prospect_email(
    to_email: str,
    token: str,
    leads: list,
    price: int,
    first_name: str = None,
    last_name: str = None,
    user_id: str = None,
    variant: str = "default",
) -> None:
    """Send a marketing prospect email with sample leads and subscribe/unsubscribe links.

    When FROM_EMAIL is unset the email content is logged to console instead.

    Args:
        to_email:   Recipient email address (plain "email@example.com" format).
        token:      Signed prospect JWT (used to build subscribe/unsubscribe links).
        leads:      List of lead dicts with at least grantor, recordedDate, docNumber.
        price:      Offered monthly subscription price in dollars.
        first_name: Optional first name for subject-line personalization.
        last_name:  Optional last name (unused currently, available for templates).
        user_id:    User ID for event logging after a successful send.
        variant:    A/B test variant name for event tracking (default: "default").
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
        log.error("Prospect email template not found at %s", template_path)
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

    if not FROM_EMAIL or not RESEND_API_KEY:
        log.info(
            "Prospect email (FROM_EMAIL/RESEND_API_KEY unset — not sent) to=%s price=%s subscribe=%s",
            to_email, price, subscribe_url,
        )
        return

    import resend  # noqa: PLC0415
    resend.api_key = RESEND_API_KEY
    source_email = f"{from_name} <{FROM_EMAIL}>" if from_name else FROM_EMAIL
    send_params = {
        "from":    source_email,
        "to":      [to_email],
        "subject": subject,
        "text":    text_body,
        "html":    html_body,
        "tags": [
            {"name": "user_id", "value": user_id or ""},
            {"name": "variant", "value": variant},
        ],
    }
    try:
        resend.Emails.send(send_params)
    except Exception as exc:
        log.error("Resend send (prospect) failed for %s: %s", to_email, exc)
        raise

    # Log event only after a confirmed successful send
    if user_id:
        from auth_helpers import log_event  # local import avoids circular dep at module load
        log_event(
            user_id=user_id,
            event_type="email_sent",
            variant=variant,
            email_template="prospect_email_v1.html",
            from_name=from_name,
            subject_line=subject,
            prospect_token=token,
            metadata={
                "to_email":    to_email,
                "price":       price,
                "lead_count":  len(leads),
                "personalized": bool(first_name),
            },
        )
