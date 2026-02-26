#!/usr/bin/env python3
"""
Smoke tests for the deployed probate-leads API.

Exercises every major endpoint, creates and cleans up a test subscriber,
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
import datetime
import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
API_KEY  = os.environ.get("SMOKE_API_KEY", "")

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

def _headers(require_key: bool = True) -> dict:
    h = {"Content-Type": "application/json"}
    if require_key:
        h["x-api-key"] = API_KEY
    return h


def get(path: str, params: dict | None = None) -> requests.Response:
    return requests.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=TIMEOUT)


def post(path: str, body: dict, require_key: bool = True) -> requests.Response:
    return requests.post(
        f"{BASE}{path}", headers=_headers(require_key), json=body, timeout=TIMEOUT
    )


def patch(path: str, body: dict) -> requests.Response:
    return requests.patch(f"{BASE}{path}", headers=_headers(), json=body, timeout=TIMEOUT)


def delete(path: str) -> requests.Response:
    return requests.delete(f"{BASE}{path}", headers=_headers(), timeout=TIMEOUT)


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
# Leads
# ---------------------------------------------------------------------------

def test_leads() -> None:
    print(f"\n{YELLOW}── Leads ──────────────────────────────────────────────────────────────{RESET}")

    today      = datetime.date.today().isoformat()
    from_date  = "2020-01-01"

    r = get("/collin-tx/leads", params={"from_date": from_date, "to_date": today, "limit": "5"})
    if check("GET /collin-tx/leads → 200", r.status_code == 200, _snippet(r)):
        body = r.json()
        check("response has 'leads' array",    "leads"    in body, str(body.keys()))
        check("response has 'location' object", "location" in body)
        check("response has 'count' field",     "count"    in body)
        check("response has 'query' field",     "query"    in body)
        leads = body.get("leads", [])
        if leads:
            lead = leads[0]
            check("lead has docNumber",    "docNumber"    in lead)
            check("lead has recordedDate", "recordedDate" in lead)
            check("lead has locationCode", "locationCode" in lead)

    # limit is respected
    r = get("/collin-tx/leads", params={"from_date": from_date, "to_date": today, "limit": "2"})
    if check("GET /collin-tx/leads?limit=2 → 200", r.status_code == 200, _snippet(r)):
        leads = r.json().get("leads", [])
        check("at most 2 leads returned", len(leads) <= 2, f"got {len(leads)}")

    # unknown location → 404
    r = get("/no-such-county/leads", params={"from_date": from_date})
    check("GET /no-such-county/leads → 404", r.status_code == 404, _snippet(r))

    # no date params → most recent leads (200)
    r = get("/collin-tx/leads")
    if check("GET /collin-tx/leads (no dates) → 200", r.status_code == 200, _snippet(r)):
        check("no-date response has 'leads' array", "leads" in r.json())


# ---------------------------------------------------------------------------
# Subscribers (CRUD)
# ---------------------------------------------------------------------------

def test_subscribers() -> None:
    print(f"\n{YELLOW}── Subscribers ────────────────────────────────────────────────────────{RESET}")

    test_email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    subscriber_id: str | None = None

    # --- CREATE ---
    r = post("/subscribers", {"email": test_email, "location_codes": ["CollinTx"]})
    if check("POST /subscribers → 201", r.status_code == 201, _snippet(r)):
        sub = r.json().get("subscriber", {})
        subscriber_id = sub.get("subscriberId")
        check("response has subscriberId",  bool(subscriber_id))
        check("email matches",              sub.get("email") == test_email)
        check("status is active",           sub.get("status") == "active")
        check("locationCodes is a list",    isinstance(sub.get("locationCodes"), list))

    # --- validation: bad payload ---
    r = post("/subscribers", {"location_codes": ["CollinTx"]})  # missing email
    check("POST /subscribers (no email) → 400", r.status_code == 400, _snippet(r))

    r = post("/subscribers", {"email": test_email, "location_codes": ["DoesNotExist999"]})
    check("POST /subscribers (bad location) → 422", r.status_code == 422, _snippet(r))

    if subscriber_id:
        # --- READ ---
        r = get(f"/subscribers/{subscriber_id}")
        if check("GET /subscribers/{id} → 200", r.status_code == 200, _snippet(r)):
            sub = r.json().get("subscriber", {})
            check("subscriberId matches", sub.get("subscriberId") == subscriber_id)
            check("email matches",        sub.get("email") == test_email)

        # --- UPDATE ---
        r = patch(f"/subscribers/{subscriber_id}", {"status": "inactive"})
        if check("PATCH /subscribers/{id} → 200", r.status_code == 200, _snippet(r)):
            sub = r.json().get("subscriber", {})
            check("status updated to inactive", sub.get("status") == "inactive")

        r = patch(f"/subscribers/{subscriber_id}", {"status": "flying"})
        check("PATCH /subscribers/{id} (bad status) → 400", r.status_code == 400, _snippet(r))

        # --- DELETE (soft) ---
        r = delete(f"/subscribers/{subscriber_id}")
        if check("DELETE /subscribers/{id} → 200", r.status_code == 200, _snippet(r)):
            sub = r.json().get("subscriber", {})
            check("status set to inactive on delete", sub.get("status") == "inactive")

    # --- not found ---
    r = get(f"/subscribers/does-not-exist-{uuid.uuid4().hex}")
    check("GET /subscribers/nonexistent → 404", r.status_code == 404, _snippet(r))

    # --- auth: missing API key ---
    r = requests.get(f"{BASE}/subscribers", timeout=TIMEOUT)  # no x-api-key
    check("GET /subscribers (no API key) → 403", r.status_code == 403, _snippet(r))


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
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"  Smoke tests — {BASE_URL}")
    print(f"{'='*70}")

    test_locations()
    test_leads()
    test_subscribers()
    test_stripe_webhook()

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
