"""
migrate_leads_to_split_tables.py — one-time migration from leads-v2 → documents + contacts + properties.

Scans the old `leads-v2` DynamoDB table and writes each item into the three
new purpose-built tables:

  documents   — the scraped/immutable record (PK: document_id)
  contacts    — one row per person parsed from the document
  properties  — one row per real-estate asset parsed from the document

All writes are idempotent (PutItem with the same deterministic PK).

Usage:
    # Dry run — show counts only, no writes
    python scripts/migrate_leads_to_split_tables.py --dry-run

    # Live run — write to DynamoDB
    python scripts/migrate_leads_to_split_tables.py

    # Point at DynamoDB Local for testing
    AWS_ENDPOINT_URL=http://localhost:8000 python scripts/migrate_leads_to_split_tables.py --dry-run

Environment variables:
    SOURCE_TABLE_NAME     — old table (default: leads-v2)
    DOCUMENTS_TABLE_NAME  — target documents table (default: documents)
    CONTACTS_TABLE_NAME   — target contacts table (default: contacts)
    PROPERTIES_TABLE_NAME — target properties table (default: properties)
    AWS_DEFAULT_REGION    — AWS region (default: us-east-1)
"""

import argparse
import os
import uuid
import logging
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Must match _DOC_NS in src/scraper/dynamo.py
_DOC_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

SOURCE_TABLE_NAME     = os.environ.get("SOURCE_TABLE_NAME",     "leads-v2")
DOCUMENTS_TABLE_NAME  = os.environ.get("DOCUMENTS_TABLE_NAME",  "documents")
CONTACTS_TABLE_NAME   = os.environ.get("CONTACTS_TABLE_NAME",   "contacts")
PROPERTIES_TABLE_NAME = os.environ.get("PROPERTIES_TABLE_NAME", "properties")
AWS_REGION            = os.environ.get("AWS_DEFAULT_REGION",    "us-east-1")
ENDPOINT              = os.environ.get("AWS_ENDPOINT_URL",      None)

# Fields that belong in the documents table (scraped immutable data)
_DOCUMENT_FIELDS = {
    "document_id", "doc_number", "grantor", "grantee", "doc_type",
    "recorded_date", "book_volume_page", "legal_description",
    "pdf_url", "doc_local_path", "doc_s3_uri", "location_code",
    "record_number", "page_number", "offset", "extracted_at",
    "scrape_run_id", "processed_at",
    # Parse status (written by ParseDocumentFunction, included here for completeness)
    "parsed_at", "parsed_model", "parse_error",
}


def _document_id_for(doc_number: str) -> str:
    return str(uuid.uuid5(_DOC_NS, str(doc_number)))


def _build_document_item(old_item: dict) -> dict:
    """Extract the document-table fields from an old leads-v2 item."""
    doc_number  = old_item.get("doc_number", "UNKNOWN")
    document_id = _document_id_for(doc_number)

    item = {"document_id": document_id}
    for field in _DOCUMENT_FIELDS - {"document_id"}:
        if field in old_item:
            item[field] = old_item[field]
        # Ensure doc_number is always present
    item.setdefault("doc_number", doc_number)
    return item


def _build_contact_items(old_item: dict, document_id: str, migrated_at: str) -> list[dict]:
    """Build Contact rows from an old leads-v2 item's parsed fields."""
    contacts = []

    deceased_name = old_item.get("deceased_name") or ""
    if deceased_name:
        contacts.append({
            "contact_id":   str(uuid.uuid4()),
            "document_id":  document_id,
            "role":         "deceased",
            "name":         deceased_name,
            "dob":          old_item.get("deceased_dob") or "",
            "dod":          old_item.get("deceased_dod") or "",
            "address":      old_item.get("deceased_last_address") or "",
            "notes":        "",
            "parsed_at":    old_item.get("parsed_at") or migrated_at,
            "parsed_model": old_item.get("parsed_model") or "migrated",
        })

    for person in (old_item.get("people") or []):
        if not isinstance(person, dict):
            continue
        name = person.get("name") or ""
        if not name:
            continue
        contacts.append({
            "contact_id":   str(uuid.uuid4()),
            "document_id":  document_id,
            "role":         (person.get("role") or "other").lower(),
            "name":         name,
            "dob":          "",
            "dod":          "",
            "address":      "",
            "notes":        "",
            "parsed_at":    old_item.get("parsed_at") or migrated_at,
            "parsed_model": old_item.get("parsed_model") or "migrated",
        })

    return contacts


