"""
Unit tests for src/api/app.py — subscribers endpoints.

  GET    /real-estate/probate-leads/subscribers
  POST   /real-estate/probate-leads/subscribers
  GET    /real-estate/probate-leads/subscribers/{subscriber_id}
  PATCH  /real-estate/probate-leads/subscribers/{subscriber_id}
  DELETE /real-estate/probate-leads/subscribers/{subscriber_id}
  POST   /real-estate/probate-leads/stripe/webhook

Run with:
    pipenv run python -m unittest tests.test_subscribers -v
"""

import copy
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
from tests.fixtures.locations  import COLLIN_TX
from tests.fixtures.subscribers import MOCK_SUBSCRIBERS, ALICE, BOB


def _body(resp):
    return json.loads(resp["body"])


def _call(method: str, path: str, path_params=None, body=None):
    event = {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params,
        "headers": {"x-api-key": "test-key", "Content-Type": "application/json"},
        "queryStringParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


BASE = "/real-estate/probate-leads/subscribers"


# ---------------------------------------------------------------------------
# Tests — GET /subscribers
# ---------------------------------------------------------------------------

class TestListSubscribers(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        db.subscribers_table = self.mock_sub_table
        # Return copies to avoid set mutation issues across tests
        self.mock_sub_table.scan.return_value = {"Items": [copy.deepcopy(s) for s in MOCK_SUBSCRIBERS]}

    def test_returns_200(self):
        resp = _call("GET", BASE)
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_subscribers_array(self):
        resp = _call("GET", BASE)
        body = _body(resp)
        self.assertEqual(body["count"], 2)
        self.assertIn("subscribers", body)

    def test_location_codes_are_lists_not_sets(self):
        resp = _call("GET", BASE)
        for sub in _body(resp)["subscribers"]:
            self.assertIsInstance(sub["locationCodes"], list)

    def test_dynamo_error_returns_500(self):
        self.mock_sub_table.scan.side_effect = Exception("DynamoDB unavailable")
        resp = _call("GET", BASE)
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# Tests — POST /subscribers
# ---------------------------------------------------------------------------

class TestCreateSubscriber(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        self.mock_loc_table = MagicMock()
        db.subscribers_table = self.mock_sub_table
        db.locations_table   = self.mock_loc_table
        self.mock_loc_table.get_item.return_value = {"Item": COLLIN_TX}
        self.mock_sub_table.put_item.return_value = {}

    def _create(self, body):
        return _call("POST", BASE, body=body)

    def test_returns_201_on_success(self):
        resp = self._create({"email": "test@example.com", "location_codes": ["CollinTx"]})
        self.assertEqual(resp["statusCode"], 201)

    def test_response_contains_subscriber(self):
        resp = self._create({"email": "test@example.com", "location_codes": ["CollinTx"]})
        sub = _body(resp)["subscriber"]
        self.assertEqual(sub["email"], "test@example.com")
        self.assertIn("subscriberId", sub)
        self.assertEqual(sub["status"], "active")

    def test_location_codes_validated(self):
        self.mock_loc_table.get_item.return_value = {}  # location not found
        resp = self._create({"email": "a@b.com", "location_codes": ["NoSuchPlace"]})
        self.assertEqual(resp["statusCode"], 422)

    def test_missing_email_returns_400(self):
        resp = self._create({"location_codes": ["CollinTx"]})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("email", _body(resp)["error"])

    def test_missing_location_codes_returns_400(self):
        resp = self._create({"email": "a@b.com"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("location_codes", _body(resp)["error"])

    def test_empty_location_codes_returns_400(self):
        resp = self._create({"email": "a@b.com", "location_codes": []})
        self.assertEqual(resp["statusCode"], 400)

    def test_accepts_optional_stripe_fields(self):
        resp = self._create({
            "email": "a@b.com",
            "location_codes": ["CollinTx"],
            "stripe_customer_id": "cus_abc",
            "stripe_subscription_id": "sub_xyz",
        })
        self.assertEqual(resp["statusCode"], 201)
        sub = _body(resp)["subscriber"]
        self.assertEqual(sub["stripeCustomerId"], "cus_abc")

    def test_dynamo_error_returns_500(self):
        self.mock_sub_table.put_item.side_effect = Exception("DynamoDB unavailable")
        resp = self._create({"email": "a@b.com", "location_codes": ["CollinTx"]})
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# Tests — GET /subscribers/{subscriber_id}
# ---------------------------------------------------------------------------

class TestGetSubscriber(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        db.subscribers_table = self.mock_sub_table

    def test_returns_200_for_existing_subscriber(self):
        self.mock_sub_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        resp = _call("GET", f"{BASE}/sub-uuid-001", {"subscriber_id": "sub-uuid-001"})
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_subscriber_object(self):
        self.mock_sub_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        resp = _call("GET", f"{BASE}/sub-uuid-001", {"subscriber_id": "sub-uuid-001"})
        sub = _body(resp)["subscriber"]
        self.assertEqual(sub["subscriberId"], "sub-uuid-001")
        self.assertEqual(sub["email"], "alice@example.com")

    def test_returns_404_for_missing_subscriber(self):
        self.mock_sub_table.get_item.return_value = {}
        resp = _call("GET", f"{BASE}/no-such-id", {"subscriber_id": "no-such-id"})
        self.assertEqual(resp["statusCode"], 404)


# ---------------------------------------------------------------------------
# Tests — PATCH /subscribers/{subscriber_id}
# ---------------------------------------------------------------------------

class TestUpdateSubscriber(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        self.mock_loc_table = MagicMock()
        db.subscribers_table = self.mock_sub_table
        db.locations_table   = self.mock_loc_table
        self.mock_sub_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        self.mock_loc_table.get_item.return_value = {"Item": COLLIN_TX}

        updated = copy.deepcopy(ALICE)
        updated["status"] = "inactive"
        self.mock_sub_table.update_item.return_value = {"Attributes": updated}

    def _patch(self, body):
        return _call("PATCH", f"{BASE}/sub-uuid-001", {"subscriber_id": "sub-uuid-001"}, body)

    def test_returns_200(self):
        resp = self._patch({"status": "inactive"})
        self.assertEqual(resp["statusCode"], 200)

    def test_invalid_status_returns_400(self):
        resp = self._patch({"status": "flying"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("status", _body(resp)["error"])

    def test_invalid_location_code_returns_422(self):
        self.mock_loc_table.get_item.return_value = {}
        resp = self._patch({"location_codes": ["NoSuchPlace"]})
        self.assertEqual(resp["statusCode"], 422)

    def test_not_found_returns_404(self):
        self.mock_sub_table.get_item.return_value = {}
        resp = self._patch({"status": "inactive"})
        self.assertEqual(resp["statusCode"], 404)


# ---------------------------------------------------------------------------
# Tests — DELETE /subscribers/{subscriber_id}
# ---------------------------------------------------------------------------

class TestDeleteSubscriber(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        db.subscribers_table = self.mock_sub_table
        self.mock_sub_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        deleted = copy.deepcopy(ALICE)
        deleted["status"] = "inactive"
        self.mock_sub_table.update_item.return_value = {"Attributes": deleted}

    def test_returns_200(self):
        resp = _call("DELETE", f"{BASE}/sub-uuid-001", {"subscriber_id": "sub-uuid-001"})
        self.assertEqual(resp["statusCode"], 200)

    def test_status_set_to_inactive(self):
        resp = _call("DELETE", f"{BASE}/sub-uuid-001", {"subscriber_id": "sub-uuid-001"})
        self.assertEqual(_body(resp)["subscriber"]["status"], "inactive")

    def test_not_found_returns_404(self):
        self.mock_sub_table.get_item.return_value = {}
        resp = _call("DELETE", f"{BASE}/no-such-id", {"subscriber_id": "no-such-id"})
        self.assertEqual(resp["statusCode"], 404)


# ---------------------------------------------------------------------------
# Tests — POST /stripe/webhook
# ---------------------------------------------------------------------------

WEBHOOK_PATH = "/real-estate/probate-leads/stripe/webhook"


class TestStripeWebhook(unittest.TestCase):

    def setUp(self):
        self.mock_sub_table = MagicMock()
        db.subscribers_table = self.mock_sub_table

    def _webhook(self, event_type: str, customer_id: str, stripe_status: str = "active"):
        """Helper to post a Stripe-style webhook event (no signature verification in tests)."""
        payload = {
            "type": event_type,
            "data": {
                "object": {
                    "id":       "sub_test",
                    "customer": customer_id,
                    "status":   stripe_status,
                }
            },
        }
        event = {
            "httpMethod": "POST",
            "path": WEBHOOK_PATH,
            "pathParameters": None,
            "headers": {
                "Content-Type": "application/json",
                "Stripe-Signature": "",  # empty → skips verification (no STRIPE_WEBHOOK_SECRET)
            },
            "queryStringParameters": None,
            "body": json.dumps(payload),
            "isBase64Encoded": False,
        }
        return app.handler(event, MockContext())

    def test_subscription_created_sets_active(self):
        self.mock_sub_table.scan.return_value = {"Items": [copy.deepcopy(ALICE)]}
        self.mock_sub_table.update_item.return_value = {}
        resp = self._webhook("customer.subscription.created", "cus_alice123")
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["subscriberId"], "sub-uuid-001")

    def test_subscription_deleted_sets_canceled(self):
        self.mock_sub_table.scan.return_value = {"Items": [copy.deepcopy(ALICE)]}
        self.mock_sub_table.update_item.return_value = {}
        resp = self._webhook("customer.subscription.deleted", "cus_alice123")
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["status"], "canceled")

    def test_payment_failed_sets_past_due(self):
        self.mock_sub_table.scan.return_value = {"Items": [copy.deepcopy(ALICE)]}
        self.mock_sub_table.update_item.return_value = {}
        resp = self._webhook("invoice.payment_failed", "cus_alice123")
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["status"], "past_due")

    def test_unknown_event_returns_ignored(self):
        resp = self._webhook("some.other.event", "cus_xyz")
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["action"], "ignored")

    def test_no_matching_subscriber_returns_200(self):
        self.mock_sub_table.scan.return_value = {"Items": []}
        resp = self._webhook("customer.subscription.updated", "cus_nobody")
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["action"], "no_subscriber_found")


if __name__ == "__main__":
    unittest.main()
