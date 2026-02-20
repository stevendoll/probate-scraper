"""
seed_local.py — create the DynamoDB table locally and load CSV data.

Usage:
    python scripts/seed_local.py [path/to/file.csv]

Defaults to data/2026-01-29-probate-records.csv if no argument given.
Reads AWS_ENDPOINT_URL from environment (default: http://localhost:8000).
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeSerializer

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:8000")
TABLE_NAME = os.environ.get("DYNAMO_TABLE_NAME", "probate-leads-collin-tx")
GSI_NAME = "recorded-date-index"

# Dummy credentials required by DynamoDB Local (values don't matter)
session = boto3.Session(
    aws_access_key_id="local",
    aws_secret_access_key="local",
    region_name="us-east-1",
)
ddb = session.client("dynamodb", endpoint_url=ENDPOINT)
serializer = TypeSerializer()


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def table_exists() -> bool:
    try:
        ddb.describe_table(TableName=TABLE_NAME)
        return True
    except ddb.exceptions.ResourceNotFoundException:
        return False


def create_table():
    print(f"Creating table '{TABLE_NAME}' at {ENDPOINT} ...")
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "doc_number",    "AttributeType": "S"},
            {"AttributeName": "doc_type",      "AttributeType": "S"},
            {"AttributeName": "recorded_date", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "doc_number", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI_NAME,
                "KeySchema": [
                    {"AttributeName": "doc_type",      "KeyType": "HASH"},
                    {"AttributeName": "recorded_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    # Wait for the table to become active
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    print("Table created.")


# ---------------------------------------------------------------------------
# Date normalisation (mirrors dynamo.py)
# ---------------------------------------------------------------------------

def normalize_date(date_str: str) -> str:
    if not date_str or date_str in ("N/A", "--/--/--", ""):
        return date_str
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


# ---------------------------------------------------------------------------
# Seed from CSV
# ---------------------------------------------------------------------------

def seed_csv(csv_path: Path):
    print(f"Loading {csv_path} ...")
    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    print(f"  {len(rows)} rows found")

    now = datetime.now(timezone.utc).isoformat()
    put_requests = []

    for row in rows:
        item = {
            "doc_number":        row.get("doc_number", "UNKNOWN"),
            "grantor":           row.get("grantor", "N/A"),
            "grantee":           row.get("grantee", "N/A"),
            "doc_type":          row.get("doc_type", "PROBATE") or "PROBATE",
            "recorded_date":     normalize_date(row.get("recorded_date", "")),
            "book_volume_page":  row.get("book_volume_page", "N/A"),
            "legal_description": row.get("legal_description", "N/A"),
            "record_number":     row.get("record_number", "0"),
            "page_number":       row.get("page_number", "0"),
            "offset":            row.get("offset", "0"),
            "extracted_at":      row.get("extracted_at", now),
            "processed_at":      now,
            "scrape_run_id":     "seed-local",
        }
        # Skip rows without a valid doc_number
        if not item["doc_number"] or item["doc_number"] == "N/A":
            continue

        dynamo_item = {k: serializer.serialize(v) for k, v in item.items() if v}
        put_requests.append({"PutRequest": {"Item": dynamo_item}})

    # Batch write in chunks of 25
    total = 0
    for i in range(0, len(put_requests), 25):
        chunk = put_requests[i : i + 25]
        resp = ddb.batch_write_item(RequestItems={TABLE_NAME: chunk})
        unprocessed = resp.get("UnprocessedItems", {}).get(TABLE_NAME, [])
        total += len(chunk) - len(unprocessed)

    print(f"  {total} records written to '{TABLE_NAME}'")


# ---------------------------------------------------------------------------
# Verify — quick item count
# ---------------------------------------------------------------------------

def verify():
    resp = ddb.scan(TableName=TABLE_NAME, Select="COUNT")
    print(f"  Table count: {resp['Count']} items")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    csv_file = Path(sys.argv[1]) if len(sys.argv) > 1 else \
               Path(__file__).parent.parent / "data" / "2026-01-29-probate-records.csv"

    if not csv_file.exists():
        print(f"CSV not found: {csv_file}")
        sys.exit(1)

    if table_exists():
        print(f"Table '{TABLE_NAME}' already exists — skipping creation")
    else:
        create_table()

    seed_csv(csv_file)
    verify()
    print("\nDone. Connect with:")
    print(f"  AWS_ENDPOINT_URL={ENDPOINT} aws dynamodb scan --table-name {TABLE_NAME} --endpoint-url {ENDPOINT}")
