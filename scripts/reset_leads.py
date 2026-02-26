"""
reset_leads.py — delete every item from the leads table.

Works against both DynamoDB Local and production AWS depending on env vars.

Local:
    make local-db-reset          # preferred (drops + recreates the table)
    # or directly:
    AWS_ENDPOINT_URL=http://localhost:8000 AWS_DEFAULT_REGION=us-east-1 \
    AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local \
    pipenv run python3 scripts/reset_leads.py

Production:
    make aws-db-reset
    # or directly:
    pipenv run python3 scripts/reset_leads.py
"""

import os
import boto3

ENDPOINT   = os.environ.get("AWS_ENDPOINT_URL")
TABLE_NAME = os.environ.get("DYNAMO_TABLE_NAME", "leads")
REGION     = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

session = boto3.Session(
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name=REGION,
)
kwargs = {"endpoint_url": ENDPOINT} if ENDPOINT else {}
ddb = session.client("dynamodb", **kwargs)

print(f"Scanning '{TABLE_NAME}' for all doc_number keys...")

paginator = ddb.get_paginator("scan")
delete_requests = []

for page in paginator.paginate(
    TableName=TABLE_NAME,
    ProjectionExpression="doc_number",
):
    for item in page.get("Items", []):
        delete_requests.append(
            {"DeleteRequest": {"Key": {"doc_number": item["doc_number"]}}}
        )

if not delete_requests:
    print("Table is already empty.")
else:
    total = len(delete_requests)
    print(f"  Deleting {total} item(s) in batches of 25...")
    deleted = 0
    for i in range(0, total, 25):
        chunk = delete_requests[i : i + 25]
        resp = ddb.batch_write_item(RequestItems={TABLE_NAME: chunk})
        unprocessed = resp.get("UnprocessedItems", {}).get(TABLE_NAME, [])
        deleted += len(chunk) - len(unprocessed)
        if unprocessed:
            print(f"  WARNING: {len(unprocessed)} items not deleted in batch {i // 25}")

    print(f"  {deleted}/{total} items deleted from '{TABLE_NAME}'.")
