"""
Route: GET /real-estate/probate-leads/{location_path}/leads

Queries the location-date-index GSI and returns paginated probate leads
for the requested county.
"""

import uuid
from datetime import datetime, timezone

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Attr, Key

import db
from models import Lead, Location
from utils import decode_key, encode_key, parse_date

logger = Logger(service="probate-api")
router = Router()


def _get_location_by_path(location_path: str) -> dict | None:
    """Look up a location item using the location-path-index GSI.

    Returns the raw DynamoDB item or ``None`` if not found.
    """
    try:
        result = db.locations_table.query(
            IndexName="location-path-index",
            KeyConditionExpression=Key("location_path").eq(location_path),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        logger.exception("locations GSI query failed", exc_info=exc)
        return None


@router.get("/real-estate/probate-leads/<location_path>/leads")
def get_leads_by_location(location_path: str):
    # 1. Resolve location_path → location record
    location = _get_location_by_path(location_path)
    if location is None:
        return {"error": f"Location not found: {location_path!r}"}, 404

    location_code = location["location_code"]

    qs = router.current_event.query_string_parameters or {}

    raw_from = qs.get("from_date", "")
    raw_to   = qs.get("to_date", "")
    doc_type = qs.get("doc_type", "PROBATE")

    try:
        limit = min(int(qs.get("limit", db.DEFAULT_LIMIT)), db.MAX_LIMIT)
        limit = max(limit, 1)
    except (ValueError, TypeError):
        return {"error": "'limit' must be an integer between 1 and 200"}, 400

    from_date = parse_date(raw_from) if raw_from else None
    to_date   = parse_date(raw_to)   if raw_to   else None

    if raw_from and from_date is None:
        return {"error": f"'from_date' must be YYYY-MM-DD, got: {raw_from!r}"}, 400
    if raw_to and to_date is None:
        return {"error": f"'to_date' must be YYYY-MM-DD, got: {raw_to!r}"}, 400

    last_key = None
    if qs.get("last_key"):
        last_key = decode_key(qs["last_key"])
        if last_key is None:
            return {"error": "'last_key' is not a valid pagination cursor"}, 400

    # 2. Build key condition expression for the location-date GSI.
    # Both dates optional; no dates → most-recent-first via ScanIndexForward=False.
    if from_date and to_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").between(from_date, to_date)
        )
    elif from_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").gte(from_date)
        )
    elif to_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").lte(to_date)
        )
    else:
        kce = Key("location_code").eq(location_code)

    query_kwargs = {
        "IndexName": db.location_date_gsi,
        "KeyConditionExpression": kce,
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if doc_type != "ALL":
        query_kwargs["FilterExpression"] = Attr("doc_type").eq(doc_type)
    if last_key:
        query_kwargs["ExclusiveStartKey"] = last_key

    try:
        result = db.table.query(**query_kwargs)
    except Exception as exc:
        logger.exception("DynamoDB query error", exc_info=exc)
        return {"error": "Database query failed"}, 500

    leads = [Lead.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    next_key = None
    if "LastEvaluatedKey" in result:
        next_key = encode_key(result["LastEvaluatedKey"])

    body = {
        "requestId": str(uuid.uuid4()),
        "location": Location.from_dynamo(location).to_dict(),
        "leads": leads,
        "count": len(leads),
        "nextKey": next_key,
        "query": {
            "locationPath": location_path,
            "fromDate": from_date,
            "toDate": to_date,
            "docType": doc_type,
            "limit": limit,
        },
    }

    return body
