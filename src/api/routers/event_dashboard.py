"""
Admin event dashboard routes (no API key — admin Bearer JWT required):

  GET /real-estate/probate-leads/admin/events
      Optional params: user_id, event_type, from_date, to_date, limit (default 50)

  GET /real-estate/probate-leads/admin/events/dashboard
      Optional params: weeks (default 8)
      Aggregates funnel, weekly, user statuses, and recent conversions.
"""

import uuid
from datetime import datetime, timedelta, timezone

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Attr, Key

import db
from auth_helpers import get_bearer_payload
from models import Event

logger = Logger(service="probate-api")
router = Router()

# Canonical funnel order for the prospect-to-subscriber journey
FUNNEL_STEPS = [
    "email_sent",
    "email_open",
    "link_clicked",
    "subscribe_clicked",
    "signup_completed",
]


def _require_admin(event: dict) -> dict | None:
    payload = get_bearer_payload(event)
    if not payload:
        return None
    if payload.get("type") != "access":
        return None
    if payload.get("role") != "admin":
        return None
    return payload


# ---------------------------------------------------------------------------
# GET /admin/events
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/admin/events")
def admin_list_events():
    """Return events with optional filtering (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    params     = router.current_event.query_string_parameters or {}
    user_id    = params.get("user_id")
    event_type = params.get("event_type")
    from_date  = params.get("from_date")
    to_date    = params.get("to_date")
    try:
        limit = int(params.get("limit", 50))
    except (ValueError, TypeError):
        return {"error": "'limit' must be an integer"}, 400

    try:
        if user_id:
            # Efficient GSI query when filtering by user
            kwargs: dict = dict(
                IndexName=db.user_event_gsi,
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=False,
                Limit=limit,
            )
            if from_date or to_date:
                range_expr = None
                if from_date and to_date:
                    range_expr = Key("timestamp").between(from_date, to_date)
                elif from_date:
                    range_expr = Key("timestamp").gte(from_date)
                elif to_date:
                    range_expr = Key("timestamp").lte(to_date)
                kwargs["KeyConditionExpression"] &= range_expr
            if event_type:
                kwargs["FilterExpression"] = Attr("event_type").eq(event_type)
            result = db.events_table.query(**kwargs)
        else:
            # Full scan with optional filters (admin-only path)
            filter_parts = []
            if event_type:
                filter_parts.append(Attr("event_type").eq(event_type))
            if from_date:
                filter_parts.append(Attr("timestamp").gte(from_date))
            if to_date:
                filter_parts.append(Attr("timestamp").lte(to_date))

            scan_kwargs: dict = {}
            if filter_parts:
                combined = filter_parts[0]
                for part in filter_parts[1:]:
                    combined = combined & part
                scan_kwargs["FilterExpression"] = combined

            result = db.events_table.scan(**scan_kwargs)
    except Exception as exc:
        logger.error("admin_list_events failed: %s", exc)
        return {"error": "Database query failed"}, 500

    events = [Event.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    # When scanning without user_id apply limit in Python (scan doesn't support Limit + filter well)
    if not user_id:
        events = events[:limit]

    return {
        "requestId": str(uuid.uuid4()),
        "events":    events,
        "count":     len(events),
    }


# ---------------------------------------------------------------------------
# GET /admin/events/dashboard
# ---------------------------------------------------------------------------

@router.get("/real-estate/probate-leads/admin/events/dashboard")
def admin_events_dashboard():
    """Return aggregated funnel, weekly, and user-status metrics (admin only)."""
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    params = router.current_event.query_string_parameters or {}
    try:
        weeks = int(params.get("weeks", 8))
    except (ValueError, TypeError):
        return {"error": "'weeks' must be an integer"}, 400

    # Date range for weekly bucketing
    now        = datetime.now(timezone.utc)
    week_start = now - timedelta(weeks=weeks)
    from_iso   = week_start.strftime("%Y-%m-%dT00:00:00+00:00")

    # ── Fetch all events (filtered to the window) ────────────────────────────
    try:
        scan_result = db.events_table.scan(
            FilterExpression=Attr("timestamp").gte(from_iso)
        )
        all_events = scan_result.get("Items", [])
        # Handle pagination
        while "LastEvaluatedKey" in scan_result:
            scan_result = db.events_table.scan(
                FilterExpression=Attr("timestamp").gte(from_iso),
                ExclusiveStartKey=scan_result["LastEvaluatedKey"],
            )
            all_events.extend(scan_result.get("Items", []))
    except Exception as exc:
        logger.error("events scan failed: %s", exc)
        return {"error": "Database scan failed"}, 500

    # ── Fetch all users ──────────────────────────────────────────────────────
    try:
        user_result = db.users_table.scan()
        all_users = user_result.get("Items", [])
        while "LastEvaluatedKey" in user_result:
            user_result = db.users_table.scan(
                ExclusiveStartKey=user_result["LastEvaluatedKey"],
            )
            all_users.extend(user_result.get("Items", []))
    except Exception as exc:
        logger.error("users scan failed: %s", exc)
        return {"error": "Database scan failed"}, 500

    # ── Funnel ────────────────────────────────────────────────────────────────
    funnel_counts: dict[str, int] = {step: 0 for step in FUNNEL_STEPS}
    for ev in all_events:
        etype = ev.get("event_type", "")
        if etype in funnel_counts:
            funnel_counts[etype] += 1

    email_sent = funnel_counts.get("email_sent", 0)
    funnel = []
    for step in FUNNEL_STEPS:
        count = funnel_counts[step]
        rate  = round(count / email_sent * 100, 1) if email_sent else 0.0
        funnel.append({"event_type": step, "count": count, "conversion_rate": rate})

    # ── Weekly bucketing ──────────────────────────────────────────────────────
    # Generate the N week buckets (ISO Monday dates)
    week_buckets: list[str] = []
    cursor = week_start
    while cursor <= now:
        monday = cursor - timedelta(days=cursor.weekday())
        label  = monday.strftime("%Y-%m-%d")
        if label not in week_buckets:
            week_buckets.append(label)
        cursor += timedelta(days=7)

    weekly_map: dict[str, dict[str, int]] = {w: {} for w in week_buckets}
    tracked_types = {"email_sent", "email_open", "link_clicked", "subscribe_clicked", "signup_completed"}

    for ev in all_events:
        ts_str = ev.get("timestamp", "")
        etype  = ev.get("event_type", "")
        if etype not in tracked_types:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        monday = ts - timedelta(days=ts.weekday())
        bucket = monday.strftime("%Y-%m-%d")
        if bucket in weekly_map:
            weekly_map[bucket][etype] = weekly_map[bucket].get(etype, 0) + 1

    weekly = [{"week": w, "counts": weekly_map[w]} for w in week_buckets]

    # ── User status breakdown ─────────────────────────────────────────────────
    user_statuses: dict[str, int] = {}
    for user in all_users:
        status = user.get("status", "unknown")
        user_statuses[status] = user_statuses.get(status, 0) + 1

    # ── Recent conversions ────────────────────────────────────────────────────
    conversions = [ev for ev in all_events if ev.get("event_type") == "signup_completed"]
    conversions.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    # Build user lookup for email enrichment
    user_email_map = {u.get("user_id", ""): u.get("email", "") for u in all_users}

    recent_conversions = []
    for ev in conversions[:20]:
        uid = ev.get("user_id", "")
        recent_conversions.append({
            "user_id":      uid,
            "email":        user_email_map.get(uid, ""),
            "converted_at": ev.get("timestamp", ""),
        })

    return {
        "requestId": str(uuid.uuid4()),
        "dashboard": {
            "funnel":             funnel,
            "weekly":             weekly,
            "user_statuses":      user_statuses,
            "recent_conversions": recent_conversions,
        },
    }
