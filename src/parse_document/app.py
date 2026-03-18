"""
ParseDocumentFunction — Lambda handler.

Route (registered in template.yaml):
  POST /real-estate/probate-leads/documents/{document_id}/parse-document

Flow:
  1. Look up the document by document_id in the documents table.
  2. Verify it has a doc_s3_uri pointing to the stored PDF.
  3. Fetch the PDF bytes from S3.
  4. Send the PDF to Amazon Bedrock (Nova Pro) via the Converse API
     together with a structured-extraction prompt.
  5. Parse the JSON response from Bedrock.
  6. Write contact records to the contacts table.
  7. Write property records to the properties table.
  8. Enrich up to 10 non-deceased contacts via Enformion (if credentials set).
  9. Stamp parsed_at + parse_error on the documents table.
  10. Return a summary response.

Environment variables:
  DOCUMENTS_TABLE_NAME  — documents table (default: documents)
  CONTACTS_TABLE_NAME   — contacts table (default: contacts)
  PROPERTIES_TABLE_NAME — properties table (default: properties)
  LINKS_TABLE_NAME      — links table (default: links)
  DOCUMENTS_BUCKET      — S3 bucket where PDFs are stored
  BEDROCK_MODEL_ID      — Bedrock model ID (default: us.amazon.nova-pro-v1:0)
  ENFORMION_AP_NAME     — Enformion galaxy-ap-name credential
  ENFORMION_AP_PASSWORD — Enformion galaxy-ap-password credential
  AWS_DEFAULT_REGION    — AWS region (injected by Lambda runtime)
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, quote_plus

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key

from prompt import SYSTEM_PROMPT, USER_PROMPT

# usaddress is an optional dependency used to parse / validate street addresses.
# If the package is not installed (e.g. during unit tests without the extra dep)
# the fallback simply leaves city/state/zip empty and is_verified = False.
try:
    import usaddress as _usaddress
    _USADDRESS_AVAILABLE = True
except ImportError:                         # pragma: no cover
    _usaddress = None                       # type: ignore[assignment]
    _USADDRESS_AVAILABLE = False

logger = Logger(service="parse-document")
api    = APIGatewayRestResolver()

# ---------------------------------------------------------------------------
# AWS clients (module-level so they are reused across warm invocations)
# ---------------------------------------------------------------------------

_region               = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_documents_table_name = os.environ.get("DOCUMENTS_TABLE_NAME", "documents")
_contacts_table_name  = os.environ.get("CONTACTS_TABLE_NAME", "contacts")
_properties_table_name = os.environ.get("PROPERTIES_TABLE_NAME", "properties")
_bucket_name          = os.environ.get("DOCUMENTS_BUCKET", "")
_model_id             = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.amazon.nova-pro-v1:0",
)

_links_table_name        = os.environ.get("LINKS_TABLE_NAME", "links")
_enformion_ap_name       = os.environ.get("ENFORMION_AP_NAME", "")
_enformion_ap_password   = os.environ.get("ENFORMION_AP_PASSWORD", "")

_dynamodb          = boto3.resource("dynamodb", region_name=_region)
_documents_table   = _dynamodb.Table(_documents_table_name)
_contacts_table    = _dynamodb.Table(_contacts_table_name)
_properties_table  = _dynamodb.Table(_properties_table_name)
_links_table       = _dynamodb.Table(_links_table_name)
_s3                = boto3.client("s3", region_name=_region)
_bedrock           = boto3.client("bedrock-runtime", region_name=_region)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capitalize_name(name: str) -> str:
    """Title-case a probate document name, handling hyphens and apostrophes.

    Probate documents are typically ALL-CAPS; this converts them to
    First Last style matching the API's capitalize_name() in data_helpers.py.
    """
    if not name:
        return ""
    parts = []
    for word in name.split():
        if "-" in word:
            parts.append("-".join(p.capitalize() for p in word.split("-")))
        elif "'" in word:
            parts.append("'".join(p.capitalize() for p in word.split("'")))
        else:
            parts.append(word.capitalize())
    return " ".join(parts)


# Role priority for deduplication: lower index = higher priority.
_ROLE_PRIORITY = [
    "executor", "attorney", "trustee", "guardian",
    "beneficiary", "heir", "spouse", "other",
]


def _role_rank(role: str) -> int:
    try:
        return _ROLE_PRIORITY.index(role.lower())
    except ValueError:
        return len(_ROLE_PRIORITY)


def _deduplicate_people(people: list[dict]) -> list[dict]:
    """Merge duplicate people entries (same normalised name) into one record.

    The highest-priority role is kept; secondary roles are appended to notes.
    """
    seen: dict[str, dict] = {}   # normalised_name → merged entry

    for person in people:
        name = (person.get("name") or "").strip()
        if not name:
            continue
        key = " ".join(name.lower().split())

        if key not in seen:
            seen[key] = {**person, "_extra_roles": []}
        else:
            existing    = seen[key]
            new_role    = (person.get("role") or "other").lower()
            exist_role  = (existing.get("role") or "other").lower()
            if _role_rank(new_role) < _role_rank(exist_role):
                existing["_extra_roles"].append(exist_role)
                existing["role"] = new_role
            else:
                existing["_extra_roles"].append(new_role)

    result = []
    for entry in seen.values():
        extra = entry.pop("_extra_roles", [])
        if extra:
            role_note    = "Also: " + ", ".join(extra)
            entry["notes"] = (
                ((entry.get("notes") or "") + "; " + role_note).lstrip("; ")
            )
        result.append(entry)
    return result


def _s3_uri_to_bucket_key(s3_uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key`` into ``(bucket, key)``."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Not an S3 URI: {s3_uri!r}")
    bucket = parsed.netloc
    key    = parsed.path.lstrip("/")
    return bucket, key


def _fetch_pdf_bytes(s3_uri: str) -> bytes:
    """Download the PDF from S3 and return its raw bytes."""
    bucket, key = _s3_uri_to_bucket_key(s3_uri)
    response = _s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _call_bedrock(pdf_bytes: bytes) -> tuple[dict, str]:
    """
    Send the PDF to Bedrock via the Converse API and return ``(parsed_dict, raw_text)``.

    Uses a document block with Amazon Nova Pro, which supports document blocks
    natively via its cross-region inference profile.  Anthropic Claude models
    (Haiku, Sonnet, etc.) silently ignore the document bytes even when the API
    call succeeds, returning "no document attached" responses.

    The model is expected to return a single JSON object — no markdown fences.
    If the response contains a fenced code block we strip the fences first.
    The raw model output is returned alongside the parsed dict so callers can
    store it for debugging / reprocessing.
    """
    response = _bedrock.converse(
        modelId=_model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "document": {
                            "format": "pdf",
                            "name":   "probate-filing",
                            "source": {"bytes": pdf_bytes},
                        },
                    },
                    {"text": USER_PROMPT},
                ],
            }
        ],
        inferenceConfig={
            "maxTokens": 5120,  # Nova Pro max; 2048 truncated long people arrays
            "temperature": 0,
        },
    )

    raw_text = response["output"]["message"]["content"][0]["text"].strip()

    # 1. Try parsing as-is (ideal: model returned pure JSON)
    try:
        return json.loads(raw_text), raw_text
    except json.JSONDecodeError:
        pass

    # 2. Strip optional ```json ... ``` fences then retry
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw_text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip()), raw_text
        except json.JSONDecodeError:
            pass

    # 3. Slice from the first '{' to the last '}' — handles preamble/postamble prose
    start = raw_text.find("{")
    end   = raw_text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw_text[start : end + 1]), raw_text
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON in model response: {raw_text[:300]!r}")


def _write_contacts(
    document_id: str, parsed: dict, model_id: str, parsed_at: str, raw_response: str
) -> tuple[int, list[dict]]:
    """
    Write one Contact record per person extracted from the document.
    Includes the deceased person (from deceased_* fields) + people list.
    Returns (count_written, contacts_list) where contacts_list contains
    dicts with at minimum contact_id, name, role (for enrichment).
    """
    written = 0
    contacts: list[dict] = []

    # Deceased contact
    deceased_name    = _capitalize_name(parsed.get("deceased_name") or "")
    deceased_dob     = parsed.get("deceased_dob") or ""
    deceased_dod     = parsed.get("deceased_dod") or ""
    deceased_address = parsed.get("deceased_last_address") or ""
    if deceased_name:
        deceased_contact_id = str(uuid.uuid4())
        _contacts_table.put_item(Item={
            "contact_id":     deceased_contact_id,
            "document_id":    document_id,
            # editable (ground-truth) fields — start as the parsed values
            "role":           "deceased",
            "name":           deceased_name,
            "email":          "",
            "dob":            deceased_dob,
            "dod":            deceased_dod,
            "address":        deceased_address,
            "notes":          "",
            "edited_at":      "",
            # parse metadata
            "parsed_at":      parsed_at,
            "parsed_model":   model_id,
            "raw_response":   raw_response,
            # bedrock snapshot — preserved for golden-dataset comparison
            "parsed_role":    "deceased",
            "parsed_name":    deceased_name,
            "parsed_email":   "",
            "parsed_dob":     deceased_dob,
            "parsed_dod":     deceased_dod,
            "parsed_address": deceased_address,
            "parsed_notes":   "",
        })
        contacts.append({"contact_id": deceased_contact_id, "name": deceased_name, "role": "deceased"})
        written += 1
        # Auto-insert a Legacy.com obituary search link for the deceased
        try:
            _links_table.put_item(Item={
                "link_id":     str(uuid.uuid4()),
                "document_id": document_id,
                "parent_id":   deceased_contact_id,
                "parent_type": "contact",
                "label":       "Legacy.com",
                "url":         f"https://www.legacy.com/search?name={quote_plus(deceased_name)}",
                "link_type":   "legacy",
                "notes":       "",
                "created_at":  parsed_at,
            })
        except Exception as exc:                     # pragma: no cover
            logger.warning("Failed to insert Legacy.com link: %s", exc)

    # People list — deduplicate by name, then capitalise
    people = _deduplicate_people([
        p for p in (parsed.get("people") or []) if isinstance(p, dict)
    ])
    for person in people:
        name = _capitalize_name(person.get("name") or "")
        if not name:
            continue
        role  = (person.get("role") or "other").lower()
        email = person.get("email") or ""
        notes = person.get("notes") or ""
        contact_id = str(uuid.uuid4())
        _contacts_table.put_item(Item={
            "contact_id":     contact_id,
            "document_id":    document_id,
            # editable (ground-truth) fields — start as the parsed values
            "role":           role,
            "name":           name,
            "email":          email,
            "dob":            "",
            "dod":            "",
            "address":        "",
            "notes":          notes,
            "edited_at":      "",
            # parse metadata
            "parsed_at":      parsed_at,
            "parsed_model":   model_id,
            "raw_response":   raw_response,
            # bedrock snapshot — preserved for golden-dataset comparison
            "parsed_role":    role,
            "parsed_name":    name,
            "parsed_email":   email,
            "parsed_dob":     "",
            "parsed_dod":     "",
            "parsed_address": "",
            "parsed_notes":   notes,
        })
        contacts.append({"contact_id": contact_id, "name": name, "role": role})
        written += 1

    return written, contacts


def _try_usaddress(raw: str) -> tuple[str, str, str, bool]:
    """
    Attempt to extract city, state, ZIP from a raw address string using usaddress.
    Returns (city, state, zip, is_verified).
    is_verified is True only when usaddress classifies the input as a Street Address
    and at minimum an AddressNumber + PlaceName were found.
    """
    if not _USADDRESS_AVAILABLE or not raw:
        return "", "", "", False
    try:
        tagged, addr_type = _usaddress.tag(raw)
        if addr_type != "Street Address":
            return "", "", "", False
        city  = tagged.get("PlaceName", "") or ""
        state = tagged.get("StateName", "") or ""
        zip_  = tagged.get("ZipCode",   "") or ""
        is_ok = bool(tagged.get("AddressNumber") and city)
        return city, state, zip_, is_ok
    except Exception:
        return "", "", "", False


def _write_properties(
    document_id: str, parsed: dict, model_id: str, parsed_at: str, raw_response: str
) -> int:
    """
    Write one Property record per real-property entry extracted from the document.

    Accepts both the legacy flat-string format and the new structured-object format
    returned by the updated Bedrock prompt:
      { address, city, state, zip, legal_description }

    When city/state/zip are absent from the Bedrock output, usaddress is used as a
    fallback parser on the address string. is_verified is True when all three
    components (address number + city + zip) could be resolved.

    Returns the number of properties written.
    """
    written = 0
    for prop in (parsed.get("real_property") or []):
        if isinstance(prop, str):
            # Legacy / model-regression: flat string → treat as full address
            address           = prop
            bedrock_city      = ""
            bedrock_state     = ""
            bedrock_zip       = ""
            legal_description = ""
        elif isinstance(prop, dict):
            address           = prop.get("address") or ""
            bedrock_city      = prop.get("city") or ""
            bedrock_state     = prop.get("state") or ""
            bedrock_zip       = prop.get("zip") or ""
            legal_description = prop.get("legal_description") or ""
        else:
            continue

        # Resolve city/state/zip — prefer Bedrock output, fall back to usaddress
        if bedrock_city and bedrock_state and bedrock_zip:
            city, state, zip_ = bedrock_city, bedrock_state, bedrock_zip
            is_verified = bool(address)        # Bedrock gave everything; verified if address present
        else:
            ua_city, ua_state, ua_zip, ua_ok = _try_usaddress(address)
            city        = bedrock_city  or ua_city
            state       = bedrock_state or ua_state
            zip_        = bedrock_zip   or ua_zip
            is_verified = ua_ok and bool(address)

        property_id = str(uuid.uuid4())
        _properties_table.put_item(Item={
            "property_id":              property_id,
            "document_id":              document_id,
            # editable (ground-truth) fields — start as the resolved values
            "address":                  address,
            "legal_description":        legal_description,
            "parcel_id":                "",
            "city":                     city,
            "state":                    state,
            "zip":                      zip_,
            "notes":                    "",
            "edited_at":                "",
            "is_verified":              is_verified,
            # parse metadata
            "parsed_at":                parsed_at,
            "parsed_model":             model_id,
            "raw_response":             raw_response,
            # bedrock snapshot — preserved for golden-dataset comparison
            "parsed_address":           address,
            "parsed_legal_description": legal_description,
            "parsed_parcel_id":         "",
            "parsed_city":              bedrock_city,
            "parsed_state":             bedrock_state,
            "parsed_zip":               bedrock_zip,
            "parsed_notes":             "",
        })
        written += 1
        # Auto-insert a Google Maps search link when the property has an address
        if address:
            try:
                full_addr = ", ".join(filter(None, [address, city, f"{state} {zip_}".strip()]))
                _links_table.put_item(Item={
                    "link_id":     str(uuid.uuid4()),
                    "document_id": document_id,
                    "parent_id":   property_id,
                    "parent_type": "property",
                    "label":       "Google Maps",
                    "url":         f"https://www.google.com/maps/search/?api=1&query={quote_plus(full_addr)}",
                    "link_type":   "google_maps",
                    "notes":       "",
                    "created_at":  parsed_at,
                })
            except Exception as exc:               # pragma: no cover
                logger.warning("Failed to insert Google Maps link: %s", exc)

    return written


def _apply_enrichment(enrichment_results: list[dict]) -> None:
    """
    Write Enformion enrichment results back to DynamoDB contacts table.
    Uses UpdateItem so only enrichment columns are touched.
    """
    for result in enrichment_results:
        contact_id = result.get("contact_id")
        if not contact_id:
            continue
        try:
            _contacts_table.update_item(
                Key={"contact_id": contact_id},
                UpdateExpression=(
                    "SET enrichment_status = :es, enriched_at = :ea,"
                    " enriched_phone = :ep, enriched_email = :ee,"
                    " enriched_name = :en, enriched_identity_score = :ei"
                ),
                ExpressionAttributeValues={
                    ":es": result.get("enrichment_status", ""),
                    ":ea": result.get("enriched_at", ""),
                    ":ep": result.get("enriched_phone", ""),
                    ":ee": result.get("enriched_email", ""),
                    ":en": result.get("enriched_name", ""),
                    ":ei": result.get("enriched_identity_score", ""),
                },
            )
        except Exception as exc:
            logger.warning("Failed to write enrichment for contact %s: %s", contact_id, exc)


def _clear_existing(document_id: str) -> tuple[int, int]:
    """
    Delete all contacts, properties, and links previously written for this document.

    Called before writing new parse results so a re-parse fully replaces the
    old data rather than appending duplicates.  Only invoked after Bedrock has
    returned successfully — if S3 or Bedrock fail the existing records are kept.

    Links are always cleared alongside contacts/properties because contact and
    property UUIDs change on every re-parse, leaving any surviving links
    orphaned (they would never appear in the UI again).

    Returns (contacts_deleted, properties_deleted).
    """
    # Contacts
    contacts_result = _contacts_table.query(
        IndexName="document-contact-index",
        KeyConditionExpression=Key("document_id").eq(document_id),
        ProjectionExpression="contact_id",
    )
    contacts_deleted = 0
    with _contacts_table.batch_writer() as batch:
        for item in contacts_result.get("Items", []):
            batch.delete_item(Key={"contact_id": item["contact_id"]})
            contacts_deleted += 1

    # Properties
    properties_result = _properties_table.query(
        IndexName="document-property-index",
        KeyConditionExpression=Key("document_id").eq(document_id),
        ProjectionExpression="property_id",
    )
    properties_deleted = 0
    with _properties_table.batch_writer() as batch:
        for item in properties_result.get("Items", []):
            batch.delete_item(Key={"property_id": item["property_id"]})
            properties_deleted += 1

    # Links — orphaned by new contact/property UUIDs; always purge
    links_result = _links_table.query(
        IndexName="document-link-index",
        KeyConditionExpression=Key("document_id").eq(document_id),
        ProjectionExpression="link_id",
    )
    with _links_table.batch_writer() as batch:
        for item in links_result.get("Items", []):
            batch.delete_item(Key={"link_id": item["link_id"]})

    return contacts_deleted, properties_deleted


def _update_document_status(
    document_id: str,
    model_id: str,
    parsed_at: str,
    error: str = "",
    summary: str = "",
    raw_response: str = "",
) -> None:
    """
    Stamp parsed_at, parsed_model, parse_error, summary, and raw_response on
    the documents table.  Uses UpdateItem so only the status columns are touched.
    """
    _documents_table.update_item(
        Key={"document_id": document_id},
        UpdateExpression=(
            "SET parsed_at = :pa, parsed_model = :pm, parse_error = :pe,"
            " summary = :su, raw_response = :rr"
        ),
        ExpressionAttributeValues={
            ":pa": parsed_at,
            ":pm": model_id,
            ":pe": error,
            ":su": summary,
            ":rr": raw_response,
        },
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@api.post("/real-estate/probate-leads/documents/<document_id>/parse-document")
def parse_document(document_id: str):
    # 1. Fetch the document
    result = _documents_table.get_item(Key={"document_id": document_id})
    item   = result.get("Item")
    if not item:
        return {"error": f"Document not found: {document_id!r}"}, 404

    doc_s3_uri = item.get("doc_s3_uri", "")
    if not doc_s3_uri:
        return {
            "error": (
                f"Document {document_id!r} has no doc_s3_uri. "
                "The document must be scraped and uploaded to S3 first."
            )
        }, 422

    now = _now_iso()

    # 2. Fetch the PDF from S3
    try:
        pdf_bytes = _fetch_pdf_bytes(doc_s3_uri)
    except Exception as exc:
        logger.error("S3 fetch failed: %s", exc)
        err_msg = f"S3 fetch failed: {exc}"
        _update_document_status(document_id, _model_id, now, error=err_msg)
        return {"error": err_msg}, 500

    # 3. Call Bedrock
    try:
        parsed, raw_response = _call_bedrock(pdf_bytes)
    except Exception as exc:
        logger.error("Bedrock call failed: %s", exc)
        err_msg = f"Bedrock call failed: {exc}"
        _update_document_status(document_id, _model_id, now, error=err_msg)
        return {"error": err_msg}, 500

    # 4. Clear any previously parsed records, then write fresh results
    try:
        _clear_existing(document_id)
    except Exception as exc:
        logger.error("DynamoDB clear failed: %s", exc)
        _update_document_status(document_id, _model_id, now, error=str(exc))
        return {"error": f"DynamoDB clear failed: {exc}"}, 500

    contacts_written = 0
    properties_written = 0
    contacts_list: list[dict] = []
    try:
        contacts_written, contacts_list = _write_contacts(document_id, parsed, _model_id, now, raw_response)
        properties_written = _write_properties(document_id, parsed, _model_id, now, raw_response)
    except Exception as exc:
        logger.error("DynamoDB write failed: %s", exc)
        _update_document_status(document_id, _model_id, now, error=str(exc))
        return {"error": f"DynamoDB write failed: {exc}"}, 500

    # Enrich contacts via Enformion (best-effort — never blocks parse success)
    if _enformion_ap_name and _enformion_ap_password:
        try:
            from enformion import enrich_contacts  # noqa: PLC0415
            enrichment_results = enrich_contacts(
                contacts_list, _enformion_ap_name, _enformion_ap_password
            )
            if enrichment_results:
                _apply_enrichment(enrichment_results)
                logger.info(
                    "Enformion enrichment complete: %d contacts processed",
                    len(enrichment_results),
                )
        except Exception as exc:
            logger.error("Enformion enrichment failed (non-fatal): %s", exc)

    # 5. Stamp status on the documents table
    summary = parsed.get("summary") or ""
    try:
        _update_document_status(
            document_id, _model_id, now,
            summary=summary, raw_response=raw_response,
        )
    except Exception as exc:
        logger.error("DynamoDB update failed: %s", exc)
        return {"error": f"DynamoDB update failed: {exc}"}, 500

    return {
        "documentId":        document_id,
        "docNumber":         item.get("doc_number", ""),
        "docS3Uri":          doc_s3_uri,
        "parsedAt":          now,
        "parseError":        "",
        "contactsWritten":   contacts_written,
        "propertiesWritten": properties_written,
    }, 200


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
