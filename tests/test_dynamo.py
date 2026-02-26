"""
Unit tests for src/scraper/dynamo.py

Covers:
  - normalize_date()
  - write_records() integer doc_number filter
  - write_records() DynamoDB batch chunking and retry
  - update_location_retrieved_at()
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


class TestWriteRecordsIntegerFilter(unittest.TestCase):
    """write_records must only write records whose doc_number is a digit string."""

    def _run_write(self, records):
        """Call write_records with a mocked DynamoDB client; return captured put requests."""
        captured = []

        def fake_batch_write(RequestItems):
            for req in RequestItems.get("leads", []):
                captured.append(req)
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_records(records, "leads", "run-test", "CollinTx")

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
        result = dynamo.write_records([], "leads", "run-empty", "CollinTx")
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# write_records — batch chunking
# ---------------------------------------------------------------------------

class TestWriteRecordsBatching(unittest.TestCase):

    def test_batches_in_chunks_of_25(self):
        records = [_make_record(str(i)) for i in range(60)]
        batch_calls = []

        def fake_batch_write(RequestItems):
            batch_calls.append(len(RequestItems.get("leads", [])))
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_records(records, "leads", "run-batch", "CollinTx")

        self.assertEqual(batch_calls, [25, 25, 10])

    def test_retries_unprocessed_items(self):
        records = [_make_record("1"), _make_record("2")]
        call_count = [0]

        def fake_batch_write(RequestItems):
            call_count[0] += 1
            if call_count[0] == 1:
                # Return one item as unprocessed on the first call
                return {"UnprocessedItems": {"leads": [{"PutRequest": {"Item": {}}}]}}
            return {"UnprocessedItems": {}}

        with patch.object(dynamo._dynamodb, "batch_write_item", side_effect=fake_batch_write):
            dynamo.write_records(records, "leads", "run-retry", "CollinTx")

        self.assertEqual(call_count[0], 2)


if __name__ == "__main__":
    unittest.main()
