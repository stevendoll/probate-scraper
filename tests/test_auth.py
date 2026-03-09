"""
Unit tests for auth_helpers.py and the /auth/* + /admin/* routes.

Run with:
    pipenv run python -m unittest tests.test_auth -v
"""

import copy
import json
import os
import sys
import time
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
        "STRIPE_SECRET_KEY":         "",
        "STRIPE_WEBHOOK_SECRET":     "",
        "JWT_SECRET":                "test-secret-for-unit-tests",
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
    import app          # noqa: E402
    import db           # noqa: E402
    import auth_helpers  # noqa: E402
    import email_helpers  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures.users import ALICE, BOB, MOCK_USERS
from tests.fixtures.locations import COLLIN_TX


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


def _call_qs(method: str, path: str, qs: dict, headers=None):
    base_headers = {"Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)
    event = {
        "httpMethod": method,
        "path": path,
        "pathParameters": None,
        "headers": base_headers,
        "queryStringParameters": qs,
        "body": None,
        "isBase64Encoded": False,
    }
    return app.handler(event, MockContext())


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# auth_helpers — unit tests (pure logic, no HTTP)
# ---------------------------------------------------------------------------

class TestCreateMagicToken(unittest.TestCase):

    def test_returns_string(self):
        token = auth_helpers.create_magic_token("test@example.com")
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_payload_has_correct_fields(self):
        import jwt
        token = auth_helpers.create_magic_token("test@example.com")
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], "test@example.com")
        self.assertEqual(payload["type"], "magic")
        self.assertIn("exp", payload)

    def test_expiry_is_15_minutes(self):
        import jwt
        before = datetime.now(timezone.utc)
        token   = auth_helpers.create_magic_token("x@y.com")
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        exp     = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta   = exp - before
        # Allow ±5 s of clock drift
        self.assertAlmostEqual(delta.total_seconds(), 15 * 60, delta=5)


class TestCreateAccessToken(unittest.TestCase):

    def test_returns_string(self):
        token = auth_helpers.create_access_token("user-123", "user")
        self.assertIsInstance(token, str)

    def test_payload_has_correct_fields(self):
        import jwt
        token = auth_helpers.create_access_token("user-123", "admin")
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], "user-123")
        self.assertEqual(payload["role"], "admin")
        self.assertEqual(payload["type"], "access")

    def test_expiry_is_7_days(self):
        import jwt
        before = datetime.now(timezone.utc)
        token   = auth_helpers.create_access_token("u", "user")
        payload = jwt.decode(token, auth_helpers.JWT_SECRET, algorithms=["HS256"])
        exp     = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta   = exp - before
        self.assertAlmostEqual(delta.total_seconds(), 7 * 24 * 3600, delta=5)


