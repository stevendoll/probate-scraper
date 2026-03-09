#!/usr/bin/env python3
"""
backfill_s3_uris.py — back-fill doc_s3_uri in the AWS DynamoDB documents table.

Lists every file under ``documents/`` in DOCUMENTS_BUCKET. For each file
whose base-name (stripped of extension) matches a numeric doc_number that
exists in the DynamoDB documents table with a blank (or missing) doc_s3_uri,
the record is updated with the canonical ``s3://bucket/key`` URI.

Only rows that already exist in DynamoDB are touched — no new rows are created.
Already-populated doc_s3_uri values are never overwritten.

Usage:
    DOCUMENTS_BUCKET=my-bucket \\
        pipenv run python scripts/backfill_s3_uris.py [--dry-run]

Environment variables:
    DOCUMENTS_BUCKET      — S3 bucket name (required)
    DOCUMENTS_TABLE_NAME  — DynamoDB table  (default: documents)
    AWS_DEFAULT_REGION    — AWS region      (default: us-east-1)
"""

import argparse
import logging
import os
import sys
import uuid

import boto3
from boto3.dynamodb.conditions import Attr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Must match _DOC_NS in src/scraper/dynamo.py
_DOC_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

REGION     = os.environ.get("AWS_DEFAULT_REGION",   "us-east-1")
BUCKET     = os.environ.get("DOCUMENTS_BUCKET",     "")
TABLE_NAME = os.environ.get("DOCUMENTS_TABLE_NAME", "documents")


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _list_s3_documents(bucket: str) -> dict[str, str]:
    """
    Page through ``s3://bucket/documents/`` and return a mapping of
    ``document_id → s3_uri`` for every file whose base-name is a pure integer
    doc_number.

    Key format expected: ``documents/{location_code}/{doc_number}{ext}``
    """
    s3 = boto3.client("s3", region_name=REGION)
    doc_id_to_uri: dict[str, str] = {}
    skipped = 0

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="documents/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            # Expect exactly: documents / {location_code} / {filename}
            if len(parts) != 3 or not parts[2]:
                skipped += 1
                continue

            filename  = parts[2]
            doc_number = os.path.splitext(filename)[0]

            if not doc_number.strip().isdigit():
                log.debug("Skipping non-numeric doc_number in key: %s", key)
                skipped += 1
                continue

            doc_id  = str(uuid.uuid5(_DOC_NS, doc_number))
            s3_uri  = f"s3://{bucket}/{key}"
            doc_id_to_uri[doc_id] = s3_uri

    log.info(
        "S3 scan complete: %d eligible file(s), %d skipped",
        len(doc_id_to_uri), skipped,
    )
    return doc_id_to_uri


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _batch_get(dynamo, table_name: str, doc_ids: list[str]) -> dict[str, str]:
    """
    Batch-fetch ``document_id`` + ``doc_s3_uri`` for *doc_ids*.
    Returns a mapping of ``document_id → doc_s3_uri`` (value may be ``""``).
    Items not found in DynamoDB are absent from the result.
    """
    found: dict[str, str] = {}

    for i in range(0, len(doc_ids), 100):
        chunk = doc_ids[i : i + 100]
        response = dynamo.batch_get_item(
            RequestItems={
                table_name: {
                    "Keys": [{"document_id": did} for did in chunk],
                    "ProjectionExpression": "document_id, doc_s3_uri",
                }
            }
        )
        for item in response.get("Responses", {}).get(table_name, []):
            did = item["document_id"]
            found[did] = item.get("doc_s3_uri", "")

        # Retry any unprocessed keys (rare, but possible under heavy load)
        unprocessed = response.get("UnprocessedKeys", {})
        if unprocessed:
            log.warning("Retrying %d unprocessed batch_get_item keys", len(unprocessed))
            retry = dynamo.batch_get_item(RequestItems=unprocessed)
            for item in retry.get("Responses", {}).get(table_name, []):
                did = item["document_id"]
                found[did] = item.get("doc_s3_uri", "")

    return found


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------

