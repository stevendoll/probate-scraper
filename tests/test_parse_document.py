"""
Unit tests for src/parse_document/app.py

Covers:
  - Happy path: S3 + Bedrock succeed → fields persisted, 200 returned
  - Lead not found → 404
  - Lead has no doc_s3_uri → 422
  - S3 fetch fails → parse_error stored, 500 returned
  - Bedrock call fails → parse_error stored, 500 returned
  - DynamoDB update fails → 500 returned
  - Markdown-fenced JSON response is handled correctly
  - _s3_uri_to_bucket_key parses correctly
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

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
        "123 Main St, Plano, TX 75001",
        "Lot 7, Block 3, Willow Creek Estates",
    ],
    "summary": (
        "This probate petition was filed on behalf of the estate of Jane A. Smith, "
        "who died on 1 November 2025 in Collin County, Texas. Her son Robert Smith "
        "is named independent executor. Two heirs and one attorney are listed. The "
        "estate includes the decedent's primary residence and one additional parcel."
    ),
}


def _make_lead(doc_s3_uri: str = "s3://mybucket/documents/CollinTx/20240001.pdf") -> dict:
    return {
        "doc_number": "20240001",
        "grantor":    "Smith, Jane A.",
        "doc_s3_uri": doc_s3_uri,
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
        self.mock_table   = MagicMock()
        self.mock_s3      = MagicMock()
        self.mock_bedrock = MagicMock()

        parse_app._table    = self.mock_table
        parse_app._s3       = self.mock_s3
        parse_app._bedrock  = self.mock_bedrock
        parse_app._model_id = "us.amazon.nova-pro-v1:0"

    # ── 404 — lead not found ────────────────────────────────────────────────

    def test_lead_not_found_returns_404(self):
        self.mock_table.get_item.return_value = {"Item": None}
        body, status = parse_app.parse_document("99999999")
        self.assertEqual(status, 404)
        self.assertIn("not found", body["error"].lower())

    def test_lead_missing_from_response_returns_404(self):
        self.mock_table.get_item.return_value = {}
        body, status = parse_app.parse_document("99999999")
        self.assertEqual(status, 404)

    # ── 422 — no doc_s3_uri ─────────────────────────────────────────────────

    def test_no_doc_s3_uri_returns_422(self):
        lead = _make_lead(doc_s3_uri="")
        self.mock_table.get_item.return_value = {"Item": lead}
        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 422)
        self.assertIn("doc_s3_uri", body["error"])

    # ── 500 — S3 fetch fails ────────────────────────────────────────────────

    def test_s3_failure_returns_500_and_stores_parse_error(self):
        self.mock_table.get_item.return_value = {"Item": _make_lead()}
        self.mock_s3.get_object.side_effect = Exception("NoSuchKey")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("S3 fetch failed", body["error"])

        # parse_error must be persisted via update_item
        self.mock_table.update_item.assert_called_once()
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        self.assertIn("NoSuchKey", call_kwargs["ExpressionAttributeValues"][":pe"])

    # ── 500 — Bedrock fails ─────────────────────────────────────────────────

    def test_bedrock_failure_returns_500_and_stores_parse_error(self):
        self.mock_table.get_item.return_value = {"Item": _make_lead()}
        self.mock_s3.get_object.return_value  = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.side_effect = Exception("ThrottlingException")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("Bedrock call failed", body["error"])
        self.mock_table.update_item.assert_called_once()
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        self.assertIn("ThrottlingException", call_kwargs["ExpressionAttributeValues"][":pe"])

    # ── 500 — DynamoDB update fails ─────────────────────────────────────────

    def test_dynamodb_update_failure_returns_500(self):
        self.mock_table.get_item.return_value = {"Item": _make_lead()}
        self.mock_s3.get_object.return_value  = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)
        self.mock_table.update_item.side_effect = Exception("ProvisionedThroughputExceeded")

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 500)
        self.assertIn("DynamoDB update failed", body["error"])

    # ── 200 — happy path ────────────────────────────────────────────────────

    def test_happy_path_returns_200_with_parsed_fields(self):
        lead = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},                           # first call (fetch lead)
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,  # second call (re-fetch after update)
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        body, status = parse_app.parse_document("20240001")

        self.assertEqual(status, 200)
        self.assertEqual(body["deceasedName"], "Jane A. Smith")
        self.assertEqual(body["deceasedDob"],  "1942-03-15")
        self.assertEqual(body["deceasedDod"],  "2025-11-01")
        self.assertEqual(body["deceasedLastAddress"], "123 Main St, Plano, TX 75001")
        self.assertEqual(len(body["people"]),       3)
        self.assertEqual(len(body["realProperty"]), 2)
        self.assertIn("Jane A. Smith", body["summary"])
        self.assertEqual(body["parseError"], "")

    def test_happy_path_persists_correct_update_expression(self):
        lead = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(_GOOD_BEDROCK_PAYLOAD)

        parse_app.parse_document("20240001")

        self.mock_table.update_item.assert_called_once()
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        ev = call_kwargs["ExpressionAttributeValues"]
        self.assertEqual(ev[":dn"], "Jane A. Smith")
        self.assertEqual(ev[":pe"], "")   # no error on happy path
        self.assertEqual(len(ev[":pp"]), 3)
        self.assertEqual(len(ev[":rp"]), 2)

    # ── Markdown-fenced response ─────────────────────────────────────────────

    def test_fenced_json_response_is_parsed_correctly(self):
        fenced = f"```json\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}\n```"
        lead   = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(fenced)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["deceasedName"], "Jane A. Smith")

    def test_preamble_prose_before_json_is_handled(self):
        """Model sometimes adds prose before the JSON — slice from first { to last }."""
        preamble = f"Here is the extracted information:\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}"
        lead     = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(preamble)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["deceasedName"], "Jane A. Smith")

    def test_plain_fenced_block_no_language_tag(self):
        fenced = f"```\n{json.dumps(_GOOD_BEDROCK_PAYLOAD)}\n```"
        lead   = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(fenced)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["deceasedName"], "Jane A. Smith")

    # ── S3 URI is forwarded correctly to boto3 ──────────────────────────────

    def test_s3_get_object_called_with_correct_bucket_and_key(self):
        lead = _make_lead("s3://mybucket/documents/CollinTx/20240001.pdf")
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
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
        lead = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **_GOOD_BEDROCK_PAYLOAD,
                      "parsed_at": "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error": ""}},
        ]
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
        # Bedrock returns None for optional fields
        sparse_bedrock = {
            "deceased_name":         "Unknown Decedent",
            "deceased_dob":          None,
            "deceased_dod":          None,
            "deceased_last_address": None,
            "people":                [],
            "real_property":         [],
            "summary":               "A probate filing with minimal information.",
        }
        # _persist_parsed_fields coerces None → ""; the re-fetched DynamoDB item
        # reflects the persisted (coerced) values, not the raw Bedrock payload.
        stored = {
            "deceased_name":         "Unknown Decedent",
            "deceased_dob":          "",
            "deceased_dod":          "",
            "deceased_last_address": "",
            "people":                [],
            "real_property":         [],
            "summary":               "A probate filing with minimal information.",
        }
        lead = _make_lead()
        self.mock_table.get_item.side_effect = [
            {"Item": lead},
            {"Item": {**lead, **stored,
                      "parsed_at":    "2026-02-26T00:00:00+00:00",
                      "parsed_model": parse_app._model_id,
                      "parse_error":  ""}},
        ]
        self.mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"%PDF fake"))
        }
        self.mock_bedrock.converse.return_value = _bedrock_response(sparse_bedrock)

        body, status = parse_app.parse_document("20240001")
        self.assertEqual(status, 200)
        self.assertEqual(body["deceasedDob"], "")   # None coerced → "" by persist helper
        self.assertEqual(body["people"],      [])
        self.assertEqual(body["realProperty"], [])


if __name__ == "__main__":
    unittest.main()
