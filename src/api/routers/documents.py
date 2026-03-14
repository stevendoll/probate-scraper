"""
Routes:
  GET    /real-estate/probate-leads/{location_path}/documents
  GET    /real-estate/probate-leads/documents/{document_id}
  GET    /real-estate/probate-leads/documents/{document_id}/contacts
  PATCH  /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}
  DELETE /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}
  POST   /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}/links
  DELETE /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}/links/{link_id}
  GET    /real-estate/probate-leads/documents/{document_id}/properties
  PATCH  /real-estate/probate-leads/documents/{document_id}/properties/{property_id}
  DELETE /real-estate/probate-leads/documents/{document_id}/properties/{property_id}
  POST   /real-estate/probate-leads/documents/{document_id}/properties/{property_id}/links
  DELETE /real-estate/probate-leads/documents/{document_id}/properties/{property_id}/links/{link_id}
"""

import json
import uuid
from datetime import datetime, timezone

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Attr, Key

import db
from models import Contact, Document, Link, Location, Property
from utils import decode_key, encode_key, parse_date

logger = Logger(service="probate-api")
router = Router()


def _dynamo_update_expression(updates: dict) -> tuple[str, dict, dict]:
    """Build a DynamoDB SET expression from a plain field→value dict.

    All field names are aliased with # to avoid reserved-word collisions.
    Returns (UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues).

    Example:
        expr, names, vals = _dynamo_update_expression({"role": "heir", "edited_at": "…"})
        table.update_item(Key=…, UpdateExpression=expr,
                          ExpressionAttributeNames=names,
                          ExpressionAttributeValues=vals)
    """
    set_clause = ", ".join(f"#{k} = :{k}" for k in updates)
    return (
        f"SET {set_clause}",
        {f"#{k}": k for k in updates},
        {f":{k}": v for k, v in updates.items()},
    )


