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
    create_funnel_token,
    create_magic_token,
    get_bearer_payload,
    send_funnel_email,
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


def _create_inbound_user(email: str, first_name: str = "", last_name: str = "") -> dict:
    """Create a new user with 'inbound' status and CollinTx location."""
    user_id = str(uuid.uuid4())
    now = now_iso()
    
    user_item = {
        "user_id":                user_id,
        "email":                  email,
        "first_name":             first_name,
        "last_name":              last_name,
        "role":                   "user",
        "stripe_customer_id":     "",
        "stripe_subscription_id": "",
        "status":                 "inbound",
        "location_codes":         {"CollinTx"},
        "offered_price":          19,  # Default starting price
        "created_at":             now,
        "updated_at":             now,
    }
    
    try:
        db.users_table.put_item(Item=user_item)
        logger.info("Created inbound user: %s", email)
        return user_item
    except Exception as exc:
        logger.error("Failed to create inbound user %s: %s", email, exc)
        raise


def _fetch_sample_leads(count: int = 10) -> list:
    """Fetch sample leads for funnel email."""
    try:
        # Query Collin TX for recent leads
        result = db.table.query(
            IndexName=db.location_date_gsi,
            KeyConditionExpression=Key("location_code").eq("CollinTx"),
            ScanIndexForward=False,
            Limit=count,
        )
        return result.get("Items", [])
    except Exception as exc:
        logger.error("Failed to fetch sample leads: %s", exc)
        return []


def _parse_email_name(email_input: str) -> tuple[str, str, str]:
    """Parse email in 'Name <email@domain.com>' format."""
    email_input = email_input.strip().lower()
    
    if "<" in email_input and ">" in email_input:
        # Extract name and email
        name_part = email_input.split("<")[0].strip()
        clean_email = email_input.split("<")[1].split(">")[0].strip()
        
        # Simple name parsing
        if " " in name_part:
            name_parts = name_part.split()
            first_name = name_parts[0].capitalize()
            last_name = name_parts[-1].capitalize() if len(name_parts) > 1 else ""
        else:
            first_name = name_part.capitalize()
            last_name = ""
        
        return clean_email, first_name, last_name
    else:
        return email_input, "", ""


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

    email_input = (body.get("email") or "").strip()
    if not email_input:
        return {"error": "'email' is required"}, 400

    # Parse email to extract name and clean email
    clean_email, first_name, last_name = _parse_email_name(email_input)
    
    user = _get_user_by_email(clean_email)
    if user:
        # Existing user - send magic link
        token = create_magic_token(clean_email)
        send_magic_link(clean_email, token)
        logger.info("Magic link sent to existing user: %s", clean_email)
    else:
        # New user - create inbound user and send funnel email
        try:
            # Create the user
            user = _create_inbound_user(clean_email, first_name, last_name)
            
            # Send funnel email
            leads_raw = _fetch_sample_leads(10)
            leads_dicts = [Lead.from_dynamo(item).to_dict() for item in leads_raw]
            
            funnel_token = create_funnel_token(user["user_id"], clean_email, user["offered_price"])
            send_funnel_email(clean_email, funnel_token, leads_dicts, user["offered_price"], first_name, last_name, user["user_id"])
            
            logger.info("Created inbound user and sent funnel email: %s", clean_email)
        except Exception as exc:
            logger.error("Failed to create inbound user or send funnel email for %s: %s", clean_email, exc)
            # Still return 200 to prevent email enumeration

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
