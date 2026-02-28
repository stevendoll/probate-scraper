"""
Unit tests for src/api/app.py — GET /{location_path}/leads route.

Run with:
    pipenv run python -m pytest tests/test_api.py -v
    pipenv run python -m unittest tests.test_api
"""

import base64
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap — set env vars and mock boto3 BEFORE importing the module
# ---------------------------------------------------------------------------
os.environ.update(
    {
        "AWS_ENDPOINT_URL":          "http://localhost:8000",
        "AWS_ACCESS_KEY_ID":         "local",
        "AWS_SECRET_ACCESS_KEY":     "local",
        "AWS_DEFAULT_REGION":        "us-east-1",
        "DYNAMO_TABLE_NAME":         "leads",
        "LOCATIONS_TABLE_NAME":      "locations",
        "USERS_TABLE_NAME":          "users",
        "GSI_NAME":                  "recorded-date-index",
        "LOCATION_DATE_GSI":         "location-date-index",
        "STRIPE_SECRET_KEY":         "",
        "STRIPE_WEBHOOK_SECRET":     "",
        "JWT_SECRET":                "test-secret",
        "FROM_EMAIL":                "",
        "MAGIC_LINK_BASE_URL":       "http://localhost:3000/auth/verify",
        "POWERTOOLS_TRACE_DISABLED": "true",
        "POWERTOOLS_SERVICE_NAME":   "probate-api-test",
        "LOG_LEVEL":                 "WARNING",
    }
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "api"))

_mock_tracer = MagicMock()
_mock_tracer.capture_lambda_handler = lambda f: f
_mock_tracer.capture_method = lambda f: f

with patch("boto3.resource", return_value=MagicMock()), \
     patch("aws_lambda_powertools.Tracer", return_value=_mock_tracer):
    import app  # noqa: E402
    import db   # noqa: E402


# ---------------------------------------------------------------------------
# Mock Lambda context
# ---------------------------------------------------------------------------
class MockContext:
    aws_request_id       = "test-request-id"
    function_name        = "probate-leads-api-test"
    memory_limit_in_mb   = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    log_stream_name      = "test-log-stream"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures.leads     import MOCK_LEADS, PAGINATION_KEY
from tests.fixtures.locations import COLLIN_TX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LOCATION_PATH = "collin-tx"


