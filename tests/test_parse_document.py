"""
Unit tests for src/parse_document/app.py

Covers:
  - Happy path: S3 + Bedrock succeed → contacts/properties written, 200 returned
  - Document not found → 404
  - Document has no doc_s3_uri → 422
  - S3 fetch fails → parse_error stored on documents table, 500 returned
  - Bedrock call fails → parse_error stored on documents table, 500 returned
  - DynamoDB write fails (contacts/properties) → 500 returned
  - DynamoDB update fails (documents status) → 500 returned
  - Markdown-fenced JSON response is handled correctly
  - _s3_uri_to_bucket_key parses correctly
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path setup — add src/parse_document so 'prompt' can be found at import time
# ---------------------------------------------------------------------------
import importlib.util
import types

_PARSE_DOC_SRC = os.path.join(os.path.dirname(__file__), "..", "src", "parse_document")
sys.path.insert(0, _PARSE_DOC_SRC)

# Stub out aws_lambda_powertools before importing app so we don't need the
# full package installed.  We only need Logger + APIGatewayRestResolver.

# Minimal Logger stub
_powertools_pkg = types.ModuleType("aws_lambda_powertools")
_Logger_stub = MagicMock()
_Logger_instance = MagicMock()
_Logger_instance.inject_lambda_context = lambda **kw: (lambda f: f)
_Logger_instance.exception = lambda *a, **kw: None
_Logger_stub.return_value = _Logger_instance
_powertools_pkg.Logger = _Logger_stub

# Minimal APIGatewayRestResolver stub — post() must return the function unchanged
_resolver_instance = MagicMock()
_resolver_instance.post = lambda path: (lambda f: f)
_resolver_instance.resolve = MagicMock(return_value={"statusCode": 200})
_resolver_cls = MagicMock(return_value=_resolver_instance)

_event_handler_mod = types.ModuleType("aws_lambda_powertools.event_handler")
_event_handler_mod.APIGatewayRestResolver = _resolver_cls

_utilities_mod  = types.ModuleType("aws_lambda_powertools.utilities")
_typing_mod     = types.ModuleType("aws_lambda_powertools.utilities.typing")
_typing_mod.LambdaContext = object

sys.modules.setdefault("aws_lambda_powertools", _powertools_pkg)
sys.modules.setdefault("aws_lambda_powertools.event_handler", _event_handler_mod)
sys.modules.setdefault("aws_lambda_powertools.utilities", _utilities_mod)
sys.modules.setdefault("aws_lambda_powertools.utilities.typing", _typing_mod)

# Load src/parse_document/app.py by file path with a unique module name so it
# does NOT collide with the "app" module that test_api.py already cached in
# sys.modules (Python caches by name, not by path).
def _load_parse_document_app():
    spec = importlib.util.spec_from_file_location(
        "parse_document_app",
        os.path.join(_PARSE_DOC_SRC, "app.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parse_document_app"] = mod
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(mod)
    return mod

parse_app = _load_parse_document_app()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_BEDROCK_PAYLOAD = {
    "deceased_name":         "Jane A. Smith",
    "deceased_dob":          "1942-03-15",
    "deceased_dod":          "2025-11-01",
    "deceased_last_address": "123 Main St, Plano, TX 75001",
    "people": [
        {"name": "Robert Smith",   "role": "Executor"},
        {"name": "Emily Jones",    "role": "Heir"},
        {"name": "Tom Brown, Esq", "role": "Attorney"},
    ],
    "real_property": [
        {
            "address":           "123 Main St",
            "city":              "Plano",
            "state":             "TX",
            "zip":               "75001",
            "legal_description": None,
        },
        {
            "address":           None,
            "city":              None,
            "state":             None,
            "zip":               None,
            "legal_description": "Lot 7, Block 3, Willow Creek Estates",
        },
    ],
    "summary": (
        "This probate petition was filed on behalf of the estate of Jane A. Smith, "
        "who died on 1 November 2025 in Collin County, Texas. Her son Robert Smith "
        "is named independent executor. Two heirs and one attorney are listed. The "
        "estate includes the decedent's primary residence and one additional parcel."
    ),
}


def _make_document(doc_s3_uri: str = "s3://mybucket/documents/CollinTx/20240001.pdf") -> dict:
    return {
        "document_id": "550e8400-e29b-41d4-a716-446655440000",
        "doc_number":  "20240001",
        "grantor":     "Smith, Jane A.",
        "doc_s3_uri":  doc_s3_uri,
    }


def _bedrock_response(payload: dict | str) -> dict:
    """Build a minimal Bedrock Converse response dict."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "output": {
            "message": {
                "content": [{"text": text}]
            }
        }
    }


