"""
auth_helpers.py — JWT creation/verification, magic-link sending, and activity logging.

Token types
-----------
  magic    — 15-min token sent in the login email; sub = email
  access   — 7-day session token returned by /auth/verify; sub = user_id
  prospect — 30-day token for marketing prospect emails; sub = user_id

Email sending
-------------
send_magic_link is here because it is part of the auth flow (login).
send_prospect_email lives in email_helpers.py (marketing, not auth).

Local dev / tests
-----------------
When FROM_EMAIL is unset, send_magic_link logs to console instead of calling SES.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import jwt

from utils import now_iso  # noqa: F401 — re-exported for convenience in tests

log = logging.getLogger(__name__)

JWT_SECRET                  = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
MAGIC_LINK_EXPIRY_MIN       = 15
ACCESS_TOKEN_EXPIRY_DAYS    = 7
PROSPECT_TOKEN_EXPIRY_DAYS  = 30

FROM_EMAIL          = os.environ.get("FROM_EMAIL", "")
MAGIC_LINK_BASE_URL = os.environ.get("MAGIC_LINK_BASE_URL", "http://localhost:3000/auth/verify")


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


def create_prospect_token(user_id: str, email: str, price: int) -> str:
    """Return a signed 30-day JWT for prospect funnel links."""
    payload = {
        "sub":   user_id,
        "email": email,
        "price": price,
        "type":  "prospect",
        "exp":   datetime.now(timezone.utc) + timedelta(days=PROSPECT_TOKEN_EXPIRY_DAYS),
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


def log_activity(
    user_id: str,
    activity_type: str,
    email_template: str = "",
    from_name: str = "",
    subject_line: str = "",
    prospect_token: str = "",
    metadata: dict = None,
) -> None:
    """Write a user activity record to the activities DynamoDB table.

    Failures are logged and swallowed — activity logging must never break
    the primary email or auth flow.
    """
    if metadata is None:
        metadata = {}
    try:
        import db  # local import keeps auth_helpers free of top-level db dependency
        activity_item = {
            "activity_id":    str(uuid.uuid4()),
            "user_id":        user_id,
            "activity_type":  activity_type,
            "timestamp":      now_iso(),
            "email_template": email_template,
            "from_name":      from_name,
            "subject_line":   subject_line,
            "prospect_token": prospect_token,
            "metadata":       metadata,
        }
        db.activities_table.put_item(Item=activity_item)
        log.info("Activity logged: %s for user %s", activity_type, user_id)
    except Exception as exc:
        log.error("Failed to log activity: %s", exc)
