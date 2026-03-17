"""
Customer Journey API endpoints:

  POST /real-estate/probate-leads/journeys/invite-to-waitlist
  POST /real-estate/probate-leads/journeys/accept-waitlist
  POST /real-estate/probate-leads/journeys/invite-to-join-from-waitlist
  POST /real-estate/probate-leads/journeys/invite-to-trial
  POST /real-estate/probate-leads/journeys/start-trial
  GET  /real-estate/probate-leads/journeys/trial-status/{user_id}
"""

import os
import uuid
from datetime import datetime, timedelta

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
from email_templates import send_journey_email
from models import User
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

UI_BASE_URL = os.environ.get("UI_BASE_URL", "http://localhost:3001")


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


def _create_or_update_user_for_journey(
    email: str,
    journey_type: str,
    journey_step: str,
    first_name: str = "",
    last_name: str = "",
    trial_days: int = 14
) -> dict:
    """Create or update a user for a specific customer journey."""
    now = now_iso()

    # Check if user exists
    existing = db.get_user_by_email(email)

    if existing:
        # Update existing user
        user_id = existing["user_id"]

        update_expr_parts = [
            "journey_type = :journey_type",
            "journey_step = :journey_step",
            "updated_at = :updated_at"
        ]
        expr_values = {
            ":journey_type": journey_type,
            ":journey_step": journey_step,
            ":updated_at": now,
        }

        # Add trial expiration for free trial journeys
        if journey_type == "free_trial" and journey_step in ["invited_to_trial", "trialing"]:
            trial_end = (datetime.fromisoformat(now.replace('Z', '+00:00')) + timedelta(days=trial_days)).isoformat() + 'Z'
            update_expr_parts.append("trial_expires_on = :trial_expires_on")
            expr_values[":trial_expires_on"] = trial_end

        # Update name fields if provided
        if first_name:
            update_expr_parts.append("first_name = :first_name")
            expr_values[":first_name"] = first_name
        if last_name:
            update_expr_parts.append("last_name = :last_name")
            expr_values[":last_name"] = last_name

        db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(update_expr_parts),
            ExpressionAttributeValues=expr_values,
        )

        # Fetch updated user
        result = db.users_table.get_item(Key={"user_id": user_id})
        return result["Item"]

    else:
        # Create new user
        user_id = str(uuid.uuid4())
        trial_expires_on = ""

        if journey_type == "free_trial" and journey_step in ["invited_to_trial", "trialing"]:
            trial_end = (datetime.fromisoformat(now.replace('Z', '+00:00')) + timedelta(days=trial_days)).isoformat() + 'Z'
            trial_expires_on = trial_end

        user_item = {
            "user_id": user_id,
            "email": email,
            "first_name": first_name or "",
            "last_name": last_name or "",
            "role": "user",
            "stripe_customer_id": "",
            "stripe_subscription_id": "",
            "status": journey_step,
            "location_codes": {"CollinTx"},
            "offered_price": 19,  # Default price
            "created_at": now,
            "updated_at": now,
            "trial_expires_on": trial_expires_on,
            "journey_type": journey_type,
            "journey_step": journey_step,
        }

        db.users_table.put_item(Item=user_item)
        return user_item


