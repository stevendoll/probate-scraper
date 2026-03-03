"""
local_api_server.py — run the ApiFunction, TriggerFunction, and
ParseDocumentFunction Lambda handlers as a single local HTTP server.

Usage:
    pipenv run python scripts/local_api_server.py [port]

Defaults to port 3000. Connects to DynamoDB Local at http://localhost:8000.

Supported routes:
  GET    /real-estate/probate-leads/{location_path}/leads
  GET    /real-estate/probate-leads/locations
  GET    /real-estate/probate-leads/locations/{location_code}
  GET    /real-estate/probate-leads/users
  POST   /real-estate/probate-leads/users
  GET    /real-estate/probate-leads/users/{user_id}
  PATCH  /real-estate/probate-leads/users/{user_id}
  DELETE /real-estate/probate-leads/users/{user_id}
  POST   /real-estate/probate-leads/stripe/webhook
  POST   /real-estate/probate-leads/{location_path}/update   (ECS stubbed locally)
  POST   /real-estate/probate-leads/leads/{lead_id}/parse-document
           (calls real Bedrock + S3; requires DOCUMENTS_BUCKET env var and
            AWS credentials with bedrock:InvokeModel + s3:GetObject access)
"""

import importlib.util
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ── env vars (must be set before importing app) ────────────────────────────────
os.environ.setdefault("AWS_ENDPOINT_URL_DYNAMODB", "http://localhost:8000")
os.environ.setdefault("AWS_ACCESS_KEY_ID",       "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY",   "local")
os.environ.setdefault("AWS_DEFAULT_REGION",      "us-east-1")
os.environ.setdefault("DYNAMO_TABLE_NAME",       "leads")
os.environ.setdefault("LOCATIONS_TABLE_NAME",    "locations")
os.environ.setdefault("USERS_TABLE_NAME",        "users")
os.environ.setdefault("GSI_NAME",                "recorded-date-index")
os.environ.setdefault("LOCATION_DATE_GSI",       "location-date-index")
os.environ.setdefault("STRIPE_SECRET_KEY",       "")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET",   "")
os.environ.setdefault("JWT_SECRET",          "dev-secret-change-in-prod")
os.environ.setdefault("FROM_EMAIL",          "")
os.environ.setdefault("MAGIC_LINK_BASE_URL", "http://localhost:3000/auth/verify")
os.environ.setdefault("UI_BASE_URL",         "http://localhost:3001")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("LOG_LEVEL",               "INFO")
os.environ.setdefault("DOCUMENTS_BUCKET",         "")
os.environ.setdefault("BEDROCK_MODEL_ID",         "us.anthropic.claude-3-5-haiku-20241022-v1:0")

# Dummy ECS env vars so the TriggerFunction handler can be imported
os.environ.setdefault("ECS_CLUSTER_ARN",     "arn:aws:ecs:us-east-1:000000000000:cluster/local")
os.environ.setdefault("TASK_DEFINITION_ARN", "arn:aws:ecs:us-east-1:000000000000:task-definition/local:1")
os.environ.setdefault("TASK_SUBNETS",        "subnet-00000000000000000")
os.environ.setdefault("TASK_SECURITY_GROUP", "sg-00000000000000000")

# ── mock Tracer (aws-xray-sdk not needed locally) ─────────────────────────────
_mock_tracer = MagicMock()
_mock_tracer.capture_lambda_handler = lambda f: f
_mock_tracer.capture_method = lambda f: f

# ── load the ApiFunction handler ──────────────────────────────────────────────
# Add src/api/ to sys.path so that app.py and all its sub-modules
# (db, models, utils, routers/*) are importable as top-level packages.
_src_api_path = os.path.join(os.path.dirname(__file__), "..", "src", "api")
sys.path.insert(0, os.path.abspath(_src_api_path))

with patch("aws_lambda_powertools.Tracer", return_value=_mock_tracer):
    import app as _api_app  # noqa: E402

api_handler = _api_app.handler

# ── load the TriggerFunction handler (with ECS stubbed) ───────────────────────
# The trigger handler creates `ecs = boto3.client("ecs")` at module load time.
# We intercept that with a mock so no real ECS calls are made locally.
_mock_ecs = MagicMock()
_mock_ecs.run_task.return_value = {
    "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:000000000000:task/local-stub"}],
    "failures": [],
}

_trigger_file = os.path.join(os.path.dirname(__file__), "..", "src", "trigger", "app.py")
with patch("boto3.client", return_value=_mock_ecs):
    _tspec = importlib.util.spec_from_file_location("_trigger_app", _trigger_file)
    _trigger_mod = importlib.util.module_from_spec(_tspec)
    _tspec.loader.exec_module(_trigger_mod)

trigger_handler = _trigger_mod.handler

# ── load the ParseDocumentFunction handler ────────────────────────────────────
# Uses real AWS credentials for Bedrock + S3 (set DOCUMENTS_BUCKET to your
# bucket name and ensure your shell credentials have the required permissions).
# DynamoDB calls still hit DynamoDB Local.
_parse_doc_src = os.path.join(os.path.dirname(__file__), "..", "src", "parse_document")
sys.path.insert(0, os.path.abspath(_parse_doc_src))

_parse_doc_file = os.path.join(_parse_doc_src, "app.py")
_pdspec = importlib.util.spec_from_file_location("_parse_document_app", _parse_doc_file)
_parse_doc_mod = importlib.util.module_from_spec(_pdspec)
_pdspec.loader.exec_module(_parse_doc_mod)

# Point parse-document's DynamoDB table at DynamoDB Local
_parse_doc_mod._table = _parse_doc_mod._dynamodb.Table(os.environ["DYNAMO_TABLE_NAME"])

