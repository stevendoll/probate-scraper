"""
Route: POST /real-estate/probate-leads/stripe/webhook

Handles Stripe lifecycle events to keep subscriber status in sync.

Handled event types:
  customer.subscription.created  → status = active
  customer.subscription.updated  → status = <stripe subscription status>
  customer.subscription.deleted  → status = canceled
  invoice.payment_failed         → status = past_due
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Attr

import db
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()


@router.post("/real-estate/probate-leads/stripe/webhook")
def stripe_webhook():
    from stripe_helpers import construct_stripe_event  # noqa: PLC0415 — local for testability

    raw_body   = router.current_event.raw_event.get("body") or ""
    sig_header = (router.current_event.headers or {}).get("Stripe-Signature", "")

    payload = raw_body.encode() if isinstance(raw_body, str) else raw_body
    event, err = construct_stripe_event(payload=payload, sig_header=sig_header)
    if err:
        logger.warning("Stripe signature error: %s", err)
        return {"error": err}, 400

    event_type  = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    stripe_customer_id = data_object.get("customer") or data_object.get("id", "")

    # Map Stripe event type → our subscriber status
    if event_type == "customer.subscription.created":
        new_status = "active"
    elif event_type == "customer.subscription.updated":
        new_status = data_object.get("status", "active")
    elif event_type == "customer.subscription.deleted":
        new_status = "canceled"
    elif event_type == "invoice.payment_failed":
        new_status = "past_due"
        stripe_customer_id = data_object.get("customer", stripe_customer_id)
    else:
        logger.info("Unhandled Stripe event: %s", event_type)
        return {"received": True, "action": "ignored", "type": event_type}

    logger.info(
        "Stripe event type=%s customer=%s new_status=%s",
        event_type, stripe_customer_id, new_status,
    )

    if not stripe_customer_id:
        logger.warning("No customer ID in Stripe event %s", event_type)
        return {"received": True, "action": "no_customer_id"}, 200

    # Find subscriber by stripe_customer_id
    try:
        result = db.subscribers_table.scan(
            FilterExpression=Attr("stripe_customer_id").eq(stripe_customer_id)
        )
        items = result.get("Items", [])
    except Exception as exc:
        logger.exception("subscribers scan for webhook failed", exc_info=exc)
        return {"error": "Database error"}, 500

    if not items:
        logger.warning("No subscriber for Stripe customer: %s", stripe_customer_id)
        return {"received": True, "action": "no_subscriber_found"}, 200

    subscriber_id = items[0]["subscriber_id"]
    try:
        db.subscribers_table.update_item(
            Key={"subscriber_id": subscriber_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     new_status,
                ":updated_at": now_iso(),
            },
        )
    except Exception as exc:
        logger.exception("subscribers update for webhook failed", exc_info=exc)
        return {"error": "Failed to update subscriber"}, 500

    logger.info("Subscriber %s status → %s", subscriber_id, new_status)
    return {
        "received":     True,
        "action":       "subscriber_updated",
        "subscriberId": subscriber_id,
        "status":       new_status,
    }
