#!/usr/bin/env python3
"""
backfill_s3_uris_local.py — back-fill doc_s3_uri in the LOCAL DynamoDB documents table.

Identical logic to backfill_s3_uris.py but targets DynamoDB Local
(http://localhost:8000) instead of AWS DynamoDB. S3 still uses real AWS
credentials — the bucket is in AWS, only the DynamoDB target is local.

Typical workflow:
  1. Run the scraper with DOCUMENTS_BUCKET set (uploads PDFs to S3 + AWS DDB).
  2. Reset local DynamoDB: ``make local-db-reset && make local-db-seed``
  3. Re-scrape locally (without DOCUMENTS_BUCKET) to populate local DDB rows.
  4. Run this script to copy the S3 URIs from S3 into local DDB rows so that
     the local parse-document endpoint can find the PDFs.

Usage:
    DOCUMENTS_BUCKET=my-bucket \\
        pipenv run python scripts/backfill_s3_uris_local.py [--dry-run]

Environment variables:
    DOCUMENTS_BUCKET          — S3 bucket name (required; files must exist in AWS S3)
    DOCUMENTS_TABLE_NAME      — DynamoDB table  (default: documents)
    AWS_DEFAULT_REGION        — AWS region      (default: us-east-1)
    LOCAL_DYNAMO_URL          — DynamoDB Local URL (default: http://localhost:8000)
"""

import argparse
import logging
import os
import sys

# Import shared backfill logic from the sibling script
sys.path.insert(0, os.path.dirname(__file__))
from backfill_s3_uris import backfill  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

BUCKET          = os.environ.get("DOCUMENTS_BUCKET",     "")
TABLE_NAME      = os.environ.get("DOCUMENTS_TABLE_NAME", "documents")
LOCAL_DYNAMO_URL = os.environ.get("LOCAL_DYNAMO_URL",    "http://localhost:8000")


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
    p.add_argument(
        "--dynamo-url", default=LOCAL_DYNAMO_URL,
        help=f"DynamoDB Local endpoint (default: {LOCAL_DYNAMO_URL}).",
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

    log.info("Targeting LOCAL DynamoDB at %s", args.dynamo_url)

    if args.dry_run:
        log.info("*** DRY RUN — no changes will be written ***")

    backfill(
        bucket=args.bucket,
        table_name=args.table,
        dynamo_endpoint=args.dynamo_url,
        dry_run=args.dry_run,
    )
