"""
DynamoDB helpers for the probate scraper.

Responsibilities:
  - normalize_date(): convert "1/23/2026" → "2026-01-23" so the GSI sort key
    is lexicographically equivalent to chronological order.
  - write_documents(): batch-write a list of record dicts to DynamoDB using
    batch_write_item in chunks of 25 (the DDB hard limit per batch).
    Uses PutRequest with a deterministic uuid5 document_id derived from doc_number.
    Documents are only written once — existing entries are skipped entirely
    to prevent redundant web clicks and re-downloads.
  - get_existing_doc_numbers(): uses batch_get_item on the documents table PK
    to determine which doc_numbers are already stored, before Phase 2 clicking.
  - update_location_retrieved_at(): stamp the locations table with the time
    the last successful scrape completed for a given location.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeSerializer

log = logging.getLogger(__name__)

# Fixed namespace for deterministic UUID5 generation.
# Using the same namespace everywhere ensures that the same doc_number always
# produces the same document_id.  Value is identical to the legacy _LEAD_NS
# so that existing data in the documents table (migrated from leads-v2) keeps
# the same primary key.
_DOC_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

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

def _to_document_item(record: dict, scrape_run_id: str, location_code: str) -> dict:
    """
    Convert a scraper record dict into a DynamoDB-typed attribute map.
    Applies date normalisation and appends scrape metadata.
    Only scraped fields are included — no parsed/enriched data.
    """
    doc_number = record.get("doc_number", "UNKNOWN")
    item = {
        # Primary key — deterministic UUID derived from doc_number so that
        # the same document always maps to the same document_id.
        "document_id":       str(uuid.uuid5(_DOC_NS, str(doc_number))),
        # Core fields
        "doc_number":        doc_number,
        "grantor":           record.get("grantor", "N/A"),
        "grantee":           record.get("grantee", "N/A"),
        "doc_type":          record.get("doc_type", "PROBATE") or "PROBATE",
        "recorded_date":     normalize_date(record.get("recorded_date", "")),
        "book_volume_page":  record.get("book_volume_page", "N/A"),
        "legal_description": record.get("legal_description", "N/A"),
        # Document PDF/image link extracted by the scraper (may be empty string)
        "pdf_url":           record.get("pdf_url") or "",
        # Local filesystem path written by Chrome's Download button (ephemeral on Fargate)
        "doc_local_path":    record.get("doc_local_path") or "",
        # S3 URI of the uploaded document copy, e.g. s3://bucket/documents/CollinTx/123.pdf
        "doc_s3_uri":        record.get("doc_s3_uri") or "",
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


def write_documents(
    records: list,
    table_name: str,
    scrape_run_id: str,
    location_code: str,
) -> int:
    """
    Write *records* to *table_name* in DynamoDB, tagging each with *location_code*.
    Only records with integer doc_numbers are written.
    Processes in chunks of 25 (DDB batch_write_item limit).
    Retries unprocessed items once per chunk.
    Returns total number of items successfully written.

    Note: callers should pre-filter using get_existing_doc_numbers() before
    calling this function to avoid re-writing documents that already exist.
    """
    if not records:
        return 0

    put_requests = [
        {"PutRequest": {"Item": _to_document_item(r, scrape_run_id, location_code)}}
        for r in records
        if str(r.get("doc_number", "")).strip().isdigit()
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
        "Wrote %d/%d documents to %s (location=%s)",
        total_written, len(put_requests), table_name, location_code,
    )
    return total_written


# ---------------------------------------------------------------------------
# Existing document lookup (skip-if-exists)
# ---------------------------------------------------------------------------

def get_existing_doc_numbers(
    table_name: str,
    doc_numbers: list,
) -> set:
    """
    Use batch_get_item to check which doc_numbers already exist in the documents table.
    Returns a set of doc_number strings that are already stored.

    Called before Phase 2 (clicking/downloading) to avoid redundant web interactions.
    Uses the table PK (document_id) directly — no GSI query needed.
    batch_get_item limit is 100 keys per call; handled automatically.
    """
    eligible = [str(dn) for dn in doc_numbers if str(dn).strip().isdigit()]
    if not eligible:
        return set()

    # Map document_id → doc_number so we can return doc_numbers
    doc_id_to_num = {str(uuid.uuid5(_DOC_NS, dn)): dn for dn in eligible}
    existing = set()
    keys = [{"document_id": {"S": did}} for did in doc_id_to_num]

    for i in range(0, len(keys), 100):
        chunk = keys[i : i + 100]
        try:
            response = _dynamodb.batch_get_item(
                RequestItems={
                    table_name: {
                        "Keys": chunk,
                        "ProjectionExpression": "document_id",
                    }
                }
            )
            for item in response.get("Responses", {}).get(table_name, []):
                did = item.get("document_id", {}).get("S", "")
                if did in doc_id_to_num:
                    existing.add(doc_id_to_num[did])
        except Exception as exc:
            log.warning("get_existing_doc_numbers error: %s", exc)

    log.info(
        "Found %d/%d doc_numbers already in documents table",
        len(existing), len(eligible),
    )
    return existing


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
