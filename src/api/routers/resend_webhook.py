"""
Route: POST /real-estate/probate-leads/resend/webhook

Handles Resend email event notifications and writes them to the events table.
Replaces the former SES → SNS → SesEventsFunction pipeline.

Handled event types (Resend naming):
  email.sent        → email_sent
  email.delivered   → email_delivered
  email.opened      → email_open
  email.clicked     → email_click
  email.bounced     → email_bounce
  email.complained  → email_complaint
"""

import uuid
from datetime import datetime, timezone

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router

import db

logger = Logger(service="probate-api")
router = Router()

# Map Resend event types to our internal event_type strings
_EVENT_TYPE_MAP = {
    "email.sent":       "email_sent",
    "email.delivered":  "email_delivered",
    "email.opened":     "email_open",
    "email.clicked":    "email_click",
    "email.bounced":    "email_bounce",
    "email.complained": "email_complaint",
}


@router.post("/real-estate/probate-leads/resend/webhook")
def resend_webhook():
    from resend_helpers import construct_resend_event  # noqa: PLC0415

    raw_body = router.current_event.raw_event.get("body") or ""
    headers  = router.current_event.headers or {}

    payload = raw_body.encode() if isinstance(raw_body, str) else raw_body
    event, err = construct_resend_event(payload=payload, headers=headers)
    if err:
        logger.warning("Resend signature error: %s", err)
        return {"error": err}, 400

    resend_type = event.get("type", "")
    event_type  = _EVENT_TYPE_MAP.get(resend_type)
    if not event_type:
        logger.info("Unhandled Resend event: %s", resend_type)
        return {"received": True, "action": "ignored", "type": resend_type}

    data = event.get("data", {})
    tags = data.get("tags") or {}

    # Tags are set as a dict when sending via Resend SDK
    user_id = tags.get("user_id", "")
    variant = tags.get("variant", "")

    if not user_id:
        logger.info("Resend event %s has no user_id tag — skipping", resend_type)
        return {"received": True, "action": "no_user_id"}

    metadata = {"email_id": data.get("email_id", "")}

    if resend_type == "email.bounced":
        metadata["bounce_type"] = data.get("bounce", {}).get("type", "")
    elif resend_type == "email.opened":
        metadata["user_agent"] = data.get("click", {}).get("userAgent", "")
    elif resend_type == "email.clicked":
        metadata["link"]       = data.get("click", {}).get("link", "")
        metadata["user_agent"] = data.get("click", {}).get("userAgent", "")

    event_item = {
        "event_id":   str(uuid.uuid4()),
        "user_id":    user_id,
        "event_type": event_type,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "variant":    variant,
        "metadata":   metadata,
    }

    try:
        db.events_table.put_item(Item=event_item)
        logger.info("Resend event %s logged for user %s", event_type, user_id)
    except Exception as exc:
        logger.error("Failed to write Resend event to DynamoDB: %s", exc)
        return {"error": "Database error"}, 500

    return {"received": True, "action": "logged", "event_type": event_type}
