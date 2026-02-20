"""
Probate Leads API — Lambda handler.

Routes (all under /real-estate/probate-leads/):
  GET  /{location_path}/leads               — leads for a location (date-range query)
  GET  /locations                           — list all locations
  GET  /locations/{location_code}           — get a single location
  GET  /subscribers                         — list all subscribers
  POST /subscribers                         — create a subscriber
  GET  /subscribers/{subscriber_id}         — get a subscriber
  PATCH /subscribers/{subscriber_id}        — update subscriber (locations, status)
  DELETE /subscribers/{subscriber_id}       — soft-delete subscriber (status → inactive)
  POST /stripe/webhook                      — Stripe event webhook (no API key)

Environment variables:
  DYNAMO_TABLE_NAME       — leads table
  LOCATIONS_TABLE_NAME    — locations table
  SUBSCRIBERS_TABLE_NAME  — subscribers table
  GSI_NAME                — legacy leads GSI (recorded-date-index)
  LOCATION_DATE_GSI       — new leads GSI (location-date-index)
  STRIPE_SECRET_KEY       — Stripe secret key
  STRIPE_WEBHOOK_SECRET   — Stripe webhook signing secret
"""

import base64
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, Response
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="probate-api")
tracer = Tracer(service="probate-api")
api = APIGatewayRestResolver()

# ---------------------------------------------------------------------------
# DynamoDB tables
# ---------------------------------------------------------------------------

_dynamodb = boto3.resource("dynamodb")

_table_name             = os.environ.get("DYNAMO_TABLE_NAME", "leads")
_locations_table_name   = os.environ.get("LOCATIONS_TABLE_NAME", "locations")
_subscribers_table_name = os.environ.get("SUBSCRIBERS_TABLE_NAME", "subscribers")
_gsi_name               = os.environ.get("GSI_NAME", "recorded-date-index")
_location_date_gsi      = os.environ.get("LOCATION_DATE_GSI", "location-date-index")

table             = _dynamodb.Table(_table_name)
locations_table   = _dynamodb.Table(_locations_table_name)
subscribers_table = _dynamodb.Table(_subscribers_table_name)

MAX_LIMIT     = 200
DEFAULT_LIMIT = 50

# ---------------------------------------------------------------------------
# Field maps & transforms
# ---------------------------------------------------------------------------

_LEAD_FIELD_MAP = {
    "doc_number":        "docNumber",
    "grantor":           "grantor",
    "grantee":           "grantee",
    "doc_type":          "docType",
    "recorded_date":     "recordedDate",
    "book_volume_page":  "bookVolumePage",
    "legal_description": "legalDescription",
    "record_number":     "recordNumber",
    "page_number":       "pageNumber",
    "extracted_at":      "extractedAt",
    "processed_at":      "processedAt",
    "scrape_run_id":     "scrapeRunId",
    "location_code":     "locationCode",
    "offset":            "offset",
}

_TIMESTAMP_FIELDS = {"extracted_at", "processed_at"}

_LOCATION_FIELD_MAP = {
    "location_code": "locationCode",
    "location_path": "locationPath",
    "location_name": "locationName",
    "search_url":    "searchUrl",
    "retrieved_at":  "retrievedAt",
}

_SUBSCRIBER_FIELD_MAP = {
    "subscriber_id":          "subscriberId",
    "email":                  "email",
    "stripe_customer_id":     "stripeCustomerId",
    "stripe_subscription_id": "stripeSubscriptionId",
    "status":                 "status",
    "location_codes":         "locationCodes",
    "created_at":             "createdAt",
    "updated_at":             "updatedAt",
}

# ---------------------------------------------------------------------------
# Helpers — dates, keys, transforms
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> str | None:
    """Return s if it is a valid YYYY-MM-DD string, otherwise None."""
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _encode_key(last_evaluated_key: dict) -> str:
    return base64.b64encode(json.dumps(last_evaluated_key, default=str).encode()).decode()


def _decode_key(encoded: str) -> dict | None:
    try:
        return json.loads(base64.b64decode(encoded.encode()).decode())
    except Exception:
        return None


def _normalize_timestamp(ts: str) -> str:
    """Normalize any ISO timestamp to 3-decimal-millisecond UTC with Z suffix."""
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return ts


