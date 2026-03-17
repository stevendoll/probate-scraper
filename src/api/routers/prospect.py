"""
Marketing prospect routes (no API key required for public endpoints):

  POST /real-estate/probate-leads/admin/prospect/send  — admin Bearer required
  POST /real-estate/probate-leads/auth/unsubscribe     — public, prospect JWT in body
  POST /real-estate/probate-leads/stripe/checkout      — public, prospect JWT in body
"""

import os
import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Key

import db
from auth_helpers import (
    create_prospect_token,
    get_bearer_payload,
    verify_token,
)
from data_helpers import parse_email_input
from email_helpers import send_prospect_email
from email_templates import send_journey_email
from models import Document, User
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

# Round-robin price ladder for new free-trial users (dollars/month)
_PRICE_LADDER = [19, 39, 59, 79]

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
UI_BASE_URL       = os.environ.get("UI_BASE_URL", "http://localhost:3001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin(event: dict) -> dict | None:
    """Verify the request carries a valid admin-role access token."""
    payload = get_bearer_payload(event)
    if not payload:
        return None
    if payload.get("type") != "access":
        return None
    if payload.get("role") != "admin":
        return None
    return payload


def _fetch_recent_documents(lead_count: int) -> list:
    """Return up to lead_count recent documents across all known locations.

    Queries the location-date-index GSI for each location, merges results,
    sorts by recorded_date descending, and returns the top lead_count items.
    """
    try:
        loc_result = db.locations_table.scan(ProjectionExpression="location_code")
        location_codes = [item["location_code"] for item in loc_result.get("Items", [])]
    except Exception as exc:
        logger.error("locations scan failed: %s", exc)
        return []

    all_items: list = []
    for location_code in location_codes:
        try:
            result = db.documents_table.query(
                IndexName=db.location_date_gsi,
                KeyConditionExpression=Key("location_code").eq(location_code),
                ScanIndexForward=False,
                Limit=lead_count,
            )
            all_items.extend(result.get("Items", []))
        except Exception as exc:
            logger.error("documents query for %s failed: %s", location_code, exc)

    all_items.sort(key=lambda x: x.get("recorded_date", ""), reverse=True)
    return all_items[:lead_count]


# ---------------------------------------------------------------------------
# POST /admin/prospect/send
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/admin/prospect/send")
def admin_prospect_send():
    """Create prospect users and send them a leads email with a subscribe link.

    Request body (JSON):
      emails      (list[str], required) — prospect email addresses
      lead_count  (int, optional, default 10) — number of sample leads to include

    Returns per-email results: sent | skipped | error.
    """
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    raw_emails = body.get("emails") or []
    if not isinstance(raw_emails, list) or not raw_emails:
        return {"error": "'emails' must be a non-empty list"}, 400

    lead_count = int(body.get("lead_count") or 10)
    lead_count = max(1, min(lead_count, 50))

    leads_raw   = _fetch_recent_documents(lead_count)
    leads_dicts = [Document.from_dynamo(item).to_dict() for item in leads_raw]

    # Count existing prospect users to continue the round-robin correctly
    try:
        count_result = db.users_table.scan(
            FilterExpression="attribute_exists(offered_price)",
            Select="COUNT",
        )
        existing_count = count_result.get("Count", 0)
    except Exception:
        existing_count = 0

    results = []
    now     = now_iso()

    for idx, raw_email in enumerate(raw_emails):
        raw_email = (raw_email or "").strip()
        if not raw_email:
            results.append({"email": raw_email, "status": "skipped", "message": "empty email"})
            continue

        clean_email, first_name, last_name = parse_email_input(raw_email)
        price = _PRICE_LADDER[(existing_count + idx) % len(_PRICE_LADDER)]

        existing = db.get_user_by_email(clean_email)
        if existing:
            user_id = existing["user_id"]
            try:
                update_expr = (
                    "SET #status = :status, offered_price = :price, updated_at = :updated_at"
                )
                if first_name:
                    update_expr += ", first_name = :first_name"
                if last_name:
                    update_expr += ", last_name = :last_name"
                if not existing.get("location_codes"):
                    update_expr += ", location_codes = :location_codes"

                expr_attrs = {
                    ":status":     "prospect",
                    ":price":      price,
                    ":updated_at": now,
                }
                if first_name:
                    expr_attrs[":first_name"] = first_name
                if last_name:
                    expr_attrs[":last_name"] = last_name
                if not existing.get("location_codes"):
                    expr_attrs[":location_codes"] = {"CollinTx"}

                result = db.users_table.update_item(
                    Key={"user_id": user_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues=expr_attrs,
                    ReturnValues="ALL_NEW",
                )
                user_item = result["Attributes"]
            except Exception as exc:
                logger.error("users update_item (prospect) for %s failed: %s", clean_email, exc)
                results.append({"email": clean_email, "status": "error", "message": "database error"})
                continue
        else:
            user_id = str(uuid.uuid4())
            user_item = {
                "user_id":                user_id,
                "email":                  clean_email,
                "first_name":             first_name or "",
                "last_name":              last_name or "",
                "role":                   "user",
                "stripe_customer_id":     "",
                "stripe_subscription_id": "",
                "status":                 "prospect",
                "location_codes":         {"CollinTx"},
                "offered_price":          price,
                "created_at":             now,
                "updated_at":             now,
                "trial_expires_on":       "",
                "journey_type":           "prospect",
                "journey_step":           "prospect",
            }
            try:
                db.users_table.put_item(Item=user_item)
            except Exception as exc:
                logger.error("users put_item (prospect) for %s failed: %s", clean_email, exc)
                results.append({"email": clean_email, "status": "error", "message": "database error"})
                continue

        token = create_prospect_token(user_id, clean_email, price)
        try:
            send_prospect_email(clean_email, token, leads_dicts, price, first_name, last_name, user_id)
            results.append({
                "email":  clean_email,
                "status": "sent",
                "userId": user_id,
                "price":  price,
            })
        except Exception as exc:
            logger.error("send_prospect_email failed for %s: %s", clean_email, exc)
            results.append({"email": clean_email, "status": "error", "message": "email send failed"})

    return {
        "requestId": str(uuid.uuid4()),
        "results":   results,
        "count":     len(results),
    }


# ---------------------------------------------------------------------------
# POST /auth/unsubscribe
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/auth/unsubscribe")
def auth_unsubscribe():
    """Set the user's status to 'unsubscribed' using a prospect JWT.

    Request body (JSON):
      token  (str, required) — prospect JWT from the marketing email
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    token = (body.get("token") or "").strip()
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "prospect":
        return {"error": "Invalid or expired token"}, 401

    user_id = payload.get("sub", "")
    if not user_id:
        return {"error": "Invalid token: missing user"}, 401

    try:
        db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     "unsubscribed",
                ":updated_at": now_iso(),
            },
        )
    except Exception as exc:
        logger.error("users update_item (unsubscribe) failed: %s", exc)
        return {"error": "Failed to update status"}, 500

    logger.info("User %s unsubscribed via prospect token", user_id)
    return {"message": "You have been unsubscribed."}


# ---------------------------------------------------------------------------
# POST /stripe/checkout
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/stripe/checkout")
def stripe_checkout():
    """Create a Stripe Checkout Session for a prospect.

    Request body (JSON):
      token  (str, required) — prospect JWT from the marketing email

    Returns:
      { url: <stripe_checkout_url> }
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    token = (body.get("token") or "").strip()
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "prospect":
        return {"error": "Invalid or expired token"}, 401

    user_id = payload.get("sub", "")
    email   = payload.get("email", "")
    price   = int(payload.get("price", 0) or 0)

    if not user_id or not email or not price:
        return {"error": "Invalid token: missing required claims"}, 401

    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe is not configured"}, 503

    try:
        import stripe  # noqa: PLC0415 — local for testability
        stripe.api_key = STRIPE_SECRET_KEY

        cancel_url  = f"{UI_BASE_URL}/signup?token={token}"
        success_url = f"{UI_BASE_URL}/dashboard?checkout=success"

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency":    "usd",
                    "unit_amount": price * 100,
                    "recurring":   {"interval": "month"},
                    "product_data": {
                        "name": "Collin County Probate Leads",
                    },
                },
                "quantity": 1,
            }],
            client_reference_id=user_id,
            customer_email=email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        return {"error": "Failed to create checkout session"}, 500

    logger.info("Stripe checkout session created for user %s price=%s", user_id, price)
    return {"url": session.url}
