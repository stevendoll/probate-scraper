"""
Collin County probate records scraper.
Ported from probate-scraper.ipynb — functions kept at same names for traceability.
Key changes from notebook:
  - initialize_driver() uses CHROMEDRIVER_PATH env var (not webdriver-manager)
  - scrape_all() scrapes only the first page (most-recent records, sorted desc).
  - extract_page_data() adds pdf_url to every record:
      first checks for an inline document link in the row;
      if absent, clicks the row to open the detail panel and extracts it there.
"""

import os
import re
import time
import logging
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import dynamo
import s3 as s3_helper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://collin.tx.publicsearch.us"

SEARCH_PARAMS = {
    "department": "RP",
    "keywordSearch": "false",
    "limit": "50",
    "offset": "0",
    "recordedDateRange": "18930107,20991231",
    "searchOcrText": "false",
    "searchType": "quickSearch",
    "searchValue": "probate",
    "sort": "desc",
    "sortBy": "recordedDate",
}

PAGE_LOAD_WAIT = 10   # seconds to sleep after driver.get()
DETAIL_WAIT    = 3    # seconds to wait for the detail panel to open

# CSS selectors tried in order when looking for a document link directly in the row
ROW_PDF_SELECTORS = [
    'a[href*="/doc/"]',
    'a[href*=".pdf"]',
    'a[href*="/document/"]',
    'a[href*="/images/"]',
]

# CSS selectors tried in order to locate the detail panel after clicking a row
DETAIL_PANEL_SELECTORS = [
    ".document-detail",
    ".record-detail",
    ".doc-viewer",
    ".document-viewer",
    '[class*="document-detail"]',
    '[class*="record-detail"]',
]

# CSS selectors tried in order to find the document link inside the detail panel
PANEL_PDF_SELECTORS = [
    'a[href*="/doc/"]',
    'a[href*=".pdf"]',
    'a[href*="/document/"]',
    'a[href*="/images/"]',
    ".document-pdf-link",
]


# ---------------------------------------------------------------------------
# Cell 3: WebDriver initialisation
# ---------------------------------------------------------------------------

def initialize_driver():
    """
    Spin up a headless Chrome session.
    Uses CHROMEDRIVER_PATH env var (baked into the Docker image) instead of
    webdriver-manager, which tries to download at runtime.
    """
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")

    options = Options()
    options.binary_location = chrome_bin
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    log.info("WebDriver initialised (chromedriver=%s)", chromedriver_path)
    return driver


# ---------------------------------------------------------------------------
# Cell 4: URL builder + page loader
# ---------------------------------------------------------------------------

def build_search_url(params, offset=0):
    """Return a paginated search URL for the given offset."""
    p = params.copy()
    p["offset"] = str(offset)
    qs = "&".join(f"{k}={v}" for k, v in p.items())
    return f"{BASE_URL}/results?{qs}"


def load_page(driver, url, wait_time=PAGE_LOAD_WAIT):
    """Load *url* and wait for the DOM to be ready. Returns True on success."""
    try:
        log.info("Loading: %s", url[:120])
        driver.get(url)
        time.sleep(wait_time)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        log.info("Page loaded — title: %s", driver.title)
        return True
    except Exception as exc:
        log.error("Error loading page: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Cell 5: Data extraction helpers
# ---------------------------------------------------------------------------

def get_total_results(driver):
    """
    Parse the 'Search Result Totals' span to find the total record count.
    Returns an integer (e.g. 6720) or None if the element is not found.
    """
    try:
        elem = driver.find_element(
            By.CSS_SELECTOR, 'span[aria-label="Search Result Totals"]'
        )
        text = elem.text.strip()
        log.info("Search Result Totals: '%s'", text)

        match = re.search(r"of\s+([\d,]+)\s+results", text, re.IGNORECASE)
        if match:
            total = int(match.group(1).replace(",", ""))
            log.info("Total results: %d", total)
            return total

        # Fallback split
        if "of" in text and "results" in text:
            part = text.split("of")[1].split("results")[0].strip()
            total = int(part.replace(",", ""))
            log.info("Total results (fallback): %d", total)
            return total

        log.warning("Could not parse total results from: %s", text)
        return None
    except Exception as exc:
        log.warning("get_total_results error: %s", exc)
        return None


def get_pdf_url_from_row(row) -> str | None:
    """
    Return the document URL if a link is directly present in the row, else None.
    Tries ROW_PDF_SELECTORS in order.
    """
    for sel in ROW_PDF_SELECTORS:
        try:
            link = row.find_element(By.CSS_SELECTOR, sel)
            href = link.get_attribute("href")
            if href:
                log.debug("Inline PDF link found (%s): %s", sel, href)
                return href
        except Exception:
            continue
    return None


def get_pdf_url_by_clicking(driver, row) -> str | None:
    """
    Click the row to open its detail panel, extract the document URL,
    then dismiss the panel with Escape. Returns the URL or None on failure.
    """
    try:
        row.click()
        time.sleep(DETAIL_WAIT)

        # Find the detail panel
        panel = None
        for sel in DETAIL_PANEL_SELECTORS:
            try:
                panel = WebDriverWait(driver, 5).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
                )
                log.debug("Detail panel found (%s)", sel)
                break
            except Exception:
                continue

        if panel is None:
            log.warning("No detail panel found after clicking row")
            return None

        # Find the document link inside the panel
        for sel in PANEL_PDF_SELECTORS:
            try:
                link = panel.find_element(By.CSS_SELECTOR, sel)
                href = link.get_attribute("href")
                if href:
                    log.debug("PDF link found in panel (%s): %s", sel, href)
                    # Dismiss the panel
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        time.sleep(0.5)
                    except Exception:
                        pass
                    return href
            except Exception:
                continue

        log.warning("No document link found in detail panel")
        return None

    except Exception as exc:
        log.warning("get_pdf_url_by_clicking error: %s", exc)
        return None


