"""
Unit tests for src/scraper/scraper.py

All tests use mock Selenium elements — no browser or network required.
The mock structure mirrors the CSS selectors used in the live scraper.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure the scraper package is importable and dynamo is mocked out
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

# dynamo is only needed for scrape_all(); mock it before the module loads
dynamo_mock = MagicMock()
sys.modules["dynamo"] = dynamo_mock

from selenium.webdriver.common.by import By                     # noqa: E402
from selenium.common.exceptions import NoSuchElementException   # noqa: E402

import scraper  # noqa: E402  (imported after sys.modules patch)
from scraper import (
    build_search_url,
    get_pdf_url_from_row,
    get_pdf_url_by_clicking,
    get_pdf_url,
    extract_page_data,
    get_total_results,
    scrape_all,
    SEARCH_PARAMS,
)

from tests.fixtures.scraper_html import ROW_WITH_PDF, ROW_WITHOUT_PDF_INLINE  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _elem(text: str) -> MagicMock:
    """Return a mock Selenium element whose .text equals *text*."""
    e = MagicMock()
    e.text = text
    return e


def _link(href: str) -> MagicMock:
    """Return a mock <a> element whose href attribute equals *href*."""
    e = MagicMock()
    e.get_attribute.return_value = href
    return e


# CSS selector → text value for a standard data row
_TEXT_MAP = {
    'td.col-3[column="[object Object]"] span': "SMITH JOHN A",
    'td.col-4[column="[object Object]"] span': "JONES MARY B",
    'td.col-5[column="[object Object]"] span em': "PROBATE",
    'td.col-6[column="[object Object]"] span': "01/15/2024",
    'td.col-7[column="[object Object]"] span': "20240001234",
    'td.col-8[column="[object Object]"] span': "",
    'td.col-9': "LOT 5 BLK 3 SUNNY ACRES PH 1",
}


def _make_row(pdf_href: str | None = None) -> MagicMock:
    """
    Build a mock TR element.

    If *pdf_href* is given the row contains an inline document link;
    otherwise find_element raises NoSuchElementException for link selectors.
    """
    row = MagicMock()
    pdf_selectors = scraper.ROW_PDF_SELECTORS

    def find_element(by, sel):
        if sel in _TEXT_MAP:
            return _elem(_TEXT_MAP[sel])
        if pdf_href and sel in pdf_selectors:
            return _link(pdf_href)
        raise NoSuchElementException(f"No element: {sel}")

    row.find_element.side_effect = find_element
    return row


def _make_driver_with_rows(*rows: MagicMock, total_text: str = "1-50 of 6,720 results"):
    """
    Build a mock WebDriver containing a single table whose rows are:
      [header_row, spacer_row, *rows]
    """
    driver = MagicMock()

    # Search Result Totals span
    totals_span = _elem(total_text)
    driver.find_element.return_value = totals_span

    # Table structure
    header = MagicMock()
    spacer = MagicMock()
    table = MagicMock()
    table.find_elements.return_value = [header, spacer, *rows]
    driver.find_elements.return_value = [table]

    return driver


# ---------------------------------------------------------------------------
# build_search_url
# ---------------------------------------------------------------------------

class TestBuildSearchUrl(unittest.TestCase):

    def test_default_offset(self):
        url = build_search_url(SEARCH_PARAMS)
        self.assertIn("offset=0", url)
        self.assertIn("searchValue=probate", url)
        self.assertIn("collin.tx.publicsearch.us/results", url)

    def test_custom_offset(self):
        url = build_search_url(SEARCH_PARAMS, offset=50)
        self.assertIn("offset=50", url)

    def test_does_not_mutate_params(self):
        original = SEARCH_PARAMS.copy()
        build_search_url(SEARCH_PARAMS, offset=99)
        self.assertEqual(SEARCH_PARAMS, original)


# ---------------------------------------------------------------------------
# get_total_results
# ---------------------------------------------------------------------------

class TestGetTotalResults(unittest.TestCase):

    def test_parses_standard_format(self):
        driver = MagicMock()
        driver.find_element.return_value = _elem("1-50 of 6,720 results")
        self.assertEqual(get_total_results(driver), 6720)

    def test_parses_small_count(self):
        driver = MagicMock()
        driver.find_element.return_value = _elem("1-3 of 3 results")
        self.assertEqual(get_total_results(driver), 3)

    def test_returns_none_on_missing_element(self):
        driver = MagicMock()
        driver.find_element.side_effect = NoSuchElementException("not found")
        self.assertIsNone(get_total_results(driver))

    def test_returns_none_on_unparseable_text(self):
        driver = MagicMock()
        driver.find_element.return_value = _elem("No results found")
        self.assertIsNone(get_total_results(driver))


# ---------------------------------------------------------------------------
# get_pdf_url_from_row
# ---------------------------------------------------------------------------

class TestGetPdfUrlFromRow(unittest.TestCase):

    def test_returns_href_when_link_present(self):
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/20240001234")
        result = get_pdf_url_from_row(row)
        self.assertEqual(result, "https://collin.tx.publicsearch.us/doc/20240001234")

    def test_returns_none_when_no_link(self):
        row = _make_row(pdf_href=None)
        result = get_pdf_url_from_row(row)
        self.assertIsNone(result)

    def test_returns_none_when_link_has_empty_href(self):
        row = MagicMock()
        link = MagicMock()
        link.get_attribute.return_value = ""
        row.find_element.return_value = link
        result = get_pdf_url_from_row(row)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# get_pdf_url_by_clicking
# ---------------------------------------------------------------------------

class TestGetPdfUrlByClicking(unittest.TestCase):

    def _make_panel(self, pdf_href: str) -> MagicMock:
        panel = MagicMock()
        link = _link(pdf_href)
        panel.find_element.return_value = link
        return panel

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_href_from_panel(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        panel = self._make_panel("https://collin.tx.publicsearch.us/doc/99999")

        mock_wait.return_value.until.return_value = panel

        result = get_pdf_url_by_clicking(driver, row)
        self.assertEqual(result, "https://collin.tx.publicsearch.us/doc/99999")
        row.click.assert_called_once()

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_none_when_panel_not_found(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        mock_wait.return_value.until.side_effect = Exception("timeout")

        result = get_pdf_url_by_clicking(driver, row)
        self.assertIsNone(result)

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_none_when_link_not_in_panel(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        panel = MagicMock()
        panel.find_element.side_effect = NoSuchElementException("not found")
        mock_wait.return_value.until.return_value = panel

        result = get_pdf_url_by_clicking(driver, row)
        self.assertIsNone(result)

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_dismisses_panel_with_escape(self, mock_sleep, mock_wait):
        driver = MagicMock()
        body = MagicMock()
        driver.find_element.return_value = body
        row = MagicMock()
        panel = self._make_panel("https://collin.tx.publicsearch.us/doc/11111")
        mock_wait.return_value.until.return_value = panel

        get_pdf_url_by_clicking(driver, row)
        body.send_keys.assert_called_once()  # Escape key sent


# ---------------------------------------------------------------------------
# get_pdf_url  (orchestrator)
# ---------------------------------------------------------------------------

class TestGetPdfUrl(unittest.TestCase):

    def test_uses_inline_link_when_available(self):
        driver = MagicMock()
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/INLINE")
        result = get_pdf_url(driver, row)
        self.assertEqual(result, "https://collin.tx.publicsearch.us/doc/INLINE")

    @patch("scraper.get_pdf_url_by_clicking", return_value="https://collin.tx.publicsearch.us/doc/CLICKED")
    def test_falls_back_to_clicking_when_no_inline_link(self, mock_click):
        driver = MagicMock()
        row = _make_row(pdf_href=None)
        result = get_pdf_url(driver, row)
        self.assertEqual(result, "https://collin.tx.publicsearch.us/doc/CLICKED")
        mock_click.assert_called_once_with(driver, row)

    @patch("scraper.get_pdf_url_by_clicking", return_value=None)
    def test_returns_none_when_both_strategies_fail(self, mock_click):
        driver = MagicMock()
        row = _make_row(pdf_href=None)
        result = get_pdf_url(driver, row)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# extract_page_data
# ---------------------------------------------------------------------------

class TestExtractPageData(unittest.TestCase):

    def test_extracts_record_with_inline_pdf(self):
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/20240001234")
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)

        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["grantor"],           ROW_WITH_PDF["grantor"])
        self.assertEqual(r["grantee"],           ROW_WITH_PDF["grantee"])
        self.assertEqual(r["doc_type"],          ROW_WITH_PDF["doc_type"])
        self.assertEqual(r["recorded_date"],     ROW_WITH_PDF["recorded_date"])
        self.assertEqual(r["doc_number"],        ROW_WITH_PDF["doc_number"])
        self.assertEqual(r["legal_description"], ROW_WITH_PDF["legal_description"])
        self.assertEqual(r["pdf_url"],           ROW_WITH_PDF["pdf_url"])

    @patch("scraper.get_pdf_url_by_clicking",
           return_value="https://collin.tx.publicsearch.us/doc/20240005678")
    def test_extracts_pdf_via_click_when_not_inline(self, mock_click):
        row = _make_row(pdf_href=None)
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pdf_url"],
                         "https://collin.tx.publicsearch.us/doc/20240005678")
        mock_click.assert_called_once()

    def test_includes_record_number_and_extracted_at(self):
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/X")
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)

        self.assertEqual(records[0]["record_number"], 1)
        self.assertIn("extracted_at", records[0])
        self.assertIsNotNone(records[0]["extracted_at"])

    def test_returns_empty_list_for_empty_table(self):
        driver = MagicMock()
        driver.find_element.return_value = _elem("0 results")
        table = MagicMock()
        table.find_elements.return_value = []   # no rows
        driver.find_elements.return_value = [table]

        records = extract_page_data(driver)
        self.assertEqual(records, [])

    def test_skips_header_and_spacer_rows(self):
        """Only rows[2:] should be processed."""
        data_row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/1")
        driver = _make_driver_with_rows(data_row)

        records = extract_page_data(driver)
        # The two injected header/spacer rows must not appear as records
        self.assertEqual(len(records), 1)

    def test_multiple_rows_extracted(self):
        row1 = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/1")
        row2 = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/2")
        driver = _make_driver_with_rows(row1, row2)

        records = extract_page_data(driver)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["record_number"], 1)
        self.assertEqual(records[1]["record_number"], 2)

    @patch("scraper.get_pdf_url")
    def test_row_error_does_not_abort_page(self, mock_get_pdf):
        """An unexpected error in one row should be skipped; the next row is still processed."""
        # First call raises (simulates an unexpected error escaping all inner try/excepts)
        # Second call returns a valid URL
        mock_get_pdf.side_effect = [
            Exception("unexpected DOM explosion"),
            "https://collin.tx.publicsearch.us/doc/OK",
        ]
        row1 = _make_row()
        row2 = _make_row()
        driver = _make_driver_with_rows(row1, row2)

        records = extract_page_data(driver)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pdf_url"], "https://collin.tx.publicsearch.us/doc/OK")

    def test_stops_at_first_table_with_data(self):
        """extract_page_data() should not process a second table once the first yields rows."""
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/T1")
        header, spacer = MagicMock(), MagicMock()

        table1 = MagicMock()
        table1.find_elements.return_value = [header, spacer, row]

        table2 = MagicMock()
        table2.find_elements.return_value = [header, spacer,
                                             _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/T2")]

        driver = MagicMock()
        driver.find_element.return_value = _elem("1-50 of 100 results")
        driver.find_elements.return_value = [table1, table2]

        records = extract_page_data(driver)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pdf_url"], "https://collin.tx.publicsearch.us/doc/T1")


# ---------------------------------------------------------------------------
# scrape_all
# ---------------------------------------------------------------------------

class TestScrapeAll(unittest.TestCase):

    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_scrapes_only_one_page(self, mock_init, mock_load, mock_extract, mock_dynamo):
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [{"doc_number": "1", "pdf_url": None}]
        mock_dynamo.write_records.return_value = 1

        with patch.dict(os.environ, {"DYNAMO_TABLE_NAME": "leads"}):
            scrape_all("run-001", "CollinTx")

        # load_page called exactly once (first page only)
        mock_load.assert_called_once()
        # extract_page_data called exactly once
        mock_extract.assert_called_once_with(driver)

    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_adds_page_number_and_offset_to_records(
        self, mock_init, mock_load, mock_extract, mock_dynamo
    ):
        driver = MagicMock()
        mock_init.return_value = driver
        record = {"doc_number": "X", "pdf_url": None}
        mock_extract.return_value = [record]
        mock_dynamo.write_records.return_value = 1

        with patch.dict(os.environ, {"DYNAMO_TABLE_NAME": "leads"}):
            scrape_all("run-002", "CollinTx")

        written_records = mock_dynamo.write_records.call_args[0][0]
        self.assertEqual(written_records[0]["page_number"], 1)
        self.assertEqual(written_records[0]["offset"], 0)

    @patch("scraper.load_page", return_value=False)
    @patch("scraper.initialize_driver")
    def test_returns_zero_when_page_fails_to_load(self, mock_init, mock_load):
        mock_init.return_value = MagicMock()
        with patch.dict(os.environ, {"DYNAMO_TABLE_NAME": "leads"}):
            result = scrape_all("run-003", "CollinTx")
        self.assertEqual(result, 0)

    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data", return_value=[])
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_returns_zero_when_no_records_extracted(
        self, mock_init, mock_load, mock_extract, mock_dynamo
    ):
        mock_init.return_value = MagicMock()
        with patch.dict(os.environ, {"DYNAMO_TABLE_NAME": "leads"}):
            result = scrape_all("run-004", "CollinTx")
        self.assertEqual(result, 0)
        mock_dynamo.write_records.assert_not_called()

    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_driver_always_quit(self, mock_init, mock_load, mock_extract, mock_dynamo):
        """WebDriver must be closed even if extract_page_data raises."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.side_effect = RuntimeError("unexpected")

        with patch.dict(os.environ, {"DYNAMO_TABLE_NAME": "leads"}):
            with self.assertRaises(RuntimeError):
                scrape_all("run-005", "CollinTx")

        driver.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
