"""
ses_events/app.py — Lambda handler for SES event notifications via SNS.

Receives delivery, open, bounce, and complaint events from SES and writes
them to the events DynamoDB table for prospect journey tracking.

SES tags passed when sending (user_id, variant) are used to attribute
each event to the correct user.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3

_dynamodb    = boto3.resource("dynamodb")
_events_table = _dynamodb.Table(os.environ.get("EVENTS_TABLE_NAME", "events"))


def handler(event, context):
    for record in event.get("Records", []):
        if record.get("EventSource") != "aws:sns":
            continue

        try:
            message = json.loads(record["Sns"]["Message"])
        except (KeyError, json.JSONDecodeError):
            continue

        _process_ses_event(message)


def _process_ses_event(message: dict) -> None:
    event_type = message.get("eventType", "").lower()
    mail       = message.get("mail", {})

    # Tags are set via send_email Tags=[{"Name":..,"Value":..}]
    # SES delivers them as {"tag_name": ["value"]} in the notification.
    tags    = mail.get("tags", {})
    user_id = next(iter(tags.get("user_id", [])), None)
    variant = next(iter(tags.get("variant", [])), "")

    if not user_id:
        return  # Can't attribute to a user; skip

    timestamp = datetime.now(timezone.utc).isoformat()
    metadata  = {"message_id": mail.get("messageId", "")}

    if event_type == "bounce":
        bounce = message.get("bounce", {})
        metadata["bounce_type"]    = bounce.get("bounceType", "")
        metadata["bounce_subtype"] = bounce.get("bounceSubType", "")
        metadata["bounced_recipients"] = [
            r.get("emailAddress") for r in bounce.get("bouncedRecipients", [])
        ]
    elif event_type == "complaint":
        complaint = message.get("complaint", {})
        metadata["feedback_type"] = complaint.get("complaintFeedbackType", "")
        metadata["complained_recipients"] = [
            r.get("emailAddress") for r in complaint.get("complainedRecipients", [])
        ]
    elif event_type == "open":
        open_data = message.get("open", {})
        metadata["user_agent"] = open_data.get("userAgent", "")
        metadata["ip_address"] = open_data.get("ipAddress", "")

    event_item = {
        "event_id":   str(uuid.uuid4()),
        "user_id":    user_id,
        "event_type": f"email_{event_type}",
        "timestamp":  timestamp,
        "variant":    variant,
        "metadata":   metadata,
    }

    try:
        _events_table.put_item(Item=event_item)
    except Exception as exc:
        print(f"Failed to write SES event to DynamoDB: {exc}")
