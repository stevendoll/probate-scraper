"""Event tracking for user prospect journey.

POST /events   — track prospect-initiated events (prospect JWT)
GET  /events   — query events for a user (admin Bearer token)
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Key

import db
from auth_helpers import get_bearer_payload, verify_token
from models import Event
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

# ---------------------------------------------------------------------------
# POST /events
# Prospect JWT required (embedded in email links).
# Logs a browser-initiated event (link_clicked, subscribe_clicked, etc.).
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/events")
def post_event():
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    token = body.get("token")
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "prospect":
        return {"error": "Invalid or expired token"}, 401

    event_type = body.get("event_type")
    if not event_type:
        return {"error": "'event_type' is required"}, 400

    user_id = payload.get("sub")
    if not user_id:
        return {"error": "Invalid token payload"}, 400

    event_id = str(uuid.uuid4())
    event_item = {
        "event_id":       event_id,
        "user_id":        user_id,
        "event_type":     event_type,
        "timestamp":      now_iso(),
        "variant":        body.get("variant", ""),
        "prospect_token": token,
        "metadata":       {
            "email":      payload.get("email", ""),
            "price":      payload.get("price", 0),
            "user_agent": router.current_event.headers.get("User-Agent", ""),
            "ip":         router.current_event.request_context.get("identity", {}).get("sourceIp", ""),
        }
    }

    try:
        db.events_table.put_item(Item=event_item)
        logger.info("Event tracked: %s for user %s", event_type, user_id)
        return {
            "requestId": str(uuid.uuid4()),
            "eventId":   event_id,
            "message":   "Event tracked successfully",
        }
    except Exception as exc:
        logger.error("Failed to track event: %s", exc)
        return {"error": "Failed to track event"}, 500


# ---------------------------------------------------------------------------
# GET /events?user_id=xxx&limit=50
# Admin Bearer token required.
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/events")
def get_events():
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401
    if payload.get("role") != "admin":
        return {"error": "Admin access required"}, 403

    params  = router.current_event.query_string_parameters or {}
    user_id = params.get("user_id")
    if not user_id:
        return {"error": "'user_id' query parameter is required"}, 400

    try:
        limit = int(params.get("limit", 50))
    except (ValueError, TypeError):
        return {"error": "'limit' must be an integer"}, 400

    try:
        result = db.events_table.query(
            IndexName=db.user_event_gsi,
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        events = [Event.from_dynamo(item).to_dict() for item in result.get("Items", [])]
        return {
            "requestId": str(uuid.uuid4()),
            "events":    events,
            "count":     len(events),
        }
    except Exception as exc:
        logger.error("Failed to query events: %s", exc)
        return {"error": "Failed to query events"}, 500
