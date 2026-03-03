"""
Unit tests for the marketing funnel feature.

Covers:
  - auth_helpers: create_funnel_token, send_funnel_email
  - POST /admin/funnel/send
  - POST /auth/unsubscribe
  - POST /stripe/checkout
  - routers/stripe.py: checkout.session.completed webhook branch

Run with:
    pipenv run python -m unittest tests.test_funnel -v
"""

import copy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
        "GSI_NAME":                  "recorded-date-index",
        "LOCATION_DATE_GSI":         "location-date-index",
        "STRIPE_SECRET_KEY":         "sk_test_dummy",
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
    import app        # noqa: E402
    import db         # noqa: E402
    import auth_helpers  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures.users import ALICE
from tests.fixtures.leads import MOCK_LEADS
from tests.fixtures.locations import COLLIN_TX


# ---------------------------------------------------------------------------
# Helpers shared across test cases
# ---------------------------------------------------------------------------

class MockContext:
    aws_request_id       = "test-request-id"
    function_name        = "probate-leads-api-test"
    memory_limit_in_mb   = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    log_stream_name      = "test-log-stream"


def _body(resp):
    return json.loads(resp["body"])


def _call(method: str, path: str, path_params=None, body=None, headers=None):
    base_headers = {"Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)
    event = {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params,
        "headers": base_headers,
        "queryStringParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


def _admin_bearer() -> dict:
    token = auth_helpers.create_access_token("admin-id", "admin")
    return {"Authorization": f"Bearer {token}"}


BASE = "/real-estate/probate-leads"


# ---------------------------------------------------------------------------
# auth_helpers — create_funnel_token
# ---------------------------------------------------------------------------

class TestCreateFunnelToken(unittest.TestCase):

    def test_returns_string(self):
        token = auth_helpers.create_funnel_token("user-1", "x@example.com", 39)
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_payload_claims(self):
        import jwt
        token   = auth_helpers.create_funnel_token("user-1", "x@example.com", 39)
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"],   "user-1")
        self.assertEqual(payload["email"], "x@example.com")
        self.assertEqual(payload["price"], 39)
        self.assertEqual(payload["type"],  "funnel")

    def test_expiry_is_30_days(self):
        import jwt
        before  = datetime.now(timezone.utc)
        token   = auth_helpers.create_funnel_token("u", "a@b.com", 19)
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        exp     = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta   = exp - before
        self.assertAlmostEqual(delta.total_seconds(), 30 * 24 * 3600, delta=5)


# ---------------------------------------------------------------------------
# auth_helpers — send_funnel_email
# ---------------------------------------------------------------------------

class TestSendFunnelEmail(unittest.TestCase):

    def test_no_ses_when_from_email_unset(self):
        original = auth_helpers.FROM_EMAIL
        auth_helpers.FROM_EMAIL = ""
        try:
            leads = [{"grantor": "SMITH JOHN", "recordedDate": "2026-01-23", "docNumber": "123"}]
            token = auth_helpers.create_funnel_token("u1", "x@y.com", 19)
            with patch("boto3.client") as mock_boto:
                auth_helpers.send_funnel_email("x@y.com", token, leads, 19)
                mock_boto.assert_not_called()
        finally:
            auth_helpers.FROM_EMAIL = original

    def test_calls_ses_when_from_email_set(self):
        original = auth_helpers.FROM_EMAIL
        auth_helpers.FROM_EMAIL = "noreply@example.com"
        try:
            leads = [{"grantor": "SMITH JOHN", "recordedDate": "2026-01-23", "docNumber": "123"}]
            token = auth_helpers.create_funnel_token("u1", "x@y.com", 19)
            mock_ses = MagicMock()
            with patch("boto3.client", return_value=mock_ses):
                auth_helpers.send_funnel_email("x@y.com", token, leads, 19)
            mock_ses.send_email.assert_called_once()
            call_kwargs = mock_ses.send_email.call_args[1]
            self.assertIn("Html", call_kwargs["Message"]["Body"])
        finally:
            auth_helpers.FROM_EMAIL = original

    def test_subscribe_url_in_html(self):
        original_from = auth_helpers.FROM_EMAIL
        original_ui   = auth_helpers.UI_BASE_URL
        auth_helpers.FROM_EMAIL  = "noreply@example.com"
        auth_helpers.UI_BASE_URL = "https://example.com"
        try:
            leads = []
            token = auth_helpers.create_funnel_token("u1", "x@y.com", 39)
            mock_ses = MagicMock()
            with patch("boto3.client", return_value=mock_ses):
                auth_helpers.send_funnel_email("x@y.com", token, leads, 39)
            html = mock_ses.send_email.call_args[1]["Message"]["Body"]["Html"]["Data"]
            self.assertIn("/signup?token=", html)
            self.assertIn("/unsubscribe?token=", html)
        finally:
            auth_helpers.FROM_EMAIL  = original_from
            auth_helpers.UI_BASE_URL = original_ui


# ---------------------------------------------------------------------------
# POST /admin/funnel/send
# ---------------------------------------------------------------------------

FUNNEL_SEND_PATH = f"{BASE}/admin/funnel/send"


class TestAdminFunnelSend(unittest.TestCase):

    def setUp(self):
        self.mock_users_table    = MagicMock()
        self.mock_leads_table    = MagicMock()
        self.mock_locations_table = MagicMock()
        db.users_table     = self.mock_users_table
        db.table           = self.mock_leads_table
        db.locations_table = self.mock_locations_table

        # Default: no existing user by email
        self.mock_users_table.query.return_value  = {"Items": []}
        # scan for Count of existing funnel users
        self.mock_users_table.scan.return_value   = {"Count": 0}
        # locations scan returns CollinTx
        self.mock_locations_table.scan.return_value = {"Items": [COLLIN_TX]}
        # leads query returns sample leads
        self.mock_leads_table.query.return_value  = {"Items": list(MOCK_LEADS[:3])}

    def _post(self, body, headers=None):
        h = _admin_bearer()
        if headers:
            h.update(headers)
        return _call("POST", FUNNEL_SEND_PATH, body=body, headers=h)

    def test_no_auth_returns_403(self):
        resp = _call("POST", FUNNEL_SEND_PATH, body={"emails": ["x@y.com"]})
        self.assertEqual(resp["statusCode"], 403)

    def test_non_admin_returns_403(self):
        token = auth_helpers.create_access_token("user-1", "user")
        resp  = _call("POST", FUNNEL_SEND_PATH, body={"emails": ["x@y.com"]},
                      headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp["statusCode"], 403)

    def test_missing_emails_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_empty_emails_list_returns_400(self):
        resp = self._post({"emails": []})
        self.assertEqual(resp["statusCode"], 400)

    def test_success_returns_200_with_results(self):
        with patch("routers.funnel.send_funnel_email"):
            resp = self._post({"emails": ["new@example.com"]})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["status"], "sent")
        self.assertEqual(body["results"][0]["email"], "new@example.com")

    def test_round_robin_price_assignment(self):
        """First email gets $19, second $39, third $59, fourth $79, fifth cycles to $19."""
        emails = [f"user{i}@example.com" for i in range(5)]
        with patch("routers.funnel.send_funnel_email"):
            resp = self._post({"emails": emails})
        body = _body(resp)
        prices = [r["price"] for r in body["results"] if r["status"] == "sent"]
        self.assertEqual(prices, [19, 39, 59, 79, 19])

    def test_existing_user_gets_updated(self):
        existing = copy.deepcopy(ALICE)
        self.mock_users_table.query.return_value = {"Items": [existing]}
        updated = copy.deepcopy(existing)
        updated["status"] = "free_trial"
        self.mock_users_table.update_item.return_value = {"Attributes": updated}
        with patch("routers.funnel.send_funnel_email"):
            resp = self._post({"emails": ["alice@example.com"]})
        self.assertEqual(resp["statusCode"], 200)
        # update_item called (not put_item)
        self.mock_users_table.update_item.assert_called_once()
        self.mock_users_table.put_item.assert_not_called()

    def test_email_send_failure_returns_error_status(self):
        with patch("routers.funnel.send_funnel_email", side_effect=Exception("SES error")):
            resp = self._post({"emails": ["fail@example.com"]})
        body = _body(resp)
        self.assertEqual(body["results"][0]["status"], "error")

    def test_skips_empty_emails(self):
        with patch("routers.funnel.send_funnel_email"):
            resp = self._post({"emails": ["", "  ", "valid@example.com"]})
        body = _body(resp)
        sent    = [r for r in body["results"] if r["status"] == "sent"]
        skipped = [r for r in body["results"] if r["status"] == "skipped"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(skipped), 2)


# ---------------------------------------------------------------------------
# POST /auth/unsubscribe
# ---------------------------------------------------------------------------

UNSUBSCRIBE_PATH = f"{BASE}/auth/unsubscribe"


class TestAuthUnsubscribe(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _post(self, body):
        return _call("POST", UNSUBSCRIBE_PATH, body=body)

    def _funnel_token(self, user_id="user-1", email="x@y.com", price=39):
        return auth_helpers.create_funnel_token(user_id, email, price)

    def test_valid_token_returns_200(self):
        token = self._funnel_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("message", _body(resp))

    def test_valid_token_calls_update_item(self):
        token = self._funnel_token(user_id="user-abc")
        self._post({"token": token})
        self.mock_table.update_item.assert_called_once()
        call_kwargs = self.mock_table.update_item.call_args[1]
        self.assertEqual(call_kwargs["Key"], {"user_id": "user-abc"})
        self.assertIn(":status", call_kwargs["ExpressionAttributeValues"])
        self.assertEqual(
            call_kwargs["ExpressionAttributeValues"][":status"], "unsubscribed"
        )

    def test_missing_token_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_token_returns_401(self):
        resp = self._post({"token": "not.a.jwt"})
        self.assertEqual(resp["statusCode"], 401)

    def test_access_token_rejected(self):
        """Access tokens (type=access) must not work as funnel tokens."""
        token = auth_helpers.create_access_token("user-1", "user")
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 401)

    def test_expired_funnel_token_returns_401(self):
        import jwt
        payload = {
            "sub":   "user-1",
            "email": "x@y.com",
            "price": 39,
            "type":  "funnel",
            "exp":   datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, auth_helpers.JWT_SECRET, algorithm="HS256")
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 401)

    def test_database_error_returns_500(self):
        self.mock_table.update_item.side_effect = Exception("DynamoDB error")
        token = self._funnel_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /stripe/checkout
