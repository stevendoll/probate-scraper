"""
Collin County probate records scraper.
Ported from probate-scraper.ipynb — functions kept at same names for traceability.
Key changes from notebook:
  - initialize_driver() uses CHROMEDRIVER_PATH env var (not webdriver-manager)
  - initialize_driver() applies anti-detection: rotating UAs, random viewport,
    excludeSwitches, useAutomationExtension=False, CDP navigator.webdriver mask.
  - login() logs in with SCRAPER_USERNAME / SCRAPER_PASSWORD env vars before
    the first search page is loaded, so authenticated documents are accessible.
  - scrape_all() scrapes only the first page (most-recent records, sorted desc).
  - extract_page_data() adds pdf_url + doc_local_path to every record:
      first checks for an inline document link in the row;
      if absent, clicks the row to open the detail panel, extracts the link href
      and attempts to click the panel's Download button to save a local copy.
"""

import os
import re
import random
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

# Default local directory for Chrome-triggered document downloads
DOWNLOAD_DIR = "/tmp/scraper_downloads"

# Rotating user-agent pool — picked randomly each driver init
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
        "Gecko/20100101 Firefox/122.0"
    ),
]

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

# CSS selectors tried in order to find the Download button inside the detail panel
PANEL_DOWNLOAD_BUTTON_SELECTORS = [
    'button[class*="download"]',
    'a[class*="download"]',
    '[aria-label*="Download"]',
    '[title*="Download"]',
    '[data-action="download"]',
    '.download-btn',
    '.btn-download',
]

# CSS selectors tried in order to find the login email/username field
_LOGIN_EMAIL_SELECTORS = [
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    '#email',
    '#username',
]

# CSS selectors tried in order to find the login password field
_LOGIN_PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    '#password',
]

# CSS selectors tried in order to find the login submit button
_LOGIN_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    '.login-button',
    '.btn-login',
    'button[class*="login"]',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Sleep a random duration in [min_s, max_s] to mimic human pacing."""
    time.sleep(random.uniform(min_s, max_s))


def _wait_for_new_download(
    download_dir: str,
    existing_files: set,
    timeout: int = 30,
) -> str | None:
    """
    Poll *download_dir* until a new completed file (not .crdownload) appears.
    *existing_files* is the set of filenames present before the download started.
    Returns the full path of the new file, or None on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current = set(os.listdir(download_dir))
        except OSError:
            time.sleep(0.5)
            continue
        new_files = current - existing_files
        completed = [
            f for f in new_files
            if not f.endswith(".crdownload") and not f.startswith(".")
        ]
        if completed:
            return os.path.join(download_dir, completed[-1])
        time.sleep(0.5)
    log.warning("Download timed out after %ds in %s", timeout, download_dir)
    return None


# ---------------------------------------------------------------------------
# Cell 3: WebDriver initialisation
# ---------------------------------------------------------------------------

