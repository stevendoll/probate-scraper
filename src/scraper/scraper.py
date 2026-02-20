"""
Collin County probate records scraper.
Ported from probate-scraper.ipynb — functions kept at same names for traceability.
Key changes from notebook:
  - initialize_driver() uses CHROMEDRIVER_PATH env var (not webdriver-manager)
  - scrape_all() replaces scrape_collin_county_records(): no max_pages cap,
    writes to DynamoDB after each page (resilient to crashes)
"""

import os
import re
import time
import logging
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import dynamo

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
DELAY_BETWEEN_PAGES = int(os.environ.get("DELAY_BETWEEN_PAGES", "3"))


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
# Cell 5: Pagination sentinel
# ---------------------------------------------------------------------------

def has_more_pages(driver, current_offset, limit=50):
    """
    Return True if there are more pages beyond current_offset.
    Primary: count records on the current page; if < limit, we're at the end.
    Secondary: look for explicit 'no results' DOM indicators.
    """
    record_selectors = [
        ".record", ".result-item", ".search-result",
        "tr.record-row", ".data-row", "[data-record]", ".result",
    ]
    actual_count = 0
    for sel in record_selectors:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems:
                actual_count = len(elems)
                break
        except Exception:
            continue

    if actual_count < limit:
        log.info("Found %d records (< limit %d) — end of results", actual_count, limit)
        return False

    no_results_selectors = [
        ".no-results", ".no-more-results", ".end-of-results", "[data-no-results]",
    ]
    for sel in no_results_selectors:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            if elem.is_displayed():
                log.info("'No more results' indicator found")
                return False
        except Exception:
            continue

    return True


# ---------------------------------------------------------------------------
# Cell 6: Data extraction
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


def extract_page_data(driver):
    """
    Extract all record rows from the current page.
    Returns a list of dicts with 9 fields (grantor … legal_description + metadata).
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
# Main scrape loop (replaces scrape_collin_county_records)
# ---------------------------------------------------------------------------

def scrape_all(scrape_run_id: str):
    """
    Scrape every page of results, writing to DynamoDB after each page.
    No max_pages cap — runs until has_more_pages() returns False.
    """
    table_name = os.environ["DYNAMO_TABLE_NAME"]
    limit = int(SEARCH_PARAMS["limit"])
    current_offset = 0
    page_num = 1
    total_written = 0

    driver = initialize_driver()
    try:
        while True:
            log.info("=== Page %d (offset %d) ===", page_num, current_offset)
            url = build_search_url(SEARCH_PARAMS, offset=current_offset)

            if not load_page(driver, url):
                log.error("Failed to load page %d — stopping", page_num)
                break

            page_records = extract_page_data(driver)

            if page_records:
                for rec in page_records:
                    rec["page_number"] = page_num
                    rec["offset"] = current_offset

                written = dynamo.write_records(page_records, table_name, scrape_run_id)
                total_written += written
                log.info("Wrote %d records (total so far: %d)", written, total_written)
            else:
                log.warning("No records on page %d — stopping", page_num)
                break

            if not has_more_pages(driver, current_offset, limit):
                log.info("No more pages — scrape complete")
                break

            current_offset += limit
            page_num += 1
            time.sleep(DELAY_BETWEEN_PAGES)

    finally:
        driver.quit()
        log.info("WebDriver closed")

    log.info("Scrape finished: %d total records written across %d pages", total_written, page_num)
    return total_written
