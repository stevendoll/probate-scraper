"""
seed_local.py — create all DynamoDB tables locally and load initial data.

Usage:
    python scripts/seed_local.py [path/to/leads.csv]

Defaults to data/2026-01-29-probate-records.csv if no argument given.
Reads AWS_ENDPOINT_URL from environment (default: http://localhost:8000).

Tables created:
  leads        — scraped probate records (formerly probate-leads-collin-tx)
  locations    — supported counties/jurisdictions
  subscribers  — Stripe-backed subscriber accounts
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeSerializer

ENDPOINT   = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:8000")
GSI_NAME   = "recorded-date-index"

LEADS_TABLE_NAME       = os.environ.get("DYNAMO_TABLE_NAME",       "leads")
LOCATIONS_TABLE_NAME   = os.environ.get("LOCATIONS_TABLE_NAME",    "locations")
SUBSCRIBERS_TABLE_NAME = os.environ.get("SUBSCRIBERS_TABLE_NAME",  "subscribers")

# Dummy credentials required by DynamoDB Local (values don't matter)
session = boto3.Session(
    aws_access_key_id="local",
    aws_secret_access_key="local",
    region_name="us-east-1",
)
ddb = session.client("dynamodb", endpoint_url=ENDPOINT)
serializer = TypeSerializer()


# ---------------------------------------------------------------------------
# Generic table helpers
# ---------------------------------------------------------------------------

def table_exists(table_name: str) -> bool:
    try:
        ddb.describe_table(TableName=table_name)
        return True
    except ddb.exceptions.ResourceNotFoundException:
        return False


def _wait_active(table_name: str):
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=table_name)


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_leads_table():
    print(f"Creating table '{LEADS_TABLE_NAME}' at {ENDPOINT} ...")
    ddb.create_table(
        TableName=LEADS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "doc_number",    "AttributeType": "S"},
            {"AttributeName": "doc_type",      "AttributeType": "S"},
            {"AttributeName": "recorded_date", "AttributeType": "S"},
            {"AttributeName": "location_code", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "doc_number", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "recorded-date-index",
                "KeySchema": [
                    {"AttributeName": "doc_type",      "KeyType": "HASH"},
                    {"AttributeName": "recorded_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "location-date-index",
                "KeySchema": [
                    {"AttributeName": "location_code", "KeyType": "HASH"},
                    {"AttributeName": "recorded_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    _wait_active(LEADS_TABLE_NAME)
    print(f"  '{LEADS_TABLE_NAME}' ready.")


def create_locations_table():
    print(f"Creating table '{LOCATIONS_TABLE_NAME}' at {ENDPOINT} ...")
    ddb.create_table(
        TableName=LOCATIONS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "location_code", "AttributeType": "S"},
            {"AttributeName": "location_path", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "location_code", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "location-path-index",
                "KeySchema": [
                    {"AttributeName": "location_path", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    _wait_active(LOCATIONS_TABLE_NAME)
    print(f"  '{LOCATIONS_TABLE_NAME}' ready.")


def create_subscribers_table():
    print(f"Creating table '{SUBSCRIBERS_TABLE_NAME}' at {ENDPOINT} ...")
    ddb.create_table(
        TableName=SUBSCRIBERS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "subscriber_id", "AttributeType": "S"},
            {"AttributeName": "email",         "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "subscriber_id", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "email-index",
                "KeySchema": [
                    {"AttributeName": "email", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    _wait_active(SUBSCRIBERS_TABLE_NAME)
    print(f"  '{SUBSCRIBERS_TABLE_NAME}' ready.")


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
# Seed — locations
# ---------------------------------------------------------------------------

SEED_LOCATIONS = [
    {
        "location_code": "CollinTx",
        "location_path": "collin-tx",
        "location_name": "Collin County TX",
        "search_url":    "https://collin.tx.publicsearch.us",
        "retrieved_at":  "",
    },
]


def seed_locations():
    print(f"Seeding '{LOCATIONS_TABLE_NAME}' ...")
    for loc in SEED_LOCATIONS:
        item = {k: serializer.serialize(v) for k, v in loc.items() if v is not None}
        ddb.put_item(TableName=LOCATIONS_TABLE_NAME, Item=item)
    print(f"  {len(SEED_LOCATIONS)} location(s) written.")


# ---------------------------------------------------------------------------
# Seed — leads from CSV
# ---------------------------------------------------------------------------

def seed_leads_csv(csv_path: Path):
    print(f"Loading leads from {csv_path} ...")
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
            "pdf_url":           row.get("pdf_url", ""),
            "location_code":     row.get("location_code", "CollinTx"),
            "record_number":     row.get("record_number", "0"),
            "page_number":       row.get("page_number", "0"),
            "offset":            row.get("offset", "0"),
            "extracted_at":      row.get("extracted_at", now),
            "processed_at":      now,
            "scrape_run_id":     "seed-local",
        }
        if not item["doc_number"] or item["doc_number"] == "N/A":
            continue

        dynamo_item = {k: serializer.serialize(v) for k, v in item.items() if v}
        put_requests.append({"PutRequest": {"Item": dynamo_item}})

    total = 0
    for i in range(0, len(put_requests), 25):
        chunk = put_requests[i : i + 25]
        resp = ddb.batch_write_item(RequestItems={LEADS_TABLE_NAME: chunk})
        unprocessed = resp.get("UnprocessedItems", {}).get(LEADS_TABLE_NAME, [])
        total += len(chunk) - len(unprocessed)

    print(f"  {total} leads written to '{LEADS_TABLE_NAME}'")


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify():
    for name in (LEADS_TABLE_NAME, LOCATIONS_TABLE_NAME, SUBSCRIBERS_TABLE_NAME):
        resp = ddb.scan(TableName=name, Select="COUNT")
        print(f"  {name}: {resp['Count']} item(s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    csv_file = Path(sys.argv[1]) if len(sys.argv) > 1 else \
               Path(__file__).parent.parent / "data" / "2026-01-29-probate-records.csv"

    # ── Leads table
    if table_exists(LEADS_TABLE_NAME):
        print(f"Table '{LEADS_TABLE_NAME}' already exists — skipping creation")
    else:
        create_leads_table()

    if csv_file.exists():
        seed_leads_csv(csv_file)
    else:
        print(f"CSV not found ({csv_file}) — skipping leads seed")

    # ── Locations table
    if table_exists(LOCATIONS_TABLE_NAME):
        print(f"Table '{LOCATIONS_TABLE_NAME}' already exists — skipping creation")
    else:
        create_locations_table()
    seed_locations()  # idempotent (PutItem overwrites)

    # ── Subscribers table (starts empty)
    if table_exists(SUBSCRIBERS_TABLE_NAME):
        print(f"Table '{SUBSCRIBERS_TABLE_NAME}' already exists — skipping creation")
    else:
        create_subscribers_table()

    print("\nVerification:")
    verify()

    print("\nDone. Connect with:")
    print(f"  AWS_ENDPOINT_URL={ENDPOINT} aws dynamodb scan --table-name {LEADS_TABLE_NAME} --endpoint-url {ENDPOINT}")
    print(f"  AWS_ENDPOINT_URL={ENDPOINT} aws dynamodb scan --table-name {LOCATIONS_TABLE_NAME} --endpoint-url {ENDPOINT}")