def initialize_driver():
    """
    Spin up a headless Chrome session with anti-detection measures applied.

    Anti-detection techniques:
      - Rotating randomised User-Agent string.
      - Random viewport dimensions (1366–1920 × 768–1080).
      - excludeSwitches: ["enable-automation"] + useAutomationExtension: False.
      - CDP Page.addScriptToEvaluateOnNewDocument masks navigator.webdriver.
      - Chrome download directory pre-configured so Download-button clicks
        save to DOWNLOAD_DIR without a file-picker dialog.

    Uses CHROMEDRIVER_PATH / CHROME_BIN env vars (baked into the Docker image)
    instead of webdriver-manager, which tries to download at runtime.
    """
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
    download_dir = os.environ.get("DOWNLOAD_DIR", DOWNLOAD_DIR)
    os.makedirs(download_dir, exist_ok=True)

    ua = random.choice(_USER_AGENTS)
    width = random.randint(1366, 1920)
    height = random.randint(768, 1080)

    options = Options()
    options.binary_location = chrome_bin
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument(f"--user-agent={ua}")

    # Anti-detection: remove Chrome automation flags
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Configure Chrome to save downloads to download_dir without a dialog
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)

    # Anti-detection: mask navigator.webdriver via CDP
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )

    log.info(
        "WebDriver initialised (chromedriver=%s, ua=%.40s...)",
        chromedriver_path, ua,
    )
    return driver


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(driver) -> bool:
    """
    Log in to BASE_URL using SCRAPER_USERNAME / SCRAPER_PASSWORD env vars.
    Skips silently when credentials are not configured.
    Returns True on success (or skip), False if login could not be completed.

    Keystrokes are sent character-by-character with micro-delays to mimic
    human typing and reduce the chance of bot-detection heuristics triggering.
    """
    username = os.environ.get("SCRAPER_USERNAME", "")
    password = os.environ.get("SCRAPER_PASSWORD", "")

    if not username or not password:
        log.info("No credentials configured (SCRAPER_USERNAME/SCRAPER_PASSWORD) — skipping login")
        return True

    log.info("Logging in as %s", username)
    try:
        driver.get(f"{BASE_URL}/login")
        _random_sleep(2, 4)

        # Locate email / username field
        email_field = None
        for sel in _LOGIN_EMAIL_SELECTORS:
            try:
                email_field = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                log.debug("Login email field found (%s)", sel)
                break
            except Exception:
                continue

        if email_field is None:
            log.warning("Could not find email/username field on login page")
            return False

        # Locate password field
        password_field = None
        for sel in _LOGIN_PASSWORD_SELECTORS:
            try:
                password_field = driver.find_element(By.CSS_SELECTOR, sel)
                log.debug("Login password field found (%s)", sel)
                break
            except Exception:
                continue

        if password_field is None:
            log.warning("Could not find password field on login page")
            return False

        # Type credentials character-by-character (human-like)
        email_field.clear()
        for ch in username:
            email_field.send_keys(ch)
            _random_sleep(0.02, 0.08)

        _random_sleep(0.3, 0.7)

        password_field.clear()
        for ch in password:
            password_field.send_keys(ch)
            _random_sleep(0.02, 0.08)

        _random_sleep(0.5, 1.0)

        # Submit — prefer an explicit button; fall back to Enter in the password field
        submitted = False
        for sel in _LOGIN_SUBMIT_SELECTORS:
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, sel)
                submit_btn.click()
                submitted = True
                log.debug("Login submit button clicked (%s)", sel)
                break
            except Exception:
                continue

        if not submitted:
            password_field.send_keys(Keys.RETURN)
            log.debug("Login submitted via Enter key")

        _random_sleep(3, 5)
        log.info("Login submitted — current URL: %s", driver.current_url)
        return True

    except Exception as exc:
        log.warning("Login failed: %s", exc)
        return False


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


def get_pdf_url_by_clicking(
    driver,
    row,
    download_dir: str = "",
) -> tuple[str | None, str | None]:
    """
    Click the row to open its detail panel then:
      1. Extract the document URL from a panel link href.
      2. Attempt to click the panel's Download button so Chrome saves a local copy.

    Returns ``(pdf_url, local_path)``:
      pdf_url    — href extracted from the first matching panel link, or None.
      local_path — path of the file saved by Chrome's download, or None
                   (requires *download_dir* to be set and the button to exist).

    The panel is dismissed with Escape after extraction.
    """
    try:
        row.click()
        _random_sleep(DETAIL_WAIT - 0.5, DETAIL_WAIT + 1.0)

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
            return None, None

        # 1. Extract href from the first matching panel link
        pdf_url = None
        for sel in PANEL_PDF_SELECTORS:
            try:
                link = panel.find_element(By.CSS_SELECTOR, sel)
                href = link.get_attribute("href")
                if href:
                    log.debug("PDF link found in panel (%s): %s", sel, href)
                    pdf_url = href
                    break
            except Exception:
                continue

        # 2. Try to click the Download button to trigger a Chrome-managed download
        local_path = None
        if download_dir:
            existing = set(os.listdir(download_dir)) if os.path.isdir(download_dir) else set()
            for sel in PANEL_DOWNLOAD_BUTTON_SELECTORS:
                try:
                    btn = panel.find_element(By.CSS_SELECTOR, sel)
                    btn.click()
                    log.debug("Download button clicked (%s) — waiting for file", sel)
                    local_path = _wait_for_new_download(download_dir, existing)
                    if local_path:
                        log.info("Document downloaded locally: %s", local_path)
                        break
                except Exception:
                    continue

        # Dismiss the panel
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            _random_sleep(0.3, 0.7)
        except Exception:
            pass

        return pdf_url, local_path

    except Exception as exc:
        log.warning("get_pdf_url_by_clicking error: %s", exc)
        return None, None


