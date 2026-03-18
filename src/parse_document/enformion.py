"""
Enformion contact enrichment helper.

enrich_contacts(contacts, ap_name, ap_password) -> list[dict]

Enriches up to MAX_ENRICH non-deceased contacts in order, using the
Enformion Contact Enrichment API (POST /Contact/Enrich).

Fallback strategy:
  - If the API returns 0 matches or >1 match, retry with state="TX" added
    to the request.  If still ambiguous, skip enrichment for that contact.
  - If the API returns exactly 1 match, use it.
  - If an error occurs, record enrichment_status="error" and move on.

Returns a list of update dicts, each containing contact_id plus any
enriched fields (enriched_phone, enriched_email, enriched_name,
enriched_identity_score, enrichment_status, enriched_at).
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

ENFORMION_URL = "https://devapi.enformion.com/Contact/Enrich"
MAX_ENRICH = 10

# ---------------------------------------------------------------------------
# Name splitter
# ---------------------------------------------------------------------------

def _split_name(full_name: str) -> tuple[str, str]:
    """Split 'First Last' into (first, last). Handles multiple words."""
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


# ---------------------------------------------------------------------------
# Single-contact enrichment
# ---------------------------------------------------------------------------

def _enrich_one(
    contact_id: str,
    name: str,
    ap_name: str,
    ap_password: str,
    state_hint: Optional[str] = None,
) -> dict:
    """
    Call Enformion for one contact.  Returns a result dict.
    state_hint, when provided, is added to the request body as 'State'.
    """
    first, last = _split_name(name)
    if not first and not last:
        return {
            "contact_id":             contact_id,
            "enrichment_status":      "skipped",
            "enriched_at":            _now_iso(),
            "enriched_phone":         "",
            "enriched_email":         "",
            "enriched_name":          "",
            "enriched_identity_score": "",
        }

    body: dict = {"FirstName": first, "LastName": last}
    if state_hint:
        body["State"] = state_hint

    headers = {
        "galaxy-ap-name":     ap_name,
        "galaxy-ap-password": ap_password,
        "Content-Type":       "application/json",
    }

    try:
        resp = requests.post(ENFORMION_URL, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Enformion API error for contact %s: %s", contact_id, exc)
        return {
            "contact_id":             contact_id,
            "enrichment_status":      "error",
            "enriched_at":            _now_iso(),
            "enriched_phone":         "",
            "enriched_email":         "",
            "enriched_name":          "",
            "enriched_identity_score": "",
        }

    persons = data.get("Persons") or data.get("persons") or []
    count = len(persons)

    if count == 1:
        return _extract_fields(contact_id, persons[0])

    # 0 or multiple matches — caller should retry with TX
    return None  # type: ignore[return-value]  # signals "retry"


def _extract_fields(contact_id: str, person: dict) -> dict:
    """Extract the fields we care about from one Enformion person record."""
    # Phone — prefer mobile, fall back to first available
    phones = person.get("Phones") or person.get("phones") or []
    phone = ""
    for p in phones:
        if isinstance(p, dict):
            num = p.get("Phone") or p.get("phone") or p.get("Number") or p.get("number") or ""
            ptype = (p.get("Type") or p.get("type") or "").lower()
            if num and ptype in ("mobile", "cell"):
                phone = num
                break
    if not phone and phones:
        first = phones[0]
        if isinstance(first, dict):
            phone = (
                first.get("Phone") or first.get("phone") or
                first.get("Number") or first.get("number") or ""
            )
        elif isinstance(first, str):
            phone = first

    # Email — first available
    emails = person.get("Emails") or person.get("emails") or []
    email = ""
    for e in emails:
        if isinstance(e, dict):
            email = e.get("Email") or e.get("email") or e.get("Address") or e.get("address") or ""
        elif isinstance(e, str):
            email = e
        if email:
            break

    # Full name from record
    first_n = person.get("FirstName") or person.get("firstName") or ""
    last_n  = person.get("LastName")  or person.get("lastName")  or ""
    enriched_name = " ".join(filter(None, [first_n, last_n]))

    # Identity score
    score = str(
        person.get("IdentityScore") or person.get("identityScore") or
        person.get("Score") or person.get("score") or ""
    )

    return {
        "contact_id":              contact_id,
        "enrichment_status":       "success",
        "enriched_at":             _now_iso(),
        "enriched_phone":          phone,
        "enriched_email":          email,
        "enriched_name":           enriched_name,
        "enriched_identity_score": score,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_contacts(
    contacts: list[dict],
    ap_name: str,
    ap_password: str,
) -> list[dict]:
    """
    Enrich up to MAX_ENRICH non-deceased contacts.

    contacts: list of dicts with at minimum 'contact_id', 'name', 'role'.
    Returns a list of result dicts (one per contact attempted).
    """
    if not ap_name or not ap_password:
        log.warning("Enformion credentials not set — skipping enrichment")
        return []

    # Filter: skip deceased, take first MAX_ENRICH
    eligible = [
        c for c in contacts
        if (c.get("role") or "").lower() != "deceased"
    ][:MAX_ENRICH]

    if not eligible:
        return []

    results: list[dict] = []

    def _work(contact: dict) -> dict:
        cid  = contact["contact_id"]
        name = contact.get("name") or ""
        if not name.strip():
            return {
                "contact_id":              cid,
                "enrichment_status":       "skipped",
                "enriched_at":             _now_iso(),
                "enriched_phone":          "",
                "enriched_email":          "",
                "enriched_name":           "",
                "enriched_identity_score": "",
            }

        result = _enrich_one(cid, name, ap_name, ap_password)
        if result is None:
            # 0 or >1 match — retry with TX
            result = _enrich_one(cid, name, ap_name, ap_password, state_hint="TX")
        if result is None:
            # Still ambiguous after TX fallback
            result = {
                "contact_id":              cid,
                "enrichment_status":       "no_match",
                "enriched_at":             _now_iso(),
                "enriched_phone":          "",
                "enriched_email":          "",
                "enriched_name":           "",
                "enriched_identity_score": "",
            }
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_work, c): c for c in eligible}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                contact = futures[fut]
                log.error("Enformion worker error for %s: %s", contact.get("contact_id"), exc)
                results.append({
                    "contact_id":              contact.get("contact_id", ""),
                    "enrichment_status":       "error",
                    "enriched_at":             _now_iso(),
                    "enriched_phone":          "",
                    "enriched_email":          "",
                    "enriched_name":           "",
                    "enriched_identity_score": "",
                })

    return results