def _build_property_items(old_item: dict, document_id: str, migrated_at: str) -> list[dict]:
    """Build Property rows from an old leads-v2 item's real_property list."""
    properties = []
    for prop in (old_item.get("real_property") or []):
        address = prop if isinstance(prop, str) else ""
        properties.append({
            "property_id":       str(uuid.uuid4()),
            "document_id":       document_id,
            "address":           address,
            "legal_description": "",
            "parcel_id":         "",
            "city":              "",
            "state":             "",
            "zip":               "",
            "notes":             "",
            "parsed_at":         old_item.get("parsed_at") or migrated_at,
            "parsed_model":      old_item.get("parsed_model") or "migrated",
        })
    return properties


def migrate(dry_run: bool = False):
    kwargs = {"region_name": AWS_REGION}
    if ENDPOINT:
        kwargs["endpoint_url"] = ENDPOINT

    ddb = boto3.resource("dynamodb", **kwargs)

    source_table      = ddb.Table(SOURCE_TABLE_NAME)
    documents_table   = ddb.Table(DOCUMENTS_TABLE_NAME)
    contacts_table    = ddb.Table(CONTACTS_TABLE_NAME)
    properties_table  = ddb.Table(PROPERTIES_TABLE_NAME)

    migrated_at = datetime.now(timezone.utc).isoformat()

    log.info("Scanning source table: %s", SOURCE_TABLE_NAME)
    log.info("Dry run: %s", dry_run)

    total_items      = 0
    docs_written     = 0
    contacts_written = 0
    props_written    = 0
    skipped          = 0

    paginator_kwargs: dict = {}
    while True:
        if paginator_kwargs:
            resp = source_table.scan(**paginator_kwargs)
        else:
            resp = source_table.scan()

        items = resp.get("Items", [])
        log.info("  Retrieved %d item(s) from source table", len(items))
        total_items += len(items)

        for old_item in items:
            doc_number = old_item.get("doc_number", "")
            if not str(doc_number).strip().isdigit():
                log.debug("Skipping non-integer doc_number: %r", doc_number)
                skipped += 1
                continue

            document_id      = _document_id_for(str(doc_number))
            doc_item         = _build_document_item(old_item)
            contact_items    = _build_contact_items(old_item, document_id, migrated_at)
            property_items   = _build_property_items(old_item, document_id, migrated_at)

            if not dry_run:
                documents_table.put_item(Item=doc_item)
                docs_written += 1

                for c in contact_items:
                    contacts_table.put_item(Item=c)
                contacts_written += len(contact_items)

                for p in property_items:
                    properties_table.put_item(Item=p)
                props_written += len(property_items)
            else:
                docs_written     += 1
                contacts_written += len(contact_items)
                props_written    += len(property_items)

        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        paginator_kwargs = {"ExclusiveStartKey": last_key}

    log.info("Migration complete.")
    log.info("  Total source items scanned : %d", total_items)
    log.info("  Skipped (non-integer doc#) : %d", skipped)
    log.info("  Documents %s           : %d",
             "would write" if dry_run else "written", docs_written)
    log.info("  Contacts  %s           : %d",
             "would write" if dry_run else "written", contacts_written)
    log.info("  Properties %s          : %d",
             "would write" if dry_run else "written", props_written)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate leads-v2 → documents/contacts/properties")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Scan source table and count rows without writing anything",
    )
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
