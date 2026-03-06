"""Activity tracking for user prospect journey.

POST /admin/activity/log
POST /admin/activity/query
POST /activity/track  - for tracking link clicks from emails
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Key

import db
from auth_helpers import get_bearer_payload, verify_token
from models import Activity
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

# ---------------------------------------------------------------------------
# POST /admin/activity/log
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/admin/activity/log")
def log_activity():
    """Log user activity (email sent, link clicked, etc.)."""
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401
    if payload.get("role") != "admin":
        return {"error": "Admin access required"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    required_fields = ["user_id", "activity_type"]
    for field in required_fields:
        if not body.get(field):
            return {"error": f"'{field}' is required"}, 400

    activity_id = str(uuid.uuid4())
    activity_item = {
        "activity_id":    activity_id,
        "user_id":        body["user_id"],
        "activity_type":  body["activity_type"],
        "timestamp":      now_iso(),
        "email_template":  body.get("email_template", ""),
        "from_name":      body.get("from_name", ""),
        "subject_line":   body.get("subject_line", ""),
        "prospect_token": body.get("prospect_token", ""),
        "metadata":       body.get("metadata", {}),
    }

    try:
        db.activities_table.put_item(Item=activity_item)
        logger.info("Activity logged: %s for user %s", body["activity_type"], body["user_id"])
        return {
            "requestId": str(uuid.uuid4()),
            "activityId": activity_id,
            "message": "Activity logged successfully",
        }
    except Exception as exc:
        logger.error("Failed to log activity: %s", exc)
        return {"error": "Failed to log activity"}, 500

# ---------------------------------------------------------------------------
# POST /admin/activity/query
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/admin/activity/query")
def query_activities():
    """Query activities for a user."""
    payload = get_bearer_payload(router.current_event.raw_event)
    if not payload or payload.get("type") != "access":
        return {"error": "Unauthorized"}, 401
    if payload.get("role") != "admin":
        return {"error": "Admin access required"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    user_id = body.get("user_id")
    if not user_id:
        return {"error": "'user_id' is required"}, 400

    try:
        result = db.activities_table.query(
            IndexName="user-activity-index",
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
            Limit=body.get("limit", 50),
        )
        activities = [Activity.from_dynamo(item).to_dict() for item in result.get("Items", [])]
        
        return {
            "requestId": str(uuid.uuid4()),
            "activities": activities,
            "count": len(activities),
        }
    except Exception as exc:
        logger.error("Failed to query activities: %s", exc)
        return {"error": "Failed to query activities"}, 500

# ---------------------------------------------------------------------------
# POST /activity/track
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/activity/track")
def track_activity():
    """Track user activity from funnel links (subscribe, unsubscribe, etc.)."""
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    # Verify funnel token
    token = body.get("token")
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "prospect":
        return {"error": "Invalid or expired token"}, 401

    activity_type = body.get("activity_type")
    if not activity_type:
        return {"error": "'activity_type' is required"}, 400

    user_id = payload.get("sub")
    if not user_id:
        return {"error": "Invalid token payload"}, 400

    activity_id = str(uuid.uuid4())
    activity_item = {
        "activity_id":    activity_id,
        "user_id":        user_id,
        "activity_type":  activity_type,
        "timestamp":      now_iso(),
        "prospect_token": token,
        "metadata":       {
            "email": payload.get("email", ""),
            "price": payload.get("price", 0),
            "user_agent": router.current_event.headers.get("User-Agent", ""),
            "ip": router.current_event.request_context.get("identity", {}).get("sourceIp", ""),
        }
    }

    try:
        db.activities_table.put_item(Item=activity_item)
        logger.info("Activity tracked: %s for user %s", activity_type, user_id)
        return {
            "requestId": str(uuid.uuid4()),
            "activityId": activity_id,
            "message": "Activity tracked successfully",
        }
    except Exception as exc:
        logger.error("Failed to track activity: %s", exc)
        return {"error": "Failed to track activity"}, 500
