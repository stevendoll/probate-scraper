"""
Public feedback route (no API key, no auth required):

  POST /real-estate/probate-leads/feedback

Logs a DynamoDB event and sends a Resend email to ADMIN_EMAIL.
"""

import logging
import os
import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Attr

import db
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL", "admin@collincountyleads.com")
FROM_EMAIL     = os.environ.get("FROM_EMAIL", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")


# ---------------------------------------------------------------------------
# POST /feedback
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/feedback")
def post_feedback():
    """Accept user feedback, log it, and email admin."""
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    message = (body.get("message") or "").strip()
    if not message:
        return {"error": "'message' is required"}, 400

    source = (body.get("source") or "unknown").strip()
    email  = (body.get("email") or "").strip()

    # Resolve user_id from email if possible (best-effort — don't fail on error)
    user_id = "anonymous"
    if email:
        try:
            result = db.users_table.query(
                IndexName="email-index",
                KeyConditionExpression=__import__("boto3.dynamodb.conditions", fromlist=["Key"]).Key("email").eq(email),
            )
            items = result.get("Items", [])
            if items:
                user_id = items[0].get("user_id", "anonymous")
        except Exception as exc:
            logger.warning("Could not resolve user_id for feedback: %s", exc)

    # Log event to DynamoDB
    event_id = str(uuid.uuid4())
    try:
        db.events_table.put_item(Item={
            "event_id":   event_id,
            "user_id":    user_id,
            "event_type": "feedback",
            "timestamp":  now_iso(),
            "variant":    "",
            "metadata":   {
                "message": message,
                "source":  source,
                "email":   email,
            },
        })
    except Exception as exc:
        logger.error("Failed to store feedback event: %s", exc)
        # Continue — still try to send the email

    # Send email to admin (skip if FROM_EMAIL / RESEND_API_KEY not configured)
    if FROM_EMAIL and ADMIN_EMAIL and RESEND_API_KEY:
        ts = now_iso()
        body_text = "\n".join([
            f"Source: {source}",
            f"Email:  {email or '(not provided)'}",
            f"Time:   {ts}",
            "",
            message,
        ])
        subject = f"New feedback — {source}"
        try:
            import resend  # noqa: PLC0415
            resend.api_key = RESEND_API_KEY
            resend.Emails.send({
                "from":    FROM_EMAIL,
                "to":      [ADMIN_EMAIL],
                "subject": subject,
                "text":    body_text,
            })
            logger.info("Feedback email sent to %s", ADMIN_EMAIL)
        except Exception as exc:
            logger.error("Failed to send feedback email: %s", exc)
    else:
        logger.info(
            "Feedback received (email skipped — FROM_EMAIL/RESEND_API_KEY not set): source=%s",
            source,
        )

    return {
        "requestId": str(uuid.uuid4()),
        "status":    "ok",
    }