def _call(qs=None):
    """Invoke the Lambda handler for GET /{location_path}/leads."""
    event = {
        "httpMethod": "GET",
        "path": f"/real-estate/probate-leads/{LOCATION_PATH}/leads",
        "pathParameters": {"location_path": LOCATION_PATH},
        "headers": {"x-api-key": "test-key"},
        "queryStringParameters": qs or None,
        "body": None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


def _body(resp):
    return json.loads(resp["body"])


def _encoded_key(key: dict) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


# ---------------------------------------------------------------------------
# Tests — location resolved successfully
# ---------------------------------------------------------------------------
class TestHandlerDateRangeQuery(unittest.TestCase):
    """GSI query with both from_date and to_date."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table

        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        self.mock_table.query.return_value     = {"Items": MOCK_LEADS[:3]}

    def test_returns_200(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 200)

    def test_uses_location_date_gsi(self):
        _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.mock_table.query.assert_called_once()
        kwargs = self.mock_table.query.call_args[1]
        self.assertEqual(kwargs["IndexName"], "location-date-index")

    def test_returns_correct_count(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(_body(resp)["count"], 3)

    def test_returns_leads_array(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        leads = _body(resp)["leads"]
        self.assertEqual(len(leads), 3)
        self.assertEqual(leads[0]["leadId"],    MOCK_LEADS[0]["lead_id"])
        self.assertEqual(leads[0]["docNumber"], MOCK_LEADS[0]["doc_number"])

    def test_response_includes_location(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        loc = _body(resp)["location"]
        self.assertEqual(loc["locationCode"], "CollinTx")
        self.assertEqual(loc["locationPath"], "collin-tx")

    def test_query_metadata_in_response(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        query = _body(resp)["query"]
        self.assertEqual(query["fromDate"], "2026-01-01")
        self.assertEqual(query["toDate"], "2026-02-20")
        self.assertEqual(query["docType"], "PROBATE")
        self.assertEqual(query["locationPath"], LOCATION_PATH)

    def test_no_next_key_when_no_more_pages(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertIsNone(_body(resp)["nextKey"])

    def test_request_id_is_uuid(self):
        import re
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        request_id = _body(resp)["requestId"]
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        self.assertRegex(request_id, uuid_pattern)

    def test_timestamps_normalized(self):
        import re
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        leads = _body(resp)["leads"]
        ts_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
        for lead in leads:
            self.assertRegex(lead["extractedAt"], ts_pattern)
            self.assertRegex(lead["processedAt"], ts_pattern)

    def test_lead_includes_location_code(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        leads = _body(resp)["leads"]
        for lead in leads:
            self.assertEqual(lead["locationCode"], "CollinTx")


class TestHandlerLocationNotFound(unittest.TestCase):
    """Unknown location_path → 404."""

    def setUp(self):
        self.mock_loc_table = MagicMock()
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": []}

    def test_returns_404(self):
        event = {
            "httpMethod": "GET",
            "path": "/real-estate/probate-leads/unknown-county/leads",
            "pathParameters": {"location_path": "unknown-county"},
            "headers": {"x-api-key": "test-key"},
            "queryStringParameters": None,
            "body": None,
            "isBase64Encoded": False,
        }
        resp = app.handler(event, MockContext())
        self.assertEqual(resp["statusCode"], 404)
        self.assertIn("not found", _body(resp)["error"].lower())


class TestHandlerToDateOnly(unittest.TestCase):
    """GSI query with only to_date (no lower bound)."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        self.mock_table.query.return_value     = {"Items": MOCK_LEADS[:2]}

    def test_returns_200(self):
        resp = _call({"to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 200)

    def test_uses_query_not_scan(self):
        _call({"to_date": "2026-02-20"})
        self.mock_table.query.assert_called_once()
        self.mock_table.scan.assert_not_called()

    def test_from_date_is_none_in_response(self):
        resp = _call({"to_date": "2026-02-20"})
        self.assertIsNone(_body(resp)["query"]["fromDate"])


class TestHandlerNoDates(unittest.TestCase):
    """GSI query with no date params — returns most-recent leads."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        self.mock_table.query.return_value     = {"Items": MOCK_LEADS}

    def test_returns_200(self):
        resp = _call({})
        self.assertEqual(resp["statusCode"], 200)

    def test_uses_query_not_scan(self):
        _call({})
        self.mock_table.query.assert_called_once()
        self.mock_table.scan.assert_not_called()

    def test_sorted_descending(self):
        _call({})
        kwargs = self.mock_table.query.call_args[1]
        self.assertFalse(kwargs["ScanIndexForward"])

    def test_both_dates_none_in_response(self):
        resp = _call({})
        body = _body(resp)
        self.assertIsNone(body["query"]["fromDate"])
        self.assertIsNone(body["query"]["toDate"])


class TestHandlerLimit(unittest.TestCase):
    """Limit parameter handling."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        self.mock_table.query.return_value     = {"Items": []}

    def test_custom_limit_passed_to_dynamo(self):
        _call({"from_date": "2026-01-01", "to_date": "2026-02-20", "limit": "10"})
        kwargs = self.mock_table.query.call_args[1]
        self.assertEqual(kwargs["Limit"], 10)

    def test_limit_capped_at_200(self):
        _call({"from_date": "2026-01-01", "to_date": "2026-02-20", "limit": "999"})
        kwargs = self.mock_table.query.call_args[1]
        self.assertEqual(kwargs["Limit"], 200)

    def test_limit_minimum_is_1(self):
        _call({"from_date": "2026-01-01", "to_date": "2026-02-20", "limit": "-5"})
        kwargs = self.mock_table.query.call_args[1]
        self.assertEqual(kwargs["Limit"], 1)

    def test_invalid_limit_returns_400(self):
        resp = _call({"limit": "abc"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("limit", _body(resp)["error"])


class TestHandlerDateValidation(unittest.TestCase):
    """Date parameter validation."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}

    def test_invalid_from_date_returns_400(self):
        resp = _call({"from_date": "01-23-2026", "to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("from_date", _body(resp)["error"])

    def test_invalid_to_date_returns_400(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "20/02/2026"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("to_date", _body(resp)["error"])

    def test_valid_dates_accepted(self):
        self.mock_table.query.return_value = {"Items": []}
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 200)


class TestHandlerPagination(unittest.TestCase):
    """Cursor-based pagination."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}

    def test_next_key_present_when_more_pages(self):
        self.mock_table.query.return_value = {
            "Items": MOCK_LEADS[:2],
            "LastEvaluatedKey": PAGINATION_KEY,
        }
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertIsNotNone(_body(resp)["nextKey"])

    def test_next_key_is_base64_encoded(self):
        self.mock_table.query.return_value = {
            "Items": MOCK_LEADS[:2],
            "LastEvaluatedKey": PAGINATION_KEY,
        }
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        next_key = _body(resp)["nextKey"]
        decoded = json.loads(base64.b64decode(next_key.encode()).decode())
        self.assertEqual(decoded["lead_id"], PAGINATION_KEY["lead_id"])

    def test_last_key_passed_to_dynamo(self):
        self.mock_table.query.return_value = {"Items": MOCK_LEADS[2:]}
        encoded = _encoded_key(PAGINATION_KEY)
        _call({"from_date": "2026-01-01", "to_date": "2026-02-20", "last_key": encoded})
        kwargs = self.mock_table.query.call_args[1]
        self.assertIn("ExclusiveStartKey", kwargs)
        self.assertEqual(kwargs["ExclusiveStartKey"]["lead_id"], PAGINATION_KEY["lead_id"])

    def test_invalid_last_key_returns_400(self):
        resp = _call(
            {"from_date": "2026-01-01", "to_date": "2026-02-20", "last_key": "!!!invalid!!!"}
        )
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("last_key", _body(resp)["error"])


class TestHandlerDocType(unittest.TestCase):
    """Custom doc_type parameter."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        self.mock_table.query.return_value     = {"Items": []}

    def test_default_doc_type_is_probate(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(_body(resp)["query"]["docType"], "PROBATE")

    def test_custom_doc_type_reflected_in_response(self):
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20", "doc_type": "DEED"})
        self.assertEqual(_body(resp)["query"]["docType"], "DEED")


class TestHandlerErrors(unittest.TestCase):
    """DynamoDB error handling."""

    def setUp(self):
        self.mock_table     = MagicMock()
        self.mock_loc_table = MagicMock()
        db.table           = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}

    def test_dynamo_query_exception_returns_500(self):
        self.mock_table.query.side_effect = Exception("DynamoDB unavailable")
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 500)
        self.assertIn("error", _body(resp))

    def test_empty_results_returns_200(self):
        self.mock_table.query.return_value = {"Items": []}
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["leads"], [])
        self.assertIsNone(body["nextKey"])


class TestHelpers(unittest.TestCase):
    """Unit tests for pure helper functions."""

    def test_parse_date_valid(self):
        self.assertEqual(app._parse_date("2026-01-23"), "2026-01-23")

    def test_parse_date_invalid_format(self):
        self.assertIsNone(app._parse_date("01/23/2026"))

    def test_parse_date_empty(self):
        self.assertIsNone(app._parse_date(""))

    def test_parse_date_none(self):
        self.assertIsNone(app._parse_date(None))

    def test_encode_decode_key_roundtrip(self):
        original = {
            "doc_number": "123",
            "recorded_date": "2026-01-01",
            "location_code": "CollinTx",
        }
        encoded = app._encode_key(original)
        decoded = app._decode_key(encoded)
        self.assertEqual(decoded, original)

    def test_decode_key_invalid_returns_none(self):
        self.assertIsNone(app._decode_key("not-valid-base64!!!"))

    def test_transform_lead_camel_case(self):
        item = {
            "doc_number": "123",
            "recorded_date": "2026-01-01",
            "location_code": "CollinTx",
            "extracted_at": "2026-01-01T00:00:00",
            "processed_at": "2026-01-01T00:00:00",
        }
        result = app._transform_lead(item)
        self.assertIn("docNumber", result)
        self.assertIn("recordedDate", result)
        self.assertIn("locationCode", result)

    def test_transform_location_camel_case(self):
        result = app._transform_location(COLLIN_TX)
        self.assertEqual(result["locationCode"], "CollinTx")
        self.assertEqual(result["locationPath"], "collin-tx")
        self.assertEqual(result["locationName"], "Collin County TX")

    def test_transform_user_set_to_list(self):
        from tests.fixtures.users import ALICE
        result = app._transform_user(ALICE)
        self.assertIsInstance(result["locationCodes"], list)
        self.assertIn("userId", result)
        self.assertIn("CollinTx", result["locationCodes"])

    def test_response_structure(self):
        """Resolver returns a well-formed Lambda proxy response."""
        mock_table     = MagicMock()
        mock_loc_table = MagicMock()
        db.table           = mock_table
        db.locations_table = mock_loc_table
        mock_loc_table.query.return_value = {"Items": [COLLIN_TX]}
        mock_table.query.return_value     = {"Items": []}
        resp = _call({"from_date": "2026-01-01", "to_date": "2026-02-20"})
        self.assertIn("statusCode", resp)
        self.assertIn("body", resp)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIsInstance(json.loads(resp["body"]), dict)


if __name__ == "__main__":
    unittest.main()