def _get_location_by_path(location_path: str) -> dict | None:
    """Look up a location item using the location-path-index GSI.

    Returns the raw DynamoDB item or ``None`` if not found.
    """
    try:
        result = db.locations_table.query(
            IndexName="location-path-index",
            KeyConditionExpression=Key("location_path").eq(location_path),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        logger.error("locations GSI query failed: %s", exc)
        return None


@router.get("/real-estate/probate-leads/<location_path>/documents")
def get_documents_by_location(location_path: str):
    # 1. Resolve location_path → location record
    location = _get_location_by_path(location_path)
    if location is None:
        return {"error": f"Location not found: {location_path!r}"}, 404

    location_code = location["location_code"]

    qs = router.current_event.query_string_parameters or {}

    raw_from = qs.get("from_date", "")
    raw_to   = qs.get("to_date", "")
    doc_type = qs.get("doc_type", "PROBATE")

    try:
        limit = min(int(qs.get("limit", db.DEFAULT_LIMIT)), db.MAX_LIMIT)
        limit = max(limit, 1)
    except (ValueError, TypeError):
        return {"error": "'limit' must be an integer between 1 and 200"}, 400

    from_date = parse_date(raw_from) if raw_from else None
    to_date   = parse_date(raw_to)   if raw_to   else None

    if raw_from and from_date is None:
        return {"error": f"'from_date' must be YYYY-MM-DD, got: {raw_from!r}"}, 400
    if raw_to and to_date is None:
        return {"error": f"'to_date' must be YYYY-MM-DD, got: {raw_to!r}"}, 400

    last_key = None
    if qs.get("last_key"):
        last_key = decode_key(qs["last_key"])
        if last_key is None:
            return {"error": "'last_key' is not a valid pagination cursor"}, 400

    # 2. Build key condition expression for the location-date GSI.
    # Both dates optional; no dates → most-recent-first via ScanIndexForward=False.
    if from_date and to_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").between(from_date, to_date)
        )
    elif from_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").gte(from_date)
        )
    elif to_date:
        kce = (
            Key("location_code").eq(location_code)
            & Key("recorded_date").lte(to_date)
        )
    else:
        kce = Key("location_code").eq(location_code)

    query_kwargs = {
        "IndexName": db.location_date_gsi,
        "KeyConditionExpression": kce,
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if doc_type != "ALL":
        query_kwargs["FilterExpression"] = Attr("doc_type").eq(doc_type)
    if last_key:
        query_kwargs["ExclusiveStartKey"] = last_key

    try:
        result = db.documents_table.query(**query_kwargs)
    except Exception as exc:
        logger.error("DynamoDB query error: %s", exc)
        return {"error": "Database query failed"}, 500

    documents = [Document.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    next_key = None
    if "LastEvaluatedKey" in result:
        next_key = encode_key(result["LastEvaluatedKey"])

    body = {
        "requestId": str(uuid.uuid4()),
        "location": Location.from_dynamo(location).to_dict(),
        "documents": documents,
        "count": len(documents),
        "nextKey": next_key,
        "query": {
            "locationPath": location_path,
            "fromDate": from_date,
            "toDate": to_date,
            "docType": doc_type,
            "limit": limit,
        },
    }

    return body


def _fetch_links_for_document(document_id: str) -> dict[str, list]:
    """Query all links for a document and return a dict of parent_id → [link dicts]."""
    try:
        result = db.links_table.query(
            IndexName="document-link-index",
            KeyConditionExpression=Key("document_id").eq(document_id),
        )
        links_by_parent: dict[str, list] = {}
        for item in result.get("Items", []):
            pid = item.get("parent_id", "")
            links_by_parent.setdefault(pid, []).append(Link.from_dynamo(item).to_dict())
        return links_by_parent
    except Exception as exc:
        logger.error("links GSI query failed: %s", exc)
        return {}


@router.get("/real-estate/probate-leads/documents/<document_id>")
def get_document(document_id: str):
    """Return a single document with its contacts, properties, and links."""
    # 1. Fetch the document
    try:
        result = db.documents_table.get_item(Key={"document_id": document_id})
    except Exception as exc:
        logger.error("documents get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if not item:
        return {"error": f"Document not found: {document_id!r}"}, 404

    document = Document.from_dynamo(item).to_dict()

    # 2. Fetch contacts
    try:
        contacts_result = db.contacts_table.query(
            IndexName="document-contact-index",
            KeyConditionExpression=Key("document_id").eq(document_id),
        )
        contacts_raw = contacts_result.get("Items", [])
    except Exception as exc:
        logger.error("contacts GSI query failed: %s", exc)
        contacts_raw = []

    # 3. Fetch properties
    try:
        props_result = db.properties_table.query(
            IndexName="document-property-index",
            KeyConditionExpression=Key("document_id").eq(document_id),
        )
        props_raw = props_result.get("Items", [])
    except Exception as exc:
        logger.error("properties GSI query failed: %s", exc)
        props_raw = []

    # 4. Fetch links (one query, distribute by parent_id)
    links_by_parent = _fetch_links_for_document(document_id)

    def _with_links(item_dict: dict, id_key: str) -> dict:
        item_dict["links"] = links_by_parent.get(item_dict.get(id_key, ""), [])
        return item_dict

    contacts   = [_with_links(Contact.from_dynamo(c).to_dict(),  "contactId")  for c in contacts_raw]
    properties = [_with_links(Property.from_dynamo(p).to_dict(), "propertyId") for p in props_raw]

    return {
        "requestId":  str(uuid.uuid4()),
        "document":   document,
        "contacts":   contacts,
        "properties": properties,
    }


@router.get("/real-estate/probate-leads/documents/<document_id>/contacts")
def get_document_contacts(document_id: str):
    """Return all contacts associated with a document."""
    try:
        result = db.contacts_table.query(
            IndexName="document-contact-index",
            KeyConditionExpression=Key("document_id").eq(document_id),
        )
    except Exception as exc:
        logger.error("contacts GSI query failed: %s", exc)
        return {"error": "Database query failed"}, 500

    contacts = [Contact.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    return {
        "requestId":  str(uuid.uuid4()),
        "documentId": document_id,
        "contacts":   contacts,
        "count":      len(contacts),
    }


@router.get("/real-estate/probate-leads/documents/<document_id>/properties")
def get_document_properties(document_id: str):
    """Return all properties associated with a document."""
    try:
        result = db.properties_table.query(
            IndexName="document-property-index",
            KeyConditionExpression=Key("document_id").eq(document_id),
        )
    except Exception as exc:
        logger.error("properties GSI query failed: %s", exc)
        return {"error": "Database query failed"}, 500

    properties = [Property.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    return {
        "requestId":  str(uuid.uuid4()),
        "documentId": document_id,
        "properties": properties,
        "count":      len(properties),
    }


# ---------------------------------------------------------------------------
# Contacts — PATCH / DELETE
# ---------------------------------------------------------------------------

_CONTACT_MUTABLE = {"role", "name", "email", "dob", "dod", "address", "notes"}


@router.patch("/real-estate/probate-leads/documents/<document_id>/contacts/<contact_id>")
def update_contact(document_id: str, contact_id: str):
    """Partially update a contact record. Only mutable fields are accepted."""
    try:
        body = json.loads(router.current_event.body or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"error": "Request body must be valid JSON"}, 400

    updates = {k: v for k, v in body.items() if k in _CONTACT_MUTABLE}
    if not updates:
        return {"error": f"No updatable fields provided. Allowed: {sorted(_CONTACT_MUTABLE)}"}, 400

    try:
        existing = db.contacts_table.get_item(Key={"contact_id": contact_id}).get("Item")
    except Exception as exc:
        logger.error("contacts get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    if not existing:
        return {"error": f"Contact not found: {contact_id!r}"}, 404
    if existing.get("document_id") != document_id:
        return {"error": "Contact does not belong to the specified document"}, 403

    all_updates = {**updates, "edited_at": datetime.now(timezone.utc).isoformat()}
    update_expr, expr_names, expr_vals = _dynamo_update_expression(all_updates)

    try:
        result = db.contacts_table.update_item(
            Key={"contact_id": contact_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.error("contacts update_item failed: %s", exc)
        return {"error": "Database update failed"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "contact":   Contact.from_dynamo(result["Attributes"]).to_dict(),
    }


@router.delete("/real-estate/probate-leads/documents/<document_id>/contacts/<contact_id>")
def delete_contact(document_id: str, contact_id: str):
    """Delete a single contact record."""
    try:
        existing = db.contacts_table.get_item(Key={"contact_id": contact_id}).get("Item")
    except Exception as exc:
        logger.error("contacts get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    if not existing:
        return {"error": f"Contact not found: {contact_id!r}"}, 404
    if existing.get("document_id") != document_id:
        return {"error": "Contact does not belong to the specified document"}, 403

    try:
        db.contacts_table.delete_item(Key={"contact_id": contact_id})
    except Exception as exc:
        logger.error("contacts delete_item failed: %s", exc)
        return {"error": "Database delete failed"}, 500

    return {"requestId": str(uuid.uuid4()), "deleted": contact_id}


# ---------------------------------------------------------------------------
# Properties — PATCH / DELETE
# ---------------------------------------------------------------------------

_PROPERTY_MUTABLE = {"address", "legal_description", "parcel_id", "city", "state", "zip", "notes"}


@router.patch("/real-estate/probate-leads/documents/<document_id>/properties/<property_id>")
def update_property(document_id: str, property_id: str):
    """Partially update a property record. Only mutable fields are accepted."""
    try:
        body = json.loads(router.current_event.body or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"error": "Request body must be valid JSON"}, 400

    updates = {k: v for k, v in body.items() if k in _PROPERTY_MUTABLE}
    if not updates:
        return {"error": f"No updatable fields provided. Allowed: {sorted(_PROPERTY_MUTABLE)}"}, 400

    try:
        existing = db.properties_table.get_item(Key={"property_id": property_id}).get("Item")
    except Exception as exc:
        logger.error("properties get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    if not existing:
        return {"error": f"Property not found: {property_id!r}"}, 404
    if existing.get("document_id") != document_id:
        return {"error": "Property does not belong to the specified document"}, 403

    all_updates = {**updates, "edited_at": datetime.now(timezone.utc).isoformat()}
    # Changing the address invalidates the previous usaddress verification.
    if "address" in updates:
        all_updates["is_verified"] = False
    update_expr, expr_names, expr_vals = _dynamo_update_expression(all_updates)

    try:
        result = db.properties_table.update_item(
            Key={"property_id": property_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:
        logger.error("properties update_item failed: %s", exc)
        return {"error": "Database update failed"}, 500

    return {
        "requestId": str(uuid.uuid4()),
        "property":  Property.from_dynamo(result["Attributes"]).to_dict(),
    }


@router.delete("/real-estate/probate-leads/documents/<document_id>/properties/<property_id>")
def delete_property(document_id: str, property_id: str):
    """Delete a single property record."""
    try:
        existing = db.properties_table.get_item(Key={"property_id": property_id}).get("Item")
    except Exception as exc:
        logger.error("properties get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    if not existing:
        return {"error": f"Property not found: {property_id!r}"}, 404
    if existing.get("document_id") != document_id:
        return {"error": "Property does not belong to the specified document"}, 403

    try:
        db.properties_table.delete_item(Key={"property_id": property_id})
    except Exception as exc:
        logger.error("properties delete_item failed: %s", exc)
        return {"error": "Database delete failed"}, 500

    return {"requestId": str(uuid.uuid4()), "deleted": property_id}


# ---------------------------------------------------------------------------
# Links — POST / DELETE  (shared logic for contacts and properties)
# ---------------------------------------------------------------------------

_VALID_LINK_TYPES = {
    "zillow", "realtor", "redfin", "google_maps",
    "county_record", "obituary", "legacy", "findagrave", "other",
}


def _create_link(document_id: str, parent_id: str, parent_type: str):
    """Shared POST handler — creates a link attached to a contact or property."""
    try:
        body = json.loads(router.current_event.body or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"error": "Request body must be valid JSON"}, 400

    url = (body.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}, 400

    label     = (body.get("label") or "").strip()
    link_type = (body.get("link_type") or "other").strip().lower()
    notes     = (body.get("notes") or "").strip()

    if link_type not in _VALID_LINK_TYPES:
        return {"error": f"link_type must be one of: {sorted(_VALID_LINK_TYPES)}"}, 400

    item = {
        "link_id":     str(uuid.uuid4()),
        "parent_id":   parent_id,
        "parent_type": parent_type,
        "document_id": document_id,
        "label":       label,
        "url":         url,
        "link_type":   link_type,
        "notes":       notes,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }

    try:
        db.links_table.put_item(Item=item)
    except Exception as exc:
        logger.error("links put_item failed: %s", exc)
        return {"error": "Database write failed"}, 500

    return {"requestId": str(uuid.uuid4()), "link": Link.from_dynamo(item).to_dict()}, 201


def _delete_link(document_id: str, parent_id: str, link_id: str):
    """Shared DELETE handler — removes a link by link_id after ownership checks."""
    try:
        existing = db.links_table.get_item(Key={"link_id": link_id}).get("Item")
    except Exception as exc:
        logger.error("links get_item failed: %s", exc)
        return {"error": "Database query failed"}, 500

    if not existing:
        return {"error": f"Link not found: {link_id!r}"}, 404
    if existing.get("document_id") != document_id:
        return {"error": "Link does not belong to the specified document"}, 403
    if existing.get("parent_id") != parent_id:
        return {"error": "Link does not belong to the specified parent"}, 403

    try:
        db.links_table.delete_item(Key={"link_id": link_id})
    except Exception as exc:
        logger.error("links delete_item failed: %s", exc)
        return {"error": "Database delete failed"}, 500

    return {"requestId": str(uuid.uuid4()), "deleted": link_id}


@router.post("/real-estate/probate-leads/documents/<document_id>/contacts/<contact_id>/links")
def create_contact_link(document_id: str, contact_id: str):
    return _create_link(document_id, parent_id=contact_id, parent_type="contact")


@router.delete("/real-estate/probate-leads/documents/<document_id>/contacts/<contact_id>/links/<link_id>")
def delete_contact_link(document_id: str, contact_id: str, link_id: str):
    return _delete_link(document_id, parent_id=contact_id, link_id=link_id)


@router.post("/real-estate/probate-leads/documents/<document_id>/properties/<property_id>/links")
def create_property_link(document_id: str, property_id: str):
    return _create_link(document_id, parent_id=property_id, parent_type="property")


@router.delete("/real-estate/probate-leads/documents/<document_id>/properties/<property_id>/links/<link_id>")
def delete_property_link(document_id: str, property_id: str, link_id: str):
    return _delete_link(document_id, parent_id=property_id, link_id=link_id)
