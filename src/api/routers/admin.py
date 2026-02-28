"""
Admin routes (no API key required — gated by admin-role Bearer JWT):

  GET    /real-estate/probate-leads/admin/users
  GET    /real-estate/probate-leads/admin/users/{user_id}
  PATCH  /real-estate/probate-leads/admin/users/{user_id}
  DELETE /real-estate/probate-leads/admin/users/{user_id}
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router

import db
from auth_helpers import get_bearer_payload
from models import User
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

_VALID_STATUSES = {"active", "inactive", "canceled", "past_due", "trialing"}
_VALID_ROLES    = {"user", "admin"}


def _require_admin(event: dict) -> dict | None:
    """Verify the request carries a valid admin-role access token.

    Returns the decoded JWT payload or ``None`` if the check fails.
    """
    payload = get_bearer_payload(event)
    if not payload:
        return None
    if payload.get("type") != "access":
        return None
    if payload.get("role") != "admin":
        return None
    return payload


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/admin/users")
def admin_list_users():
    """Return all users (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        result = db.users_table.scan()
    except Exception as exc:
        logger.error("admin users scan failed: %s", exc)
        return {"error": "Database scan failed"}, 500

    items = [User.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    return {
        "requestId": str(uuid.uuid4()),
        "users":     items,
        "count":     len(items),
    }


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/admin/users/<user_id>")
def admin_get_user(user_id: str):
    """Return a single user (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        result = db.users_table.get_item(Key={"user_id": user_id})
    except Exception as exc:
        logger.error("admin users get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if item is None:
        return {"error": f"User not found: {user_id!r}"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "user":      User.from_dynamo(item).to_dict(),
    }


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.patch("/real-estate/probate-leads/admin/users/<user_id>")
def admin_update_user(user_id: str):
    """Update a user's role, status, and/or location_codes (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    # Verify user exists
    try:
        existing = db.users_table.get_item(Key={"user_id": user_id}).get("Item")
    except Exception as exc:
        logger.error("admin users get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"User not found: {user_id!r}"}, 404

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
                logger.error("locations validation failed: %s", exc)
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

    role = body.get("role")
    if role is not None:
        if role not in _VALID_ROLES:
            return {"error": f"'role' must be one of {sorted(_VALID_ROLES)}"}, 400
        update_expr_parts.append("#role = :role")
        expr_attr_names["#role"] = "role"
        expr_attr_values[":role"] = role

    try:
        result = db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(update_expr_parts),
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.error("admin users update_item failed: %s", exc)
        return {"error": "Failed to update user"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "user":      User.from_dynamo(result["Attributes"]).to_dict(),
    }


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.delete("/real-estate/probate-leads/admin/users/<user_id>")
def admin_delete_user(user_id: str):
    """Soft-delete a user by setting status → 'inactive' (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        existing = db.users_table.get_item(Key={"user_id": user_id}).get("Item")
    except Exception as exc:
        logger.error("admin users get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"User not found: {user_id!r}"}, 404

    try:
        result = db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     "inactive",
                ":updated_at": now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.error("admin users soft-delete failed: %s", exc)
        return {"error": "Failed to delete user"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "user":      User.from_dynamo(result["Attributes"]).to_dict(),
    }