# ---------------------------------------------------------------------------

CHECKOUT_PATH = f"{BASE}/stripe/checkout"


class TestStripeCheckout(unittest.TestCase):
    """Tests for POST /stripe/checkout.

    The funnel router does `import stripe` lazily inside the handler, so we
    inject a mock stripe module into sys.modules in setUp / tearDown to avoid
    needing the real package installed in the test environment.
    """

    def setUp(self):
        import routers.funnel as funnel_module

        # Build a minimal mock stripe module
        self._mock_stripe = MagicMock()
        self._mock_session = MagicMock()
        self._mock_session.url = "https://checkout.stripe.com/test-session"
        self._mock_stripe.checkout.Session.create.return_value = self._mock_session
        sys.modules["stripe"] = self._mock_stripe

        # Ensure STRIPE_SECRET_KEY is non-empty (may be "" if test_auth loaded the
        # module first with STRIPE_SECRET_KEY="" in os.environ).
        self._funnel_module        = funnel_module
        self._orig_stripe_key      = funnel_module.STRIPE_SECRET_KEY
        funnel_module.STRIPE_SECRET_KEY = "sk_test_dummy"

    def tearDown(self):
        sys.modules.pop("stripe", None)
        self._funnel_module.STRIPE_SECRET_KEY = self._orig_stripe_key

    def _funnel_token(self, user_id="user-1", email="x@y.com", price=39):
        return auth_helpers.create_funnel_token(user_id, email, price)

    def _post(self, body):
        return _call("POST", CHECKOUT_PATH, body=body)

    def test_missing_token_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_token_returns_401(self):
        resp = self._post({"token": "bad.token"})
        self.assertEqual(resp["statusCode"], 401)

    def test_access_token_rejected(self):
        token = auth_helpers.create_access_token("user-1", "user")
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 401)

    def test_valid_token_creates_stripe_session(self):
        token = self._funnel_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("url", body)
        self.assertEqual(body["url"], "https://checkout.stripe.com/test-session")
        self._mock_stripe.checkout.Session.create.assert_called_once()

    def test_stripe_session_params(self):
        """Verify the Checkout Session is created with the correct parameters."""
        token = self._funnel_token(user_id="user-abc", email="x@y.com", price=59)
        self._post({"token": token})
        call_kwargs = self._mock_stripe.checkout.Session.create.call_args[1]
        self.assertEqual(call_kwargs["mode"], "subscription")
        self.assertEqual(call_kwargs["client_reference_id"], "user-abc")
        self.assertEqual(call_kwargs["customer_email"], "x@y.com")
        line_item = call_kwargs["line_items"][0]
        self.assertEqual(line_item["price_data"]["unit_amount"], 59 * 100)
        self.assertEqual(line_item["price_data"]["currency"], "usd")
        self.assertEqual(line_item["price_data"]["recurring"]["interval"], "month")

    def test_stripe_error_returns_500(self):
        self._mock_stripe.checkout.Session.create.side_effect = Exception("Stripe down")
        token = self._funnel_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 500)

    def test_no_stripe_key_returns_503(self):
        """When STRIPE_SECRET_KEY is empty, return 503."""
        import routers.funnel as funnel_module
        original = funnel_module.STRIPE_SECRET_KEY
        funnel_module.STRIPE_SECRET_KEY = ""
        try:
            token = self._funnel_token()
            resp  = self._post({"token": token})
            self.assertEqual(resp["statusCode"], 503)
        finally:
            funnel_module.STRIPE_SECRET_KEY = original