# ---------------------------------------------------------------------------
# _s3_uri_to_bucket_key
# ---------------------------------------------------------------------------

class TestS3UriParsing(unittest.TestCase):

    def test_standard_uri(self):
        bucket, key = parse_app._s3_uri_to_bucket_key(
            "s3://mybucket/documents/CollinTx/20240001.pdf"
        )
        self.assertEqual(bucket, "mybucket")
        self.assertEqual(key,    "documents/CollinTx/20240001.pdf")

    def test_uri_without_leading_slash_in_key(self):
        bucket, key = parse_app._s3_uri_to_bucket_key("s3://b/k/e/y")
        self.assertEqual(bucket, "b")
        self.assertEqual(key,    "k/e/y")

    def test_invalid_scheme_raises(self):
        with self.assertRaises(ValueError):
            parse_app._s3_uri_to_bucket_key("https://example.com/file.pdf")


# ---------------------------------------------------------------------------
# parse_document route
# ---------------------------------------------------------------------------

class TestParseDocument(unittest.TestCase):

    def setUp(self):
        """Replace the module-level AWS clients with fresh MagicMocks."""
        self.mock_documents_table  = MagicMock()
        self.mock_contacts_table   = MagicMock()
        self.mock_properties_table = MagicMock()
        self.mock_links_table      = MagicMock()
        self.mock_s3               = MagicMock()
        self.mock_bedrock          = MagicMock()

        parse_app._documents_table  = self.mock_documents_table
        parse_app._contacts_table   = self.mock_contacts_table
        parse_app._properties_table = self.mock_properties_table
        parse_app._links_table      = self.mock_links_table
        parse_app._s3               = self.mock_s3
        parse_app._bedrock          = self.mock_bedrock
        parse_app._model_id         = "us.amazon.nova-pro-v1:0"

        # Default: no pre-existing records to clear
        self.mock_contacts_table.query.return_value   = {"Items": []}
        self.mock_properties_table.query.return_value = {"Items": []}
        self.mock_links_table.query.return_value      = {"Items": []}
        self.mock_contacts_table.batch_writer.return_value.__enter__.return_value   = MagicMock()
        self.mock_contacts_table.batch_writer.return_value.__exit__.return_value    = False
        self.mock_properties_table.batch_writer.return_value.__enter__.return_value = MagicMock()
        self.mock_properties_table.batch_writer.return_value.__exit__.return_value  = False
        self.mock_links_table.batch_writer.return_value.__enter__.return_value      = MagicMock()
        self.mock_links_table.batch_writer.return_value.__exit__.return_value       = False

    # ── 404 — document not found ─────────────────────────────────────────────

    def test_document_not_found_returns_404(self):
        self.mock_documents_table.get_item.return_value = {"Item": None}
        body, status = parse_app.parse_document("99999999")
        self.assertEqual(status, 404)
        self.assertIn("not found", body["error"].lower())

    def test_document_missing_from_response_returns_404(self):
        self.mock_documents_table.get_item.return_value = {}
        body, status = parse_app.parse_document("99999999")
        self.assertEqual(status, 404)

    # ── 422 — no doc_s3_uri ─────────────────────────────────────────────────

    def test_no_doc_s3_uri_returns_422(self):
        doc = _make_document(doc_s3_uri="")
        self.mock_documents_table.get_item.return_value = {"Item": doc}
        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 422)
        self.assertIn("doc_s3_uri", body["error"])

    # ── 500 — S3 fetch fails ────────────────────────────────────────────────

    def test_s3_failure_returns_500_and_stores_parse_error(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.side_effect = Exception("NoSuchKey")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("S3 fetch failed", body["error"])

        # parse_error must be persisted on the documents table via update_item
        self.mock_documents_table.update_item.assert_called_once()
        call_kwargs = self.mock_documents_table.update_item.call_args.kwargs
        self.assertIn("NoSuchKey", call_kwargs["ExpressionAttributeValues"][":pe"])

    # ── 500 — Bedrock fails ─────────────────────────────────────────────────

    def test_bedrock_failure_returns_500_and_stores_parse_error(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.side_effect = Exception("ThrottlingException")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("Bedrock call failed", body["error"])
        self.mock_documents_table.update_item.assert_called_once()
        call_kwargs = self.mock_documents_table.update_item.call_args.kwargs
        self.assertIn("ThrottlingException", call_kwargs["ExpressionAttributeValues"][":pe"])

    # ── 500 — DynamoDB write fails (contacts/properties) ────────────────────

    def test_dynamodb_write_failure_returns_500(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)
        self.mock_contacts_table.put_item.side_effect = Exception("ProvisionedThroughputExceeded")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("DynamoDB write failed", body["error"])

    # ── 500 — DynamoDB update fails (documents status stamp) ─────────────────

    def test_dynamodb_update_failure_returns_500(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)
        self.mock_documents_table.update_item.side_effect = Exception("ProvisionedThroughputExceeded")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("DynamoDB update failed", body["error"])

    # ── 500 — clear fails ───────────────────────────────────────────────────

    def test_clear_failure_returns_500_and_stores_parse_error(self):
        """If _clear_existing raises, we return 500 and stamp parse_error."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)
        self.mock_contacts_table.query.side_effect = Exception("ServiceUnavailable")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("DynamoDB clear failed", body["error"])
        # parse_error must be persisted
        self.mock_documents_table.update_item.assert_called_once()
        call_kwargs = self.mock_documents_table.update_item.call_args.kwargs
        self.assertIn("ServiceUnavailable", call_kwargs["ExpressionAttributeValues"][":pe"])

    def test_clear_not_called_when_bedrock_fails(self):
        """Existing records must be preserved if Bedrock itself fails."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.side_effect = Exception("ThrottlingException")

        parse_app.parse_document("20240001")

        self.mock_contacts_table.query.assert_not_called()
        self.mock_properties_table.query.assert_not_called()
        self.mock_links_table.query.assert_not_called()

    # ── reparsing clears existing records ───────────────────────────────────

    def _setup_existing_records(self, contact_ids=("old-c-1",), property_ids=("old-p-1",), link_ids=()):
        """Configure mocks so the contacts/properties/links GSIs return existing records."""
        self.mock_contacts_table.query.return_value = {
            "Items": [{"contact_id": cid} for cid in contact_ids]
        }
        self.mock_properties_table.query.return_value = {
            "Items": [{"property_id": pid} for pid in property_ids]
        }
        self.mock_links_table.query.return_value = {
            "Items": [{"link_id": lid} for lid in link_ids]
        }
        # batch_writer() context manager
        self._mock_contact_batch   = MagicMock()
        self._mock_property_batch  = MagicMock()
        self._mock_link_batch      = MagicMock()
        self.mock_contacts_table.batch_writer.return_value.__enter__.return_value   = self._mock_contact_batch
        self.mock_contacts_table.batch_writer.return_value.__exit__.return_value    = False
        self.mock_properties_table.batch_writer.return_value.__enter__.return_value = self._mock_property_batch
        self.mock_properties_table.batch_writer.return_value.__exit__.return_value  = False
        self.mock_links_table.batch_writer.return_value.__enter__.return_value      = self._mock_link_batch
        self.mock_links_table.batch_writer.return_value.__exit__.return_value       = False

    def test_reparsing_deletes_existing_contacts(self):
        """Re-parse must delete all previously written contacts for the document."""
        self._setup_existing_records(contact_ids=["old-c-1", "old-c-2"])
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        delete_calls = self._mock_contact_batch.delete_item.call_args_list
        deleted_ids = {c.kwargs["Key"]["contact_id"] for c in delete_calls}
        self.assertEqual(deleted_ids, {"old-c-1", "old-c-2"})

    def test_reparsing_deletes_existing_properties(self):
        """Re-parse must delete all previously written properties for the document."""
        self._setup_existing_records(property_ids=["old-p-1", "old-p-2"])
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        delete_calls = self._mock_property_batch.delete_item.call_args_list
        deleted_ids = {c.kwargs["Key"]["property_id"] for c in delete_calls}
        self.assertEqual(deleted_ids, {"old-p-1", "old-p-2"})

    def test_reparsing_with_no_existing_records_succeeds(self):
        """First-time parse (no existing records) must still succeed cleanly."""
        # setUp already configures empty query returns + batch_writer mocks
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        self.assertEqual(body["contactsWritten"],   4)
        self.assertEqual(body["propertiesWritten"], 2)

    # ── 200 — happy path ────────────────────────────────────────────────────

    def test_happy_path_returns_200_with_counts(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        self.assertEqual(body["docNumber"],         "20240001")
        self.assertEqual(body["parseError"],        "")
        # 1 deceased + 3 people = 4 contacts; 2 real_property entries
        self.assertEqual(body["contactsWritten"],   4)
        self.assertEqual(body["propertiesWritten"], 2)

    def test_happy_path_writes_contacts_to_contacts_table(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        # 4 put_item calls: 1 deceased + 3 people
        self.assertEqual(self.mock_contacts_table.put_item.call_count, 4)
        self.mock_properties_table.put_item.assert_called()
        self.assertEqual(self.mock_properties_table.put_item.call_count, 2)

    def test_contact_parsed_snapshot_fields_written(self):
        """parsed_* fields must mirror the editable fields on first write."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        calls = self.mock_contacts_table.put_item.call_args_list
        # First call is the deceased contact
        deceased_item = calls[0].kwargs["Item"]
        self.assertEqual(deceased_item["role"],           "deceased")
        self.assertEqual(deceased_item["parsed_role"],    "deceased")
        self.assertEqual(deceased_item["name"],           "Jane A. Smith")
        self.assertEqual(deceased_item["parsed_name"],    "Jane A. Smith")
        self.assertEqual(deceased_item["dob"],            "1942-03-15")
        self.assertEqual(deceased_item["parsed_dob"],     "1942-03-15")
        self.assertEqual(deceased_item["dod"],            "2025-11-01")
        self.assertEqual(deceased_item["parsed_dod"],     "2025-11-01")
        self.assertEqual(deceased_item["address"],        "123 Main St, Plano, TX 75001")
        self.assertEqual(deceased_item["parsed_address"], "123 Main St, Plano, TX 75001")
        self.assertEqual(deceased_item["edited_at"],      "")

        # Second call is the executor (first people entry)
        executor_item = calls[1].kwargs["Item"]
        self.assertEqual(executor_item["role"],        "executor")
        self.assertEqual(executor_item["parsed_role"], "executor")
        self.assertEqual(executor_item["name"],        "Robert Smith")
        self.assertEqual(executor_item["parsed_name"], "Robert Smith")
        self.assertEqual(executor_item["edited_at"],   "")

    def test_property_structured_fields_written(self):
        """Structured real_property dicts are split into address + city/state/zip fields."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        calls = self.mock_properties_table.put_item.call_args_list
        # First property — has full address + city/state/zip from Bedrock
        p1 = calls[0].kwargs["Item"]
        self.assertEqual(p1["address"],           "123 Main St")
        self.assertEqual(p1["city"],              "Plano")
        self.assertEqual(p1["state"],             "TX")
        self.assertEqual(p1["zip"],               "75001")
        self.assertEqual(p1["parsed_address"],    "123 Main St")
        self.assertEqual(p1["parsed_city"],       "Plano")
        self.assertEqual(p1["parsed_state"],      "TX")
        self.assertEqual(p1["parsed_zip"],        "75001")
        self.assertTrue(p1["is_verified"])
        self.assertEqual(p1["edited_at"],         "")

        # Second property — legal description only; no address, city, state, zip
        p2 = calls[1].kwargs["Item"]
        self.assertEqual(p2["address"],           "")
        self.assertEqual(p2["legal_description"], "Lot 7, Block 3, Willow Creek Estates")
        self.assertEqual(p2["parsed_legal_description"], "Lot 7, Block 3, Willow Creek Estates")
        self.assertFalse(p2["is_verified"])

    def test_property_is_verified_false_for_legal_description_only(self):
        """A property with no street address must have is_verified=False."""
        payload = {**_GOOD_BEDROCK_PAYLOAD, "real_property": [
            {"address": None, "city": None, "state": None, "zip": None,
             "legal_description": "LOT 12 BLK 4 STAR CREEK ESTATES"}
        ]}
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(payload)

        parse_app.parse_document("20240001")

        item = self.mock_properties_table.put_item.call_args.kwargs["Item"]
        self.assertFalse(item["is_verified"])

    def test_property_legacy_string_format_handled(self):
        """Legacy flat string in real_property is still accepted without error."""
        payload = {**_GOOD_BEDROCK_PAYLOAD, "real_property": [
            "123 Main St, Plano, TX 75001"
        ]}
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(payload)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        self.assertEqual(body["propertiesWritten"], 1)
        item = self.mock_properties_table.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["address"], "123 Main St, Plano, TX 75001")

    def test_property_full_address_string_fallback(self):
        """When Bedrock can't split parts it returns the full string in address
        with city/state/zip null — the property must still be written."""
        payload = {**_GOOD_BEDROCK_PAYLOAD, "real_property": [
            {
                "address":           "6502 Star Creek, Frisco, TX 75034",
                "city":              None,
                "state":             None,
                "zip":               None,
                "legal_description": None,
            }
        ]}
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(payload)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        self.assertEqual(body["propertiesWritten"], 1)
        item = self.mock_properties_table.put_item.call_args.kwargs["Item"]
        # Full unsplit address must be stored as-is
        self.assertEqual(item["address"], "6502 Star Creek, Frisco, TX 75034")
        # parsed_* snapshot must reflect the raw Bedrock output (empty city/state/zip)
        self.assertEqual(item["parsed_city"],  "")
        self.assertEqual(item["parsed_state"], "")
        self.assertEqual(item["parsed_zip"],   "")

    def test_try_usaddress_returns_components_for_valid_address(self):
        """_try_usaddress extracts city/state/zip from a well-formed US address."""
        if not parse_app._USADDRESS_AVAILABLE:
            self.skipTest("usaddress not installed")
        city, state, zip_, ok = parse_app._try_usaddress(
            "6502 Star Creek Dr, Frisco, TX 75034"
        )
        self.assertEqual(city,  "Frisco")
        self.assertEqual(state, "TX")
        self.assertEqual(zip_,  "75034")
        self.assertTrue(ok)

    def test_try_usaddress_returns_empty_for_legal_description(self):
        """_try_usaddress returns falsy values for non-address strings."""
        if not parse_app._USADDRESS_AVAILABLE:
            self.skipTest("usaddress not installed")
        city, state, zip_, ok = parse_app._try_usaddress(
            "LOT 12 BLK 4 STAR CREEK ESTATES PHASE 2"
        )
        self.assertFalse(ok)

    def test_try_usaddress_returns_empty_when_unavailable(self):
        """When usaddress is not available the function returns empty strings."""
        original = parse_app._USADDRESS_AVAILABLE
        try:
            parse_app._USADDRESS_AVAILABLE = False
            city, state, zip_, ok = parse_app._try_usaddress("123 Main St, Plano, TX")
            self.assertEqual(city,  "")
            self.assertEqual(state, "")
            self.assertEqual(zip_,  "")
            self.assertFalse(ok)
        finally:
            parse_app._USADDRESS_AVAILABLE = original

    def test_happy_path_stamps_documents_table(self):
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        self.mock_documents_table.update_item.assert_called_once()
        call_kwargs = self.mock_documents_table.update_item.call_args.kwargs
        ev = call_kwargs["ExpressionAttributeValues"]
        self.assertEqual(ev[":pe"], "")  # no error on happy path
        self.assertIn(":pa", ev)         # parsed_at set
        self.assertIn(":pm", ev)         # parsed_model set

    # ── Markdown-fenced response ─────────────────────────────────────────────

    def test_fenced_json_response_is_parsed_correctly(self):
        fenced = f"```json\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}\n```"
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(fenced)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["contactsWritten"], 4)

    def test_preamble_prose_before_json_is_handled(self):
        """Model sometimes adds prose before the JSON — slice from first { to last }."""
        preamble = f"Here is the extracted information:\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}"
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(preamble)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["contactsWritten"], 4)

    def test_plain_fenced_block_no_language_tag(self):
        fenced = f"```\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}\n```"
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(fenced)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["contactsWritten"], 4)

    # ── S3 URI is forwarded correctly to boto3 ──────────────────────────────

    def test_s3_get_object_called_with_correct_bucket_and_key(self):
        doc = _make_document("s3://mybucket/documents/CollinTx/20240001.pdf")
        self.mock_documents_table.get_item.return_value = {"Item": doc}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        self.mock_s3.get_object.assert_called_once_with(
            Bucket="mybucket",
            Key="documents/CollinTx/20240001.pdf",
        )

    # ── Bedrock PDF bytes forwarded via document block ───────────────────────

    def test_pdf_bytes_forwarded_to_bedrock(self):
        pdf_content = b"%PDF-1.4 fake content"
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=pdf_content))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        converse_call = self.mock_bedrock.converse.call_args.kwargs
        doc_block = converse_call["messages"][0]["content"][0]["document"]
        self.assertEqual(doc_block["source"]["bytes"], pdf_content)
        self.assertEqual(doc_block["format"], "pdf")

    # ── Null fields from Bedrock are handled gracefully ──────────────────────

    def test_null_optional_fields_handled(self):
        # Bedrock returns None for optional fields and empty lists
        sparse_bedrock = {
            "deceased_name":         "Unknown Decedent",
            "deceased_dob":          None,
            "deceased_dod":          None,
            "deceased_last_address": None,
            "people":                [],
            "real_property":         [],
            "summary":               "A probate filing with minimal information.",
        }
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(sparse_bedrock)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        # 1 deceased contact, no people, no properties
        self.assertEqual(body["contactsWritten"],   1)
        self.assertEqual(body["propertiesWritten"], 0)

    # ── auto-link insertion ──────────────────────────────────────────────────

    def test_deceased_contact_inserts_legacy_link(self):
        """Parsing a deceased contact auto-inserts a Legacy.com search link."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        # At least one put_item call to links_table should be the Legacy.com link
        link_calls = self.mock_links_table.put_item.call_args_list
        legacy_calls = [
            c for c in link_calls
            if c.kwargs["Item"].get("link_type") == "legacy"
        ]
        self.assertEqual(len(legacy_calls), 1)
        item = legacy_calls[0].kwargs["Item"]
        self.assertEqual(item["link_type"],   "legacy")
        self.assertIn("legacy.com/search",    item["url"])
        self.assertIn("Jane",                 item["url"])  # URL-encoded name present
        self.assertEqual(item["parent_type"], "contact")
        self.assertEqual(item["document_id"], "20240001")  # document_id is the route arg

    def test_legacy_link_parent_id_matches_deceased_contact_id(self):
        """The Legacy.com link's parent_id must equal the deceased contact's contact_id."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        # The deceased contact is always the first put_item call to contacts_table
        deceased_contact_id = self.mock_contacts_table.put_item.call_args_list[0].kwargs["Item"]["contact_id"]
        link_calls = self.mock_links_table.put_item.call_args_list
        legacy_calls = [c for c in link_calls if c.kwargs["Item"].get("link_type") == "legacy"]
        self.assertEqual(len(legacy_calls), 1)
        self.assertEqual(legacy_calls[0].kwargs["Item"]["parent_id"], deceased_contact_id)

    def test_property_with_address_inserts_google_maps_link(self):
        """Parsing a property with an address auto-inserts a Google Maps search link."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        # _GOOD_BEDROCK_PAYLOAD has 2 real_property entries; only the first has an address
        link_calls = self.mock_links_table.put_item.call_args_list
        maps_calls = [
            c for c in link_calls
            if c.kwargs["Item"].get("link_type") == "google_maps"
        ]
        self.assertEqual(len(maps_calls), 1)
        item = maps_calls[0].kwargs["Item"]
        self.assertEqual(item["link_type"],   "google_maps")
        self.assertIn("google.com/maps",      item["url"])
        self.assertIn("123",                  item["url"])  # address present
        self.assertEqual(item["parent_type"], "property")
        self.assertEqual(item["document_id"], "20240001")  # document_id is the route arg

    def test_google_maps_link_parent_id_matches_property_id(self):
        """The Google Maps link's parent_id must equal the property's property_id."""
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        # The first property put_item call (has address) → its property_id should be parent_id
        first_property_id = self.mock_properties_table.put_item.call_args_list[0].kwargs["Item"]["property_id"]
        link_calls = self.mock_links_table.put_item.call_args_list
        maps_calls = [c for c in link_calls if c.kwargs["Item"].get("link_type") == "google_maps"]
        self.assertEqual(len(maps_calls), 1)
        self.assertEqual(maps_calls[0].kwargs["Item"]["parent_id"], first_property_id)

    def test_property_without_address_does_not_insert_maps_link(self):
        """A property with no address must NOT get a Google Maps link."""
        payload = {**_GOOD_BEDROCK_PAYLOAD, "real_property": [
            {"address": None, "city": None, "state": None, "zip": None,
             "legal_description": "Lot 7, Block 3, Willow Creek Estates"}
        ]}
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(payload)

        parse_app.parse_document("20240001")

        link_calls = self.mock_links_table.put_item.call_args_list
        maps_calls = [c for c in link_calls if c.kwargs["Item"].get("link_type") == "google_maps"]
        self.assertEqual(len(maps_calls), 0)

    def test_no_deceased_name_does_not_insert_legacy_link(self):
        """When the deceased name is empty no Legacy.com link should be inserted."""
        payload = {**_GOOD_BEDROCK_PAYLOAD, "deceased_name": None}
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(payload)

        parse_app.parse_document("20240001")

        link_calls = self.mock_links_table.put_item.call_args_list
        legacy_calls = [c for c in link_calls if c.kwargs["Item"].get("link_type") == "legacy"]
        self.assertEqual(len(legacy_calls), 0)

    def test_reparsing_deletes_existing_links(self):
        """Re-parse must delete all previously written links for the document."""
        self._setup_existing_records(link_ids=["old-l-1", "old-l-2"])
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        delete_calls = self._mock_link_batch.delete_item.call_args_list
        deleted_ids = {c.kwargs["Key"]["link_id"] for c in delete_calls}
        self.assertEqual(deleted_ids, {"old-l-1", "old-l-2"})

    def test_links_table_failure_is_non_fatal(self):
        """A failure writing to the links table must not abort the parse."""
        self.mock_links_table.put_item.side_effect = Exception("LinksTableError")
        self.mock_documents_table.get_item.return_value = {"Item": _make_document()}
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        # Contacts and properties must still be written successfully
        self.assertEqual(status, 200)
        self.assertEqual(body["contactsWritten"],   4)
        self.assertEqual(body["propertiesWritten"], 2)


# ---------------------------------------------------------------------------
# _capitalize_name
# ---------------------------------------------------------------------------

class TestCapitalizeName(unittest.TestCase):

    def test_all_caps_converted_to_title_case(self):
        self.assertEqual(parse_app._capitalize_name("JOHN SMITH"), "John Smith")

    def test_already_title_case_unchanged(self):
        self.assertEqual(parse_app._capitalize_name("Jane Doe"), "Jane Doe")

    def test_hyphenated_name(self):
        self.assertEqual(parse_app._capitalize_name("MARY-JANE WATSON"), "Mary-Jane Watson")

    def test_double_hyphen_name(self):
        self.assertEqual(parse_app._capitalize_name("ANNA-LOU-BETH JONES"), "Anna-Lou-Beth Jones")

    def test_name_with_apostrophe(self):
        self.assertEqual(parse_app._capitalize_name("O'BRIEN"), "O'Brien")

    def test_mixed_case_normalised(self):
        self.assertEqual(parse_app._capitalize_name("roBERT smiTH"), "Robert Smith")

    def test_single_word(self):
        self.assertEqual(parse_app._capitalize_name("ADMINISTRATOR"), "Administrator")

    def test_empty_string_returns_empty(self):
        self.assertEqual(parse_app._capitalize_name(""), "")

    def test_whitespace_preserved_between_words(self):
        result = parse_app._capitalize_name("  JOHN   DOE  ")
        # split/join normalises spacing
        self.assertIn("John", result)
        self.assertIn("Doe", result)


# ---------------------------------------------------------------------------
# _deduplicate_people
# ---------------------------------------------------------------------------

class TestDeduplicatePeople(unittest.TestCase):

    def test_no_duplicates_unchanged(self):
        people = [
            {"name": "Alice Jones",  "role": "executor"},
            {"name": "Bob Williams", "role": "heir"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 2)

    def test_duplicate_keeps_higher_priority_role(self):
        """When the same person has two roles, keep the higher-priority one."""
        people = [
            {"name": "John Smith", "role": "heir"},
            {"name": "John Smith", "role": "executor"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "executor")

    def test_lower_priority_role_appended_to_notes(self):
        people = [
            {"name": "John Smith", "role": "heir"},
            {"name": "John Smith", "role": "executor"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertIn("heir", result[0].get("notes", ""))

    def test_existing_notes_preserved_on_merge(self):
        people = [
            {"name": "John Smith", "role": "heir",     "notes": "see prior case"},
            {"name": "John Smith", "role": "executor", "notes": ""},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertIn("heir",           result[0]["notes"])
        self.assertIn("see prior case", result[0]["notes"])

    def test_case_insensitive_dedup(self):
        """JOHN SMITH and John Smith are the same person after normalisation."""
        people = [
            {"name": "JOHN SMITH", "role": "executor"},
            {"name": "john smith", "role": "heir"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 1)

    def test_extra_whitespace_normalised(self):
        people = [
            {"name": "Jane  Doe", "role": "heir"},
            {"name": "Jane Doe",  "role": "executor"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 1)

    def test_empty_name_skipped(self):
        people = [
            {"name": "",          "role": "heir"},
            {"name": "Bob Jones", "role": "executor"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Bob Jones")

    def test_three_roles_same_person(self):
        """Three entries for the same person collapse into one with all extras noted."""
        people = [
            {"name": "Carol Reed", "role": "beneficiary"},
            {"name": "Carol Reed", "role": "executor"},
            {"name": "Carol Reed", "role": "heir"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "executor")
        notes = result[0].get("notes", "")
        self.assertIn("beneficiary", notes)
        self.assertIn("heir", notes)

    def test_order_of_roles_does_not_matter(self):
        """Priority must be by _ROLE_PRIORITY, not by list position."""
        people = [
            {"name": "Dan White", "role": "attorney"},
            {"name": "Dan White", "role": "heir"},
        ]
        result = parse_app._deduplicate_people(people)
        self.assertEqual(result[0]["role"], "attorney")


if __name__ == "__main__":
    unittest.main()
