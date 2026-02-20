"""
DynamoDB helpers for the probate scraper.

Responsibilities:
  - normalize_date(): convert "1/23/2026" → "2026-01-23" so the GSI sort key
    is lexicographically equivalent to chronological order.
  - write_records(): batch-write a list of record dicts to DynamoDB using
    batch_write_item in chunks of 25 (the DDB hard limit per batch).
    Uses PutRequest, so duplicate doc_number values are silently overwritten
    (natural upsert semantics).
  - update_location_retrieved_at(): stamp the locations table with the time
    the last successful scrape completed for a given location.
"""

import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer

log = logging.getLogger(__name__)

_serializer = TypeSerializer()
_dynamodb = boto3.client("dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

def normalize_date(date_str: str) -> str:
    """
    Convert M/D/YYYY → YYYY-MM-DD for DynamoDB GSI sort key correctness.
    Passes through any value that doesn't match (e.g. "N/A", "--/--/--").

    >>> normalize_date("1/23/2026")
    '2026-01-23'
    >>> normalize_date("11/7/2025")
    '2025-11-07'
    >>> normalize_date("N/A")
    'N/A'
    """
    if not date_str or date_str in ("N/A", "--/--/--", ""):
        return date_str
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        log.debug("Could not normalise date '%s' — keeping as-is", date_str)
        return date_str


# ---------------------------------------------------------------------------
# Batch writer
# ---------------------------------------------------------------------------

def _to_dynamo_item(record: dict, scrape_run_id: str, location_code: str) -> dict:
    """
    Convert a scraper record dict into a DynamoDB-typed attribute map.
    Applies date normalisation and appends scrape metadata.
    """
    item = {
        # Core fields
        "doc_number":        record.get("doc_number", "UNKNOWN"),
        "grantor":           record.get("grantor", "N/A"),
        "grantee":           record.get("grantee", "N/A"),
        "doc_type":          record.get("doc_type", "PROBATE") or "PROBATE",
        "recorded_date":     normalize_date(record.get("recorded_date", "")),
        "book_volume_page":  record.get("book_volume_page", "N/A"),
        "legal_description": record.get("legal_description", "N/A"),
        # FK to locations table
        "location_code":     location_code,
        # Numeric metadata (store as strings to avoid DDB number precision issues)
        "record_number":     str(record.get("record_number", 0)),
        "page_number":       str(record.get("page_number", 0)),
        "offset":            str(record.get("offset", 0)),
        # Timestamps
        "extracted_at":      record.get("extracted_at", ""),
        "processed_at":      datetime.now(timezone.utc).isoformat(),
        "scrape_run_id":     scrape_run_id,
    }

    # Serialise to DynamoDB attribute format {"S": "...", "N": "..."}
    return {k: _serializer.serialize(v) for k, v in item.items() if v is not None}


def write_records(
    records: list,
    table_name: str,
    scrape_run_id: str,
    location_code: str,
) -> int:
    """
    Write *records* to *table_name* in DynamoDB, tagging each with *location_code*.
    Processes in chunks of 25 (DDB batch_write_item limit).
    Retries unprocessed items once per chunk.
    Returns total number of items successfully written.
    """
    if not records:
        return 0

    put_requests = [
        {"PutRequest": {"Item": _to_dynamo_item(r, scrape_run_id, location_code)}}
        for r in records
        if r.get("doc_number") and r["doc_number"] != "N/A"
    ]

    total_written = 0
    chunk_size = 25

    for i in range(0, len(put_requests), chunk_size):
        chunk = put_requests[i : i + chunk_size]
        try:
            response = _dynamodb.batch_write_item(
                RequestItems={table_name: chunk}
            )
            # Retry unprocessed items once
            unprocessed = response.get("UnprocessedItems", {}).get(table_name, [])
            if unprocessed:
                log.warning("Retrying %d unprocessed items", len(unprocessed))
                retry_resp = _dynamodb.batch_write_item(
                    RequestItems={table_name: unprocessed}
                )
                still_unprocessed = retry_resp.get("UnprocessedItems", {}).get(table_name, [])
                if still_unprocessed:
                    log.error("%d items failed after retry", len(still_unprocessed))

            total_written += len(chunk) - len(unprocessed)
        except Exception as exc:
            log.error("batch_write_item error for chunk %d: %s", i // chunk_size, exc)

    log.info(
        "write_records: %d/%d items written to %s (location=%s)",
        total_written, len(put_requests), table_name, location_code,
    )
    return total_written


# ---------------------------------------------------------------------------
# Location timestamp updater
# ---------------------------------------------------------------------------

def update_location_retrieved_at(locations_table_name: str, location_code: str) -> None:
    """
    Stamp the locations table with the current UTC time as retrieved_at.
    Called after a successful scrape run.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        _dynamodb.update_item(
            TableName=locations_table_name,
            Key={"location_code": {"S": location_code}},
            UpdateExpression="SET retrieved_at = :ts",
            ExpressionAttributeValues={":ts": {"S": now}},
        )
        log.info("Updated locations.retrieved_at for %s → %s", location_code, now)
    except Exception as exc:
        # Non-fatal — log and continue; the scrape data is already written
        log.error(
            "Failed to update locations.retrieved_at for %s: %s",
            location_code, exc,
        )
