"""
auth_helpers.py — JWT creation/verification and activity logging.

Token types
-----------
  magic   — 15-min token sent in the login email; sub = email
  access  — 7-day session token returned by /auth/verify; sub = user_id
  funnel  — 30-day token for marketing funnel emails; sub = user_id

Email sending
-------------
See email_helpers.py for send_magic_link and send_funnel_email.

Local dev / tests
-----------------
When FROM_EMAIL is unset, email_helpers skips SES and logs to console.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import jwt

from utils import now_iso  # noqa: F401 — re-exported for convenience in tests

log = logging.getLogger(__name__)

JWT_SECRET               = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
MAGIC_LINK_EXPIRY_MIN    = 15
ACCESS_TOKEN_EXPIRY_DAYS = 7
FUNNEL_TOKEN_EXPIRY_DAYS = 30


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


def log_activity(
    user_id: str,
    activity_type: str,
    email_template: str = "",
    from_name: str = "",
    subject_line: str = "",
    funnel_token: str = "",
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
            "activity_id":   str(uuid.uuid4()),
            "user_id":       user_id,
            "activity_type": activity_type,
            "timestamp":     now_iso(),
            "email_template": email_template,
            "from_name":     from_name,
            "subject_line":  subject_line,
            "funnel_token":  funnel_token,
            "metadata":      metadata,
        }
        db.activities_table.put_item(Item=activity_item)
        log.info("Activity logged: %s for user %s", activity_type, user_id)
    except Exception as exc:
        log.error("Failed to log activity: %s", exc)
