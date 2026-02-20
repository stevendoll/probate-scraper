"""
Lambda handler for GET /real-estate/probate-leads/collin-tx/leads

Queries the 'recorded-date-index' GSI on DynamoDB and returns paginated
probate lead records as JSON.

Query parameters:
  from_date  (str, optional)  ISO date YYYY-MM-DD — inclusive lower bound on recorded_date
  to_date    (str, optional)  ISO date YYYY-MM-DD — inclusive upper bound (default: today)
  limit      (int, optional)  Records per page, 1-200 (default: 50)
  last_key   (str, optional)  Base64-encoded LastEvaluatedKey for cursor pagination
  doc_type   (str, optional)  GSI partition key value (default: "PROBATE")

Environment variables:
  DYNAMO_TABLE_NAME — DynamoDB table name
  GSI_NAME          — GSI name (default: recorded-date-index)
"""

import base64
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, Response
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="probate-api")
tracer = Tracer(service="probate-api")
api = APIGatewayRestResolver()

_table_name = os.environ.get("DYNAMO_TABLE_NAME", "probate-leads-collin-tx")
_gsi_name = os.environ.get("GSI_NAME", "recorded-date-index")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(_table_name)

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

_FIELD_MAP = {
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
    "offset":            "offset",
}

_TIMESTAMP_FIELDS = {"extracted_at", "processed_at"}


# ---------------------------------------------------------------------------
# Helpers
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
    """Rename fields to PascalCase and normalize timestamps."""
    result = {}
    for k, v in item.items():
        if k in _TIMESTAMP_FIELDS:
            v = _normalize_timestamp(str(v))
        result[_FIELD_MAP.get(k, k)] = v
    return result


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@api.get("/real-estate/probate-leads/collin-tx/leads")
@tracer.capture_method
def get_leads():
    qs = api.current_event.query_string_parameters or {}

    # --- Parse and validate parameters ---
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

    # Decode pagination cursor
    last_key = None
    if qs.get("last_key"):
        last_key = _decode_key(qs["last_key"])
        if last_key is None:
            return {"error": "'last_key' is not a valid pagination cursor"}, 400

    response_headers = {}

    # --- Choose query strategy ---
    if from_date and to_date:
        logger.info("GSI query", extra={
            "doc_type": doc_type, "from_date": from_date,
            "to_date": to_date, "limit": limit,
        })
        query_kwargs = {
            "IndexName": _gsi_name,
            "KeyConditionExpression": (
                Key("doc_type").eq(doc_type) & Key("recorded_date").between(from_date, to_date)
            ),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if last_key:
            query_kwargs["ExclusiveStartKey"] = last_key

        try:
            result = table.query(**query_kwargs)
        except Exception as exc:
            logger.exception("DynamoDB query error", exc_info=exc)
            return {"error": "Database query failed"}, 500

    elif to_date and not from_date:
        logger.info("GSI query (no from_date)", extra={
            "doc_type": doc_type, "to_date": to_date, "limit": limit,
        })
        query_kwargs = {
            "IndexName": _gsi_name,
            "KeyConditionExpression": (
                Key("doc_type").eq(doc_type) & Key("recorded_date").lte(to_date)
            ),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if last_key:
            query_kwargs["ExclusiveStartKey"] = last_key

        try:
            result = table.query(**query_kwargs)
        except Exception as exc:
            logger.exception("DynamoDB query error", exc_info=exc)
            return {"error": "Database query failed"}, 500

    else:
        logger.warning("Full table scan — no date range provided")
        response_headers["X-Warning"] = (
            "Full table scan in progress. Provide from_date and to_date for efficient queries."
        )
        scan_kwargs = {"Limit": limit}
        if last_key:
            scan_kwargs["ExclusiveStartKey"] = last_key

        try:
            result = table.scan(**scan_kwargs)
        except Exception as exc:
            logger.exception("DynamoDB scan error", exc_info=exc)
            return {"error": "Database scan failed"}, 500

    # --- Build response ---
    leads = [_transform_lead(item) for item in result.get("Items", [])]
    next_key = None
    if "LastEvaluatedKey" in result:
        next_key = _encode_key(result["LastEvaluatedKey"])

    body = {
        "requestId": str(uuid.uuid4()),
        "leads": leads,
        "count": len(leads),
        "nextKey": next_key,
        "query": {
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
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
