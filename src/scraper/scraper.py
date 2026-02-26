"""
Collin County probate records scraper.

Logs in with SCRAPER_USERNAME / SCRAPER_PASSWORD, scrapes the first page of
results (most-recent, sorted descending), and for the first record opens the
detail panel to capture a local copy via the Download button.  All records are
written to DynamoDB; optionally uploaded to S3.
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

# CSS selectors tried in order to locate the detail panel after clicking a row.
# publicsearch.us uses id="document-details-panel" — a stable, non-hashed ID.
DETAIL_PANEL_SELECTORS = [
    "#document-details-panel",          # publicsearch.us: stable panel ID
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

# CSS selectors tried in order to find the Download button INSIDE the detail panel.
# Used first; if none match, DOWNLOAD_BUTTON_XPATHS is tried against the full page.
PANEL_DOWNLOAD_BUTTON_SELECTORS = [
    'button[class*="download"]',
    'a[class*="download"]',
    '[aria-label*="Download"]',
    '[title*="Download"]',
    '[data-action="download"]',
    '.download-btn',
    '.btn-download',
]

# XPath expressions tried against the full page when the Download button is NOT
# inside the panel (e.g. publicsearch.us puts it in the nav bar above the panel).
# Matches on button/link visible text so it works even with CSS-in-JS class names.
DOWNLOAD_BUTTON_XPATHS = [
    "//button[contains(normalize-space(.), 'Download')]",
    "//a[contains(normalize-space(.), 'Download')]",
    "//*[@aria-label and contains(@aria-label, 'Download')]",
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

# Text fragments / CSS selectors indicating the user is already logged in
_LOGGED_IN_TEXT = ["sign out", "signout", "log out", "logout"]
_LOGGED_IN_SELECTORS = [
    'a[href*="logout"]',
    'a[href*="signout"]',
    'a[href*="sign-out"]',
    '[class*="logout"]',
    '[class*="signout"]',
]

# CSS selectors tried in order to find the Sign In trigger.
# publicsearch.us uses  <a href="/signin?..." class="a11y-menu">Sign In</a>
_SIGN_IN_TRIGGER_SELECTORS = [
    'a[href*="signin"]',      # publicsearch.us: /signin?returnPath=...
    'a[href*="/login"]',
    'button[class*="sign-in"]',
    'a[class*="sign-in"]',
    'button[class*="signin"]',
    'a[class*="signin"]',
    '[class*="login-button"]',
    'button[class*="login"]',
    'a[class*="login"]',
]

# Direct-navigation fallback used when the Sign In trigger link cannot be clicked
_SIGNIN_PATH = "/signin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Sleep a random duration in [min_s, max_s] to mimic human pacing."""
    time.sleep(random.uniform(min_s, max_s))


def _rename_download(local_path: str, doc_number: str, used_names: set) -> str:
    """
    Rename a locally-downloaded file to ``{doc_number}{ext}``.

    If ``{doc_number}{ext}`` is already in *used_names* (i.e. a duplicate
    doc_number in the same run), appends a letter suffix (a, b, c, …) until
    a unique name is found.  *used_names* is updated in-place.

    Returns the new path on success, or *local_path* unchanged if the file
    does not exist or the OS rename fails.
    """
    if not local_path or not os.path.isfile(local_path):
        return local_path

    ext = os.path.splitext(local_path)[1].lower() or ".bin"
    directory = os.path.dirname(local_path)
    safe_doc = doc_number.replace("/", "-").replace(" ", "_")

    candidate = f"{safe_doc}{ext}"
    if candidate in used_names:
        for suffix in "abcdefghijklmnopqrstuvwxyz":
            candidate = f"{safe_doc}{suffix}{ext}"
            if candidate not in used_names:
                break

    new_path = os.path.join(directory, candidate)
    try:
        os.rename(local_path, new_path)
        used_names.add(candidate)
        log.info("Renamed download: %s → %s", os.path.basename(local_path), candidate)
        return new_path
    except OSError as exc:
        log.warning("Could not rename %s → %s: %s", local_path, new_path, exc)
        return local_path


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
# WebDriver initialisation
# ---------------------------------------------------------------------------

