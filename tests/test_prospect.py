"""
Unit tests for the marketing prospect feature.

Covers:
  - auth_helpers: create_prospect_token, send_prospect_email
  - POST /admin/prospect/send
  - POST /auth/unsubscribe
  - POST /stripe/checkout
  - routers/stripe.py: checkout.session.completed webhook branch

Run with:
    pipenv run python -m unittest tests.test_prospect -v
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
    import app              # noqa: E402
    import db               # noqa: E402
    import auth_helpers     # noqa: E402
    import email_helpers    # noqa: E402
    import data_helpers     # noqa: E402
    import routers.prospect as prospect_module  # noqa: E402

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
# data_helpers — parse_name / capitalize_name
# ---------------------------------------------------------------------------

class TestParseName(unittest.TestCase):

    def test_simple_first_last(self):
        first, last = data_helpers.parse_name("John Doe")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Doe")

    def test_lowercase_names(self):
        first, last = data_helpers.parse_name("john doe")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Doe")

    def test_with_middle_initial(self):
        first, last = data_helpers.parse_name("john T. doe")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Doe")

    def test_compound_last_name_van(self):
        first, last = data_helpers.parse_name("Martin Van Buren")
        self.assertEqual(first, "Martin")
        self.assertEqual(last, "Van Buren")

    def test_apostrophe_name(self):
        first, last = data_helpers.parse_name("Ann D'Souza")
        self.assertEqual(first, "Ann")
        self.assertEqual(last, "D'Souza")

    def test_hyphenated_first_name(self):
        first, last = data_helpers.parse_name("Mary-Jane O'Connor")
        self.assertEqual(first, "Mary-Jane")
        self.assertEqual(last, "O'Connor")

    def test_single_name_only(self):
        first, last = data_helpers.parse_name("Cher")
        self.assertEqual(first, "Cher")
        self.assertEqual(last, "")

    def test_with_prefixes(self):
        first, last = data_helpers.parse_name("Dr. John Smith")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")

    def test_with_suffixes(self):
        first, last = data_helpers.parse_name("John Smith Jr.")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")

    def test_with_prefix_and_suffix(self):
        first, last = data_helpers.parse_name("Dr. John Smith Jr.")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")

    def test_empty_string(self):
        first, last = data_helpers.parse_name("")
        self.assertEqual(first, "")
        self.assertEqual(last, "")

    def test_none_input(self):
        first, last = data_helpers.parse_name(None)
        self.assertEqual(first, "")
        self.assertEqual(last, "")

    def test_multiple_middle_names(self):
        first, last = data_helpers.parse_name("John Michael Andrew Smith")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")

    def test_mixed_case_compound(self):
        first, last = data_helpers.parse_name("martin van buren")
        self.assertEqual(first, "Martin")
        self.assertEqual(last, "Van Buren")

    def test_capitalize_helper_apostrophe(self):
        result = data_helpers.capitalize_name("d'souza")
        self.assertEqual(result, "D'Souza")

    def test_capitalize_helper_hyphen(self):
        result = data_helpers.capitalize_name("mary-jane")
        self.assertEqual(result, "Mary-Jane")

    def test_capitalize_helper_simple(self):
        result = data_helpers.capitalize_name("john")
        self.assertEqual(result, "John")

    def test_capitalize_helper_initial(self):
        result = data_helpers.capitalize_name("t.")
        self.assertEqual(result, "T.")

    def test_capitalize_helper_single_letter(self):
        result = data_helpers.capitalize_name("a")
        self.assertEqual(result, "A")

    def test_capitalize_helper_empty(self):
        result = data_helpers.capitalize_name("")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# auth_helpers — create_prospect_token
# ---------------------------------------------------------------------------

class TestCreateProspectToken(unittest.TestCase):

    def test_returns_string(self):
        token = auth_helpers.create_prospect_token("user-1", "x@example.com", 39)
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_payload_claims(self):
        import jwt
        token   = auth_helpers.create_prospect_token("user-1", "x@example.com", 39)
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"],   "user-1")
        self.assertEqual(payload["email"], "x@example.com")
        self.assertEqual(payload["price"], 39)
        self.assertEqual(payload["type"],  "prospect")

    def test_expiry_is_30_days(self):
        import jwt
        before  = datetime.now(timezone.utc)
        token   = auth_helpers.create_prospect_token("u", "a@b.com", 19)
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        exp     = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta   = exp - before
        self.assertAlmostEqual(delta.total_seconds(), 30 * 24 * 3600, delta=5)


# ---------------------------------------------------------------------------
# email_helpers — send_prospect_email
# ---------------------------------------------------------------------------

class TestSendProspectEmail(unittest.TestCase):

    def test_no_send_when_from_email_unset(self):
        original_from = email_helpers.FROM_EMAIL
        original_key  = email_helpers.RESEND_API_KEY
        email_helpers.FROM_EMAIL     = ""
        email_helpers.RESEND_API_KEY = ""
        try:
            leads = [{"grantor": "SMITH JOHN", "recordedDate": "2026-01-23", "docNumber": "123"}]
            token = auth_helpers.create_prospect_token("u1", "x@y.com", 19)
            with patch("resend.Emails.send") as mock_send:
                email_helpers.send_prospect_email("x@y.com", token, leads, 19)
                mock_send.assert_not_called()
        finally:
            email_helpers.FROM_EMAIL     = original_from
            email_helpers.RESEND_API_KEY = original_key

    def test_calls_resend_when_credentials_set(self):
        original_from = email_helpers.FROM_EMAIL
        original_key  = email_helpers.RESEND_API_KEY
        email_helpers.FROM_EMAIL     = "noreply@example.com"
        email_helpers.RESEND_API_KEY = "re_test_key"
        try:
            leads = [{"grantor": "SMITH JOHN", "recordedDate": "2026-01-23", "docNumber": "123"}]
            token = auth_helpers.create_prospect_token("u1", "x@y.com", 19)
            with patch("resend.Emails.send") as mock_send:
                email_helpers.send_prospect_email("x@y.com", token, leads, 19)
            mock_send.assert_called_once()
            call_params = mock_send.call_args[0][0]
            self.assertIn("html", call_params)
        finally:
            email_helpers.FROM_EMAIL     = original_from
            email_helpers.RESEND_API_KEY = original_key

    def test_subscribe_url_in_html(self):
        original_from = email_helpers.FROM_EMAIL
        original_key  = email_helpers.RESEND_API_KEY
        original_ui   = email_helpers.UI_BASE_URL
        email_helpers.FROM_EMAIL     = "noreply@example.com"
        email_helpers.RESEND_API_KEY = "re_test_key"
        email_helpers.UI_BASE_URL    = "https://example.com"
        try:
            leads = []
            token = auth_helpers.create_prospect_token("u1", "x@y.com", 39)
            with patch("resend.Emails.send") as mock_send:
                email_helpers.send_prospect_email("x@y.com", token, leads, 39)
            call_params = mock_send.call_args[0][0]
            html = call_params["html"]
            self.assertIn("/signup?token=", html)
            self.assertIn("/unsubscribe?token=", html)
        finally:
            email_helpers.FROM_EMAIL     = original_from
            email_helpers.RESEND_API_KEY = original_key
            email_helpers.UI_BASE_URL    = original_ui


# ---------------------------------------------------------------------------
# POST /admin/prospect/send
# ---------------------------------------------------------------------------

PROSPECT_SEND_PATH = f"{BASE}/admin/prospect/send"


class TestAdminProspectSend(unittest.TestCase):

    def setUp(self):
        self.mock_users_table    = MagicMock()
        self.mock_leads_table    = MagicMock()
        self.mock_locations_table = MagicMock()
        db.users_table      = self.mock_users_table
        db.documents_table  = self.mock_leads_table
        db.locations_table  = self.mock_locations_table

        # Default: no existing user by email
        self.mock_users_table.query.return_value  = {"Items": []}
        # scan for Count of existing prospect users
        self.mock_users_table.scan.return_value   = {"Count": 0}
        # locations scan returns CollinTx
        self.mock_locations_table.scan.return_value = {"Items": [COLLIN_TX]}
        # leads query returns sample leads
        self.mock_leads_table.query.return_value  = {"Items": list(MOCK_LEADS[:3])}

    def _post(self, body, headers=None):
        h = _admin_bearer()
        if headers:
            h.update(headers)
        return _call("POST", PROSPECT_SEND_PATH, body=body, headers=h)

    def test_no_auth_returns_403(self):
        resp = _call("POST", PROSPECT_SEND_PATH, body={"emails": ["x@y.com"]})
        self.assertEqual(resp["statusCode"], 403)

    def test_non_admin_returns_403(self):
        token = auth_helpers.create_access_token("user-1", "user")
        resp  = _call("POST", PROSPECT_SEND_PATH, body={"emails": ["x@y.com"]},
                      headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp["statusCode"], 403)

    def test_missing_emails_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_empty_emails_list_returns_400(self):
        resp = self._post({"emails": []})
        self.assertEqual(resp["statusCode"], 400)

    def test_success_returns_200_with_results(self):
        with patch("routers.prospect.send_prospect_email"):
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
        with patch("routers.prospect.send_prospect_email"):
            resp = self._post({"emails": emails})
        body = _body(resp)
        prices = [r["price"] for r in body["results"] if r["status"] == "sent"]
        self.assertEqual(prices, [19, 39, 59, 79, 19])

    def test_existing_user_gets_updated(self):
        existing = copy.deepcopy(ALICE)
        self.mock_users_table.query.return_value = {"Items": [existing]}
        updated = copy.deepcopy(existing)
        updated["status"] = "prospect"
        self.mock_users_table.update_item.return_value = {"Attributes": updated}
        with patch("routers.prospect.send_prospect_email"):
            resp = self._post({"emails": ["alice@example.com"]})
        self.assertEqual(resp["statusCode"], 200)
        # update_item called (not put_item)
        self.mock_users_table.update_item.assert_called_once()
        self.mock_users_table.put_item.assert_not_called()

    def test_email_send_failure_returns_error_status(self):
        with patch("routers.prospect.send_prospect_email", side_effect=Exception("SES error")):
            resp = self._post({"emails": ["fail@example.com"]})
        body = _body(resp)
        self.assertEqual(body["results"][0]["status"], "error")

    def test_skips_empty_emails(self):
        with patch("routers.prospect.send_prospect_email"):
            resp = self._post({"emails": ["", "  ", "valid@example.com"]})
        body = _body(resp)
        sent    = [r for r in body["results"] if r["status"] == "sent"]
        skipped = [r for r in body["results"] if r["status"] == "skipped"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(skipped), 2)

    def test_parses_email_with_name_format(self):
        """Test that 'John Doe <john@email.com>' is parsed correctly."""
        with patch("routers.prospect.send_prospect_email"):
            resp = self._post({"emails": ["John Doe <john@example.com>"]})

        body = _body(resp)
        result = body["results"][0]

        # Check that clean email was used for user creation
        self.assertEqual(result["email"], "john@example.com")
        self.assertEqual(result["status"], "sent")

        # Check that user was created with parsed names
        call_args = self.mock_users_table.put_item.call_args[1]
        user_item = call_args["Item"]
        self.assertEqual(user_item["email"], "john@example.com")
        self.assertEqual(user_item["first_name"], "John")
        self.assertEqual(user_item["last_name"], "Doe")
        self.assertEqual(user_item["status"], "prospect")
        self.assertEqual(user_item["location_codes"], {"CollinTx"})

    def test_parses_complex_name_formats(self):
        """Test various complex name formats in email input."""
        test_cases = [
            ("Martin Van Buren <martin@example.com>", "Martin", "Van Buren"),
            ("Ann D'Souza <ann@example.com>", "Ann", "D'Souza"),
            ("Mary-Jane O'Connor <mary@example.com>", "Mary-Jane", "O'Connor"),
            ("john T. doe <john@example.com>", "John", "Doe"),
        ]

        for email_input, expected_first, expected_last in test_cases:
            with self.subTest(email=email_input):
                # Reset all mocks to ensure clean state
                self.mock_users_table.reset_mock()
                self.mock_users_table.query.return_value = {"Items": []}
                self.mock_users_table.put_item.return_value = {}

                with patch("routers.prospect.send_prospect_email"):
                    resp = self._post({"emails": [email_input]})

                # Check user creation call
                self.mock_users_table.put_item.assert_called_once()
                call_args = self.mock_users_table.put_item.call_args[1]
                user_item = call_args["Item"]

                self.assertEqual(user_item["first_name"], expected_first)
                self.assertEqual(user_item["last_name"], expected_last)
                self.assertEqual(user_item["email"], email_input.split("<")[1].split(">")[0].strip())

    def test_sends_clean_email_to_resend(self):
        """Test that only clean email address is passed to send_prospect_email, not the full format."""
        with patch("routers.prospect.send_prospect_email") as mock_send:
            resp = self._post({"emails": ["John Doe <john@example.com>"]})

        # Check that send_prospect_email was called with clean email
        mock_send.assert_called_once()
        send_call_args = mock_send.call_args[0]
        self.assertEqual(send_call_args[0], "john@example.com")  # to_email parameter

    def test_handles_email_without_brackets(self):
        """Test that regular email format still works."""
        with patch("routers.prospect.send_prospect_email") as mock_send:
            resp = self._post({"emails": ["simple@example.com"]})

        body = _body(resp)
        result = body["results"][0]

        self.assertEqual(result["email"], "simple@example.com")
        self.assertEqual(result["status"], "sent")

        # Check that user was created without names
        call_args = self.mock_users_table.put_item.call_args[1]
        user_item = call_args["Item"]
        self.assertEqual(user_item["email"], "simple@example.com")
        self.assertEqual(user_item["first_name"], "")
        self.assertEqual(user_item["last_name"], "")
        self.assertEqual(user_item["status"], "prospect")
        self.assertEqual(user_item["location_codes"], {"CollinTx"})


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

    def _prospect_token(self, user_id="user-1", email="x@y.com", price=39):
        return auth_helpers.create_prospect_token(user_id, email, price)

    def test_valid_token_returns_200(self):
        token = self._prospect_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("message", _body(resp))

    def test_valid_token_calls_update_item(self):
        token = self._prospect_token(user_id="user-abc")
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
        """Access tokens (type=access) must not work as prospect tokens."""
        token = auth_helpers.create_access_token("user-1", "user")
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 401)

    def test_expired_prospect_token_returns_401(self):
        import jwt
        payload = {
            "sub":   "user-1",
            "email": "x@y.com",
            "price": 39,
            "type":  "prospect",
            "exp":   datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, auth_helpers.JWT_SECRET, algorithm="HS256")
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 401)

    def test_database_error_returns_500(self):
        self.mock_table.update_item.side_effect = Exception("DynamoDB error")
        token = self._prospect_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /stripe/checkout
# ---------------------------------------------------------------------------

CHECKOUT_PATH = f"{BASE}/stripe/checkout"


class TestStripeCheckout(unittest.TestCase):
    """Tests for POST /stripe/checkout.

    The prospect router does `import stripe` lazily inside the handler, so we
    inject a mock stripe module into sys.modules in setUp / tearDown to avoid
    needing the real package installed in the test environment.
    """

    def setUp(self):
        import routers.prospect as prospect_module

        # Build a minimal mock stripe module
        self._mock_stripe = MagicMock()
        self._mock_session = MagicMock()
        self._mock_session.url = "https://checkout.stripe.com/test-session"
        self._mock_stripe.checkout.Session.create.return_value = self._mock_session
        sys.modules["stripe"] = self._mock_stripe

        # Ensure STRIPE_SECRET_KEY is non-empty
        self._prospect_module        = prospect_module
        self._orig_stripe_key        = prospect_module.STRIPE_SECRET_KEY
        prospect_module.STRIPE_SECRET_KEY = "sk_test_dummy"

    def tearDown(self):
        sys.modules.pop("stripe", None)
        self._prospect_module.STRIPE_SECRET_KEY = self._orig_stripe_key

    def _prospect_token(self, user_id="user-1", email="x@y.com", price=39):
        return auth_helpers.create_prospect_token(user_id, email, price)

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
        token = self._prospect_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("url", body)
        self.assertEqual(body["url"], "https://checkout.stripe.com/test-session")
        self._mock_stripe.checkout.Session.create.assert_called_once()

    def test_stripe_session_params(self):
        """Verify the Checkout Session is created with the correct parameters."""
        token = self._prospect_token(user_id="user-abc", email="x@y.com", price=59)
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
        token = self._prospect_token()
        resp  = self._post({"token": token})
        self.assertEqual(resp["statusCode"], 500)

    def test_no_stripe_key_returns_503(self):
        """When STRIPE_SECRET_KEY is empty, return 503."""
        import routers.prospect as prospect_module
        original = prospect_module.STRIPE_SECRET_KEY
        prospect_module.STRIPE_SECRET_KEY = ""
        try:
            token = self._prospect_token()
            resp  = self._post({"token": token})
            self.assertEqual(resp["statusCode"], 503)
        finally:
            prospect_module.STRIPE_SECRET_KEY = original


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
        # Simulate 3 existing prospect users (offset=3)
        prices = [ladder[(3 + i) % len(ladder)] for i in range(4)]
        self.assertEqual(prices, [79, 19, 39, 59])


if __name__ == "__main__":
    unittest.main()
