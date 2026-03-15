#!/usr/bin/env python3
"""
Smoke tests for the deployed probate-leads API.

Exercises every major endpoint, creates and cleans up a test user,
and exits non-zero if any check fails.

Usage:
    SMOKE_BASE_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com/prod \\
    SMOKE_API_KEY=<key-value> \\
    python scripts/smoke_test.py

Environment variables:
    SMOKE_BASE_URL   API Gateway base URL (no trailing slash)
    SMOKE_API_KEY    API key value (x-api-key header)
"""

import os
import sys
import uuid
import json
import time
import datetime
import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
API_KEY  = os.environ.get("SMOKE_API_KEY", "")
UI_URL   = os.environ.get("SMOKE_UI_URL", "").rstrip("/")

if not BASE_URL:
    print("ERROR: SMOKE_BASE_URL is not set", file=sys.stderr)
    sys.exit(1)
if not API_KEY:
    print("ERROR: SMOKE_API_KEY is not set", file=sys.stderr)
    sys.exit(1)

BASE = f"{BASE_URL}/real-estate/probate-leads"
TIMEOUT = 20  # seconds per request

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def ok(name: str) -> None:
    global _passed
    _passed += 1
    print(f"  {GREEN}✓{RESET}  {name}")


def fail(name: str, details: str = "") -> None:
    global _failed
    _failed += 1
    msg = f"  {RED}✗{RESET}  {name}"
    if details:
        msg += f"\n       {YELLOW}{details}{RESET}"
    print(msg)


def check(name: str, condition: bool, details: str = "") -> bool:
    if condition:
        ok(name)
    else:
        fail(name, details)
    return condition


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_RETRY_STATUSES = {502, 503, 504}   # transient server errors worth retrying
_MAX_RETRIES    = 3
_RETRY_DELAY    = 5  # seconds between retries


def _headers(require_key: bool = True) -> dict:
    h = {"Content-Type": "application/json"}
    if require_key:
        h["x-api-key"] = API_KEY
    return h


def _retry(fn, *args, **kwargs) -> requests.Response:
    """Call *fn* up to _MAX_RETRIES times, retrying on transient server errors."""
    for attempt in range(1, _MAX_RETRIES + 1):
        r = fn(*args, **kwargs)
        if r.status_code not in _RETRY_STATUSES:
            return r
        if attempt < _MAX_RETRIES:
            print(f"       {YELLOW}⟳  HTTP {r.status_code} — retrying in {_RETRY_DELAY}s "
                  f"(attempt {attempt}/{_MAX_RETRIES}){RESET}")
            time.sleep(_RETRY_DELAY)
    return r


def get(path: str, params: dict | None = None) -> requests.Response:
    return _retry(requests.get, f"{BASE}{path}", headers=_headers(), params=params, timeout=TIMEOUT)


def post(path: str, body: dict, require_key: bool = True) -> requests.Response:
    return _retry(
        requests.post,
        f"{BASE}{path}", headers=_headers(require_key), json=body, timeout=TIMEOUT,
    )


def patch(path: str, body: dict) -> requests.Response:
    return _retry(requests.patch, f"{BASE}{path}", headers=_headers(), json=body, timeout=TIMEOUT)


def delete(path: str) -> requests.Response:
    return _retry(requests.delete, f"{BASE}{path}", headers=_headers(), timeout=TIMEOUT)