# ---------------------------------------------------------------------------
# POST /stripe/webhook — checkout.session.completed
# ---------------------------------------------------------------------------

WEBHOOK_PATH = f"{BASE}/stripe/webhook"


class TestStripeCheckoutWebhook(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _webhook(self, event_type: str, data_object: dict):
        """Build a minimal Stripe webhook event and POST it to the handler."""
        payload = json.dumps({
            "type": event_type,
            "data": {"object": data_object},
        }).encode()
        event = {
            "httpMethod": "POST",
            "path": WEBHOOK_PATH,
            "pathParameters": None,
            "headers": {"Content-Type": "application/json"},
            "queryStringParameters": None,
            "body": payload.decode(),
            "isBase64Encoded": False,
        }
        return app.handler(event, MockContext())

    def test_checkout_session_completed_links_customer(self):
        resp = self._webhook(
            "checkout.session.completed",
            {
                "client_reference_id": "user-abc",
                "customer":            "cus_new123",
            },
        )
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertEqual(body["action"], "customer_linked")
        self.assertEqual(body["userId"], "user-abc")

    def test_checkout_session_calls_update_item(self):
        self._webhook(
            "checkout.session.completed",
            {
                "client_reference_id": "user-abc",
                "customer":            "cus_new123",
            },
        )
        self.mock_table.update_item.assert_called_once()
        call_kwargs = self.mock_table.update_item.call_args[1]
        self.assertEqual(call_kwargs["Key"], {"user_id": "user-abc"})
        self.assertEqual(
            call_kwargs["ExpressionAttributeValues"][":cid"], "cus_new123"
        )

    def test_checkout_session_missing_reference_id(self):
        resp = self._webhook(
            "checkout.session.completed",
            {"customer": "cus_new123"},  # no client_reference_id
        )
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["action"], "no_user_id")


# ---------------------------------------------------------------------------
# Round-robin price helper (unit test — pure logic)
# ---------------------------------------------------------------------------

class TestRoundRobinPrice(unittest.TestCase):

    def test_ladder_sequence(self):
        ladder = [19, 39, 59, 79]
        prices = [ladder[i % len(ladder)] for i in range(8)]
        self.assertEqual(prices, [19, 39, 59, 79, 19, 39, 59, 79])

    def test_ladder_with_offset(self):
        ladder = [19, 39, 59, 79]
        # Simulate 3 existing funnel users (offset=3)
        prices = [ladder[(3 + i) % len(ladder)] for i in range(4)]
        self.assertEqual(prices, [79, 19, 39, 59])


if __name__ == "__main__":
    unittest.main()
