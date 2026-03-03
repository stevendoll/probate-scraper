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
from datetime import datetime, timedelta, timezone

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
    """Return a signed 30-day JWT for use in marketing funnel emails.

    Payload claims:
      sub   — user_id
      email — prospect's email address
      price — offered monthly price in dollars (int)
      type  — "funnel"
    """
    payload = {
        "sub":   user_id,
        "email": email,
        "price": price,
        "type":  "funnel",
        "exp":   datetime.now(timezone.utc) + timedelta(days=FUNNEL_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


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


def send_funnel_email(
    to_email: str,
    token: str,
    leads: list,
    price: int,
) -> None:
    """Send a marketing funnel email with sample leads and subscribe/unsubscribe links.

    When FROM_EMAIL is unset (local dev / unit tests) the email content is
    logged to console at INFO level and no SES call is made.

    Args:
        to_email: Recipient email address.
        token:    Signed funnel JWT (used to build subscribe/unsubscribe links).
        leads:    List of lead dicts with at least grantor, recordedDate, docNumber.
        price:    Offered monthly subscription price in dollars.
    """
    subscribe_url   = f"{UI_BASE_URL}/signup?token={token}"
    unsubscribe_url = f"{UI_BASE_URL}/unsubscribe?token={token}"

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

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#111;max-width:600px;margin:0 auto;padding:24px">
  <h2 style="color:#1d4ed8">Collin County Probate Leads</h2>
  <p>Here is a sample of recent probate leads in Collin County, TX:</p>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    <thead>
      <tr style="background:#f3f4f6">
        <th style="padding:8px 12px;text-align:left">Grantor</th>
        <th style="padding:8px 12px;text-align:left">Recorded Date</th>
        <th style="padding:8px 12px;text-align:left">Doc Number</th>
      </tr>
    </thead>
    <tbody>
      {lead_rows_html}
    </tbody>
  </table>
  <p>
    Subscribe for <strong>${price}/month</strong> to receive daily leads delivered to your
    dashboard.
  </p>
  <p style="margin:24px 0">
    <a href="{subscribe_url}"
       style="background:#1d4ed8;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold">
      Subscribe for ${price}/mo
    </a>
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0">
  <p style="font-size:12px;color:#6b7280">
    You received this because your email was submitted for a free trial.
    <a href="{unsubscribe_url}" style="color:#6b7280">Unsubscribe</a>
  </p>
</body>
</html>"""

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
    try:
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": f"Collin County Probate Leads — Subscribe for ${price}/mo"},
                "Body": {
                    "Text": {"Data": text_body},
                    "Html": {"Data": html_body},
                },
            },
        )
    except Exception as exc:
        log.error("SES send_email (funnel) failed for %s: %s", to_email, exc)
        raise