def _snippet(r: requests.Response) -> str:
    """Short summary of a response for failure messages."""
    return f"HTTP {r.status_code}: {r.text[:160]}"


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def test_locations() -> None:
    print(f"\n{YELLOW}── Locations ──────────────────────────────────────────────────────────{RESET}")

    r = get("/locations")
    if check("GET /locations → 200", r.status_code == 200, _snippet(r)):
        body = r.json()
        check("response has 'locations' array", "locations" in body, str(body.keys()))
        check("response has 'count' field",     "count"     in body)
        check(
            "CollinTx is present",
            any(loc.get("locationCode") == "CollinTx" for loc in body.get("locations", [])),
            "CollinTx not found in locations list",
        )

    r = get("/locations/CollinTx")
    if check("GET /locations/CollinTx → 200", r.status_code == 200, _snippet(r)):
        loc = r.json().get("location", {})
        check("locationCode == CollinTx",    loc.get("locationCode") == "CollinTx")
        check("locationPath == collin-tx",   loc.get("locationPath") == "collin-tx")
        check("locationName is present",     bool(loc.get("locationName")))
        check("searchUrl is present",        bool(loc.get("searchUrl")))

    r = get("/locations/DoesNotExist999")
    check("GET /locations/DoesNotExist999 → 404", r.status_code == 404, _snippet(r))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_documents() -> None:
    print(f"\n{YELLOW}── Documents ──────────────────────────────────────────────────────────{RESET}")

    today      = datetime.date.today().isoformat()
    from_date  = "2020-01-01"

    r = get("/collin-tx/documents", params={"from_date": from_date, "to_date": today, "limit": "5"})
    if check("GET /collin-tx/documents → 200", r.status_code == 200, _snippet(r)):
        body = r.json()
        check("response has 'documents' array",  "documents" in body, str(body.keys()))
        check("response has 'location' object",  "location"  in body)
        check("response has 'count' field",      "count"     in body)
        check("response has 'query' field",      "query"     in body)
        documents = body.get("documents", [])
        if documents:
            doc = documents[0]
            check("document has docNumber",    "docNumber"    in doc)
            check("document has recordedDate", "recordedDate" in doc)
            check("document has locationCode", "locationCode" in doc)

    # limit is respected
    r = get("/collin-tx/documents", params={"from_date": from_date, "to_date": today, "limit": "2"})
    if check("GET /collin-tx/documents?limit=2 → 200", r.status_code == 200, _snippet(r)):
        documents = r.json().get("documents", [])
        check("at most 2 documents returned", len(documents) <= 2, f"got {len(documents)}")

    # unknown location → 404
    r = get("/no-such-county/documents", params={"from_date": from_date})
    check("GET /no-such-county/documents → 404", r.status_code == 404, _snippet(r))

    # no date params → most recent documents (200)
    r = get("/collin-tx/documents")
    if check("GET /collin-tx/documents (no dates) → 200", r.status_code == 200, _snippet(r)):
        check("no-date response has 'documents' array", "documents" in r.json())


# ---------------------------------------------------------------------------
# Users (CRUD)
# ---------------------------------------------------------------------------

def test_users() -> None:
    print(f"\n{YELLOW}── Users ──────────────────────────────────────────────────────────────{RESET}")

    test_email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    user_id: str | None = None

    try:
        # --- CREATE ---
        r = post("/users", {"email": test_email, "location_codes": ["CollinTx"]})
        if check("POST /users → 201", r.status_code == 201, _snippet(r)):
            user = r.json().get("user", {})
            user_id = user.get("userId")
            check("response has userId",        bool(user_id))
            check("email matches",              user.get("email") == test_email)
            check("status is active",           user.get("status") == "active")
            check("locationCodes is a list",    isinstance(user.get("locationCodes"), list))

        # --- validation: bad payload ---
        r = post("/users", {"location_codes": ["CollinTx"]})  # missing email
        check("POST /users (no email) → 400", r.status_code == 400, _snippet(r))

        r = post("/users", {"email": test_email, "location_codes": ["DoesNotExist999"]})
        check("POST /users (bad location) → 422", r.status_code == 422, _snippet(r))

        if user_id:
            # --- READ ---
            r = get(f"/users/{user_id}")
            if check("GET /users/{id} → 200", r.status_code == 200, _snippet(r)):
                user = r.json().get("user", {})
                check("userId matches", user.get("userId") == user_id)
                check("email matches",  user.get("email") == test_email)

            # --- UPDATE ---
            r = patch(f"/users/{user_id}", {"status": "inactive"})
            if check("PATCH /users/{id} → 200", r.status_code == 200, _snippet(r)):
                user = r.json().get("user", {})
                check("status updated to inactive", user.get("status") == "inactive")

            r = patch(f"/users/{user_id}", {"status": "flying"})
            check("PATCH /users/{id} (bad status) → 400", r.status_code == 400, _snippet(r))

            # --- DELETE (soft) ---
            r = delete(f"/users/{user_id}")
            if check("DELETE /users/{id} → 200", r.status_code == 200, _snippet(r)):
                user = r.json().get("user", {})
                check("status set to inactive on delete", user.get("status") == "inactive")

        # --- not found ---
        r = get(f"/users/does-not-exist-{uuid.uuid4().hex}")
        check("GET /users/nonexistent → 404", r.status_code == 404, _snippet(r))

        # --- auth: missing API key ---
        r = requests.get(f"{BASE}/users", timeout=TIMEOUT)  # no x-api-key
        check("GET /users (no API key) → 403", r.status_code == 403, _snippet(r))

    finally:
        # Always clean up the test user even if assertions above failed.
        if user_id:
            delete(f"/users/{user_id}")


# ---------------------------------------------------------------------------
# Auth — CORS preflight + unauthenticated access
# ---------------------------------------------------------------------------

