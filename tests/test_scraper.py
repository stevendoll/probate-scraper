"""
Unit tests for src/scraper/scraper.py

All tests use mock Selenium elements — no browser or network required.
The mock structure mirrors the CSS selectors used in the live scraper.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure the scraper package is importable and dynamo is mocked out
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

# dynamo and s3 are only needed for scrape_all(); mock them before the module loads
dynamo_mock = MagicMock()
sys.modules["dynamo"] = dynamo_mock

s3_mock = MagicMock()
sys.modules["s3"] = s3_mock

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
    login,
    SEARCH_PARAMS,
    DOWNLOAD_BUTTON_XPATHS,
    MAX_DOC_DOWNLOADS,
    MAX_DOC_AGE_DAYS,
    _is_within_days,
)
# helpers tested directly
import scraper as _scraper_mod

from tests.fixtures.scraper_html import ROW_WITH_PDF, ROW_WITHOUT_PDF_INLINE  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A date that is always within MAX_DOC_AGE_DAYS (7 days ago)
_RECENT_DATE = (datetime.utcnow() - timedelta(days=7)).strftime("%m/%d/%Y")
# A date that is always outside MAX_DOC_AGE_DAYS (60 days ago)
_OLD_DATE    = (datetime.utcnow() - timedelta(days=60)).strftime("%m/%d/%Y")


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


# CSS selector → text value for a standard data row.
# recorded_date keeps the original fixture value ("01/15/2024") so that
# value-checking tests match ROW_WITH_PDF.  Eligibility tests override via
# _make_row(recorded_date=_RECENT_DATE/_OLD_DATE) as needed.
_TEXT_MAP = {
    'td.col-3[column="[object Object]"] span': "SMITH JOHN A",
    'td.col-4[column="[object Object]"] span': "JONES MARY B",
    'td.col-5[column="[object Object]"] span em': "PROBATE",
    'td.col-6[column="[object Object]"] span': "01/15/2024",
    'td.col-7[column="[object Object]"] span': "20240001234",
    'td.col-8[column="[object Object]"] span': "",
    'td.col-9': "LOT 5 BLK 3 SUNNY ACRES PH 1",
}


def _make_row(
    pdf_href: "str | None" = None,
    recorded_date: "str | None" = None,
    doc_number: "str | None" = None,
) -> MagicMock:
    """
    Build a mock TR element.

    If *pdf_href* is given the row contains an inline document link;
    otherwise find_element raises NoSuchElementException for link selectors.
    *recorded_date* overrides the default value from _TEXT_MAP (useful for
    testing the 30-day cutoff).  *doc_number* overrides the doc_number column.
    """
    row = MagicMock()
    pdf_selectors = scraper.ROW_PDF_SELECTORS
    date_sel   = 'td.col-6[column="[object Object]"] span'
    doc_sel    = 'td.col-7[column="[object Object]"] span'
    date_val   = recorded_date if recorded_date is not None else _TEXT_MAP[date_sel]
    doc_val    = doc_number    if doc_number    is not None else _TEXT_MAP[doc_sel]

    def find_element(by, sel):
        if sel == date_sel:
            return _elem(date_val)
        if sel == doc_sel:
            return _elem(doc_val)
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
# _rename_download
# ---------------------------------------------------------------------------

class TestRenameDownload(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, filename):
        """Create an empty file in tmpdir and return its full path."""
        path = os.path.join(self.tmpdir, filename)
        open(path, "w").close()
        return path

    def test_renames_to_doc_number(self):
        """File is renamed to {doc_number}{ext}."""
        src = self._touch("whatever-chrome-named-this.pdf")
        used = set()
        result = scraper._rename_download(src, "20240001234", used)
        self.assertEqual(result, os.path.join(self.tmpdir, "20240001234.pdf"))
        self.assertTrue(os.path.isfile(result))
        self.assertFalse(os.path.isfile(src))
        self.assertIn("20240001234.pdf", used)

    def test_dedup_first_collision_gets_a_suffix(self):
        """Second file with the same doc_number gets an 'a' suffix."""
        src1 = self._touch("file1.pdf")
        src2 = self._touch("file2.pdf")
        used = set()
        scraper._rename_download(src1, "DOC99", used)
        result2 = scraper._rename_download(src2, "DOC99", used)
        self.assertEqual(os.path.basename(result2), "DOC99a.pdf")
        self.assertIn("DOC99a.pdf", used)

    def test_dedup_second_collision_gets_b_suffix(self):
        """Third file with the same doc_number gets a 'b' suffix."""
        files = [self._touch(f"file{i}.pdf") for i in range(3)]
        used = set()
        for f in files:
            scraper._rename_download(f, "DOC99", used)
        self.assertIn("DOC99.pdf",  used)
        self.assertIn("DOC99a.pdf", used)
        self.assertIn("DOC99b.pdf", used)

    def test_skips_empty_local_path(self):
        """Returns empty string immediately when local_path is empty."""
        used = set()
        result = scraper._rename_download("", "DOC1", used)
        self.assertEqual(result, "")
        self.assertEqual(len(used), 0)

    def test_skips_nonexistent_file(self):
        """Returns original path when the file does not exist."""
        path = os.path.join(self.tmpdir, "missing.pdf")
        used = set()
        result = scraper._rename_download(path, "DOC1", used)
        self.assertEqual(result, path)
        self.assertEqual(len(used), 0)

    def test_returns_original_path_on_os_error(self):
        """Returns original path (and does not raise) when os.rename fails."""
        src = self._touch("file.pdf")
        used = set()
        with patch("scraper.os.rename", side_effect=OSError("permission denied")):
            result = scraper._rename_download(src, "DOC1", used)
        self.assertEqual(result, src)
        self.assertEqual(len(used), 0)

    def test_sanitises_slashes_in_doc_number(self):
        """Slashes in doc_number are replaced with dashes in the filename."""
        src = self._touch("orig.pdf")
        used = set()
        result = scraper._rename_download(src, "2024/0001", used)
        self.assertEqual(os.path.basename(result), "2024-0001.pdf")

    def test_preserves_extension(self):
        """Non-PDF extensions are preserved."""
        src = self._touch("orig.tif")
        used = set()
        result = scraper._rename_download(src, "DOC1", used)
        self.assertEqual(os.path.basename(result), "DOC1.tif")


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
# get_pdf_url_by_clicking  — returns (url, local_path)
# ---------------------------------------------------------------------------

class TestGetPdfUrlByClicking(unittest.TestCase):

    def _make_panel(self, pdf_href: str) -> MagicMock:
        panel = MagicMock()
        link = _link(pdf_href)
        panel.find_element.return_value = link
        return panel

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_url_from_panel(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        panel = self._make_panel("https://collin.tx.publicsearch.us/doc/99999")

        mock_wait.return_value.until.return_value = panel

        url, local_path = get_pdf_url_by_clicking(driver, row)
        self.assertEqual(url, "https://collin.tx.publicsearch.us/doc/99999")
        self.assertIsNone(local_path)  # no download_dir given
        row.click.assert_called_once()

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_none_url_when_panel_not_found(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        mock_wait.return_value.until.side_effect = Exception("timeout")

        url, local_path = get_pdf_url_by_clicking(driver, row)
        self.assertIsNone(url)
        self.assertIsNone(local_path)

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_none_url_when_link_not_in_panel(self, mock_sleep, mock_wait):
        driver = MagicMock()
        row = MagicMock()
        panel = MagicMock()
        panel.find_element.side_effect = NoSuchElementException("not found")
        mock_wait.return_value.until.return_value = panel

        url, local_path = get_pdf_url_by_clicking(driver, row)
        self.assertIsNone(url)
        self.assertIsNone(local_path)

    @patch("scraper._extract_pdf_from_detail")
    @patch("scraper.time.sleep")
    def test_delegates_to_extract_pdf_from_detail(self, mock_sleep, mock_extract):
        """get_pdf_url_by_clicking clicks the row then delegates to _extract_pdf_from_detail."""
        mock_extract.return_value = ("https://collin.tx.publicsearch.us/doc/11111", None)
        driver = MagicMock()
        row = MagicMock()

        url, local_path = get_pdf_url_by_clicking(driver, row)

        row.click.assert_called_once()
        mock_extract.assert_called_once_with(driver, "")
        self.assertEqual(url, "https://collin.tx.publicsearch.us/doc/11111")

    @patch("scraper._wait_for_new_download")
    @patch("scraper.os.listdir", return_value=[])
    @patch("scraper.os.path.isdir", return_value=True)
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_clicks_download_button_in_panel_when_css_matches(
        self, mock_sleep, mock_wait, mock_isdir, mock_listdir, mock_wait_dl
    ):
        """
        Strategy A: when the download button is inside the panel and a CSS
        selector matches it, the button is clicked and the local path is returned.
        """
        driver = MagicMock()
        row = MagicMock()

        # Panel exposes: first call → PDF link, second call → download button
        panel = MagicMock()
        link = _link("https://collin.tx.publicsearch.us/doc/DLTEST")
        download_btn = MagicMock()
        panel.find_element.side_effect = [link, download_btn]
        # WebDriverWait(...).until(...) returns the panel
        mock_wait.return_value.until.return_value = panel
        mock_wait_dl.return_value = "/tmp/scraper_downloads/20240001234.pdf"

        url, local_path = get_pdf_url_by_clicking(driver, row, download_dir="/tmp/scraper_downloads")
        self.assertEqual(local_path, "/tmp/scraper_downloads/20240001234.pdf")
        download_btn.click.assert_called_once()

    @patch("scraper._wait_for_new_download")
    @patch("scraper.os.listdir", return_value=[])
    @patch("scraper.os.path.isdir", return_value=True)
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_clicks_download_button_via_xpath_when_outside_panel(
        self, mock_sleep, mock_wait, mock_isdir, mock_listdir, mock_wait_dl
    ):
        """
        Strategy B: when no CSS selector finds the button inside the panel,
        the XPath text-match fallback finds it on the full page.
        This mirrors publicsearch.us where the Download button lives in the nav
        bar above the panel with a dynamically generated CSS-in-JS class name.
        """
        driver = MagicMock()
        row = MagicMock()

        # Panel: PDF link raises (no inline link), download CSS also raises
        panel = MagicMock()
        panel.find_element.side_effect = NoSuchElementException("not in panel")

        # WebDriverWait: first call finds the panel, second call finds download btn via XPath
        download_btn = MagicMock()
        mock_wait.return_value.until.side_effect = [panel, download_btn]
        mock_wait_dl.return_value = "/tmp/scraper_downloads/20240001234.pdf"

        url, local_path = get_pdf_url_by_clicking(driver, row, download_dir="/tmp/scraper_downloads")
        self.assertEqual(local_path, "/tmp/scraper_downloads/20240001234.pdf")
        download_btn.click.assert_called_once()

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_local_path_none_when_no_download_dir(self, mock_sleep, mock_wait):
        """Without download_dir the download-button path is skipped."""
        driver = MagicMock()
        row = MagicMock()
        panel = self._make_panel("https://collin.tx.publicsearch.us/doc/NODL")
        mock_wait.return_value.until.return_value = panel

        url, local_path = get_pdf_url_by_clicking(driver, row, download_dir="")
        self.assertIsNone(local_path)


# ---------------------------------------------------------------------------
# get_pdf_url  (orchestrator) — returns (url, local_path)
# ---------------------------------------------------------------------------

class TestGetPdfUrl(unittest.TestCase):

    def test_uses_inline_link_when_available(self):
        driver = MagicMock()
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/INLINE")
        url, local_path = get_pdf_url(driver, row)
        self.assertEqual(url, "https://collin.tx.publicsearch.us/doc/INLINE")
        self.assertIsNone(local_path)

    @patch("scraper.get_pdf_url_by_clicking",
           return_value=("https://collin.tx.publicsearch.us/doc/CLICKED", None))
    def test_falls_back_to_clicking_when_no_inline_link(self, mock_click):
        driver = MagicMock()
        row = _make_row(pdf_href=None)
        url, local_path = get_pdf_url(driver, row)
        self.assertEqual(url, "https://collin.tx.publicsearch.us/doc/CLICKED")
        self.assertIsNone(local_path)
        mock_click.assert_called_once_with(driver, row, "")

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_returns_none_when_both_strategies_fail(self, mock_click):
        driver = MagicMock()
        row = _make_row(pdf_href=None)
        url, local_path = get_pdf_url(driver, row)
        self.assertIsNone(url)
        self.assertIsNone(local_path)

    @patch("scraper.get_pdf_url_by_clicking",
           return_value=("https://collin.tx.publicsearch.us/doc/DL", "/tmp/x.pdf"))
    def test_propagates_local_path_from_click(self, mock_click):
        """Local path returned by clicking is propagated through get_pdf_url."""
        driver = MagicMock()
        row = _make_row(pdf_href=None)
        url, local_path = get_pdf_url(driver, row, download_dir="/tmp/dl")
        self.assertEqual(local_path, "/tmp/x.pdf")
        mock_click.assert_called_once_with(driver, row, "/tmp/dl")


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
           return_value=("https://collin.tx.publicsearch.us/doc/20240005678", None))
    def test_extracts_pdf_via_click_when_not_inline(self, mock_click):
        row = _make_row(pdf_href=None, recorded_date=_RECENT_DATE)
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

    def test_includes_doc_local_path_field(self):
        """Every record must have a doc_local_path key (empty string when not downloaded)."""
        row = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/X")
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)
        self.assertIn("doc_local_path", records[0])
        self.assertEqual(records[0]["doc_local_path"], "")

    @patch("scraper.get_pdf_url_by_clicking",
           return_value=("https://collin.tx.publicsearch.us/doc/DL", "/tmp/20240001.pdf"))
    def test_stores_local_path_when_download_button_used(self, mock_click):
        """doc_local_path is populated when the Download button produced a local file."""
        row = _make_row(pdf_href=None, recorded_date=_RECENT_DATE)
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver, download_dir="/tmp/dl")
        self.assertEqual(records[0]["doc_local_path"], "/tmp/20240001.pdf")

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

    @patch("scraper.get_pdf_url_by_clicking")
    def test_row_error_does_not_abort_page(self, mock_click):
        """
        An error during the panel-click (Phase 2) must not prevent other rows
        from being written.  Text extraction (Phase 1) runs before any click,
        so all rows' text is captured regardless of click failures.
        """
        # Row 1 click raises — click error is caught; row still gets a record with pdf_url=None.
        # Both rows use _RECENT_DATE so the old-date break does not fire before row 2.
        mock_click.side_effect = Exception("unexpected DOM explosion")
        row1 = _make_row(pdf_href=None, recorded_date=_RECENT_DATE)
        row2 = _make_row(pdf_href="https://collin.tx.publicsearch.us/doc/OK",
                         recorded_date=_RECENT_DATE)
        driver = _make_driver_with_rows(row1, row2)

        records = extract_page_data(driver)
        # Both rows produce records; row1 has pdf_url=None, row2 has its inline link
        self.assertEqual(len(records), 2)
        self.assertIsNone(records[0]["pdf_url"])
        self.assertEqual(records[1]["pdf_url"], "https://collin.tx.publicsearch.us/doc/OK")

    @patch("scraper._extract_pdf_from_detail", return_value=(None, None))
    @patch("scraper._click_next_result", return_value=True)
    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_download_clicks_all_eligible_rows_up_to_max(
        self, mock_click, mock_next, mock_extract
    ):
        """
        With the default max_downloads (MAX_DOC_DOWNLOADS=5), all recent
        eligible rows get their detail pages opened.  The first row uses
        get_pdf_url_by_clicking; subsequent rows use _click_next_result +
        _extract_pdf_from_detail.
        """
        rows = [_make_row(pdf_href=None, recorded_date=_RECENT_DATE) for _ in range(3)]
        driver = _make_driver_with_rows(*rows)

        extract_page_data(driver, download_dir="/tmp/dl")

        # Row 1: get_pdf_url_by_clicking; rows 2-3: _extract_pdf_from_detail
        self.assertEqual(mock_click.call_count, 1)
        self.assertEqual(mock_extract.call_count, 2)
        self.assertEqual(mock_click.call_count + mock_extract.call_count, 3)

    @patch("scraper._extract_pdf_from_detail", return_value=(None, None))
    @patch("scraper._click_next_result", return_value=True)
    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_download_stops_at_max_downloads(self, mock_click, mock_next, mock_extract):
        """Downloads stop after max_downloads rows even if more are eligible."""
        rows = [_make_row(pdf_href=None, recorded_date=_RECENT_DATE) for _ in range(7)]
        driver = _make_driver_with_rows(*rows)

        extract_page_data(driver, download_dir="/tmp/dl", max_downloads=3)

        self.assertEqual(mock_click.call_count + mock_extract.call_count, 3)

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_max_downloads_zero_skips_all_panel_clicks(self, mock_click):
        """max_downloads=0 disables panel clicks for all rows."""
        row1 = _make_row(pdf_href=None)
        row2 = _make_row(pdf_href=None)
        driver = _make_driver_with_rows(row1, row2)

        extract_page_data(driver, download_dir="/tmp/dl", max_downloads=0)

        mock_click.assert_not_called()

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
# _is_within_days
# ---------------------------------------------------------------------------

class TestIsWithinDays(unittest.TestCase):

    def test_recent_date_returns_true(self):
        self.assertTrue(_is_within_days(_RECENT_DATE))

    def test_old_date_returns_false(self):
        self.assertFalse(_is_within_days(_OLD_DATE))

    def test_today_returns_true(self):
        self.assertTrue(_is_within_days(datetime.utcnow().strftime("%m/%d/%Y")))

    def test_iso_format_within_days(self):
        iso = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertTrue(_is_within_days(iso))

    def test_iso_format_old(self):
        iso = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
        self.assertFalse(_is_within_days(iso))

    def test_na_returns_true(self):
        """Unknown dates should not cause skips."""
        self.assertTrue(_is_within_days("N/A"))

    def test_empty_returns_true(self):
        self.assertTrue(_is_within_days(""))

    def test_unparseable_returns_true(self):
        self.assertTrue(_is_within_days("bad-date"))

    def test_custom_days_boundary(self):
        exactly_10_days_ago = (datetime.utcnow() - timedelta(days=10)).strftime("%m/%d/%Y")
        self.assertTrue(_is_within_days(exactly_10_days_ago, days=11))
        self.assertFalse(_is_within_days(exactly_10_days_ago, days=9))


# ---------------------------------------------------------------------------
# extract_page_data — download eligibility (already_downloaded / date cutoff)
# ---------------------------------------------------------------------------

class TestExtractPageDataEligibility(unittest.TestCase):

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_already_downloaded_skips_detail_page(self, mock_click):
        """Rows whose doc_number is in already_downloaded must not trigger a panel click."""
        row = _make_row(pdf_href=None, recorded_date=_RECENT_DATE, doc_number="20260001")
        driver = _make_driver_with_rows(row)

        extract_page_data(driver, download_dir="/tmp/dl",
                          already_downloaded={"20260001"})

        mock_click.assert_not_called()

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_already_downloaded_does_not_remove_record(self, mock_click):
        """Skipping the detail page must not remove the row from the returned records."""
        row = _make_row(pdf_href=None, recorded_date=_RECENT_DATE, doc_number="20260001")
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver, already_downloaded={"20260001"})

        self.assertEqual(len(records), 1)

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_old_date_skips_detail_page(self, mock_click):
        """Rows with recorded_date older than MAX_DOC_AGE_DAYS skip the panel click."""
        row = _make_row(pdf_href=None, recorded_date=_OLD_DATE)
        driver = _make_driver_with_rows(row)

        extract_page_data(driver, download_dir="/tmp/dl")

        mock_click.assert_not_called()

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_old_date_still_included_in_records(self, mock_click):
        """Old records are scraped for text but not clicked — they still appear in results."""
        row = _make_row(pdf_href=None, recorded_date=_OLD_DATE)
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["pdf_url"])  # no click → no URL

    @patch("scraper.get_pdf_url_by_clicking", return_value=(None, None))
    def test_inline_pdf_url_preserved_regardless_of_date(self, mock_click):
        """An inline PDF URL is always copied to pdf_url even for old records."""
        row = _make_row(
            pdf_href="https://collin.tx.publicsearch.us/doc/OLD",
            recorded_date=_OLD_DATE,
        )
        driver = _make_driver_with_rows(row)

        records = extract_page_data(driver)

        self.assertEqual(records[0]["pdf_url"], "https://collin.tx.publicsearch.us/doc/OLD")
        mock_click.assert_not_called()

    @patch("scraper.get_pdf_url_by_clicking", return_value=("https://url", None))
    def test_only_recent_not_already_downloaded_rows_are_clicked(self, mock_click):
        """Only rows that are recent AND not already downloaded get detail page clicks."""
        recent_new    = _make_row(pdf_href=None, recorded_date=_RECENT_DATE, doc_number="NEW01")
        recent_done   = _make_row(pdf_href=None, recorded_date=_RECENT_DATE, doc_number="DONE1")
        old_new       = _make_row(pdf_href=None, recorded_date=_OLD_DATE,    doc_number="OLD01")
        driver = _make_driver_with_rows(recent_new, recent_done, old_new)

        extract_page_data(driver, download_dir="/tmp/dl",
                          already_downloaded={"DONE1"})

        # Only recent_new is eligible → exactly 1 click
        mock_click.assert_called_once()


# ---------------------------------------------------------------------------
# login helpers
# ---------------------------------------------------------------------------

class TestIsLoggedIn(unittest.TestCase):

    def test_returns_true_when_sign_out_in_page_source(self):
        driver = MagicMock()
        driver.page_source = "<html><a>Sign Out</a></html>"
        self.assertTrue(scraper._is_logged_in(driver))

    def test_returns_true_when_logout_link_present(self):
        driver = MagicMock()
        driver.page_source = "<html></html>"
        # find_element succeeds for logout selector
        driver.find_element.return_value = MagicMock()
        self.assertTrue(scraper._is_logged_in(driver))

    def test_returns_false_when_no_sign_out_indicators(self):
        driver = MagicMock()
        driver.page_source = "<html><a>Sign In</a></html>"
        driver.find_element.side_effect = NoSuchElementException("not found")
        self.assertFalse(scraper._is_logged_in(driver))

    def test_handles_page_source_exception_gracefully(self):
        """If page_source raises, fall through to CSS selector check."""
        driver = MagicMock()
        type(driver).page_source = property(lambda self: (_ for _ in ()).throw(Exception("err")))
        driver.find_element.side_effect = NoSuchElementException("not found")
        self.assertFalse(scraper._is_logged_in(driver))


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

class TestLogin(unittest.TestCase):

    def _make_logged_out_driver(self, mock_wait, email_field, password_field):
        """Helper: driver that appears logged-out, then provides login form fields."""
        driver = MagicMock()
        driver.page_source = "<html><a>Sign In</a></html>"  # not logged in
        driver.find_element.side_effect = NoSuchElementException("not found")

        # After _click_sign_in_trigger + wait, WebDriverWait returns email_field
        # (first call for sign-in trigger times out, subsequent call finds email)
        def wait_until_side_effect(condition):
            # Simulate trigger click failing, then email field found
            raise Exception("no trigger")
        mock_wait.return_value.until.side_effect = [
            Exception("no trigger"),   # _click_sign_in_trigger fails
            email_field,               # email field found
        ]
        driver.find_element.side_effect = [
            NoSuchElementException("no logout"),   # _is_logged_in CSS check
            password_field,                        # password field found
            password_field,                        # submit button
        ]
        return driver

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_skips_when_no_credentials(self, mock_sleep, mock_wait):
        """login() returns True immediately when env vars are not set."""
        driver = MagicMock()
        env = {"SCRAPER_USERNAME": "", "SCRAPER_PASSWORD": ""}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertTrue(result)
        driver.get.assert_not_called()

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_navigates_to_base_url(self, mock_sleep, mock_wait):
        """login() navigates to BASE_URL (not /login) to check for sign-out first."""
        driver = MagicMock()
        driver.page_source = "<html></html>"
        mock_wait.return_value.until.return_value = MagicMock()
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "pass"}
        with patch.dict(os.environ, env):
            login(driver)
        driver.get.assert_called_once_with(scraper.BASE_URL)

    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_skips_login_when_already_logged_in(self, mock_sleep, mock_wait):
        """login() returns True without filling the form when 'sign out' is in the banner."""
        driver = MagicMock()
        driver.page_source = "<html><a>Sign Out</a></html>"
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "pass"}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertTrue(result)
        # Should not attempt to find form fields
        mock_wait.return_value.until.assert_not_called()

    @patch("scraper._click_sign_in_trigger", return_value=False)
    @patch("scraper._is_logged_in", return_value=False)
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_false_when_email_field_not_found(
        self, mock_sleep, mock_wait, mock_is_logged_in, mock_trigger
    ):
        """login() returns False when the email field cannot be located after trigger click."""
        driver = MagicMock()
        mock_wait.return_value.until.side_effect = Exception("not found")
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "pass"}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertFalse(result)

    @patch("scraper._click_sign_in_trigger", return_value=False)
    @patch("scraper._is_logged_in", return_value=False)
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_false_when_password_field_not_found(
        self, mock_sleep, mock_wait, mock_is_logged_in, mock_trigger
    ):
        """login() returns False when the password field cannot be located."""
        driver = MagicMock()
        email_field = MagicMock()
        mock_wait.return_value.until.return_value = email_field
        driver.find_element.side_effect = NoSuchElementException("no password field")
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "pass"}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertFalse(result)

    @patch("scraper._click_sign_in_trigger", return_value=False)
    @patch("scraper._is_logged_in")
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_true_when_sign_out_appears_after_submit(
        self, mock_sleep, mock_wait, mock_is_logged_in, mock_trigger
    ):
        """login() returns True when 'sign out' appears in the banner after submitting."""
        driver = MagicMock()
        email_field = MagicMock()
        password_field = MagicMock()
        mock_is_logged_in.side_effect = [False, True]  # not logged in → then logged in
        mock_wait.return_value.until.return_value = email_field
        driver.find_element.return_value = password_field
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "secret"}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertTrue(result)

    @patch("scraper._click_sign_in_trigger", return_value=False)
    @patch("scraper._is_logged_in", return_value=False)
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_returns_false_when_sign_out_absent_after_submit(
        self, mock_sleep, mock_wait, mock_is_logged_in, mock_trigger
    ):
        """login() returns False when sign-out never appears (wrong credentials)."""
        driver = MagicMock()
        email_field = MagicMock()
        password_field = MagicMock()
        mock_wait.return_value.until.return_value = email_field
        driver.find_element.return_value = password_field
        env = {"SCRAPER_USERNAME": "user@example.com", "SCRAPER_PASSWORD": "wrongpass"}
        with patch.dict(os.environ, env):
            result = login(driver)
        self.assertFalse(result)

    @patch("scraper._click_sign_in_trigger", return_value=False)
    @patch("scraper._is_logged_in")
    @patch("scraper.WebDriverWait")
    @patch("scraper.time.sleep")
    def test_types_credentials_character_by_character(
        self, mock_sleep, mock_wait, mock_is_logged_in, mock_trigger
    ):
        """Credentials are sent as individual characters (human-like typing)."""
        driver = MagicMock()
        email_field = MagicMock()
        password_field = MagicMock()
        mock_is_logged_in.side_effect = [False, True]
        mock_wait.return_value.until.return_value = email_field
        driver.find_element.return_value = password_field

        username = "ab@c.com"
        pw = "pw1"
        env = {"SCRAPER_USERNAME": username, "SCRAPER_PASSWORD": pw}
        with patch.dict(os.environ, env):
            login(driver)

        email_calls = [str(c.args[0]) for c in email_field.send_keys.call_args_list]
        self.assertEqual(email_calls, list(username))

        pw_calls = [str(c.args[0]) for c in password_field.send_keys.call_args_list]
        self.assertEqual(pw_calls, list(pw))


# ---------------------------------------------------------------------------
# scrape_all
# ---------------------------------------------------------------------------

class TestScrapeAll(unittest.TestCase):

    def setUp(self):
        # _extract_text_rows reads DOM text without clicking; with a MagicMock
        # driver it would return [] and cause an early return.  Patch it to
        # return a minimal phase-1 list so tests can exercise the rest of scrape_all.
        self._patcher_extract_rows = patch(
            "scraper._extract_text_rows",
            return_value=[{"doc_number": "1", "pdf_url": None}],
        )
        self._patcher_extract_rows.start()

    def tearDown(self):
        self._patcher_extract_rows.stop()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_scrapes_only_one_page(self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login):
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [{"doc_number": "1", "pdf_url": None}]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-001", "CollinTx")

        # load_page called exactly once (first page only)
        mock_load.assert_called_once()
        # extract_page_data called exactly once
        mock_extract.assert_called_once()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_login_called_after_driver_init(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """login() must be invoked with the driver returned by initialize_driver()."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [{"doc_number": "1", "pdf_url": None}]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-login", "CollinTx")

        mock_login.assert_called_once_with(driver)

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_adds_page_number_and_offset_to_records(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        driver = MagicMock()
        mock_init.return_value = driver
        record = {"doc_number": "X", "pdf_url": None}
        mock_extract.return_value = [record]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-002", "CollinTx")

        written_records = mock_dynamo.write_documents.call_args[0][0]
        self.assertEqual(written_records[0]["page_number"], 1)
        self.assertEqual(written_records[0]["offset"], 0)

    @patch("scraper.login", return_value=True)
    @patch("scraper.load_page", return_value=False)
    @patch("scraper.initialize_driver")
    def test_returns_zero_when_page_fails_to_load(self, mock_init, mock_load, mock_login):
        mock_init.return_value = MagicMock()
        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            result = scrape_all("run-003", "CollinTx")
        self.assertEqual(result, 0)

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data", return_value=[])
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_returns_zero_when_no_records_extracted(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        mock_init.return_value = MagicMock()
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            result = scrape_all("run-004", "CollinTx")
        self.assertEqual(result, 0)
        mock_dynamo.write_documents.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_extract_called_with_already_downloaded(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """scrape_all() fetches already-downloaded doc_numbers from DynamoDB
        and passes them to extract_page_data as already_downloaded."""
        driver = MagicMock()
        mock_init.return_value = driver
        already = {"20260001", "20260002"}
        mock_dynamo.get_existing_doc_numbers.return_value = already
        mock_extract.return_value = [{"doc_number": "1", "pdf_url": None}]
        mock_dynamo.write_documents.return_value = 1

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-maxdl", "CollinTx")

        _, kwargs = mock_extract.call_args
        self.assertEqual(kwargs.get("already_downloaded"), already)
        # max_downloads is not passed explicitly — the default (MAX_DOC_DOWNLOADS) is used
        self.assertIsNone(kwargs.get("max_downloads"))

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_driver_always_quit(self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login):
        """WebDriver must be closed even if extract_page_data raises."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_extract.side_effect = RuntimeError("unexpected")

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            with self.assertRaises(RuntimeError):
                scrape_all("run-005", "CollinTx")

        driver.quit.assert_called_once()


    @patch("scraper._rename_download")
    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_rename_called_when_doc_number_is_integer(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login, mock_rename
    ):
        """_rename_download is called when doc_number is a valid integer string."""
        mock_init.return_value = MagicMock()
        mock_extract.return_value = [
            {"doc_number": "20240001234", "pdf_url": None, "doc_local_path": "/tmp/file.pdf"},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1
        mock_rename.return_value = "/tmp/20240001234.pdf"

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-rename-01", "CollinTx")

        mock_rename.assert_called_once()
        call_args = mock_rename.call_args[0]
        self.assertEqual(call_args[0], "/tmp/file.pdf")
        self.assertEqual(call_args[1], "20240001234")

    @patch("scraper._rename_download")
    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_rename_skipped_when_doc_number_not_integer(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login, mock_rename
    ):
        """_rename_download is NOT called when doc_number is non-numeric (e.g. 'N/A')."""
        mock_init.return_value = MagicMock()
        mock_extract.return_value = [
            {"doc_number": "N/A", "pdf_url": None, "doc_local_path": "/tmp/N-A.pdf"},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 0

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents"}):
            scrape_all("run-rename-02", "CollinTx")

        mock_rename.assert_not_called()


# ---------------------------------------------------------------------------
# scrape_all — S3 upload integration
# ---------------------------------------------------------------------------

class TestScrapeAllWithS3(unittest.TestCase):
    """
    Tests for the S3 document-upload path in scrape_all().
    Requires DOCUMENTS_BUCKET env var to be set.
    """

    def setUp(self):
        # _extract_text_rows reads DOM text without clicking; patch to return a
        # minimal phase-1 list so tests can exercise the rest of scrape_all.
        self._patcher_extract_rows = patch(
            "scraper._extract_text_rows",
            return_value=[{"doc_number": "1", "pdf_url": None}],
        )
        self._patcher_extract_rows.start()
        # Reset the module-level s3_helper mock before every test so call
        # counts don't bleed between tests.
        scraper.s3_helper.reset_mock()

    def tearDown(self):
        self._patcher_extract_rows.stop()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_fetch_and_upload_called_when_no_local_path(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """fetch_and_upload used as fallback when doc_local_path is absent."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "20240001", "pdf_url": "https://site.com/doc/20240001", "doc_local_path": ""},
            {"doc_number": "20240002", "pdf_url": "https://site.com/doc/20240002", "doc_local_path": ""},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 2
        scraper.s3_helper.fetch_and_upload.return_value = "s3://bucket/documents/CollinTx/20240001.pdf"

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-01", "CollinTx")

        self.assertEqual(scraper.s3_helper.fetch_and_upload.call_count, 2)
        scraper.s3_helper.upload_local_file.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    @patch("scraper.os.path.isfile", return_value=True)
    def test_upload_local_file_preferred_over_fetch(
        self, mock_isfile, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """upload_local_file is used (not fetch_and_upload) when doc_local_path exists."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {
                "doc_number": "20240001",
                "pdf_url": "https://site.com/doc/20240001",
                "doc_local_path": "/tmp/20240001.pdf",
            },
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1
        scraper.s3_helper.upload_local_file.return_value = "s3://bucket/documents/CollinTx/20240001.pdf"

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-localfile", "CollinTx")

        scraper.s3_helper.upload_local_file.assert_called_once()
        scraper.s3_helper.fetch_and_upload.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_upload_not_called_when_bucket_unset(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """No S3 calls should be made when DOCUMENTS_BUCKET is absent."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "DOC1", "pdf_url": "https://site.com/doc/DOC1", "doc_local_path": ""},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1

        env = {"DOCUMENTS_TABLE_NAME": "documents"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("DOCUMENTS_BUCKET", None)
            scrape_all("run-s3-02", "CollinTx")

        scraper.s3_helper.fetch_and_upload.assert_not_called()
        scraper.s3_helper.upload_local_file.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_upload_not_called_when_pdf_url_missing(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """Records without a pdf_url or local path should not trigger an S3 upload."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "20240001", "pdf_url": None, "doc_local_path": ""},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-03", "CollinTx")

        scraper.s3_helper.fetch_and_upload.assert_not_called()
        scraper.s3_helper.upload_local_file.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_s3_uri_stored_on_record(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """The S3 URI returned by fetch_and_upload must appear on the written record."""
        driver = MagicMock()
        mock_init.return_value = driver
        record = {"doc_number": "20240099", "pdf_url": "https://site.com/doc/20240099", "doc_local_path": ""}
        mock_extract.return_value = [record]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1
        scraper.s3_helper.fetch_and_upload.return_value = "s3://my-bucket/documents/CollinTx/20240099.pdf"

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-04", "CollinTx")

        written = mock_dynamo.write_documents.call_args[0][0]
        self.assertEqual(written[0]["doc_s3_uri"],
                         "s3://my-bucket/documents/CollinTx/20240099.pdf")

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_session_cookies_passed_to_fetch_and_upload(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """Selenium session cookies should be forwarded to fetch_and_upload."""
        driver = MagicMock()
        driver.get_cookies.return_value = [{"name": "sess", "value": "tok123"}]
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "20240001", "pdf_url": "https://site.com/doc/20240001", "doc_local_path": ""},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 1
        scraper.s3_helper.fetch_and_upload.return_value = "s3://b/k.pdf"

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-05", "CollinTx")

        _, kwargs = scraper.s3_helper.fetch_and_upload.call_args
        self.assertEqual(kwargs["selenium_cookies"], [{"name": "sess", "value": "tok123"}])

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_s3_upload_skipped_when_doc_number_not_integer(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """S3 upload must be skipped when doc_number is non-numeric (e.g. 'N/A')."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "N/A", "pdf_url": "https://site.com/doc/1", "doc_local_path": "/tmp/N-A.pdf"},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 0

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            scrape_all("run-s3-noint", "CollinTx")

        scraper.s3_helper.upload_local_file.assert_not_called()
        scraper.s3_helper.fetch_and_upload.assert_not_called()

    @patch("scraper.login", return_value=True)
    @patch("scraper.dynamo")
    @patch("scraper.extract_page_data")
    @patch("scraper.load_page", return_value=True)
    @patch("scraper.initialize_driver")
    def test_upload_failure_does_not_abort_scrape(
        self, mock_init, mock_load, mock_extract, mock_dynamo, mock_login
    ):
        """A None return from fetch_and_upload (upload failure) must not stop the run."""
        driver = MagicMock()
        mock_init.return_value = driver
        mock_extract.return_value = [
            {"doc_number": "20240001", "pdf_url": "https://site.com/doc/20240001", "doc_local_path": ""},
            {"doc_number": "20240002", "pdf_url": "https://site.com/doc/20240002", "doc_local_path": ""},
        ]
        mock_dynamo.get_existing_doc_numbers.return_value = set()
        mock_dynamo.write_documents.return_value = 2
        scraper.s3_helper.fetch_and_upload.return_value = None  # all uploads fail

        with patch.dict(os.environ, {"DOCUMENTS_TABLE_NAME": "documents",
                                     "DOCUMENTS_BUCKET": "my-bucket"}):
            result = scrape_all("run-s3-06", "CollinTx")

        # Scrape still completes and writes to DynamoDB
        self.assertEqual(result, 2)
        mock_dynamo.write_documents.assert_called_once()


if __name__ == "__main__":
    unittest.main()
