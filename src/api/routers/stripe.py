"""
Route: POST /real-estate/probate-leads/stripe/webhook

Handles Stripe lifecycle events to keep user status in sync.

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

    # Map Stripe event type → our user status
    if event_type == "checkout.session.completed":
        # Link the Stripe customer to our user record.
        # The subscription.created event fires next and sets status → active.
        user_id            = data_object.get("client_reference_id", "")
        stripe_customer_id = data_object.get("customer", "")
        if not user_id:
            logger.warning("checkout.session.completed missing client_reference_id")
            return {"received": True, "action": "no_user_id"}, 200
        try:
            db.users_table.update_item(
                Key={"user_id": user_id},
                UpdateExpression=(
                    "SET stripe_customer_id = :cid, #status = :status, updated_at = :updated_at"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":cid":        stripe_customer_id,
                    ":status":     "pending",
                    ":updated_at": now_iso(),
                },
            )
        except Exception as exc:
            logger.error("users update stripe_customer_id failed: %s", exc)
            return {"error": "Database error"}, 500
        logger.info(
            "checkout.session.completed user=%s stripe_customer=%s status=pending",
            user_id, stripe_customer_id,
        )
        return {
            "received": True,
            "action":   "customer_linked",
            "userId":   user_id,
        }
    elif event_type == "customer.subscription.created":
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

    # Find user by stripe_customer_id
    try:
        result = db.users_table.scan(
            FilterExpression=Attr("stripe_customer_id").eq(stripe_customer_id)
        )
        items = result.get("Items", [])
    except Exception as exc:
        logger.error("users scan for webhook failed: %s", exc)
        return {"error": "Database error"}, 500

    if not items:
        logger.warning("No user for Stripe customer: %s", stripe_customer_id)
        return {"received": True, "action": "no_subscriber_found"}, 200

    user_id = items[0]["user_id"]

    # Build update expression — always set status; also persist subscription ID when available
    update_parts  = ["#status = :status", "updated_at = :updated_at"]
    attr_names    = {"#status": "status"}
    attr_values   = {":status": new_status, ":updated_at": now_iso()}

    stripe_sub_id = data_object.get("id", "") if event_type == "customer.subscription.created" else ""
    if stripe_sub_id:
        update_parts.append("stripe_subscription_id = :sub_id")
        attr_values[":sub_id"] = stripe_sub_id

    try:
        db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )
    except Exception as exc:
        logger.error("users update for webhook failed: %s", exc)
        return {"error": "Failed to update user"}, 500

    logger.info("User %s status → %s", user_id, new_status)
    return {
        "received": True,
        "action":   "subscriber_updated",
        "userId":   user_id,
        "status":   new_status,
    }
