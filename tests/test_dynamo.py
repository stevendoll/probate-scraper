"""
Unit tests for src/scraper/dynamo.py

Covers:
  - normalize_date()
  - write_records() integer doc_number filter
  - write_records() DynamoDB batch chunking and retry
  - update_location_retrieved_at()
  - get_recently_downloaded_doc_numbers()
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


# ---------------------------------------------------------------------------
# get_recently_downloaded_doc_numbers
# ---------------------------------------------------------------------------

class TestGetRecentlyDownloadedDocNumbers(unittest.TestCase):

    def _make_ddb_item(self, doc_number: str, s3_uri: str = "") -> dict:
        item = {"doc_number": {"S": doc_number}}
        if s3_uri:
            item["doc_s3_uri"] = {"S": s3_uri}
        return item

    def test_returns_doc_numbers_with_nonempty_s3_uri(self):
        items = [
            self._make_ddb_item("20260001", "s3://bucket/a.pdf"),
            self._make_ddb_item("20260002", "s3://bucket/b.pdf"),
        ]
        mock_resp = {"Items": items, "Count": 2}

        with patch.object(dynamo._dynamodb, "query", return_value=mock_resp):
            result = dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index"
            )

        self.assertEqual(result, {"20260001", "20260002"})

    def test_excludes_items_without_s3_uri(self):
        items = [
            self._make_ddb_item("20260001", "s3://bucket/a.pdf"),
            self._make_ddb_item("20260002", ""),  # empty s3_uri
            self._make_ddb_item("20260003"),       # missing s3_uri key
        ]
        mock_resp = {"Items": items, "Count": 3}

        with patch.object(dynamo._dynamodb, "query", return_value=mock_resp):
            result = dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index"
            )

        self.assertEqual(result, {"20260001"})

    def test_returns_empty_set_when_no_items(self):
        mock_resp = {"Items": [], "Count": 0}

        with patch.object(dynamo._dynamodb, "query", return_value=mock_resp):
            result = dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index"
            )

        self.assertEqual(result, set())

    def test_paginates_until_no_last_evaluated_key(self):
        page1 = {
            "Items": [self._make_ddb_item("20260001", "s3://b/a.pdf")],
            "LastEvaluatedKey": {"doc_number": {"S": "20260001"}},
        }
        page2 = {
            "Items": [self._make_ddb_item("20260002", "s3://b/b.pdf")],
        }
        with patch.object(dynamo._dynamodb, "query", side_effect=[page1, page2]):
            result = dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index"
            )

        self.assertEqual(result, {"20260001", "20260002"})

    def test_query_exception_returns_empty_set(self):
        with patch.object(dynamo._dynamodb, "query", side_effect=Exception("DDB down")):
            result = dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index"
            )

        self.assertEqual(result, set())

    def test_uses_correct_gsi_and_key_conditions(self):
        mock_resp = {"Items": []}
        with patch.object(dynamo._dynamodb, "query", return_value=mock_resp) as mock_q:
            dynamo.get_recently_downloaded_doc_numbers(
                "leads", "CollinTx", "location-date-index", days=30
            )

        call_kwargs = mock_q.call_args[1]
        self.assertEqual(call_kwargs["TableName"], "leads")
        self.assertEqual(call_kwargs["IndexName"], "location-date-index")
        self.assertIn(":loc", call_kwargs["ExpressionAttributeValues"])
        self.assertEqual(
            call_kwargs["ExpressionAttributeValues"][":loc"], {"S": "CollinTx"}
        )
        self.assertIn("location_code = :loc", call_kwargs["KeyConditionExpression"])


if __name__ == "__main__":
    unittest.main()