def get_pdf_url(
    driver,
    row,
    download_dir: str = "",
) -> tuple[str | None, str | None]:
    """
    Get the PDF/document URL (and optional local download path) for a result row.
    First checks for an inline link in the row; falls back to clicking the row
    to open the detail panel.

    Returns ``(pdf_url, local_path)``.
    """
    url = get_pdf_url_from_row(row)
    if url:
        return url, None
    log.debug("No inline PDF link — clicking row to open detail panel")
    return get_pdf_url_by_clicking(driver, row, download_dir)


def extract_page_data(driver, download_dir: str = ""):
    """
    Extract all record rows from the current page.
    Returns a list of dicts with fields including pdf_url and doc_local_path.
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

                pdf_url, local_path = get_pdf_url(driver, row, download_dir)
                record = {
                    "grantor":           _text('td.col-3[column="[object Object]"] span'),
                    "grantee":           _text('td.col-4[column="[object Object]"] span'),
                    "doc_type":          _text('td.col-5[column="[object Object]"] span em'),
                    "recorded_date":     _text('td.col-6[column="[object Object]"] span'),
                    "doc_number":        _text('td.col-7[column="[object Object]"] span'),
                    "book_volume_page":  _text('td.col-8[column="[object Object]"] span'),
                    "legal_description": _text("td.col-9"),
                    "pdf_url":           pdf_url,
                    "doc_local_path":    local_path or "",
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
    Log in, scrape the first page of results (most recent, sorted descending),
    optionally upload each document to S3, then write records to DynamoDB.

    Each record includes:
      - pdf_url        — remote URL sourced from the row or detail panel
      - doc_local_path — local filesystem path if the Download button was clicked,
                         otherwise an empty string
      - doc_s3_uri     — ``s3://bucket/key`` if DOCUMENTS_BUCKET is configured:
                           * preferred source is the locally-downloaded file;
                           * falls back to downloading via requests if no local file.
                         Empty string when S3 is not configured.

    S3 upload is skipped when DOCUMENTS_BUCKET env var is not set.
    Session cookies from the Selenium driver are forwarded to the requests-based
    download fallback so that authenticated documents can be fetched.

    Args:
        scrape_run_id:  Unique identifier for this run (injected by ECS or caller).
        location_code:  FK into the locations table (e.g. "CollinTx").
    """
    table_name = os.environ["DYNAMO_TABLE_NAME"]
    bucket = os.environ.get("DOCUMENTS_BUCKET", "")
    download_dir = os.environ.get("DOWNLOAD_DIR", DOWNLOAD_DIR)

    driver = initialize_driver()
    try:
        login(driver)

        url = build_search_url(SEARCH_PARAMS, offset=0)
        log.info("=== Scraping first page ===")

        if not load_page(driver, url):
            log.error("Failed to load first page — aborting")
            return 0

        page_records = extract_page_data(driver, download_dir)

        if not page_records:
            log.warning("No records found on first page")
            return 0

        # Capture session cookies once; forwarded to requests-based download fallback
        # so that documents behind auth are accessible even without a local copy.
        session_cookies = driver.get_cookies() if bucket else []

        for rec in page_records:
            rec["page_number"] = 1
            rec["offset"] = 0

            if bucket and rec.get("doc_number"):
                local_path = rec.get("doc_local_path") or ""

                if local_path and os.path.isfile(local_path):
                    # Preferred: upload from the file Chrome already downloaded
                    rec["doc_s3_uri"] = s3_helper.upload_local_file(
                        local_path=local_path,
                        bucket=bucket,
                        location_code=location_code,
                        doc_number=rec["doc_number"],
                    )
                elif rec.get("pdf_url"):
                    # Fallback: download via requests (forwards session cookies)
                    rec["doc_s3_uri"] = s3_helper.fetch_and_upload(
                        pdf_url=rec["pdf_url"],
                        bucket=bucket,
                        location_code=location_code,
                        doc_number=rec["doc_number"],
                        selenium_cookies=session_cookies,
                    )
                else:
                    rec["doc_s3_uri"] = None
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
