"""
Unit tests for the activity tracking router.

Covers:
  - POST /admin/activity/log
  - POST /admin/activity/query
  - POST /activity/track

Run with:
    pipenv run python -m unittest tests.test_activity -v
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
        "ACTIVITIES_TABLE_NAME":     "activities",
        "GSI_NAME":                  "recorded-date-index",
        "LOCATION_DATE_GSI":         "location-date-index",
        "USER_ACTIVITY_GSI":         "user-activity-index",
        "STRIPE_SECRET_KEY":         "",
        "STRIPE_WEBHOOK_SECRET":     "",
        "JWT_SECRET":                "test-secret-for-unit-tests",
        "FROM_EMAIL":                "",
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


def _call(method: str, path: str, body=None, headers=None):
    base_headers = {"Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)
    event = {
        "httpMethod":            method,
        "path":                  path,
        "pathParameters":        None,
        "headers":               base_headers,
        "queryStringParameters": None,
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


BASE = "/real-estate/probate-leads"

MOCK_ACTIVITY = {
    "activity_id":   "act-001",
    "user_id":       "user-abc",
    "activity_type": "email_sent",
    "timestamp":     "2026-03-05T12:00:00+00:00",
    "email_template": "prospect_email_v1.html",
    "from_name":     "Jane Smith",
    "subject_line":  "Your leads",
    "funnel_token":  "tok.abc.xyz",
    "metadata":      {"to_email": "x@y.com", "price": 39},
}


# ---------------------------------------------------------------------------
# POST /admin/activity/log
# ---------------------------------------------------------------------------

LOG_PATH = f"{BASE}/admin/activity/log"


class TestAdminActivityLog(unittest.TestCase):

    def setUp(self):
        self.mock_activities = MagicMock()
        db.activities_table  = self.mock_activities

    def _post(self, body, headers=None):
        h = _admin_bearer()
        if headers:
            h.update(headers)
        return _call("POST", LOG_PATH, body=body, headers=h)

    def test_no_auth_returns_401(self):
        resp = _call("POST", LOG_PATH, body={"user_id": "u1", "activity_type": "email_sent"})
        self.assertEqual(resp["statusCode"], 401)

    def test_non_admin_returns_403(self):
        resp = _call("POST", LOG_PATH,
                     body={"user_id": "u1", "activity_type": "email_sent"},
                     headers=_user_bearer())
        self.assertEqual(resp["statusCode"], 403)

    def test_missing_user_id_returns_400(self):
        resp = self._post({"activity_type": "email_sent"})
        self.assertEqual(resp["statusCode"], 400)

    def test_missing_activity_type_returns_400(self):
        resp = self._post({"user_id": "u1"})
        self.assertEqual(resp["statusCode"], 400)

    def test_success_returns_200_with_activity_id(self):
        resp = self._post({"user_id": "u1", "activity_type": "email_sent"})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("activityId", body)
        self.assertIn("message", body)

    def test_success_calls_put_item(self):
        self._post({"user_id": "u1", "activity_type": "link_clicked", "metadata": {"url": "/signup"}})
        self.mock_activities.put_item.assert_called_once()
        item = self.mock_activities.put_item.call_args[1]["Item"]
        self.assertEqual(item["user_id"], "u1")
        self.assertEqual(item["activity_type"], "link_clicked")
        self.assertIn("activity_id", item)
        self.assertIn("timestamp", item)

    def test_optional_fields_stored(self):
        self._post({
            "user_id":        "u1",
            "activity_type":  "email_sent",
            "email_template": "v1.html",
            "from_name":      "Jane",
            "subject_line":   "Hello",
            "funnel_token":   "tok.123",
        })
        item = self.mock_activities.put_item.call_args[1]["Item"]
        self.assertEqual(item["email_template"], "v1.html")
        self.assertEqual(item["from_name"], "Jane")
        self.assertEqual(item["subject_line"], "Hello")
        self.assertEqual(item["funnel_token"], "tok.123")

    def test_database_error_returns_500(self):
        self.mock_activities.put_item.side_effect = Exception("DynamoDB error")
        resp = self._post({"user_id": "u1", "activity_type": "email_sent"})
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /admin/activity/query
# ---------------------------------------------------------------------------

QUERY_PATH = f"{BASE}/admin/activity/query"


class TestAdminActivityQuery(unittest.TestCase):

    def setUp(self):
        self.mock_activities = MagicMock()
        db.activities_table  = self.mock_activities
        self.mock_activities.query.return_value = {"Items": [MOCK_ACTIVITY]}

    def _post(self, body, headers=None):
        h = _admin_bearer()
        if headers:
            h.update(headers)
        return _call("POST", QUERY_PATH, body=body, headers=h)

    def test_no_auth_returns_401(self):
        resp = _call("POST", QUERY_PATH, body={"user_id": "u1"})
        self.assertEqual(resp["statusCode"], 401)

    def test_non_admin_returns_403(self):
        resp = _call("POST", QUERY_PATH, body={"user_id": "u1"}, headers=_user_bearer())
        self.assertEqual(resp["statusCode"], 403)

    def test_missing_user_id_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_success_returns_activities(self):
        resp = self._post({"user_id": "user-abc"})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("activities", body)
        self.assertEqual(body["count"], 1)
        act = body["activities"][0]
        self.assertEqual(act["activityId"], "act-001")
        self.assertEqual(act["userId"], "user-abc")
        self.assertEqual(act["activityType"], "email_sent")

    def test_empty_results_returns_empty_list(self):
        self.mock_activities.query.return_value = {"Items": []}
        resp = self._post({"user_id": "nobody"})
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["count"], 0)
        self.assertEqual(_body(resp)["activities"], [])

    def test_queries_correct_user(self):
        self._post({"user_id": "user-xyz"})
        call_kwargs = self.mock_activities.query.call_args[1]
        self.assertEqual(call_kwargs["IndexName"], "user-activity-index")

    def test_default_limit_50(self):
        self._post({"user_id": "u1"})
        call_kwargs = self.mock_activities.query.call_args[1]
        self.assertEqual(call_kwargs["Limit"], 50)

    def test_custom_limit(self):
        self._post({"user_id": "u1", "limit": 10})
        call_kwargs = self.mock_activities.query.call_args[1]
        self.assertEqual(call_kwargs["Limit"], 10)

    def test_database_error_returns_500(self):
        self.mock_activities.query.side_effect = Exception("DynamoDB error")
        resp = self._post({"user_id": "u1"})
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /activity/track
# ---------------------------------------------------------------------------

TRACK_PATH = f"{BASE}/activity/track"


class TestActivityTrack(unittest.TestCase):

    def setUp(self):
        self.mock_activities = MagicMock()
        db.activities_table  = self.mock_activities

    def _funnel_token(self, user_id="user-1", email="x@y.com", price=39):
        return auth_helpers.create_funnel_token(user_id, email, price)

    def _post(self, body):
        return _call("POST", TRACK_PATH, body=body)

    def test_missing_token_returns_400(self):
        resp = self._post({"activity_type": "link_clicked"})
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_token_returns_401(self):
        resp = self._post({"token": "bad.token", "activity_type": "link_clicked"})
        self.assertEqual(resp["statusCode"], 401)

    def test_access_token_rejected(self):
        token = auth_helpers.create_access_token("u1", "user")
        resp  = self._post({"token": token, "activity_type": "link_clicked"})
        self.assertEqual(resp["statusCode"], 401)

    def test_missing_activity_type_returns_400(self):
        token = self._funnel_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 400)

    def test_valid_request_returns_200(self):
        token = self._funnel_token()
        resp  = self._post({"token": token, "activity_type": "link_clicked"})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("activityId", body)

    def test_activity_stored_with_correct_user(self):
        token = self._funnel_token(user_id="user-abc")
        self._post({"token": token, "activity_type": "subscribe_clicked"})
        self.mock_activities.put_item.assert_called_once()
        item = self.mock_activities.put_item.call_args[1]["Item"]
        self.assertEqual(item["user_id"], "user-abc")
        self.assertEqual(item["activity_type"], "subscribe_clicked")
        self.assertEqual(item["funnel_token"], token)

    def test_metadata_includes_email_and_price(self):
        token = self._funnel_token(user_id="u1", email="test@example.com", price=59)
        self._post({"token": token, "activity_type": "link_clicked"})
        item = self.mock_activities.put_item.call_args[1]["Item"]
        self.assertEqual(item["metadata"]["email"], "test@example.com")
        self.assertEqual(item["metadata"]["price"], 59)

    def test_database_error_returns_500(self):
        self.mock_activities.put_item.side_effect = Exception("DynamoDB error")
        token = self._funnel_token()
        resp  = self._post({"token": token, "activity_type": "link_clicked"})
        self.assertEqual(resp["statusCode"], 500)


if __name__ == "__main__":
    unittest.main()