def backfill(
    bucket: str,
    table_name: str,
    dynamo_endpoint: str | None = None,
    dry_run: bool = False,
) -> None:
    # ── 1. List S3 ────────────────────────────────────────────────────────────
    log.info("Listing s3://%s/documents/ …", bucket)
    doc_id_to_s3_uri = _list_s3_documents(bucket)
    if not doc_id_to_s3_uri:
        log.info("No eligible files found in S3 — nothing to do.")
        return

    # ── 2. Batch-fetch from DynamoDB ──────────────────────────────────────────
    ddb_kwargs = {"region_name": REGION}
    if dynamo_endpoint:
        ddb_kwargs["endpoint_url"] = dynamo_endpoint
    dynamo = boto3.resource("dynamodb", **ddb_kwargs)
    table  = dynamo.Table(table_name)

    log.info(
        "Looking up %d document_id(s) in DynamoDB table '%s' …",
        len(doc_id_to_s3_uri), table_name,
    )
    existing = _batch_get(dynamo, table_name, list(doc_id_to_s3_uri))

    # ── 3. Filter: only update rows found in DDB with a blank doc_s3_uri ──────
    to_update = [
        (did, doc_id_to_s3_uri[did])
        for did, current_uri in existing.items()
        if not current_uri
    ]
    already_set   = sum(1 for uri in existing.values() if uri)
    not_in_dynamo = len(doc_id_to_s3_uri) - len(existing)

    log.info(
        "S3 files: %d total | %d already have doc_s3_uri | "
        "%d not in DynamoDB | %d to update",
        len(doc_id_to_s3_uri), already_set, not_in_dynamo, len(to_update),
    )

    if not to_update:
        log.info("Nothing to update.")
        return

    # ── 4. Update ─────────────────────────────────────────────────────────────
    updated = 0
    skipped = 0
    errors  = 0

    for doc_id, s3_uri in to_update:
        if dry_run:
            log.info("[DRY RUN] document_id=%s → %s", doc_id, s3_uri)
            continue
        try:
            table.update_item(
                Key={"document_id": doc_id},
                UpdateExpression="SET doc_s3_uri = :uri",
                # Guard: only update if doc_s3_uri is still blank/absent
                ConditionExpression=(
                    Attr("doc_s3_uri").not_exists() | Attr("doc_s3_uri").eq("")
                ),
                ExpressionAttributeValues={":uri": s3_uri},
            )
            log.info("Updated document_id=%s → %s", doc_id, s3_uri)
            updated += 1
        except dynamo.meta.client.exceptions.ConditionalCheckFailedException:
            # Race: another process wrote doc_s3_uri between batch_get and now
            log.debug("document_id=%s already has a URI (race condition), skipping", doc_id)
            skipped += 1
        except Exception as exc:
            log.error("Failed to update document_id=%s: %s", doc_id, exc)
            errors += 1

    # ── 5. Summary ────────────────────────────────────────────────────────────
    log.info(
        "Done: %d updated, %d skipped (race/already set), %d errors",
        updated, skipped, errors,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be updated without writing to DynamoDB.",
    )
    p.add_argument(
        "--bucket", default=BUCKET,
        help="S3 bucket name (overrides DOCUMENTS_BUCKET env var).",
    )
    p.add_argument(
        "--table", default=TABLE_NAME,
        help="DynamoDB table name (overrides DOCUMENTS_TABLE_NAME env var).",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if not args.bucket:
        log.error(
            "DOCUMENTS_BUCKET is not set. "
            "Set the env var or pass --bucket <name>."
        )
        sys.exit(1)

    if args.dry_run:
        log.info("*** DRY RUN — no changes will be written ***")

    backfill(
        bucket=args.bucket,
        table_name=args.table,
        dynamo_endpoint=None,   # use real AWS DynamoDB
        dry_run=args.dry_run,
    )