def initialize_driver():
    """
    Spin up a headless Chrome session with anti-detection measures applied:
    rotating User-Agent, random viewport, automation-flag removal, and CDP
    navigator.webdriver masking.  Downloads are pre-configured to save to
    DOWNLOAD_DIR without a file-picker dialog.
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

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

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
# Login helpers
# ---------------------------------------------------------------------------

def _is_logged_in(driver) -> bool:
    """Return True if the current page shows sign-out indicators in the banner."""
    try:
        src = driver.page_source.lower()
        if any(t in src for t in _LOGGED_IN_TEXT):
            return True
    except Exception:
        pass
    for sel in _LOGGED_IN_SELECTORS:
        try:
            driver.find_element(By.CSS_SELECTOR, sel)
            return True
        except Exception:
            continue
    return False


def _click_sign_in_trigger(driver) -> bool:
    """
    Click the Sign In button/link.  Returns True if clicked, False if not found.
    """
    for sel in _SIGN_IN_TRIGGER_SELECTORS:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            btn.click()
            log.debug("Sign-in trigger clicked (%s)", sel)
            return True
        except Exception:
            continue
    log.debug("No sign-in trigger found")
    return False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(driver) -> bool:
    """
    Log in to BASE_URL using SCRAPER_USERNAME / SCRAPER_PASSWORD env vars.
    Returns True on success or when credentials are not configured, False on failure.
    """
    username = os.environ.get("SCRAPER_USERNAME", "")
    password = os.environ.get("SCRAPER_PASSWORD", "")

    if not username or not password:
        log.info("No credentials configured — skipping login")
        return True

    log.info("Checking login state at %s", BASE_URL)
    try:
        driver.get(BASE_URL)
        _random_sleep(2, 4)

        if _is_logged_in(driver):
            log.info("Already logged in — skipping login")
            return True

        log.info("Not logged in — attempting login as %s", username)

        # Navigate to the sign-in form.  Try clicking the link first; if the
        # selector misses (JS not rendered, layout change), fall back to direct URL.
        if _click_sign_in_trigger(driver):
            _random_sleep(1, 2)
        else:
            signin_url = BASE_URL + _SIGNIN_PATH
            log.info("Sign-in trigger not found — navigating directly to %s", signin_url)
            driver.get(signin_url)
            _random_sleep(2, 4)

        # Locate email field
        email_field = None
        for sel in _LOGIN_EMAIL_SELECTORS:
            try:
                email_field = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                log.debug("Email field found (%s)", sel)
                break
            except Exception:
                continue

        if email_field is None:
            log.warning("Could not find email/username field")
            return False

        # Locate password field
        password_field = None
        for sel in _LOGIN_PASSWORD_SELECTORS:
            try:
                password_field = driver.find_element(By.CSS_SELECTOR, sel)
                break
            except Exception:
                continue

        if password_field is None:
            log.warning("Could not find password field")
            return False

        # Type credentials character-by-character (human-like pacing)
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

        # Submit: prefer explicit button, fall back to Enter key
        submitted = False
        for sel in _LOGIN_SUBMIT_SELECTORS:
            try:
                driver.find_element(By.CSS_SELECTOR, sel).click()
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            password_field.send_keys(Keys.RETURN)

        _random_sleep(3, 5)

        if _is_logged_in(driver):
            log.info("Login successful — signed in as %s", username)
            return True

        log.warning(
            "Login submitted but sign-out not found in banner — "
            "credentials may be wrong or the site layout changed (URL: %s)",
            driver.current_url,
        )
        return False

    except Exception as exc:
        log.warning("Login failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# URL builder + page loader
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
# Data extraction helpers
# ---------------------------------------------------------------------------

def get_total_results(driver):
    """
    Parse the 'Search Result Totals' span to find the total record count.
    Returns an integer (e.g. 6720) or None if the element is not found.
    """
    try:
        text = driver.find_element(
            By.CSS_SELECTOR, 'span[aria-label="Search Result Totals"]'
        ).text.strip()

        match = re.search(r"of\s+([\d,]+)\s+results", text, re.IGNORECASE)
        if match:
            total = int(match.group(1).replace(",", ""))
            log.info("Total results: %d", total)
            return total

        if "of" in text and "results" in text:
            total = int(text.split("of")[1].split("results")[0].strip().replace(",", ""))
            log.info("Total results: %d", total)
            return total

        log.warning("Could not parse total results from: %s", text)
        return None
    except Exception as exc:
        log.warning("get_total_results error: %s", exc)
        return None


def get_pdf_url_from_row(row) -> str | None:
    """Return the document URL if an inline link is present in the row, else None."""
    for sel in ROW_PDF_SELECTORS:
        try:
            href = row.find_element(By.CSS_SELECTOR, sel).get_attribute("href")
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
    Click the row to open its detail panel, extract the document URL, and
    optionally trigger the Download button to save a local copy.

    Returns ``(pdf_url, local_path)``.  The panel is dismissed with Escape.
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

        # Extract document URL from panel link
        pdf_url = None
        for sel in PANEL_PDF_SELECTORS:
            try:
                href = panel.find_element(By.CSS_SELECTOR, sel).get_attribute("href")
                if href:
                    log.debug("PDF link found in panel (%s): %s", sel, href)
                    pdf_url = href
                    break
            except Exception:
                continue

        # Click the Download button (Strategy A: CSS in panel; Strategy B: XPath on page)
        local_path = None
        if download_dir:
            existing = set(os.listdir(download_dir)) if os.path.isdir(download_dir) else set()
            download_clicked = False

            for sel in PANEL_DOWNLOAD_BUTTON_SELECTORS:
                try:
                    panel.find_element(By.CSS_SELECTOR, sel).click()
                    log.debug("Download button clicked in panel (%s)", sel)
                    download_clicked = True
                    break
                except Exception:
                    continue

            if not download_clicked:
                for xpath in DOWNLOAD_BUTTON_XPATHS:
                    try:
                        btn = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, xpath))
                        )
                        btn.click()
                        log.debug("Download button clicked via XPath (%s)", xpath)
                        download_clicked = True
                        break
                    except Exception:
                        continue

            if download_clicked:
                local_path = _wait_for_new_download(download_dir, existing)
                if local_path:
                    log.info("Document downloaded locally: %s", local_path)

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
    Return ``(pdf_url, local_path)`` for a result row.
    Checks for an inline link first; falls back to clicking the row to open
    the detail panel.
    """
    url = get_pdf_url_from_row(row)
    if url:
        return url, None
    return get_pdf_url_by_clicking(driver, row, download_dir)