# ---------------------------------------------------------------------------
# POST /journeys/invite-to-waitlist
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/journeys/invite-to-waitlist")
def invite_to_waitlist():
    """Create users and send waitlist invitation emails.

    Request body:
      emails (list[str], required) — email addresses to invite
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

    results = []

    for raw_email in raw_emails:
        raw_email = (raw_email or "").strip()
        if not raw_email:
            results.append({"email": raw_email, "status": "skipped", "message": "empty email"})
            continue

        clean_email, first_name, last_name = parse_email_input(raw_email)

        try:
            user_item = _create_or_update_user_for_journey(
                clean_email, "coming_soon", "invited_to_waitlist", first_name, last_name
            )

            user_dict = User.from_dynamo(user_item).to_dict()

            send_journey_email(
                to_email=clean_email,
                journey_type="coming_soon",
                journey_step="invited_to_waitlist",
                user_data=user_dict,
            )

            results.append({
                "email": clean_email,
                "status": "sent",
                "userId": user_item["user_id"],
            })

        except Exception as exc:
            logger.error("Failed to invite %s to waitlist: %s", clean_email, exc)
            results.append({"email": clean_email, "status": "error", "message": str(exc)})

    return {
        "requestId": str(uuid.uuid4()),
        "results": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# POST /journeys/accept-waitlist
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/journeys/accept-waitlist")
def accept_waitlist():
    """Accept a waitlist invitation and send confirmation email.

    Public endpoint - no auth required.

    Request body:
      email (str, required) — email address accepting waitlist
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    email = (body.get("email") or "").strip().lower()
    if not email:
        return {"error": "'email' is required"}, 400

    # Find user by email
    user = db.get_user_by_email(email)
    if not user:
        return {"error": "User not found"}, 404

    if user.get("journey_type") != "coming_soon":
        return {"error": "User is not in coming soon journey"}, 400

    try:
        # Update user to accepted_waitlist step
        user_item = _create_or_update_user_for_journey(
            email, "coming_soon", "accepted_waitlist",
            user.get("first_name", ""), user.get("last_name", "")
        )

        user_dict = User.from_dynamo(user_item).to_dict()

        send_journey_email(
            to_email=email,
            journey_type="coming_soon",
            journey_step="accepted_waitlist",
            user_data=user_dict,
        )

        return {
            "requestId": str(uuid.uuid4()),
            "message": "Successfully joined waitlist",
            "user": user_dict,
        }

    except Exception as exc:
        logger.error("Failed to accept waitlist for %s: %s", email, exc)
        return {"error": "Failed to join waitlist"}, 500


