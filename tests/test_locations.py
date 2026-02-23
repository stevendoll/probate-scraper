"""
Unit tests for src/api/app.py — locations endpoints.

  GET  /real-estate/probate-leads/locations
  GET  /real-estate/probate-leads/locations/{location_code}

Run with:
    pipenv run python -m unittest tests.test_locations -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
os.environ.update(
    {
        "AWS_ENDPOINT_URL":          "http://localhost:8000",
        "AWS_ACCESS_KEY_ID":         "local",
        "AWS_SECRET_ACCESS_KEY":     "local",
        "AWS_DEFAULT_REGION":        "us-east-1",
        "DYNAMO_TABLE_NAME":         "leads",
        "LOCATIONS_TABLE_NAME":      "locations",
        "SUBSCRIBERS_TABLE_NAME":    "subscribers",
        "GSI_NAME":                  "recorded-date-index",
        "LOCATION_DATE_GSI":         "location-date-index",
        "STRIPE_SECRET_KEY":         "",
        "STRIPE_WEBHOOK_SECRET":     "",
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


class MockContext:
    aws_request_id       = "test-request-id"
    function_name        = "probate-leads-api-test"
    memory_limit_in_mb   = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    log_stream_name      = "test-log-stream"


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures.locations import MOCK_LOCATIONS, COLLIN_TX


def _body(resp):
    return json.loads(resp["body"])


def _call_list():
    event = {
        "httpMethod": "GET",
        "path": "/real-estate/probate-leads/locations",
        "pathParameters": None,
        "headers": {"x-api-key": "test-key"},
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


def _call_get(location_code: str):
    event = {
        "httpMethod": "GET",
        "path": f"/real-estate/probate-leads/locations/{location_code}",
        "pathParameters": {"location_code": location_code},
        "headers": {"x-api-key": "test-key"},
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


# ---------------------------------------------------------------------------
# Tests — GET /locations
# ---------------------------------------------------------------------------

class TestListLocations(unittest.TestCase):

    def setUp(self):
        self.mock_loc_table = MagicMock()
        db.locations_table = self.mock_loc_table
        self.mock_loc_table.scan.return_value = {"Items": MOCK_LOCATIONS}

    def test_returns_200(self):
        resp = _call_list()
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_locations_array(self):
        resp = _call_list()
        body = _body(resp)
        self.assertIn("locations", body)
        self.assertEqual(body["count"], 2)

    def test_locations_are_camel_case(self):
        resp = _call_list()
        loc = _body(resp)["locations"][0]
        self.assertIn("locationCode", loc)
        self.assertIn("locationPath", loc)
        self.assertIn("locationName", loc)
        self.assertIn("searchUrl", loc)

    def test_locations_sorted_by_name(self):
        resp = _call_list()
        names = [loc["locationName"] for loc in _body(resp)["locations"]]
        self.assertEqual(names, sorted(names))

    def test_includes_request_id(self):
        resp = _call_list()
        self.assertIn("requestId", _body(resp))

    def test_dynamo_error_returns_500(self):
        self.mock_loc_table.scan.side_effect = Exception("DynamoDB unavailable")
        resp = _call_list()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# Tests — GET /locations/{location_code}
# ---------------------------------------------------------------------------

class TestGetLocation(unittest.TestCase):

    def setUp(self):
        self.mock_loc_table = MagicMock()
        db.locations_table = self.mock_loc_table

    def test_returns_200_for_existing_location(self):
        self.mock_loc_table.get_item.return_value = {"Item": COLLIN_TX}
        resp = _call_get("CollinTx")
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_location_object(self):
        self.mock_loc_table.get_item.return_value = {"Item": COLLIN_TX}
        resp = _call_get("CollinTx")
        loc = _body(resp)["location"]
        self.assertEqual(loc["locationCode"], "CollinTx")
        self.assertEqual(loc["locationPath"], "collin-tx")
        self.assertEqual(loc["locationName"], "Collin County TX")
        self.assertEqual(loc["searchUrl"], "https://collin.tx.publicsearch.us")

    def test_returns_404_for_missing_location(self):
        self.mock_loc_table.get_item.return_value = {}
        resp = _call_get("UnknownTx")
        self.assertEqual(resp["statusCode"], 404)
        self.assertIn("not found", _body(resp)["error"].lower())

    def test_dynamo_error_returns_500(self):
        self.mock_loc_table.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _call_get("CollinTx")
        self.assertEqual(resp["statusCode"], 500)


if __name__ == "__main__":
    unittest.main()