def extract_page_data(driver, download_dir: str = "", max_downloads: int = 1):
    """
    Extract all record rows from the current page.
    Returns a list of dicts with fields including pdf_url and doc_local_path.
    Skips the first two table rows (header + empty spacer).
    Continues past individual row errors rather than aborting the whole page.

    Args:
        download_dir:   Directory for Chrome-managed downloads.  Empty string
                        disables the download button entirely.
        max_downloads:  Rows for which the detail panel is opened and the
                        Download button is clicked.  Defaults to 1 (first row
                        only) to minimise interaction volume.  Rows beyond this
                        limit are still scraped for text fields and any inline
                        document links, but no panel is opened.
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
                def _text(*selectors):
                    """Try each selector in order; return the first non-empty match."""
                    for sel in selectors:
                        try:
                            text = row.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if text:
                                return text
                        except Exception:
                            continue
                    return "N/A"

                # Dump the first data row's HTML so we can diagnose selector mismatches
                if i == 1:
                    try:
                        log.info("First row HTML: %s", row.get_attribute("outerHTML")[:3000])
                    except Exception:
                        pass

                if i <= max_downloads:
                    pdf_url, local_path = get_pdf_url(driver, row, download_dir)
                else:
                    # Inline link only — no panel click
                    pdf_url = get_pdf_url_from_row(row)
                    local_path = None

                record = {
                    "grantor":           _text('td.col-3[column="[object Object]"] span', 'td.col-3 span'),
                    "grantee":           _text('td.col-4[column="[object Object]"] span', 'td.col-4 span'),
                    "doc_type":          _text('td.col-5[column="[object Object]"] span em', 'td.col-5 span em', 'td.col-5 span'),
                    "recorded_date":     _text('td.col-6[column="[object Object]"] span', 'td.col-6 span'),
                    "doc_number":        _text('td.col-7[column="[object Object]"] span', 'td.col-7 span'),
                    "book_volume_page":  _text('td.col-8[column="[object Object]"] span', 'td.col-8 span'),
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
    Log in, scrape the first page of results, upload documents to S3 (when
    DOCUMENTS_BUCKET is set), and write records to DynamoDB.

    S3 upload prefers a locally-downloaded file (doc_local_path); falls back to
    fetching the pdf_url with Selenium session cookies forwarded.
    """
    table_name = os.environ["DYNAMO_TABLE_NAME"]
    bucket = os.environ.get("DOCUMENTS_BUCKET", "")
    download_dir = os.environ.get("DOWNLOAD_DIR", DOWNLOAD_DIR)

    driver = initialize_driver()
    try:
        login(driver)

        url = build_search_url(SEARCH_PARAMS, offset=0)
        if not load_page(driver, url):
            log.error("Failed to load first page — aborting")
            return 0

        page_records = extract_page_data(driver, download_dir, max_downloads=1)
        if not page_records:
            log.warning("No records found on first page")
            return 0

        # Rename locally-downloaded files to use doc_number as the filename.
        # Deduplicates with a/b/c/… suffixes if the same doc_number appears twice.
        _used_download_names: set = set()
        for rec in page_records:
            local_path = rec.get("doc_local_path") or ""
            doc_number = rec.get("doc_number") or ""
            if local_path and doc_number.strip().isdigit():
                rec["doc_local_path"] = _rename_download(
                    local_path, doc_number, _used_download_names
                )

        session_cookies = driver.get_cookies() if bucket else []

        for rec in page_records:
            rec["page_number"] = 1
            rec["offset"] = 0

            if bucket and str(rec.get("doc_number", "")).strip().isdigit():
                local_path = rec.get("doc_local_path") or ""
                if local_path and os.path.isfile(local_path):
                    rec["doc_s3_uri"] = s3_helper.upload_local_file(
                        local_path=local_path,
                        bucket=bucket,
                        location_code=location_code,
                        doc_number=rec["doc_number"],
                    )
                elif rec.get("pdf_url"):
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
        log.info("Scrape finished: %d records written (location=%s)", written, location_code)
        return written

    finally:
        driver.quit()