# ---------------------------------------------------------------------------
# POST /journeys/invite-to-join-from-waitlist
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/journeys/invite-to-join-from-waitlist")
def invite_to_join_from_waitlist():
    """Send launch invitations to waitlist users.

    Request body:
      user_ids (list[str], optional) — specific users to invite, or all waitlist users if not provided
    """
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    user_ids = body.get("user_ids")

    # Get waitlist users
    if user_ids:
        # Invite specific users
        users = []
        for user_id in user_ids:
            try:
                result = db.users_table.get_item(Key={"user_id": user_id})
                if result.get("Item"):
                    users.append(result["Item"])
            except Exception as exc:
                logger.error("Failed to get user %s: %s", user_id, exc)
    else:
        # Invite all waitlist users
        try:
            result = db.users_table.scan(
                FilterExpression="journey_type = :journey_type AND journey_step = :journey_step",
                ExpressionAttributeValues={
                    ":journey_type": "coming_soon",
                    ":journey_step": "accepted_waitlist",
                }
            )
            users = result.get("Items", [])
        except Exception as exc:
            logger.error("Failed to scan waitlist users: %s", exc)
            return {"error": "Failed to get waitlist users"}, 500

    results = []

    for user_item in users:
        email = user_item.get("email", "")
        if not email:
            continue

        try:
            # Update user to invited_to_join step
            updated_user = _create_or_update_user_for_journey(
                email, "coming_soon", "invited_to_join",
                user_item.get("first_name", ""), user_item.get("last_name", "")
            )

            user_dict = User.from_dynamo(updated_user).to_dict()

            # Create prospect token for subscribe link
            token = create_prospect_token(
                updated_user["user_id"],
                email,
                updated_user.get("offered_price", 19)
            )

            send_journey_email(
                to_email=email,
                journey_type="coming_soon",
                journey_step="invited_to_join",
                user_data=user_dict,
                token=token,
            )

            results.append({
                "email": email,
                "status": "sent",
                "userId": updated_user["user_id"],
            })

        except Exception as exc:
            logger.error("Failed to invite %s to join: %s", email, exc)
            results.append({"email": email, "status": "error", "message": str(exc)})

    return {
        "requestId": str(uuid.uuid4()),
        "results": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# POST /journeys/invite-to-trial
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/journeys/invite-to-trial")
def invite_to_trial():
    """Create users and send free trial invitations.

    Request body:
      emails (list[str], required) — email addresses to invite
      trial_days (int, optional) — trial length in days (default: 14)
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

    trial_days = int(body.get("trial_days", 14))
    trial_days = max(1, min(trial_days, 30))  # Limit to 1-30 days

    results = []

    for raw_email in raw_emails:
        raw_email = (raw_email or "").strip()
        if not raw_email:
            results.append({"email": raw_email, "status": "skipped", "message": "empty email"})
            continue

        clean_email, first_name, last_name = parse_email_input(raw_email)

        try:
            user_item = _create_or_update_user_for_journey(
                clean_email, "free_trial", "invited_to_trial",
                first_name, last_name, trial_days
            )

            user_dict = User.from_dynamo(user_item).to_dict()

            # Create token for trial signup
            token = create_prospect_token(
                user_item["user_id"],
                clean_email,
                user_item.get("offered_price", 19)
            )

            send_journey_email(
                to_email=clean_email,
                journey_type="free_trial",
                journey_step="invited_to_trial",
                user_data=user_dict,
                token=token,
                trial_signup_url=f"{UI_BASE_URL}/trial/signup?token={token}",
            )

            results.append({
                "email": clean_email,
                "status": "sent",
                "userId": user_item["user_id"],
                "trialDays": trial_days,
            })

        except Exception as exc:
            logger.error("Failed to invite %s to trial: %s", clean_email, exc)
            results.append({"email": clean_email, "status": "error", "message": str(exc)})

    return {
        "requestId": str(uuid.uuid4()),
        "results": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# POST /journeys/start-trial
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/journeys/start-trial")
def start_trial():
    """Start a free trial using a prospect JWT token.

    Public endpoint - no auth required.

    Request body:
      token (str, required) — prospect JWT from trial invitation email
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
        # Get user
        result = db.users_table.get_item(Key={"user_id": user_id})
        user_item = result.get("Item")
        if not user_item:
            return {"error": "User not found"}, 404

        if user_item.get("journey_type") != "free_trial":
            return {"error": "User is not in free trial journey"}, 400

        # Update to trialing status
        email = user_item.get("email", "")
        updated_user = _create_or_update_user_for_journey(
            email, "free_trial", "trialing",
            user_item.get("first_name", ""), user_item.get("last_name", "")
        )

        return {
            "requestId": str(uuid.uuid4()),
            "message": "Free trial started",
            "user": User.from_dynamo(updated_user).to_dict(),
        }

    except Exception as exc:
        logger.error("Failed to start trial for user %s: %s", user_id, exc)
        return {"error": "Failed to start trial"}, 500


# ---------------------------------------------------------------------------
# GET /journeys/trial-status/{user_id}
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/journeys/trial-status/<user_id>")
def get_trial_status(user_id: str):
    """Get trial status for a user (for UI trial banners).

    Requires Bearer token authentication.
    """
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401

    # Users can only check their own trial status (unless admin)
    if payload.get("sub") != user_id and payload.get("role") != "admin":
        return {"error": "Forbidden"}, 403

    try:
        result = db.users_table.get_item(Key={"user_id": user_id})
        user_item = result.get("Item")
        if not user_item:
            return {"error": "User not found"}, 404

        user = User.from_dynamo(user_item)

        trial_status = {
            "userId": user.user_id,
            "journeyType": user.journey_type,
            "journeyStep": user.journey_step,
            "isTrialing": user.journey_step == "trialing",
            "trialExpiresOn": user.trial_expires_on,
            "daysRemaining": 0,
        }

        # Calculate days remaining for active trials
        if user.trial_expires_on and user.journey_step == "trialing":
            try:
                expires_dt = datetime.fromisoformat(user.trial_expires_on.replace('Z', '+00:00'))
                now_dt = datetime.now(expires_dt.tzinfo)
                days_remaining = (expires_dt - now_dt).days
                trial_status["daysRemaining"] = max(0, days_remaining)
            except Exception:
                pass

        return {
            "requestId": str(uuid.uuid4()),
            "trialStatus": trial_status,
        }

    except Exception as exc:
        logger.error("Failed to get trial status for %s: %s", user_id, exc)
        return {"error": "Failed to get trial status"}, 500
