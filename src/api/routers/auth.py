"""
Auth routes (no API key required — authenticated by JWT):

  POST  /real-estate/probate-leads/auth/request-login
  GET   /real-estate/probate-leads/auth/verify
  GET   /real-estate/probate-leads/auth/me
  PATCH /real-estate/probate-leads/auth/me
  GET   /real-estate/probate-leads/auth/leads
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Key

import db
from auth_helpers import (
    create_access_token,
    create_magic_token,
    get_bearer_payload,
    send_magic_link,
    verify_token,
)
from models import Lead, User
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()


def _get_user_by_email(email: str) -> dict | None:
    """Query the email-index GSI.  Returns the raw DynamoDB item or None."""
    try:
        result = db.users_table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        logger.error("users email-index query failed: %s", exc)
        return None


def _get_user_by_id(user_id: str) -> dict | None:
    """Fetch a user by primary key.  Returns the raw item or None."""
    try:
        result = db.users_table.get_item(Key={"user_id": user_id})
        return result.get("Item")
    except Exception as exc:
        logger.error("users get_item failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# POST /auth/request-login
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/auth/request-login")
def request_login():
    """Send a magic-link email.  Always returns 200 to prevent email enumeration."""
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    email = (body.get("email") or "").strip().lower()
    if not email:
        return {"error": "'email' is required"}, 400

    user = _get_user_by_email(email)
    if user:
        token = create_magic_token(email)
        send_magic_link(email, token)
    else:
        logger.info("Magic link requested for unknown email: %s", email)

    return {"message": "If that email is registered, a login link has been sent."}, 200


# ---------------------------------------------------------------------------
# GET /auth/verify?token=...
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/auth/verify")
def verify_login():
    """Exchange a magic token for a 7-day access token."""
    qs    = router.current_event.query_string_parameters or {}
    token = qs.get("token", "")
    if not token:
        return {"error": "Missing 'token' query parameter"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "magic":
        return {"error": "Invalid or expired login link"}, 401

    email = payload.get("sub", "")
    user  = _get_user_by_email(email)
    if not user:
        return {"error": "User not found"}, 404

    access_token = create_access_token(user["user_id"], user.get("role", "user"))
    return {
        "requestId":   str(uuid.uuid4()),
        "accessToken": access_token,
        "user":        User.from_dynamo(user).to_dict(),
    }


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/auth/me")
def get_me():
    """Return the authenticated user's own profile."""
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401

    user = _get_user_by_id(payload["sub"])
    if not user:
        return {"error": "User not found"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "user":      User.from_dynamo(user).to_dict(),
    }


# ---------------------------------------------------------------------------
# PATCH /auth/me
# ---------------------------------------------------------------------------

@router.patch("/real-estate/probate-leads/auth/me")
def update_me():
    """Allow the authenticated user to update their own email address."""
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401

    user_id = payload["sub"]
    user    = _get_user_by_id(user_id)
    if not user:
        return {"error": "User not found"}, 404

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    new_email = (body.get("email") or "").strip().lower()
    if not new_email:
        return {"error": "'email' is required"}, 400

    try:
        result = db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET email = :email, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":email":      new_email,
                ":updated_at": now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.error("users update_item (me) failed: %s", exc)
        return {"error": "Failed to update profile"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "user":      User.from_dynamo(result["Attributes"]).to_dict(),
    }


# ---------------------------------------------------------------------------
# GET /auth/leads
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/auth/leads")
def get_my_leads():
    """Return leads for the authenticated user's own location_codes.

    Only active users can access lead data.  Results are merged across all
    of the user's location_codes, sorted descending by recorded_date.
    """
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401

    user = _get_user_by_id(payload["sub"])
    if not user:
        return {"error": "User not found"}, 404

    if user.get("status") != "active":
        return {"error": "Account is not active"}, 403

    location_codes = list(user.get("location_codes") or [])
    if not location_codes:
        return {
            "requestId": str(uuid.uuid4()),
            "leads": [],
            "count": 0,
        }

    qs       = router.current_event.query_string_parameters or {}
    from_date = qs.get("from_date")
    to_date   = qs.get("to_date")

    all_leads = []
    for location_code in location_codes:
        try:
            from boto3.dynamodb.conditions import Key as K
            if from_date and to_date:
                kce = K("location_code").eq(location_code) & K("recorded_date").between(from_date, to_date)
            elif from_date:
                kce = K("location_code").eq(location_code) & K("recorded_date").gte(from_date)
            elif to_date:
                kce = K("location_code").eq(location_code) & K("recorded_date").lte(to_date)
            else:
                kce = K("location_code").eq(location_code)

            result = db.table.query(
                IndexName=db.location_date_gsi,
                KeyConditionExpression=kce,
                ScanIndexForward=False,
                Limit=db.DEFAULT_LIMIT,
            )
            all_leads.extend(result.get("Items", []))
        except Exception as exc:
            logger.error("leads query for %s failed: %s", location_code, exc)

    leads = [Lead.from_dynamo(item).to_dict() for item in all_leads]
    return {
        "requestId": str(uuid.uuid4()),
        "leads":     leads,
        "count":     len(leads),
    }
