"""
auth_helpers.py — JWT creation/verification + SES magic-link email.

Token types
-----------
  magic   — 15-min token sent in the login email; sub = email
  access  — 7-day session token returned by /auth/verify; sub = user_id
  funnel  — 30-day token for marketing funnel emails; sub = user_id

Local dev / tests
-----------------
When FROM_EMAIL is unset the magic link / funnel email is logged to console
instead of being emailed (same pattern as STRIPE_WEBHOOK_SECRET skipping
signature verification in stripe_helpers.py).
"""

import logging
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import jwt

from utils import now_iso  # noqa: F401 — re-exported for convenience in tests

log = logging.getLogger(__name__)

JWT_SECRET                = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
MAGIC_LINK_EXPIRY_MIN     = 15
ACCESS_TOKEN_EXPIRY_DAYS  = 7
FUNNEL_TOKEN_EXPIRY_DAYS  = 30
FROM_EMAIL                = os.environ.get("FROM_EMAIL", "")
MAGIC_LINK_BASE_URL       = os.environ.get(
    "MAGIC_LINK_BASE_URL", "http://localhost:3000/auth/verify"
)
UI_BASE_URL               = os.environ.get("UI_BASE_URL", "http://localhost:3001")


def create_magic_token(email: str) -> str:
    """Return a signed 15-min JWT whose ``sub`` claim is the user's email."""
    payload = {
        "sub":  email,
        "type": "magic",
        "exp":  datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_EXPIRY_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_access_token(user_id: str, role: str) -> str:
    """Return a signed 7-day access JWT whose ``sub`` claim is the user_id."""
    payload = {
        "sub":  user_id,
        "role": role,
        "type": "access",
        "exp":  datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_funnel_token(user_id: str, email: str, price: int) -> str:
    """Return a signed 30-day JWT for funnel links."""
    payload = {
        "sub":  user_id,
        "email": email,
        "price": price,
        "type": "funnel",
        "exp":  datetime.now(timezone.utc) + timedelta(days=FUNNEL_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def log_activity(
    user_id: str,
    activity_type: str,
    email_template: str = "",
    from_name: str = "",
    subject_line: str = "",
    funnel_token: str = "",
    metadata: dict = None,
) -> None:
    """Log user activity to activities table."""
    if not metadata:
        metadata = {}
    
    try:
        import db
        activity_id = str(uuid.uuid4())
        activity_item = {
            "activity_id":    activity_id,
            "user_id":        user_id,
            "activity_type":  activity_type,
            "timestamp":      now_iso(),
            "email_template":  email_template,
            "from_name":      from_name,
            "subject_line":   subject_line,
            "funnel_token":   funnel_token,
            "metadata":       metadata,
        }
        db.activities_table.put_item(Item=activity_item)
        log.info("Activity logged: %s for user %s", activity_type, user_id)
    except Exception as exc:
        log.error("Failed to log activity: %s", exc)


def verify_token(token: str) -> dict | None:
    """Decode and verify a JWT.  Returns the payload dict or ``None`` on any failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def get_bearer_payload(event: dict) -> dict | None:
    """Extract the Bearer token from the Authorization header and verify it.

    Returns the decoded payload dict or ``None`` if the header is missing,
    malformed, or the token is invalid/expired.
    """
    auth = (event.get("headers") or {}).get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return verify_token(auth[7:])


def send_magic_link(email: str, token: str) -> None:
    """Send a magic-link login email via SES.

    When FROM_EMAIL is unset (local dev / unit tests) the link is logged to
    console at INFO level and no SES call is made.
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


def _load_random_line_from_file(file_path: Path) -> str:
    """Load a random line from a text file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            return random.choice(lines) if lines else ""
    except FileNotFoundError:
        log.error("Template file not found: %s", file_path)
        return ""


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

    When FROM_EMAIL is unset (local dev / unit tests) the email content is
    logged to console at INFO level and no SES call is made.

    Args:
        to_email: Recipient email address (format: "John Doe <john@email.com>" or "john@email.com").
        token:    Signed funnel JWT (used to build subscribe/unsubscribe links).
        leads:    List of lead dicts with at least grantor, recordedDate, docNumber.
        price:    Offered monthly subscription price in dollars.
        first_name: Optional first name for personalization.
        last_name: Optional last name for personalization.
        user_id:  User ID for activity tracking.
    """
    subscribe_url   = f"{UI_BASE_URL}/signup?token={token}"
    unsubscribe_url = f"{UI_BASE_URL}/unsubscribe?token={token}"

    # Load random email components
    templates_dir = Path(__file__).parent / "templates"
    
    # Parse email address to extract name if available
    email_address = to_email
    if "<" in to_email and ">" in to_email:
        # Format: "John Doe <john@email.com>"
        name_part = to_email.split("<")[0].strip()
        email_address = to_email.split("<")[1].split(">")[0].strip()
        # Extract first and last name from name part
        if " " in name_part:
            name_parts = name_part.split()
            first_name = name_parts[0] if not first_name else first_name
            last_name = name_parts[-1] if not last_name else last_name
        else:
            first_name = name_part if not first_name else first_name
            last_name = "" if not last_name else last_name
    
    # Choose subject: personalized if we have first_name, otherwise regular
    if first_name:
        personalized_subjects = (templates_dir / "email_subjects_personalized.txt")
        if personalized_subjects.exists():
            subject = _load_random_line_from_file(personalized_subjects)
            subject = subject.replace("{first_name}", first_name)
        else:
            subject = _load_random_line_from_file(templates_dir / "email_subjects.txt")
    else:
        subject = _load_random_line_from_file(templates_dir / "email_subjects.txt")
    
    from_name = _load_random_line_from_file(templates_dir / "email_from_names.txt")
    preheader = _load_random_line_from_file(templates_dir / "email_preheaders.txt")
    
    # Build lead rows for the HTML table
    lead_rows_html = ""
    lead_rows_text = ""
    for lead in leads:
        grantor  = lead.get("grantor") or lead.get("Grantor", "")
        date     = lead.get("recordedDate") or lead.get("recorded_date", "")
        doc_num  = lead.get("docNumber") or lead.get("doc_number", "")
        lead_rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{grantor}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{date}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb'>{doc_num}</td>"
            f"</tr>"
        )
        lead_rows_text += f"  {grantor}  |  {date}  |  {doc_num}\n"

    # Load HTML template from file
    template_path = Path(__file__).parent / "templates" / "prospect_email_v1.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
    except FileNotFoundError:
        log.error("Funnel email template not found at %s", template_path)
        raise
    
    html_body = html_template.replace("{lead_rows_html}", lead_rows_html).replace("{price}", str(price)).replace("{subscribe_url}", subscribe_url).replace("{unsubscribe_url}", unsubscribe_url).replace("{preheader}", preheader)

    text_body = (
        f"Collin County Probate Leads\n\n"
        f"Here is a sample of recent probate leads:\n\n"
        f"  Grantor  |  Recorded Date  |  Doc Number\n"
        f"  {'─' * 50}\n"
        f"{lead_rows_text}\n"
        f"Subscribe for ${price}/month: {subscribe_url}\n\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )

    # Log email sent activity
    if user_id:
        log_activity(
            user_id=user_id,
            activity_type="email_sent",
            email_template="prospect_email_v1.html",
            from_name=from_name,
            subject_line=subject,
            funnel_token=token,
            metadata={
                "to_email": email_address,
                "price": price,
                "lead_count": len(leads),
                "personalized": bool(first_name),
            }
        )

    if not FROM_EMAIL:
        log.info(
            "Funnel email (FROM_EMAIL unset — not sent via SES) to=%s price=%s subscribe=%s",
            to_email, price, subscribe_url,
        )
        return

    ses = boto3.client("ses")
    try:
        # Build source with display name
        source_email = f"{from_name} <{FROM_EMAIL}>"
        
        ses.send_email(
            Source=source_email,
            Destination={"ToAddresses": [email_address]},
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
