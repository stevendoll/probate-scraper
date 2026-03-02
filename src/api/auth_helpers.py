"""
auth_helpers.py — JWT creation/verification + SES magic-link email.

Token types
-----------
  magic   — 15-min token sent in the login email; sub = email
  access  — 7-day session token returned by /auth/verify; sub = user_id

Local dev / tests
-----------------
When FROM_EMAIL is unset the magic link is logged to console instead of
being emailed (same pattern as STRIPE_WEBHOOK_SECRET skipping signature
verification in stripe_helpers.py).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
import jwt

from utils import now_iso  # noqa: F401 — re-exported for convenience in tests

log = logging.getLogger(__name__)

JWT_SECRET               = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
MAGIC_LINK_EXPIRY_MIN    = 15
ACCESS_TOKEN_EXPIRY_DAYS = 7
FROM_EMAIL               = os.environ.get("FROM_EMAIL", "")
MAGIC_LINK_BASE_URL      = os.environ.get(
    "MAGIC_LINK_BASE_URL", "http://localhost:3000/auth/verify"
)


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