def _transform_lead(item: dict) -> dict:
    """Rename fields to camelCase and normalize timestamps."""
    result = {}
    for k, v in item.items():
        if k in _TIMESTAMP_FIELDS:
            v = _normalize_timestamp(str(v))
        result[_LEAD_FIELD_MAP.get(k, k)] = v
    return result


def _transform_location(item: dict) -> dict:
    return {_LOCATION_FIELD_MAP.get(k, k): v for k, v in item.items()}


def _transform_subscriber(item: dict) -> dict:
    result = {}
    for k, v in item.items():
        mapped_key = _SUBSCRIBER_FIELD_MAP.get(k, k)
        # DynamoDB StringSet → sorted list for JSON serialization
        if isinstance(v, set):
            v = sorted(v)
        result[mapped_key] = v
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Helpers — location lookup
# ---------------------------------------------------------------------------

def _get_location_by_path(location_path: str) -> dict | None:
    """
    Look up a location item using the location-path-index GSI.
    Returns the raw DynamoDB item or None if not found.
    """
    try:
        result = locations_table.query(
            IndexName="location-path-index",
            KeyConditionExpression=Key("location_path").eq(location_path),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        logger.exception("locations GSI query failed", exc_info=exc)
        return None


# ---------------------------------------------------------------------------
# Route — GET /{location_path}/leads
# ---------------------------------------------------------------------------

@api.get("/real-estate/probate-leads/<location_path>/leads")
@tracer.capture_method
def get_leads_by_location(location_path: str):
    # 1. Resolve location_path → location record
    location = _get_location_by_path(location_path)
    if location is None:
        return {"error": f"Location not found: {location_path!r}"}, 404

    location_code = location["location_code"]

    qs = api.current_event.query_string_parameters or {}

    raw_from = qs.get("from_date", "")
    raw_to   = qs.get("to_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    doc_type = qs.get("doc_type", "PROBATE")

    try:
        limit = min(int(qs.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
        limit = max(limit, 1)
    except (ValueError, TypeError):
        return {"error": "'limit' must be an integer between 1 and 200"}, 400

    from_date = _parse_date(raw_from) if raw_from else None
    to_date   = _parse_date(raw_to)

    if raw_to and to_date is None:
        return {"error": f"'to_date' must be YYYY-MM-DD, got: {raw_to!r}"}, 400
    if raw_from and from_date is None:
        return {"error": f"'from_date' must be YYYY-MM-DD, got: {raw_from!r}"}, 400

    last_key = None
    if qs.get("last_key"):
        last_key = _decode_key(qs["last_key"])
        if last_key is None:
            return {"error": "'last_key' is not a valid pagination cursor"}, 400

    response_headers = {}

    # 2. Build key condition expression for the location-date GSI
    if from_date and to_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").between(from_date, to_date)
        )
    elif to_date and not from_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").lte(to_date)
        )
    else:
        response_headers["X-Warning"] = (
            "Broad index query in progress. "
            "Provide from_date and/or to_date for efficient queries."
        )
        kce = Key("location_code").eq(location_code)

    query_kwargs = {
        "IndexName": _location_date_gsi,
        "KeyConditionExpression": kce,
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if doc_type != "ALL":
        query_kwargs["FilterExpression"] = Attr("doc_type").eq(doc_type)
    if last_key:
        query_kwargs["ExclusiveStartKey"] = last_key

    try:
        result = table.query(**query_kwargs)
    except Exception as exc:
        logger.exception("DynamoDB query error", exc_info=exc)
        return {"error": "Database query failed"}, 500

    leads = [_transform_lead(item) for item in result.get("Items", [])]
    next_key = None
    if "LastEvaluatedKey" in result:
        next_key = _encode_key(result["LastEvaluatedKey"])

    body = {
        "requestId": str(uuid.uuid4()),
        "location": _transform_location(location),
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

    if response_headers:
        return Response(
            status_code=200,
            content_type="application/json",
            body=json.dumps(body, default=str),
            headers=response_headers,
        )

    return body


# ---------------------------------------------------------------------------
# Routes — Locations
# ---------------------------------------------------------------------------

@api.get("/real-estate/probate-leads/locations")
@tracer.capture_method
def list_locations():
    """Return all locations, sorted by name."""
    try:
        result = locations_table.scan()
    except Exception as exc:
        logger.exception("locations scan failed", exc_info=exc)
        return {"error": "Database scan failed"}, 500

    items = [_transform_location(item) for item in result.get("Items", [])]
    items.sort(key=lambda x: x.get("locationName", ""))
    return {
        "requestId": str(uuid.uuid4()),
        "locations": items,
        "count": len(items),
    }


@api.get("/real-estate/probate-leads/locations/<location_code>")
@tracer.capture_method
def get_location(location_code: str):
    """Return a single location by location_code."""
    try:
        result = locations_table.get_item(Key={"location_code": location_code})
    except Exception as exc:
        logger.exception("locations get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if item is None:
        return {"error": f"Location not found: {location_code!r}"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "location": _transform_location(item),
    }


# ---------------------------------------------------------------------------
# Routes — Subscribers
# ---------------------------------------------------------------------------

@api.get("/real-estate/probate-leads/subscribers")
@tracer.capture_method
def list_subscribers():
    """Return all subscribers."""
    try:
        result = subscribers_table.scan()
    except Exception as exc:
        logger.exception("subscribers scan failed", exc_info=exc)
        return {"error": "Database scan failed"}, 500

    items = [_transform_subscriber(item) for item in result.get("Items", [])]
    return {
        "requestId": str(uuid.uuid4()),
        "subscribers": items,
        "count": len(items),
    }


@api.post("/real-estate/probate-leads/subscribers")
@tracer.capture_method
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
        body = api.current_event.json_body or {}
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
            res = locations_table.get_item(Key={"location_code": code})
        except Exception as exc:
            logger.exception("locations validation failed", exc_info=exc)
            return {"error": "Database error during location validation"}, 500
        if not res.get("Item"):
            return {"error": f"Location not found: {code!r}"}, 422

    subscriber_id = str(uuid.uuid4())
    now = _now_iso()

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
        subscribers_table.put_item(Item=item)
    except Exception as exc:
        logger.exception("subscribers put_item failed", exc_info=exc)
        return {"error": "Failed to create subscriber"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": _transform_subscriber(item),
    }, 201


@api.get("/real-estate/probate-leads/subscribers/<subscriber_id>")
@tracer.capture_method
def get_subscriber(subscriber_id: str):
    """Return a single subscriber."""
    try:
        result = subscribers_table.get_item(Key={"subscriber_id": subscriber_id})
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if item is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": _transform_subscriber(item),
    }


@api.patch("/real-estate/probate-leads/subscribers/<subscriber_id>")
@tracer.capture_method
def update_subscriber(subscriber_id: str):
    """
    Update a subscriber's location_codes and/or status.

    Request body (JSON) — all fields optional:
      location_codes  (list[str]) — replaces the existing set
      status          (str)       — active | inactive | canceled | past_due | trialing
    """
    try:
        body = api.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    # Verify subscriber exists
    try:
        existing = subscribers_table.get_item(Key={"subscriber_id": subscriber_id}).get("Item")
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    update_expr_parts = ["#updated_at = :updated_at"]
    expr_attr_names   = {"#updated_at": "updated_at"}
    expr_attr_values  = {":updated_at": _now_iso()}

    raw_codes = body.get("location_codes")
    if raw_codes is not None:
        if not isinstance(raw_codes, list) or not raw_codes:
            return {"error": "'location_codes' must be a non-empty list"}, 400
        for code in raw_codes:
            try:
                res = locations_table.get_item(Key={"location_code": code})
            except Exception as exc:
                logger.exception("locations validation failed", exc_info=exc)
                return {"error": "Database error during location validation"}, 500
            if not res.get("Item"):
                return {"error": f"Location not found: {code!r}"}, 422
        update_expr_parts.append("location_codes = :location_codes")
        expr_attr_values[":location_codes"] = set(raw_codes)

    status = body.get("status")
    if status is not None:
        valid_statuses = {"active", "inactive", "canceled", "past_due", "trialing"}
        if status not in valid_statuses:
            return {"error": f"'status' must be one of {sorted(valid_statuses)}"}, 400
        update_expr_parts.append("#status = :status")
        expr_attr_names["#status"] = "status"
        expr_attr_values[":status"] = status

    try:
        result = subscribers_table.update_item(
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
        "subscriber": _transform_subscriber(result["Attributes"]),
    }


@api.delete("/real-estate/probate-leads/subscribers/<subscriber_id>")
@tracer.capture_method
def delete_subscriber(subscriber_id: str):
    """Soft-delete a subscriber by setting status → 'inactive'."""
    try:
        existing = subscribers_table.get_item(Key={"subscriber_id": subscriber_id}).get("Item")
    except Exception as exc:
        logger.exception("subscribers get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500
    if existing is None:
        return {"error": f"Subscriber not found: {subscriber_id!r}"}, 404

    try:
        result = subscribers_table.update_item(
            Key={"subscriber_id": subscriber_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     "inactive",
                ":updated_at": _now_iso(),
            },
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.exception("subscribers soft-delete failed", exc_info=exc)
        return {"error": "Failed to delete subscriber"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "subscriber": _transform_subscriber(result["Attributes"]),
    }


# ---------------------------------------------------------------------------
# Route — POST /stripe/webhook  (no API key; verified by Stripe signature)
# ---------------------------------------------------------------------------

@api.post("/real-estate/probate-leads/stripe/webhook")
@tracer.capture_method
def stripe_webhook():
    """
    Handle Stripe lifecycle events to keep subscriber status in sync.

    Handled event types:
      customer.subscription.created  → status = active
      customer.subscription.updated  → status = <stripe subscription status>
      customer.subscription.deleted  → status = canceled
      invoice.payment_failed         → status = past_due
    """
    from stripe_helpers import construct_stripe_event  # noqa: PLC0415 — local for testability

    raw_body   = api.current_event.raw_event.get("body") or ""
    sig_header = (api.current_event.headers or {}).get("Stripe-Signature", "")

    payload = raw_body.encode() if isinstance(raw_body, str) else raw_body
    event, err = construct_stripe_event(payload=payload, sig_header=sig_header)
    if err:
        logger.warning("Stripe signature error: %s", err)
        return {"error": err}, 400

    event_type  = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    stripe_customer_id = data_object.get("customer") or data_object.get("id", "")

    # Map Stripe event type → our subscriber status
    if event_type == "customer.subscription.created":
        new_status = "active"
    elif event_type == "customer.subscription.updated":
        # Mirror Stripe's own status (active, past_due, canceled, trialing, …)
        new_status = data_object.get("status", "active")
    elif event_type == "customer.subscription.deleted":
        new_status = "canceled"
    elif event_type == "invoice.payment_failed":
        new_status = "past_due"
        # customer is on the invoice, not the subscription object
        stripe_customer_id = data_object.get("customer", stripe_customer_id)
    else:
        logger.info("Unhandled Stripe event: %s", event_type)
        return {"received": True, "action": "ignored", "type": event_type}

    logger.info(
        "Stripe event type=%s customer=%s new_status=%s",
        event_type, stripe_customer_id, new_status,
    )

    if not stripe_customer_id:
        logger.warning("No customer ID in Stripe event %s", event_type)
        return {"received": True, "action": "no_customer_id"}, 200

    # Find subscriber by stripe_customer_id
    try:
        result = subscribers_table.scan(
            FilterExpression=Attr("stripe_customer_id").eq(stripe_customer_id)
        )
        items = result.get("Items", [])
    except Exception as exc:
        logger.exception("subscribers scan for webhook failed", exc_info=exc)
        return {"error": "Database error"}, 500

    if not items:
        logger.warning("No subscriber for Stripe customer: %s", stripe_customer_id)
        return {"received": True, "action": "no_subscriber_found"}, 200

    subscriber_id = items[0]["subscriber_id"]
    try:
        subscribers_table.update_item(
            Key={"subscriber_id": subscriber_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     new_status,
                ":updated_at": _now_iso(),
            },
        )
    except Exception as exc:
        logger.exception("subscribers update for webhook failed", exc_info=exc)
        return {"error": "Failed to update subscriber"}, 500

    logger.info("Subscriber %s status → %s", subscriber_id, new_status)
    return {
        "received":     True,
        "action":       "subscriber_updated",
        "subscriberId": subscriber_id,
        "status":       new_status,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