class TestVerifyToken(unittest.TestCase):

    def test_valid_token_returns_payload(self):
        token   = auth_helpers.create_magic_token("a@b.com")
        payload = auth_helpers.verify_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "a@b.com")

    def test_invalid_token_returns_none(self):
        self.assertIsNone(auth_helpers.verify_token("not.a.token"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(auth_helpers.verify_token(""))

    def test_expired_token_returns_none(self):
        import jwt
        payload = {
            "sub":  "x@y.com",
            "type": "magic",
            "exp":  datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, auth_helpers.JWT_SECRET, algorithm="HS256")
        self.assertIsNone(auth_helpers.verify_token(token))

    def test_wrong_secret_returns_none(self):
        import jwt
        payload = {"sub": "x@y.com", "type": "magic",
                   "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        self.assertIsNone(auth_helpers.verify_token(token))


class TestGetBearerPayload(unittest.TestCase):

    def _event(self, auth_header: str | None) -> dict:
        headers = {}
        if auth_header is not None:
            headers["Authorization"] = auth_header
        return {"headers": headers}

    def test_valid_bearer_returns_payload(self):
        token   = auth_helpers.create_access_token("u1", "user")
        payload = auth_helpers.get_bearer_payload(self._event(f"Bearer {token}"))
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "u1")

    def test_missing_header_returns_none(self):
        self.assertIsNone(auth_helpers.get_bearer_payload(self._event(None)))

    def test_non_bearer_scheme_returns_none(self):
        token = auth_helpers.create_access_token("u1", "user")
        self.assertIsNone(auth_helpers.get_bearer_payload(self._event(f"Basic {token}")))

    def test_invalid_token_returns_none(self):
        self.assertIsNone(auth_helpers.get_bearer_payload(self._event("Bearer bad.token")))

    def test_case_insensitive_bearer(self):
        token   = auth_helpers.create_access_token("u1", "user")
        payload = auth_helpers.get_bearer_payload(self._event(f"bearer {token}"))
        self.assertIsNotNone(payload)


class TestSendMagicLink(unittest.TestCase):

    def test_logs_when_from_email_unset(self):
        """When FROM_EMAIL is empty, no SES call is made (just logs)."""
        original = auth_helpers.FROM_EMAIL
        auth_helpers.FROM_EMAIL = ""
        try:
            with patch("boto3.client") as mock_boto:
                token = auth_helpers.create_magic_token("x@y.com")
                auth_helpers.send_magic_link("x@y.com", token)
                mock_boto.assert_not_called()
        finally:
            auth_helpers.FROM_EMAIL = original

    def test_calls_ses_when_from_email_set(self):
        original = auth_helpers.FROM_EMAIL
        auth_helpers.FROM_EMAIL = "noreply@example.com"
        try:
            mock_ses = MagicMock()
            with patch("boto3.client", return_value=mock_ses):
                token = auth_helpers.create_magic_token("x@y.com")
                auth_helpers.send_magic_link("x@y.com", token)
            mock_ses.send_email.assert_called_once()
        finally:
            auth_helpers.FROM_EMAIL = original


# ---------------------------------------------------------------------------
# POST /auth/request-login
# ---------------------------------------------------------------------------

AUTH_BASE = "/real-estate/probate-leads/auth"


class TestRequestLogin(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _post(self, body):
        return _call("POST", f"{AUTH_BASE}/request-login", body=body)

    def test_returns_200_for_known_email(self):
        self.mock_table.query.return_value = {"Items": [copy.deepcopy(ALICE)]}
        resp = self._post({"email": "alice@example.com"})
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_200_for_unknown_email(self):
        """Always 200 to prevent email enumeration."""
        self.mock_table.query.return_value = {"Items": []}
        resp = self._post({"email": "nobody@example.com"})
        self.assertEqual(resp["statusCode"], 200)

    def test_missing_email_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp["statusCode"], 400)

    def test_sends_magic_link_for_known_user(self):
        self.mock_table.query.return_value = {"Items": [copy.deepcopy(ALICE)]}
        with patch("routers.auth.send_magic_link") as mock_send:
            self._post({"email": "alice@example.com"})
            mock_send.assert_called_once()

    def test_creates_inbound_user_for_unknown_email(self):
        """New users should be created with 'inbound' status and get funnel email."""
        self.mock_table.query.return_value = {"Items": []}
        
        # Mock Lead.from_dynamo to avoid serialization issues
        with patch("routers.auth.Document") as mock_lead, \
             patch("routers.auth.send_prospect_email") as mock_funnel, \
             patch("routers.auth._fetch_sample_leads", return_value=[{"grantor": "Test"}]):
            
            mock_lead.from_dynamo.return_value.to_dict.return_value = {"grantor": "Test"}
            
            self._post({"email": "new@example.com"})
            
            # Check that user was created
            self.mock_table.put_item.assert_called_once()
            call_args = self.mock_table.put_item.call_args[1]
            user_item = call_args["Item"]
            
            self.assertEqual(user_item["email"], "new@example.com")
            self.assertEqual(user_item["status"], "inbound")
            
            # Check that funnel email was sent
            mock_funnel.assert_called_once()

    def test_parses_name_from_email_format(self):
        """Should parse 'John Doe <john@email.com>' format."""
        self.mock_table.query.return_value = {"Items": []}
        
        with patch("routers.auth.Document") as mock_lead, \
             patch("routers.auth._create_inbound_user") as mock_create, \
             patch("routers.auth.send_prospect_email"), \
             patch("routers.auth._fetch_sample_leads", return_value=[{"grantor": "Test"}]):
            
            mock_lead.from_dynamo.return_value.to_dict.return_value = {"grantor": "Test"}
            
            self._post({"email": "John Doe <john@example.com>"})
            
            mock_create.assert_called_once_with("john@example.com", "John", "Doe")

    def test_inbound_user_creation_details(self):
        """Verify inbound user is created with correct attributes."""
        self.mock_table.query.return_value = {"Items": []}
        
        with patch("routers.auth.Document") as mock_lead, \
             patch("routers.auth.send_prospect_email"), \
             patch("routers.auth._fetch_sample_leads", return_value=[{"grantor": "Test"}]):
            
            mock_lead.from_dynamo.return_value.to_dict.return_value = {"grantor": "Test"}
            
            self._post({"email": "new@example.com"})
            
            # Check put_item was called with correct user data
            self.mock_table.put_item.assert_called_once()
            call_args = self.mock_table.put_item.call_args[1]
            user_item = call_args["Item"]
            
            self.assertEqual(user_item["email"], "new@example.com")
            self.assertEqual(user_item["status"], "inbound")
            self.assertEqual(user_item["location_codes"], {"CollinTx"})
            self.assertEqual(user_item["offered_price"], 19)

    def test_funnel_email_sent_to_new_user(self):
        """Verify funnel email is sent with correct parameters."""
        self.mock_table.query.return_value = {"Items": []}
        
        mock_user = {
            "user_id": "test-user-id",
            "email": "new@example.com",
            "offered_price": 19,
        }
        
        with patch("routers.auth.Document") as mock_lead, \
             patch("routers.auth._create_inbound_user", return_value=mock_user), \
             patch("routers.auth.send_prospect_email") as mock_funnel, \
             patch("routers.auth._fetch_sample_leads", return_value=[{"grantor": "Test"}]):
            
            mock_lead.from_dynamo.return_value.to_dict.return_value = {"grantor": "Test"}
            
            self._post({"email": "new@example.com"})
            
            # Verify funnel email was called
            mock_funnel.assert_called_once()
            call_args = mock_funnel.call_args[0]
            
            self.assertEqual(call_args[0], "new@example.com")  # email
            self.assertEqual(call_args[3], 19)  # price

    def test_error_handling_still_returns_200(self):
        """Even if user creation fails, still return 200 to prevent enumeration."""
        self.mock_table.query.return_value = {"Items": []}
        
        with patch("routers.auth._create_inbound_user", side_effect=Exception("DB error")):
            resp = self._post({"email": "new@example.com"})
            self.assertEqual(resp["statusCode"], 200)


# ---------------------------------------------------------------------------
# GET /auth/verify
# ---------------------------------------------------------------------------

class TestVerifyLogin(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _get(self, token: str):
        return _call_qs("GET", f"{AUTH_BASE}/verify", {"token": token})

    def test_valid_magic_token_returns_200_and_access_token(self):
        self.mock_table.query.return_value = {"Items": [copy.deepcopy(ALICE)]}
        token = auth_helpers.create_magic_token("alice@example.com")
        resp  = self._get(token)
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("accessToken", body)
        self.assertIn("user", body)

    def test_access_token_is_valid_jwt(self):
        self.mock_table.query.return_value = {"Items": [copy.deepcopy(ALICE)]}
        magic = auth_helpers.create_magic_token("alice@example.com")
        resp  = self._get(magic)
        access_token = _body(resp)["accessToken"]
        payload = auth_helpers.verify_token(access_token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "access")

    def test_wrong_token_type_returns_401(self):
        """An access token presented as a magic token should be rejected."""
        token = auth_helpers.create_access_token("user-uuid-001", "user")
        resp  = self._get(token)
        self.assertEqual(resp["statusCode"], 401)

    def test_expired_token_returns_401(self):
        import jwt
        payload = {
            "sub":  "alice@example.com",
            "type": "magic",
            "exp":  datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, auth_helpers.JWT_SECRET, algorithm="HS256")
        resp  = self._get(token)
        self.assertEqual(resp["statusCode"], 401)

    def test_missing_token_param_returns_400(self):
        resp = _call_qs("GET", f"{AUTH_BASE}/verify", {})
        self.assertEqual(resp["statusCode"], 400)

    def test_user_not_found_returns_404(self):
        self.mock_table.query.return_value = {"Items": []}
        token = auth_helpers.create_magic_token("ghost@example.com")
        resp  = self._get(token)
        self.assertEqual(resp["statusCode"], 404)


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

class TestGetMe(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _access_token(self, user_id="user-uuid-001", role="user"):
        return auth_helpers.create_access_token(user_id, role)

    def test_valid_token_returns_200(self):
        self.mock_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        token = self._access_token()
        resp  = _call("GET", f"{AUTH_BASE}/me", headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("user", _body(resp))

    def test_no_token_returns_401(self):
        resp = _call("GET", f"{AUTH_BASE}/me")
        self.assertEqual(resp["statusCode"], 401)

    def test_invalid_token_returns_401(self):
        resp = _call("GET", f"{AUTH_BASE}/me", headers=_bearer("garbage"))
        self.assertEqual(resp["statusCode"], 401)

    def test_magic_token_returns_401(self):
        """Magic tokens are not valid for /auth/me — only access tokens are."""
        magic = auth_helpers.create_magic_token("alice@example.com")
        resp  = _call("GET", f"{AUTH_BASE}/me", headers=_bearer(magic))
        self.assertEqual(resp["statusCode"], 401)


# ---------------------------------------------------------------------------
# PATCH /auth/me
# ---------------------------------------------------------------------------

class TestPatchMe(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table
        self.mock_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        updated = copy.deepcopy(ALICE)
        updated["email"] = "new@example.com"
        self.mock_table.update_item.return_value = {"Attributes": updated}

    def _access_token(self):
        return auth_helpers.create_access_token("user-uuid-001", "user")

    def test_returns_200_with_updated_email(self):
        token = self._access_token()
        resp  = _call("PATCH", f"{AUTH_BASE}/me", body={"email": "new@example.com"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["user"]["email"], "new@example.com")

    def test_no_token_returns_401(self):
        resp = _call("PATCH", f"{AUTH_BASE}/me", body={"email": "x@y.com"})
        self.assertEqual(resp["statusCode"], 401)

    def test_missing_email_returns_400(self):
        token = self._access_token()
        resp  = _call("PATCH", f"{AUTH_BASE}/me", body={}, headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 400)


# ---------------------------------------------------------------------------
# GET /auth/leads
# ---------------------------------------------------------------------------

class TestGetMyLeads(unittest.TestCase):

    def setUp(self):
        self.mock_user_table  = MagicMock()
        self.mock_leads_table = MagicMock()
        db.users_table       = self.mock_user_table
        db.documents_table   = self.mock_leads_table
        self.mock_leads_table.query.return_value = {"Items": []}

    def _access_token(self, user_id="user-uuid-001", role="user"):
        return auth_helpers.create_access_token(user_id, role)

    def test_active_user_returns_200(self):
        self.mock_user_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        token = self._access_token()
        resp  = _call("GET", f"{AUTH_BASE}/leads", headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("leads", _body(resp))

    def test_inactive_user_returns_403(self):
        inactive = copy.deepcopy(ALICE)
        inactive["status"] = "inactive"
        self.mock_user_table.get_item.return_value = {"Item": inactive}
        token = self._access_token()
        resp  = _call("GET", f"{AUTH_BASE}/leads", headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 403)

    def test_no_token_returns_401(self):
        resp = _call("GET", f"{AUTH_BASE}/leads")
        self.assertEqual(resp["statusCode"], 401)


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------

ADMIN_BASE = "/real-estate/probate-leads/admin/users"


class TestAdminListUsers(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table
        self.mock_table.scan.return_value = {"Items": [copy.deepcopy(u) for u in MOCK_USERS]}

    def _admin_token(self):
        return auth_helpers.create_access_token("admin-id", "admin")

    def _user_token(self):
        return auth_helpers.create_access_token("user-uuid-001", "user")

    def test_admin_token_returns_200(self):
        token = self._admin_token()
        resp  = _call("GET", ADMIN_BASE, headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertIn("users", body)
        self.assertEqual(body["count"], 2)

    def test_non_admin_token_returns_403(self):
        token = self._user_token()
        resp  = _call("GET", ADMIN_BASE, headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 403)

    def test_no_token_returns_403(self):
        resp = _call("GET", ADMIN_BASE)
        self.assertEqual(resp["statusCode"], 403)


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}
# ---------------------------------------------------------------------------

class TestAdminGetUser(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table

    def _admin_token(self):
        return auth_helpers.create_access_token("admin-id", "admin")

    def test_returns_200_for_existing_user(self):
        self.mock_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        token = self._admin_token()
        resp  = _call("GET", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["user"]["userId"], "user-uuid-001")

    def test_returns_404_for_missing_user(self):
        self.mock_table.get_item.return_value = {}
        token = self._admin_token()
        resp  = _call("GET", f"{ADMIN_BASE}/no-such", {"user_id": "no-such"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 404)

    def test_non_admin_returns_403(self):
        token = auth_helpers.create_access_token("u1", "user")
        resp  = _call("GET", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 403)


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}
# ---------------------------------------------------------------------------

class TestAdminPatchUser(unittest.TestCase):

    def setUp(self):
        self.mock_table    = MagicMock()
        self.mock_loc_table = MagicMock()
        db.users_table     = self.mock_table
        db.locations_table = self.mock_loc_table
        self.mock_table.get_item.return_value     = {"Item": copy.deepcopy(ALICE)}
        self.mock_loc_table.get_item.return_value = {"Item": COLLIN_TX}
        updated = copy.deepcopy(ALICE)
        updated["role"] = "admin"
        self.mock_table.update_item.return_value = {"Attributes": updated}

    def _admin_token(self):
        return auth_helpers.create_access_token("admin-id", "admin")

    def _patch(self, body):
        return _call("PATCH", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                     body, headers=_bearer(self._admin_token()))

    def test_update_role_returns_200(self):
        resp = self._patch({"role": "admin"})
        self.assertEqual(resp["statusCode"], 200)

    def test_invalid_role_returns_400(self):
        resp = self._patch({"role": "superuser"})
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_status_returns_400(self):
        resp = self._patch({"status": "flying"})
        self.assertEqual(resp["statusCode"], 400)

    def test_non_admin_returns_403(self):
        token = auth_helpers.create_access_token("u1", "user")
        resp  = _call("PATCH", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                      {"role": "admin"}, headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 403)


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id}
# ---------------------------------------------------------------------------

class TestAdminDeleteUser(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        db.users_table  = self.mock_table
        self.mock_table.get_item.return_value = {"Item": copy.deepcopy(ALICE)}
        deleted = copy.deepcopy(ALICE)
        deleted["status"] = "inactive"
        self.mock_table.update_item.return_value = {"Attributes": deleted}

    def _admin_token(self):
        return auth_helpers.create_access_token("admin-id", "admin")

    def test_returns_200_and_status_inactive(self):
        token = self._admin_token()
        resp  = _call("DELETE", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(_body(resp)["user"]["status"], "inactive")

    def test_non_admin_returns_403(self):
        token = auth_helpers.create_access_token("u1", "user")
        resp  = _call("DELETE", f"{ADMIN_BASE}/user-uuid-001", {"user_id": "user-uuid-001"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 403)

    def test_not_found_returns_404(self):
        self.mock_table.get_item.return_value = {}
        token = self._admin_token()
        resp  = _call("DELETE", f"{ADMIN_BASE}/no-such", {"user_id": "no-such"},
                      headers=_bearer(token))
        self.assertEqual(resp["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
