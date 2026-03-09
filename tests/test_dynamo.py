"""
Unit tests for src/scraper/dynamo.py

Covers:
  - normalize_date()
  - write_documents() integer doc_number filter
  - write_documents() DynamoDB batch chunking and retry
  - update_location_retrieved_at()
  - get_existing_doc_numbers()
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

import dynamo


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------

class TestNormalizeDate(unittest.TestCase):

    def test_converts_m_d_yyyy(self):
        self.assertEqual(dynamo.normalize_date("1/23/2026"), "2026-01-23")

    def test_pads_single_digit_month_and_day(self):
        self.assertEqual(dynamo.normalize_date("11/7/2025"), "2025-11-07")

    def test_passthrough_na(self):
        self.assertEqual(dynamo.normalize_date("N/A"), "N/A")

    def test_passthrough_empty(self):
        self.assertEqual(dynamo.normalize_date(""), "")

    def test_passthrough_dashes(self):
        self.assertEqual(dynamo.normalize_date("--/--/--"), "--/--/--")

    def test_passthrough_unrecognised(self):
        self.assertEqual(dynamo.normalize_date("2026-01-23"), "2026-01-23")


# ---------------------------------------------------------------------------
# write_records — integer doc_number filter
# ---------------------------------------------------------------------------

def _make_record(doc_number: str) -> dict:
    return {
        "doc_number":        doc_number,
        "grantor":           "Smith, John",
        "grantee":           "Jones, Mary",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-23",
        "book_volume_page":  "N/A",
        "legal_description": "Lot 1",
        "pdf_url":           "",
        "doc_local_path":    "",
        "doc_s3_uri":        "",
    }


class TestWriteDocumentsIntegerFilter(unittest.TestCase):
    """write_documents must only write records whose doc_number is a digit string."""

    def _run_write(self, records):
        """Call write_documents with a mocked DynamoDB client; return captured put requests."""
        captured = []

        def fake_batch_write(RequestItems):
            for req in RequestItems.get("documents", []):
                captured.append(req)
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_documents(records, "documents", "run-test", "CollinTx")

        return captured

    def test_integer_doc_number_is_written(self):
        records = [_make_record("20240001234")]
        written = self._run_write(records)
        self.assertEqual(len(written), 1)

    def test_na_doc_number_is_filtered_out(self):
        records = [_make_record("N/A")]
        written = self._run_write(records)
        self.assertEqual(len(written), 0)

    def test_unknown_doc_number_is_filtered_out(self):
        records = [_make_record("UNKNOWN")]
        written = self._run_write(records)
        self.assertEqual(len(written), 0)

    def test_alphanumeric_doc_number_is_filtered_out(self):
        records = [_make_record("DOC123")]
        written = self._run_write(records)
        self.assertEqual(len(written), 0)

    def test_empty_doc_number_is_filtered_out(self):
        records = [_make_record("")]
        written = self._run_write(records)
        self.assertEqual(len(written), 0)

    def test_mixed_records_only_integers_written(self):
        records = [
            _make_record("20240001"),
            _make_record("N/A"),
            _make_record("20240002"),
            _make_record("DOC99"),
            _make_record("20240003"),
        ]
        written = self._run_write(records)
        self.assertEqual(len(written), 3)

    def test_empty_records_list_returns_zero(self):
        result = dynamo.write_documents([], "documents", "run-empty", "CollinTx")
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# write_documents — batch chunking
# ---------------------------------------------------------------------------

class TestWriteDocumentsBatching(unittest.TestCase):

    def test_batches_in_chunks_of_25(self):
        records = [_make_record(str(i)) for i in range(60)]
        batch_calls = []

        def fake_batch_write(RequestItems):
            batch_calls.append(len(RequestItems.get("documents", [])))
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_documents(records, "documents", "run-batch", "CollinTx")

        self.assertEqual(batch_calls, [25, 25, 10])

    def test_retries_unprocessed_items(self):
        records = [_make_record("1"), _make_record("2")]
        call_count = [0]

        def fake_batch_write(RequestItems):
            call_count[0] += 1
            if call_count[0] == 1:
                # Return one item as unprocessed on the first call
                return {"UnprocessedItems": {"documents": [{"PutRequest": {"Item": {}}}]}}
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_documents(records, "documents", "run-retry", "CollinTx")

        self.assertEqual(call_count[0], 2)


# ---------------------------------------------------------------------------
# get_existing_doc_numbers
# ---------------------------------------------------------------------------

import uuid as _uuid
_DOC_NS = _uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _doc_id(doc_number: str) -> str:
    return str(_uuid.uuid5(_DOC_NS, doc_number))


class TestGetExistingDocNumbers(unittest.TestCase):

    def test_returns_doc_numbers_that_exist_in_table(self):
        """Items returned by batch_get_item → doc_numbers are in the result set."""
        doc_numbers = ["20260001", "20260002"]
        mock_resp = {
            "Responses": {
                "documents": [
                    {"document_id": {"S": _doc_id("20260001")}},
                    {"document_id": {"S": _doc_id("20260002")}},
                ]
            }
        }
        with patch.object(dynamo._dynamodb, "batch_get_item", return_value=mock_resp):
            result = dynamo.get_existing_doc_numbers("documents", doc_numbers)

        self.assertEqual(result, {"20260001", "20260002"})

    def test_filters_out_non_integer_doc_numbers(self):
        """Non-digit doc_numbers must be excluded from the batch_get_item call."""
        doc_numbers = ["20260001", "N/A", "UNKNOWN", "20260002"]
        mock_resp = {"Responses": {"documents": []}}
        with patch.object(dynamo._dynamodb, "batch_get_item", return_value=mock_resp) as mock_bgi:
            dynamo.get_existing_doc_numbers("documents", doc_numbers)

        # Only integer doc_numbers produce document_ids
        keys_sent = mock_bgi.call_args[1]["RequestItems"]["documents"]["Keys"]
        sent_doc_ids = {k["document_id"]["S"] for k in keys_sent}
        self.assertIn(_doc_id("20260001"), sent_doc_ids)
        self.assertIn(_doc_id("20260002"), sent_doc_ids)
        self.assertNotIn(_doc_id("N/A"),      sent_doc_ids)
        self.assertNotIn(_doc_id("UNKNOWN"),  sent_doc_ids)

    def test_returns_empty_set_when_no_items(self):
        mock_resp = {"Responses": {"documents": []}}
        with patch.object(dynamo._dynamodb, "batch_get_item", return_value=mock_resp):
            result = dynamo.get_existing_doc_numbers("documents", ["20260001"])

        self.assertEqual(result, set())

    def test_returns_empty_set_for_empty_input(self):
        result = dynamo.get_existing_doc_numbers("documents", [])
        self.assertEqual(result, set())

    def test_returns_empty_set_for_non_integer_only_input(self):
        result = dynamo.get_existing_doc_numbers("documents", ["N/A", "UNKNOWN"])
        self.assertEqual(result, set())

    def test_batches_in_chunks_of_100(self):
        """batch_get_item is called in chunks of 100 keys."""
        doc_numbers = [str(i) for i in range(150)]
        call_counts = []

        def fake_bgi(RequestItems):
            keys = RequestItems["documents"]["Keys"]
            call_counts.append(len(keys))
            return {"Responses": {"documents": []}}

        with patch.object(dynamo._dynamodb, "batch_get_item", side_effect=fake_bgi):
            dynamo.get_existing_doc_numbers("documents", doc_numbers)

        self.assertEqual(call_counts, [100, 50])

    def test_exception_is_handled_gracefully(self):
        """Exceptions in batch_get_item should not raise; return partial/empty result."""
        with patch.object(dynamo._dynamodb, "batch_get_item", side_effect=Exception("DDB down")):
            result = dynamo.get_existing_doc_numbers("documents", ["20260001"])

        self.assertEqual(result, set())


if __name__ == "__main__":
    unittest.main()
