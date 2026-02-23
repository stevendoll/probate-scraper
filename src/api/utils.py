"""
Stateless helper utilities for the probate-leads API.

All functions are pure (no I/O, no DynamoDB) so they can be tested
without any mocking or patching.
"""

import base64
import json
from datetime import datetime, timezone


def parse_date(s: str) -> str | None:
    """Return *s* if it is a valid ``YYYY-MM-DD`` string, otherwise ``None``."""
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def encode_key(last_evaluated_key: dict) -> str:
    """Base-64-encode a DynamoDB ``LastEvaluatedKey`` for use as a pagination cursor."""
    return base64.b64encode(
        json.dumps(last_evaluated_key, default=str).encode()
    ).decode()


def decode_key(encoded: str) -> dict | None:
    """Decode a pagination cursor produced by :func:`encode_key`.

    Returns ``None`` if the string is not valid base-64 JSON.
    """
    try:
        return json.loads(base64.b64decode(encoded.encode()).decode())
    except Exception:
        return None


def normalize_timestamp(ts: str) -> str:
    """Normalize any ISO timestamp to 3-decimal-millisecond UTC with Z suffix."""
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return ts


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