parse_document_handler = _parse_doc_mod.handler


# ── mock Lambda context ────────────────────────────────────────────────────────
class _LocalContext:
    aws_request_id       = "local-dev"
    function_name        = "probate-api-local"
    memory_limit_in_mb   = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:local"
    log_stream_name      = "local"


BASE_PATH = "/real-estate/probate-leads"


class LambdaHandler(BaseHTTPRequestHandler):

    def _build_event(self, method: str, path: str, qs: dict, body: bytes | None,
                     headers: dict) -> dict:
        return {
            "httpMethod": method,
            "path": path,
            "pathParameters": self._extract_path_params(path),
            "queryStringParameters": qs or None,
            "headers": headers,
            "body": body.decode() if body else None,
            "isBase64Encoded": False,
        }

    def _extract_path_params(self, path: str) -> dict | None:
        """
        Map the request path to API Gateway-style path parameters.
        Returns a dict (possibly empty) or None.
        """
        suffix = path[len(BASE_PATH):]   # e.g. "/collin-tx/leads"
        parts  = [p for p in suffix.split("/") if p]

        # /{location_path}/leads
        if len(parts) == 2 and parts[1] == "leads":
            return {"location_path": parts[0]}

        # /{location_path}/update
        if len(parts) == 2 and parts[1] == "update":
            return {"location_path": parts[0]}

        # /locations/{location_code}
        if len(parts) == 2 and parts[0] == "locations":
            return {"location_code": parts[1]}

        # /users/{user_id}
        if len(parts) == 2 and parts[0] == "users":
            return {"user_id": parts[1]}

        # /admin/users/{user_id}
        if len(parts) == 3 and parts[0] == "admin" and parts[1] == "users":
            return {"user_id": parts[2]}

        # /leads/{lead_id}/parse-document
        if len(parts) == 3 and parts[0] == "leads" and parts[2] == "parse-document":
            return {"lead_id": parts[1]}

        return None

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        if not parsed.path.startswith(BASE_PATH):
            self._send(404, {"error": f"Not found: {parsed.path}"})
            return

        suffix = parsed.path[len(BASE_PATH):]
        parts  = [p for p in suffix.split("/") if p]
        qs_raw = parse_qs(parsed.query, keep_blank_values=True)
        qs     = {k: v[0] for k, v in qs_raw.items()}
        body   = self._read_body() if method in ("POST", "PATCH", "PUT") else None

        # POST /leads/{lead_id}/parse-document → ParseDocumentFunction
        if (method == "POST" and len(parts) == 3
                and parts[0] == "leads" and parts[2] == "parse-document"):
            event  = self._build_event(method, parsed.path, qs, body, dict(self.headers))
            result = parse_document_handler(event, _LocalContext())
            all_headers = {**result.get("headers", {}), **result.get("multiValueHeaders", {})}
            body_str = result.get("body", "{}")
            try:
                body_obj = json.loads(body_str)
            except Exception:
                body_obj = {"raw": body_str}
            self._send(result["statusCode"], body_obj, all_headers)
            return

        # POST /{location_path}/update → TriggerFunction (ECS stubbed locally)
        if method == "POST" and len(parts) == 2 and parts[1] == "update":
            event  = self._build_event(method, parsed.path, qs, body, dict(self.headers))
            result = trigger_handler(event, _LocalContext())
            all_headers = {**result.get("headers", {}), **result.get("multiValueHeaders", {})}
            body_str = result.get("body", "{}")
            try:
                body_obj = json.loads(body_str)
                # Annotate so callers know this is the local stub
                body_obj["_local"] = "ECS task was not started — this is a local dev stub"
            except Exception:
                body_obj = {"raw": body_str}
            self._send(result["statusCode"], body_obj, all_headers)
            return

        # All other routes → ApiFunction
        event  = self._build_event(method, parsed.path, qs, body, dict(self.headers))
        result = api_handler(event, _LocalContext())

        all_headers = {**result.get("headers", {}), **result.get("multiValueHeaders", {})}
        body_str    = result.get("body", "{}")
        try:
            body_obj = json.loads(body_str)
        except Exception:
            body_obj = {"raw": body_str}

        self._send(result["statusCode"], body_obj, all_headers)

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_PATCH(self):  self._dispatch("PATCH")
    def do_DELETE(self): self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _add_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-api-key")

    def _send(self, status: int, body: dict, extra_headers: dict | None = None):
        payload = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._add_cors_headers()
        for k, v in (extra_headers or {}).items():
            kl = k.lower()
            if kl == "content-type" or kl.startswith("access-control-"):
                continue
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} [{self.command}] {fmt % args}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"Local API server running at http://localhost:{port}")
    print(f"  DynamoDB → {os.environ['AWS_ENDPOINT_URL_DYNAMODB']}")
    print(f"  Tables   → leads={os.environ['DYNAMO_TABLE_NAME']}")
    print(f"             locations={os.environ['LOCATIONS_TABLE_NAME']}")
    print(f"             users={os.environ['USERS_TABLE_NAME']}")
    print(f"\n  Sample routes:")
    print(f"    GET  http://localhost:{port}{BASE_PATH}/locations")
    print(f"    GET  http://localhost:{port}{BASE_PATH}/collin-tx/leads?from_date=2026-01-01")
    print(f"    POST http://localhost:{port}{BASE_PATH}/users")
    print(f"    POST http://localhost:{port}{BASE_PATH}/collin-tx/update   (ECS stubbed)")
    print(f"    POST http://localhost:{port}{BASE_PATH}/leads/{{lead_id}}/parse-document")
    print("  Ctrl+C to stop\n")
    HTTPServer(("", port), LambdaHandler).serve_forever()
