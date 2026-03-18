"""
Unit tests for src/parse_document/enformion.py

Covers:
  - Successful single-match enrichment with phone/email extraction
  - Zero-match triggers TX fallback; TX fallback returns single match
  - Zero-match with TX fallback still zero → no_match
  - Multiple matches triggers TX fallback
  - API error → error status
  - Deceased contacts are skipped
  - Contacts without names are skipped
  - Limit capped at MAX_ENRICH (10)
  - Missing credentials returns empty list immediately
  - _split_name helper
  - _extract_fields helper
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure enformion.py is importable
_PARSE_DOC_SRC = os.path.join(os.path.dirname(__file__), "..", "src", "parse_document")
sys.path.insert(0, _PARSE_DOC_SRC)

from enformion import enrich_contacts, _split_name, _extract_fields, MAX_ENRICH  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contact(cid: str, name: str, role: str = "executor") -> dict:
    return {"contact_id": cid, "name": name, "role": role}


def _api_response(persons: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"Persons": persons}
    return mock_resp


_SENTINEL = object()

def _person(first="John", last="Smith", phones=_SENTINEL, emails=_SENTINEL, score="95"):
    return {
        "FirstName": first,
        "LastName": last,
        "Phones": [{"Phone": "5551234567", "Type": "Mobile"}] if phones is _SENTINEL else phones,
        "Emails": [{"Email": "john@example.com"}] if emails is _SENTINEL else emails,
        "IdentityScore": score,
    }


# ---------------------------------------------------------------------------
# _split_name
# ---------------------------------------------------------------------------

class TestSplitName(unittest.TestCase):
    def test_two_parts(self):
        self.assertEqual(_split_name("John Smith"), ("John", "Smith"))

    def test_single(self):
        self.assertEqual(_split_name("John"), ("John", ""))

    def test_three_parts(self):
        first, last = _split_name("John A Smith")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")

    def test_empty(self):
        self.assertEqual(_split_name(""), ("", ""))

    def test_whitespace(self):
        self.assertEqual(_split_name("  "), ("", ""))


# ---------------------------------------------------------------------------
# _extract_fields
# ---------------------------------------------------------------------------

class TestExtractFields(unittest.TestCase):
    def test_basic(self):
        person = _person()
        result = _extract_fields("c1", person)
        self.assertEqual(result["contact_id"], "c1")
        self.assertEqual(result["enrichment_status"], "success")
        self.assertEqual(result["enriched_phone"], "5551234567")
        self.assertEqual(result["enriched_email"], "john@example.com")
        self.assertEqual(result["enriched_name"], "John Smith")
        self.assertEqual(result["enriched_identity_score"], "95")

    def test_mobile_preferred_over_landline(self):
        person = _person(phones=[
            {"Phone": "5550000000", "Type": "Home"},
            {"Phone": "5551234567", "Type": "Mobile"},
        ])
        result = _extract_fields("c1", person)
        self.assertEqual(result["enriched_phone"], "5551234567")

    def test_no_phones(self):
        person = _person(phones=[])
        result = _extract_fields("c1", person)
        self.assertEqual(result["enriched_phone"], "")

    def test_no_emails(self):
        person = _person(emails=[])
        result = _extract_fields("c1", person)
        self.assertEqual(result["enriched_email"], "")


# ---------------------------------------------------------------------------
# enrich_contacts — happy path
# ---------------------------------------------------------------------------

class TestEnrichContacts(unittest.TestCase):

    @patch("enformion.requests.post")
    def test_single_match_success(self, mock_post):
        mock_post.return_value = _api_response([_person()])
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="user", ap_password="pass"
        )
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["contact_id"], "c1")
        self.assertEqual(r["enrichment_status"], "success")
        self.assertEqual(r["enriched_phone"], "5551234567")
        self.assertEqual(r["enriched_email"], "john@example.com")

    @patch("enformion.requests.post")
    def test_deceased_skipped(self, mock_post):
        contacts = [
            _contact("c1", "Jane Doe", role="deceased"),
            _contact("c2", "John Smith", role="executor"),
        ]
        mock_post.return_value = _api_response([_person()])
        results = enrich_contacts(contacts, ap_name="u", ap_password="p")
        ids = [r["contact_id"] for r in results]
        self.assertNotIn("c1", ids)
        self.assertIn("c2", ids)

    @patch("enformion.requests.post")
    def test_no_name_skipped(self, mock_post):
        results = enrich_contacts(
            [_contact("c1", "", role="executor")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["enrichment_status"], "skipped")
        mock_post.assert_not_called()

    def test_missing_credentials_returns_empty(self):
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="", ap_password=""
        )
        self.assertEqual(results, [])

    @patch("enformion.requests.post")
    def test_max_enrich_cap(self, mock_post):
        mock_post.return_value = _api_response([_person()])
        contacts = [_contact(f"c{i}", f"Person {i}") for i in range(15)]
        results = enrich_contacts(contacts, ap_name="u", ap_password="p")
        self.assertEqual(len(results), MAX_ENRICH)


# ---------------------------------------------------------------------------
# enrich_contacts — fallback and error paths
# ---------------------------------------------------------------------------

class TestEnrichContactsFallback(unittest.TestCase):

    @patch("enformion.requests.post")
    def test_zero_match_triggers_tx_fallback_success(self, mock_post):
        # First call: 0 matches; second call (TX): 1 match
        mock_post.side_effect = [
            _api_response([]),           # initial: no matches
            _api_response([_person()]),  # TX fallback: 1 match
        ]
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["enrichment_status"], "success")
        self.assertEqual(mock_post.call_count, 2)
        # Verify TX was passed in second call
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["State"], "TX")

    @patch("enformion.requests.post")
    def test_zero_match_tx_still_empty_gives_no_match(self, mock_post):
        mock_post.return_value = _api_response([])
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(results[0]["enrichment_status"], "no_match")
        self.assertEqual(mock_post.call_count, 2)

    @patch("enformion.requests.post")
    def test_multiple_matches_triggers_tx_fallback(self, mock_post):
        mock_post.side_effect = [
            _api_response([_person(), _person(first="Jane")]),  # 2 matches
            _api_response([_person()]),                          # TX: 1 match
        ]
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(results[0]["enrichment_status"], "success")

    @patch("enformion.requests.post")
    def test_api_error_returns_error_status(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(results[0]["enrichment_status"], "error")

    @patch("enformion.requests.post")
    def test_http_error_returns_error_status(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_post.return_value = mock_resp
        results = enrich_contacts(
            [_contact("c1", "John Smith")],
            ap_name="u", ap_password="p"
        )
        self.assertEqual(results[0]["enrichment_status"], "error")


if __name__ == "__main__":
    unittest.main()