def test_auth_cors() -> None:
    print(f"\n{YELLOW}── Auth / CORS ─────────────────────────────────────────────────────────{RESET}")

    # OPTIONS preflight must succeed without an API key (browsers never send
    # x-api-key in CORS preflight requests).
    r = _retry(
        requests.options,
        f"{BASE}/auth/request-login",
        headers={
            "Origin": UI_URL or "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=TIMEOUT,
    )
    if check("OPTIONS /auth/request-login (no API key) → 200 or 204", r.status_code in (200, 204), _snippet(r)):
        check(
            "CORS: access-control-allow-origin present",
            "access-control-allow-origin" in r.headers,
            str(dict(r.headers)),
        )
        check(
            "CORS: access-control-allow-methods includes POST",
            "POST" in r.headers.get("access-control-allow-methods", ""),
            r.headers.get("access-control-allow-methods", ""),
        )

    # POST /auth/request-login must accept requests without an API key.
    r = post("/auth/request-login", {"email": "smoke-noreply@example.com"}, require_key=False)
    check(
        "POST /auth/request-login (no API key) → 200",
        r.status_code == 200,
        _snippet(r),
    )

    # GET /auth/verify with a bogus token must return 401 (not 403/404).
    r = _retry(
        requests.get,
        f"{BASE}/auth/verify",
        params={"token": "not-a-real-token"},
        headers={"Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    check(
        "GET /auth/verify (bad token) → 401",
        r.status_code == 401,
        _snippet(r),
    )


# ---------------------------------------------------------------------------
# UI — CloudFront SPA reachability
# ---------------------------------------------------------------------------

def test_ui() -> None:
    if not UI_URL:
        return
    print(f"\n{YELLOW}── UI ({UI_URL}) ────────────────────────────────────────────────────────{RESET}")

    r = _retry(requests.get, UI_URL + "/", timeout=TIMEOUT)
    if check("GET / → 200", r.status_code == 200, _snippet(r)):
        ct = r.headers.get("content-type", "")
        check("Content-Type is text/html", "text/html" in ct, ct)
        check("HTML has <div id=\"root\">", '<div id="root">' in r.text, "(root div missing)")
        check("HTML references a JS bundle", ".js" in r.text, "(no JS script tag found)")

    # Deep-link (non-root path) must also serve index.html (SPA routing).
    r = _retry(requests.get, UI_URL + "/auth/verify", timeout=TIMEOUT)
    check(
        "GET /auth/verify (deep-link) → 200 with HTML",
        r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
        _snippet(r),
    )


# ---------------------------------------------------------------------------
# Stripe webhook (basic reachability — no real signature)
# ---------------------------------------------------------------------------

def test_stripe_webhook() -> None:
    print(f"\n{YELLOW}── Stripe webhook ─────────────────────────────────────────────────────{RESET}")

    # POST without a signature — if STRIPE_WEBHOOK_SECRET is set in prod this
    # will return 400 (bad signature), otherwise 200 (ignored event).
    # Either way, the endpoint must be reachable (not 404/503).
    payload = {
        "type": "some.unknown.event",
        "data": {"object": {"id": "sub_smoke", "customer": "cus_smoke", "status": "active"}},
    }
    r = post("/stripe/webhook", payload, require_key=False)
    check(
        "POST /stripe/webhook is reachable (200 or 400)",
        r.status_code in (200, 400),
        _snippet(r),
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_smoke_users() -> None:
    """Delete any lingering smoke-test users (email starts with 'smoke-')."""
    r = get("/users")
    if r.status_code != 200:
        return
    users = r.json().get("users", [])
    smoke_ids = [u["userId"] for u in users if u.get("email", "").startswith("smoke-")]
    if smoke_ids:
        print(f"\n{YELLOW}── Cleanup — removing {len(smoke_ids)} smoke user(s) ──────────────────{RESET}")
        for uid in smoke_ids:
            delete(f"/users/{uid}")
            print(f"  {GREEN}✓{RESET}  deleted {uid}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"  Smoke tests — {BASE_URL}")
    print(f"{'='*70}")

    test_locations()
    test_documents()
    test_users()
    test_stripe_webhook()
    test_auth_cors()
    test_ui()
    cleanup_smoke_users()

    print(f"\n{'='*70}")
    total = _passed + _failed
    if _failed:
        print(f"  {RED}FAILED{RESET}  {_failed}/{total} checks failed")
        print(f"{'='*70}\n")
        sys.exit(1)
    else:
        print(f"  {GREEN}PASSED{RESET}  All {total} checks passed")
        print(f"{'='*70}\n")
        sys.exit(0)
