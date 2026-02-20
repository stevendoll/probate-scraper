"""
local_api_server.py — run the ApiFunction Lambda handler as a local HTTP server.

Usage:
    pipenv run python scripts/local_api_server.py [port]

Defaults to port 3000. Connects to DynamoDB Local at http://localhost:8000.

Supported routes:
  GET  /real-estate/probate-leads/{location_path}/leads
  GET  /real-estate/probate-leads/locations
  GET  /real-estate/probate-leads/locations/{location_code}
  GET  /real-estate/probate-leads/subscribers
  POST /real-estate/probate-leads/subscribers
  GET  /real-estate/probate-leads/subscribers/{subscriber_id}
  PATCH /real-estate/probate-leads/subscribers/{subscriber_id}
  DELETE /real-estate/probate-leads/subscribers/{subscriber_id}
  POST /real-estate/probate-leads/stripe/webhook
"""

import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

# ── env vars (must be set before importing app) ────────────────────────────────
os.environ.setdefault("AWS_ENDPOINT_URL",        "http://localhost:8000")
os.environ.setdefault("AWS_ACCESS_KEY_ID",       "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY",   "local")
os.environ.setdefault("AWS_DEFAULT_REGION",      "us-east-1")
os.environ.setdefault("DYNAMO_TABLE_NAME",       "leads")
os.environ.setdefault("LOCATIONS_TABLE_NAME",    "locations")
os.environ.setdefault("SUBSCRIBERS_TABLE_NAME",  "subscribers")
os.environ.setdefault("GSI_NAME",                "recorded-date-index")
os.environ.setdefault("LOCATION_DATE_GSI",       "location-date-index")
os.environ.setdefault("STRIPE_SECRET_KEY",       "")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET",   "")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("LOG_LEVEL",               "INFO")

# ── mock Tracer (aws-xray-sdk not needed locally) ─────────────────────────────
_mock_tracer = MagicMock()
_mock_tracer.capture_lambda_handler = lambda f: f
_mock_tracer.capture_method = lambda f: f

# ── load the Lambda handler ───────────────────────────────────────────────────
_src_api_path = os.path.join(os.path.dirname(__file__), "..", "src", "api")
# Ensure stripe_helpers.py is importable from the same package
sys.path.insert(0, _src_api_path)

_api_file = os.path.join(_src_api_path, "app.py")

with patch("aws_lambda_powertools.Tracer", return_value=_mock_tracer):
    spec = importlib.util.spec_from_file_location("api_app", _api_file)
    api_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_app)

handler_fn = api_app.handler

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

        # /locations/{location_code}
        if len(parts) == 2 and parts[0] == "locations":
            return {"location_code": parts[1]}

        # /subscribers/{subscriber_id}
        if len(parts) == 2 and parts[0] == "subscribers":
            return {"subscriber_id": parts[1]}

        return None

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        if not parsed.path.startswith(BASE_PATH):
            self._send(404, {"error": f"Not found: {parsed.path}"})
            return

        qs_raw = parse_qs(parsed.query, keep_blank_values=True)
        qs     = {k: v[0] for k, v in qs_raw.items()}
        body   = self._read_body() if method in ("POST", "PATCH", "PUT") else None

        event  = self._build_event(method, parsed.path, qs, body, dict(self.headers))
        result = handler_fn(event, _LocalContext())

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

    def _send(self, status: int, body: dict, extra_headers: dict | None = None):
        payload = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (extra_headers or {}).items():
            if k.lower() != "content-type":
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} [{self.command}] {fmt % args}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"Local API server running at http://localhost:{port}")
    print(f"  DynamoDB → {os.environ['AWS_ENDPOINT_URL']}")
    print(f"  Tables   → leads={os.environ['DYNAMO_TABLE_NAME']}")
    print(f"             locations={os.environ['LOCATIONS_TABLE_NAME']}")
    print(f"             subscribers={os.environ['SUBSCRIBERS_TABLE_NAME']}")
    print(f"\n  Sample routes:")
    print(f"    GET  http://localhost:{port}{BASE_PATH}/locations")
    print(f"    GET  http://localhost:{port}{BASE_PATH}/collin-tx/leads?from_date=2026-01-01")
    print(f"    POST http://localhost:{port}{BASE_PATH}/subscribers")
    print("  Ctrl+C to stop\n")
    HTTPServer(("", port), LambdaHandler).serve_forever()