def get_pdf_url(driver, row) -> str | None:
    """
    Get the PDF/document URL for a result row.
    First checks for an inline link in the row; falls back to clicking the row
    to open the detail panel.
    """
    url = get_pdf_url_from_row(row)
    if url:
        return url
    log.debug("No inline PDF link — clicking row to open detail panel")
    return get_pdf_url_by_clicking(driver, row)


def extract_page_data(driver):
    """
    Extract all record rows from the current page.
    Returns a list of dicts with fields including pdf_url.
    Skips the first two table rows (header + empty spacer).
    Continues past individual row errors rather than aborting the whole page.
    """
    records = []
    get_total_results(driver)  # logged for observability; result unused here

    tables = driver.find_elements(By.TAG_NAME, "table")
    for table in tables:
        rows = table.find_elements(By.TAG_NAME, "tr")
        if len(rows) <= 2:
            continue

        log.info("Processing table with %d rows", len(rows))
        for i, row in enumerate(rows[2:], start=1):
            try:
                def _text(sel):
                    try:
                        return row.find_element(By.CSS_SELECTOR, sel).text.strip()
                    except Exception:
                        return "N/A"

                record = {
                    "grantor":           _text('td.col-3[column="[object Object]"] span'),
                    "grantee":           _text('td.col-4[column="[object Object]"] span'),
                    "doc_type":          _text('td.col-5[column="[object Object]"] span em'),
                    "recorded_date":     _text('td.col-6[column="[object Object]"] span'),
                    "doc_number":        _text('td.col-7[column="[object Object]"] span'),
                    "book_volume_page":  _text('td.col-8[column="[object Object]"] span'),
                    "legal_description": _text("td.col-9"),
                    "pdf_url":           get_pdf_url(driver, row),
                    "record_number":     i,
                    "extracted_at":      datetime.utcnow().isoformat(),
                }
                records.append(record)
            except Exception as exc:
                log.warning("Row %d extraction error: %s", i, exc)
                continue

        if records:
            break  # stop at the first table that yielded data

    log.info("Extracted %d records from page", len(records))
    return records


# ---------------------------------------------------------------------------
# Main scrape entry point
# ---------------------------------------------------------------------------

def scrape_all(scrape_run_id: str, location_code: str):
    """
    Scrape the first page of results (most recent, sorted descending),
    optionally upload each document to S3, then write records to DynamoDB.

    Each record includes:
      - pdf_url      — remote URL sourced from the row or detail panel
      - doc_s3_uri   — ``s3://bucket/key`` if DOCUMENTS_BUCKET is configured,
                       otherwise an empty string

    S3 upload is skipped when DOCUMENTS_BUCKET env var is not set.
    Session cookies from the Selenium driver are forwarded to the download
    request so that authenticated documents can be fetched.

    Args:
        scrape_run_id:  Unique identifier for this run (injected by ECS or caller).
        location_code:  FK into the locations table (e.g. "CollinTx").
    """
    table_name = os.environ["DYNAMO_TABLE_NAME"]
    bucket = os.environ.get("DOCUMENTS_BUCKET", "")

    driver = initialize_driver()
    try:
        url = build_search_url(SEARCH_PARAMS, offset=0)
        log.info("=== Scraping first page ===")

        if not load_page(driver, url):
            log.error("Failed to load first page — aborting")
            return 0

        page_records = extract_page_data(driver)

        if not page_records:
            log.warning("No records found on first page")
            return 0

        # Capture session cookies once; forwarded to S3 upload download requests
        # so that documents behind auth are accessible.
        session_cookies = driver.get_cookies() if bucket else []

        for rec in page_records:
            rec["page_number"] = 1
            rec["offset"] = 0

            # Upload document to S3 (no-op when bucket is empty)
            if bucket and rec.get("pdf_url") and rec.get("doc_number"):
                rec["doc_s3_uri"] = s3_helper.fetch_and_upload(
                    pdf_url=rec["pdf_url"],
                    bucket=bucket,
                    location_code=location_code,
                    doc_number=rec["doc_number"],
                    selenium_cookies=session_cookies,
                )
            else:
                rec["doc_s3_uri"] = None

        written = dynamo.write_records(
            page_records, table_name, scrape_run_id, location_code
        )
        log.info(
            "Scrape finished: %d records written (location=%s)",
            written, location_code,
        )
        return written

    finally:
        driver.quit()
        log.info("WebDriver closed")
