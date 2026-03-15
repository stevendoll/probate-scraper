"""
Unit tests for the event_dashboard and feedback routers.

Covers:
  - GET  /admin/events             (admin Bearer — list all events)
  - GET  /admin/events/dashboard   (admin Bearer — aggregated metrics)
  - POST /feedback                 (public)
  - 403 for non-admin on admin routes
  - Funnel aggregation logic and conversion rates
  - dashboard scan produces correct funnel order and user_statuses

Run with:
    pipenv run python -m unittest tests.test_event_dashboard -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap — env vars before any imports
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
        "EVENTS_TABLE_NAME":         "events",
        "GSI_NAME":                  "recorded-date-index",
        "LOCATION_DATE_GSI":         "location-date-index",
        "USER_EVENT_GSI":            "user-event-index",
        "STRIPE_SECRET_KEY":         "",
        "STRIPE_WEBHOOK_SECRET":     "",
        "JWT_SECRET":                "test-secret-for-unit-tests",
        "FROM_EMAIL":                "",
        "ADMIN_EMAIL":               "",
        "MAGIC_LINK_BASE_URL":       "http://localhost:3000/auth/verify",
        "UI_BASE_URL":               "http://localhost:3001",
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
    import app          # noqa: E402
    import db           # noqa: E402
    import auth_helpers  # noqa: E402


class MockContext:
    aws_request_id       = "test-request-id"
    function_name        = "probate-leads-api-test"
    memory_limit_in_mb   = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    log_stream_name      = "test-log-stream"


def _body(resp):
    return json.loads(resp["body"])


def _call(method: str, path: str, body=None, headers=None, query_params=None):
    base_headers = {"Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)
    event = {
        "httpMethod":            method,
        "path":                  path,
        "pathParameters":        None,
        "headers":               base_headers,
        "queryStringParameters": query_params,
        "requestContext":        {"identity": {"sourceIp": "1.2.3.4"}},
        "body":                  json.dumps(body) if body is not None else None,
        "isBase64Encoded":       False,
    }
    return app.handler(event, MockContext())


def _admin_bearer() -> dict:
    token = auth_helpers.create_access_token("admin-id", "admin")
    return {"Authorization": f"Bearer {token}"}


def _user_bearer() -> dict:
    token = auth_helpers.create_access_token("user-id", "user")
    return {"Authorization": f"Bearer {token}"}


BASE              = "/real-estate/probate-leads"
EVENTS_PATH       = f"{BASE}/admin/events"
DASHBOARD_PATH    = f"{BASE}/admin/events/dashboard"
FEEDBACK_PATH     = f"{BASE}/feedback"

MOCK_EVENTS = [
    {
        "event_id":   "evt-001",
        "user_id":    "user-abc",
        "event_type": "email_sent",
        "timestamp":  "2026-03-01T10:00:00+00:00",
        "variant":    "",
        "metadata":   {},
    },
    {
        "event_id":   "evt-002",
        "user_id":    "user-abc",
        "event_type": "email_open",
        "timestamp":  "2026-03-01T11:00:00+00:00",
        "variant":    "",
        "metadata":   {},
    },
    {
        "event_id":   "evt-003",
        "user_id":    "user-abc",
        "event_type": "signup_completed",
        "timestamp":  "2026-03-02T08:00:00+00:00",
        "variant":    "",
        "metadata":   {},
    },
]

MOCK_USERS = [
    {"user_id": "user-abc", "email": "abc@test.com", "status": "active"},
    {"user_id": "user-def", "email": "def@test.com", "status": "prospect"},
    {"user_id": "user-ghi", "email": "ghi@test.com", "status": "prospect"},
]


# ---------------------------------------------------------------------------
# GET /admin/events
# ---------------------------------------------------------------------------

class TestAdminListEvents(unittest.TestCase):

    def setUp(self):
        self.mock_events = MagicMock()
        db.events_table  = self.mock_events

    def test_403_for_non_admin(self):
        resp = _call("GET", EVENTS_PATH, headers=_user_bearer())
        self.assertEqual(resp["statusCode"], 403)

    def test_403_for_unauthenticated(self):
        resp = _call("GET", EVENTS_PATH)
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_events_scan(self):
        self.mock_events.scan.return_value = {"Items": MOCK_EVENTS}
        resp = _call("GET", EVENTS_PATH, headers=_admin_bearer())
        self.assertEqual(resp["statusCode"], 200)
        data = _body(resp)
        self.assertIn("events", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], len(MOCK_EVENTS))

    def test_returns_events_query_by_user_id(self):
        self.mock_events.query.return_value = {"Items": [MOCK_EVENTS[0]]}
        resp = _call(
            "GET", EVENTS_PATH,
            headers=_admin_bearer(),
            query_params={"user_id": "user-abc"},
        )
        self.assertEqual(resp["statusCode"], 200)
        data = _body(resp)
        self.assertEqual(data["count"], 1)
        # query should have been used, not scan
        self.mock_events.query.assert_called_once()

    def test_invalid_limit_returns_400(self):
        resp = _call(
            "GET", EVENTS_PATH,
            headers=_admin_bearer(),
            query_params={"limit": "not-a-number"},
        )
        self.assertEqual(resp["statusCode"], 400)


# ---------------------------------------------------------------------------
# GET /admin/events/dashboard
# ---------------------------------------------------------------------------

class TestAdminEventsDashboard(unittest.TestCase):

    def setUp(self):
        self.mock_events = MagicMock()
        self.mock_users  = MagicMock()
        db.events_table  = self.mock_events
        db.users_table   = self.mock_users

    def _setup_mocks(self, events=None, users=None):
        evts = events if events is not None else MOCK_EVENTS
        usrs = users  if users  is not None else MOCK_USERS
        self.mock_events.scan.return_value = {"Items": evts}
        self.mock_users.scan.return_value  = {"Items": usrs}

    def test_403_for_non_admin(self):
        resp = _call("GET", DASHBOARD_PATH, headers=_user_bearer())
        self.assertEqual(resp["statusCode"], 403)

    def test_403_for_unauthenticated(self):
        resp = _call("GET", DASHBOARD_PATH)
        self.assertEqual(resp["statusCode"], 403)

    def test_dashboard_structure(self):
        self._setup_mocks()
        resp = _call("GET", DASHBOARD_PATH, headers=_admin_bearer())
        self.assertEqual(resp["statusCode"], 200)
        data = _body(resp)
        self.assertIn("dashboard", data)
        dash = data["dashboard"]
        self.assertIn("funnel", dash)
        self.assertIn("weekly", dash)
        self.assertIn("user_statuses", dash)
        self.assertIn("recent_conversions", dash)

    def test_funnel_order_matches_canonical_steps(self):
        """Funnel steps must appear in the canonical order defined in event_dashboard.py."""
        self._setup_mocks()
        resp = _call("GET", DASHBOARD_PATH, headers=_admin_bearer())
        funnel = _body(resp)["dashboard"]["funnel"]
        expected_order = [
            "email_sent",
            "email_open",
            "link_clicked",
            "subscribe_clicked",
            "signup_completed",
        ]
        actual_order = [s["event_type"] for s in funnel]
        self.assertEqual(actual_order, expected_order)

    def test_funnel_conversion_rates(self):
        """email_sent=2, email_open=1 → open rate = 50%; signup_completed=0 → 0%"""
        events = [
            {"event_id": "e1", "user_id": "u1", "event_type": "email_sent",
             "timestamp": "2026-03-01T10:00:00+00:00", "metadata": {}},
            {"event_id": "e2", "user_id": "u1", "event_type": "email_sent",
             "timestamp": "2026-03-01T10:01:00+00:00", "metadata": {}},
            {"event_id": "e3", "user_id": "u1", "event_type": "email_open",
             "timestamp": "2026-03-01T11:00:00+00:00", "metadata": {}},
        ]
        self._setup_mocks(events=events)
        resp = _call("GET", DASHBOARD_PATH, headers=_admin_bearer())
        funnel = _body(resp)["dashboard"]["funnel"]
        by_type = {s["event_type"]: s for s in funnel}

        self.assertEqual(by_type["email_sent"]["count"], 2)
        self.assertEqual(by_type["email_sent"]["conversion_rate"], 100.0)
        self.assertEqual(by_type["email_open"]["count"], 1)
        self.assertEqual(by_type["email_open"]["conversion_rate"], 50.0)
        self.assertEqual(by_type["signup_completed"]["count"], 0)
        self.assertEqual(by_type["signup_completed"]["conversion_rate"], 0.0)

    def test_user_statuses_aggregated(self):
        """user_statuses counts match mock users: {active: 1, prospect: 2}"""
        self._setup_mocks()
        resp  = _call("GET", DASHBOARD_PATH, headers=_admin_bearer())
        stats = _body(resp)["dashboard"]["user_statuses"]
        self.assertEqual(stats.get("active"),  1)
        self.assertEqual(stats.get("prospect"), 2)

    def test_recent_conversions_from_signup_completed(self):
        """signup_completed events appear in recent_conversions."""
        self._setup_mocks()
        resp        = _call("GET", DASHBOARD_PATH, headers=_admin_bearer())
        conversions = _body(resp)["dashboard"]["recent_conversions"]
        self.assertEqual(len(conversions), 1)
        self.assertEqual(conversions[0]["user_id"], "user-abc")

    def test_invalid_weeks_returns_400(self):
        resp = _call(
            "GET", DASHBOARD_PATH,
            headers=_admin_bearer(),
            query_params={"weeks": "bad"},
        )
        self.assertEqual(resp["statusCode"], 400)


# ---------------------------------------------------------------------------
# POST /feedback
# ---------------------------------------------------------------------------

class TestPostFeedback(unittest.TestCase):

    def setUp(self):
        self.mock_events = MagicMock()
        self.mock_users  = MagicMock()
        db.events_table  = self.mock_events
        db.users_table   = self.mock_users
        # Default: email lookup finds nothing
        self.mock_users.query.return_value = {"Items": []}

    def _post(self, body):
        return _call("POST", FEEDBACK_PATH, body=body)

    def test_missing_message_returns_400(self):
        resp = self._post({"source": "test"})
        self.assertEqual(resp["statusCode"], 400)

    def test_empty_message_returns_400(self):
        resp = self._post({"message": "   ", "source": "test"})
        self.assertEqual(resp["statusCode"], 400)

    def test_valid_feedback_returns_ok(self):
        resp = self._post({"message": "Great product!", "source": "test-page"})
        self.assertEqual(resp["statusCode"], 200)
        data = _body(resp)
        self.assertEqual(data["status"], "ok")

    def test_feedback_stores_event(self):
        self._post({"message": "Nice!", "source": "test-page"})
        self.mock_events.put_item.assert_called_once()
        call_args = self.mock_events.put_item.call_args[1]["Item"]
        self.assertEqual(call_args["event_type"], "feedback")
        self.assertEqual(call_args["metadata"]["source"], "test-page")

    def test_no_auth_required(self):
        """Feedback endpoint works without any authentication header."""
        resp = _call("POST", FEEDBACK_PATH, body={"message": "Hello", "source": "test"})
        self.assertEqual(resp["statusCode"], 200)


# ---------------------------------------------------------------------------
# Stripe webhook status fixes
# ---------------------------------------------------------------------------

class TestStripeWebhookStatusFixes(unittest.TestCase):
    """
    Verify the two Stripe webhook gaps are closed:
      1. checkout.session.completed sets status=pending
      2. customer.subscription.created stores stripe_subscription_id
    """

    def setUp(self):
        self.mock_users  = MagicMock()
        db.users_table   = self.mock_users
        # scan returns a user with existing stripe_customer_id
        self.mock_users.scan.return_value = {
            "Items": [{"user_id": "user-xyz", "email": "x@y.com"}]
        }

    def _webhook(self, event_type: str, data_object: dict):
        body = json.dumps({"type": event_type, "data": {"object": data_object}})
        return _call(
            "POST",
            "/real-estate/probate-leads/stripe/webhook",
            body=json.loads(body),   # _call will re-encode it
            headers={"Stripe-Signature": ""},
        )

    def test_checkout_completed_sets_pending_status(self):
        resp = self._webhook(
            "checkout.session.completed",
            {
                "client_reference_id": "user-xyz",
                "customer": "cus_test123",
            },
        )
        self.assertEqual(resp["statusCode"], 200)
        update_call = self.mock_users.update_item.call_args
        expr  = update_call[1]["UpdateExpression"]
        values = update_call[1]["ExpressionAttributeValues"]
        self.assertIn(":status", values)
        self.assertEqual(values[":status"], "pending")
        self.assertIn("stripe_customer_id", expr)

    def test_subscription_created_stores_subscription_id(self):
        resp = self._webhook(
            "customer.subscription.created",
            {
                "id":       "sub_abc123",
                "customer": "cus_test123",
                "status":   "active",
            },
        )
        self.assertEqual(resp["statusCode"], 200)
        update_call = self.mock_users.update_item.call_args
        values = update_call[1]["ExpressionAttributeValues"]
        self.assertIn(":sub_id", values)
        self.assertEqual(values[":sub_id"], "sub_abc123")
        self.assertEqual(values[":status"], "active")


if __name__ == "__main__":
    unittest.main()
