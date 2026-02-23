"""
Routes:
  GET    /real-estate/probate-leads/subscribers
  POST   /real-estate/probate-leads/subscribers
  GET    /real-estate/probate-leads/subscribers/{subscriber_id}
  PATCH  /real-estate/probate-leads/subscribers/{subscriber_id}
  DELETE /real-estate/probate-leads/subscribers/{subscriber_id}
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router

import db
from models import Subscriber
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

_VALID_STATUSES = {"active", "inactive", "canceled", "past_due", "trialing"}


@router.get("/real-estate/probate-leads/subscribers")
def list_subscribers():
    """Return all subscribers."""
    try:
        result = db.subscribers_table.scan()
    except Exception as exc:
        logger.exception("subscribers scan failed", exc_info=exc)
        return {"error": "Database scan failed"}, 500

    items = [Subscriber.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    return {
        "requestId": str(uuid.uuid4()),
        "subscribers": items,
        "count": len(items),
    }


@router.post("/real-estate/probate-leads/subscribers")
def create_subscriber():
    """
    Create a new subscriber.

    Request body (JSON):
      email                   (str, required)
      location_codes          (list[str], required) — each must exist in locations table
      stripe_customer_id      (str, optional)
      stripe_subscription_id  (str, optional)
      status                  (str, optional, default: "active")
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    email = (body.get("email") or "").strip()
    if not email:
        return {"error": "'email' is required"}, 400

    raw_codes = body.get("location_codes") or []
    if not isinstance(raw_codes, list) or not raw_codes:
        return {"error": "'location_codes' must be a non-empty list"}, 400

    # Validate that each location_code exists
    for code in raw_codes:
        try:
            res = db.locations_table.get_item(Key={"location_code": code})
        except Exception as exc:
            logger.exception("locations validation failed", exc_info=exc)
            return {"error": "Database error during location validation"}, 500
        if not res.get("Item"):
            return {"error": f"Location not found: {code!r}"}, 422

    subscriber_id = str(uuid.uuid4())
    now = now_iso()

    item = {
        "subscriber_id":          subscriber_id,
        "email":                  email,
        "stripe_customer_id":     body.get("stripe_customer_id") or "",
        "stripe_subscription_id": body.get("stripe_subscription_id") or "",
        "status":                 body.get("status") or "active",
        "location_codes":         set(raw_codes),
        "created_at":             now,
        "updated_at":             now,
    }

    try:
        db.subscribers_table.put_item(Item=item)
    except Exception as exc:
        logger.exception("subscribers put_item failed", exc_info=exc)
        return {"error": "Failed to create subscriber"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": Subscriber.from_dynamo(item).to_dict(),
    }, 201


@router.get("/real-estate/probate-leads/subscribers/<subscriber_id>")
def get_subscriber(subscriber_id: str):
    """Return a single subscriber."""
    try:
        result = db.subscribers_table.get_item(Key={"subscriber_id": subscriber_id})
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if item is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": Subscriber.from_dynamo(item).to_dict(),
    }


@router.patch("/real-estate/probate-leads/subscribers/<subscriber_id>")
def update_subscriber(subscriber_id: str):
    """
    Update a subscriber's location_codes and/or status.

    Request body (JSON) — all fields optional:
      location_codes  (list[str]) — replaces the existing set
      status          (str)       — active | inactive | canceled | past_due | trialing
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    # Verify subscriber exists
    try:
        existing = db.subscribers_table.get_item(
            Key={"subscriber_id": subscriber_id}
        ).get("Item")
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    update_expr_parts = ["#updated_at = :updated_at"]
    expr_attr_names   = {"#updated_at": "updated_at"}
    expr_attr_values  = {":updated_at": now_iso()}

    raw_codes = body.get("location_codes")
    if raw_codes is not None:
        if not isinstance(raw_codes, list) or not raw_codes:
            return {"error": "'location_codes' must be a non-empty list"}, 400
        for code in raw_codes:
            try:
                res = db.locations_table.get_item(Key={"location_code": code})
            except Exception as exc:
                logger.exception("locations validation failed", exc_info=exc)
                return {"error": "Database error during location validation"}, 500
            if not res.get("Item"):
                return {"error": f"Location not found: {code!r}"}, 422
        update_expr_parts.append("location_codes = :location_codes")
        expr_attr_values[":location_codes"] = set(raw_codes)

    status = body.get("status")
    if status is not None:
        if status not in _VALID_STATUSES:
            return {"error": f"'status' must be one of {sorted(_VALID_STATUSES)}"}, 400
        update_expr_parts.append("#status = :status")
        expr_attr_names["#status"] = "status"
        expr_attr_values[":status"] = status

    try:
        result = db.subscribers_table.update_item(
            Key={"subscriber_id": subscriber_id},
            UpdateExpression="SET " + ", ".join(update_expr_parts),
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.exception("subscribers update_item failed", exc_info=exc)
        return {"error": "Failed to update subscriber"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": Subscriber.from_dynamo(result["Attributes"]).to_dict(),
    }


@router.delete("/real-estate/probate-leads/subscribers/<subscriber_id>")
def delete_subscriber(subscriber_id: str):
    """Soft-delete a subscriber by setting status → 'inactive'."""
    try:
        existing = db.subscribers_table.get_item(
            Key={"subscriber_id": subscriber_id}
        ).get("Item")
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    try:
        result = db.subscribers_table.update_item(
            Key={"subscriber_id": subscriber_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     "inactive",
                ":updated_at": now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.exception("subscribers soft-delete failed", exc_info=exc)
        return {"error": "Failed to delete subscriber"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": Subscriber.from_dynamo(result["Attributes"]).to_dict(),
    }
