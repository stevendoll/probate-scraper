"""
local_api_server.py — run the ApiFunction Lambda handler as a local HTTP server.

Usage:
    pipenv run python scripts/local_api_server.py [port]

Defaults to port 3000. Connects to DynamoDB Local at http://localhost:8000.
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
os.environ.setdefault("DYNAMO_TABLE_NAME",       "probate-leads-collin-tx")
os.environ.setdefault("GSI_NAME",               "recorded-date-index")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("LOG_LEVEL",              "INFO")

# ── mock Tracer (aws-xray-sdk not needed locally) ─────────────────────────────
_mock_tracer = MagicMock()
_mock_tracer.capture_lambda_handler = lambda f: f
_mock_tracer.capture_method = lambda f: f

# ── load the Lambda handler ───────────────────────────────────────────────────
_api_path = os.path.join(os.path.dirname(__file__), "..", "src", "api", "app.py")

with patch("aws_lambda_powertools.Tracer", return_value=_mock_tracer):
    spec = importlib.util.spec_from_file_location("api_app", _api_path)
    api_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api_app)

handler_fn = api_app.handler

# ── mock Lambda context (required by @logger.inject_lambda_context) ───────────
class _LocalContext:
    aws_request_id       = "local-dev"
    function_name        = "probate-api-local"
    memory_limit_in_mb   = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:local"
    log_stream_name      = "local"


API_PREFIX = "/real-estate/probate-leads/collin-tx/leads"


class LambdaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != API_PREFIX:
            self._send(404, {"error": f"Not found: {parsed.path}"})
            return

        qs_raw = parse_qs(parsed.query, keep_blank_values=True)
        qs = {k: v[0] for k, v in qs_raw.items()}

        event = {
            "httpMethod": "GET",
            "path": parsed.path,
            "queryStringParameters": qs or None,
            "headers": dict(self.headers),
            "body": None,
            "isBase64Encoded": False,
        }

        result = handler_fn(event, _LocalContext())
        all_headers = {**result.get("headers", {}), **result.get("multiValueHeaders", {})}
        self._send(result["statusCode"], json.loads(result["body"]), all_headers)

    def _send(self, status, body, extra_headers=None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (extra_headers or {}).items():
            if k.lower() != "content-type":
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"Local API server running at http://localhost:{port}")
    print(f"  GET http://localhost:{port}{API_PREFIX}")
    print(f"  DynamoDB → {os.environ['AWS_ENDPOINT_URL']}")
    print("  Ctrl+C to stop\n")
    HTTPServer(("", port), LambdaHandler).serve_forever()
