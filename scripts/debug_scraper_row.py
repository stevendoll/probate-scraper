"""
debug_scraper_row.py — show the raw HTML of the first result row and the page
state after clicking it, so we can identify the correct CSS selectors for
extracting the PDF/document URL.

Usage (from repo root):
    CHROMEDRIVER_PATH=/opt/homebrew/bin/chromedriver \
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    pipenv run python scripts/debug_scraper_row.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

from scraper import (
    DETAIL_WAIT,
    SEARCH_PARAMS,
    build_search_url,
    initialize_driver,
    load_page,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

SEP = "\n" + "=" * 80 + "\n"


def main():
    driver = initialize_driver()
    try:
        url = build_search_url(SEARCH_PARAMS, offset=0)
        print(f"Loading: {url[:100]}")
        if not load_page(driver, url):
            print("ERROR: failed to load page")
            return

        # ── find the first data row ───────────────────────────────────────────
        tables = driver.find_elements(By.TAG_NAME, "table")
        first_row = None
        for table in tables:
            rows = table.find_elements(By.TAG_NAME, "tr")
            if len(rows) > 2:
                first_row = rows[2]   # skip header + spacer
                break

        if first_row is None:
            print("ERROR: no data rows found on page")
            return

        # ── print row HTML ────────────────────────────────────────────────────
        print(SEP + "FIRST ROW outerHTML:" + SEP)
        print(first_row.get_attribute("outerHTML"))

        # ── print all <a> tags found directly in the row ──────────────────────
        links = first_row.find_elements(By.TAG_NAME, "a")
        print(SEP + f"LINKS IN ROW ({len(links)} found):" + SEP)
        for i, a in enumerate(links):
            print(f"  [{i}] href={a.get_attribute('href')!r}  text={a.text!r}")

        # ── click the row and show the resulting DOM ──────────────────────────
        print(SEP + "Clicking first row..." + SEP)
        first_row.click()
        time.sleep(DETAIL_WAIT)

        # Print everything that appeared or changed after the click:
        # 1. Any new/visible element that could be a detail panel
        candidates = driver.find_elements(
            By.CSS_SELECTOR,
            "[class*='detail'], [class*='panel'], [class*='viewer'], "
            "[class*='drawer'], [class*='modal'], [class*='overlay'], "
            "[class*='sidebar'], [class*='record'], aside, dialog",
        )
        print(f"CANDIDATE PANEL ELEMENTS ({len(candidates)} found):")
        for i, el in enumerate(candidates):
            classes = el.get_attribute("class") or ""
            tag = el.tag_name
            visible = el.is_displayed()
            html_snippet = el.get_attribute("outerHTML")[:400]
            print(f"\n  [{i}] <{tag} class=\"{classes}\"> visible={visible}")
            print(f"       {html_snippet}")

        # 2. All <a> tags now visible anywhere on the page that look like doc links
        print(SEP + "ALL <a> TAGS AFTER CLICK CONTAINING '/doc/' OR '.pdf':" + SEP)
        all_links = driver.find_elements(By.TAG_NAME, "a")
        doc_links = [
            a for a in all_links
            if any(k in (a.get_attribute("href") or "") for k in ("/doc/", ".pdf", "/document/", "/images/"))
        ]
        if doc_links:
            for a in doc_links:
                print(f"  href={a.get_attribute('href')!r}  text={a.text!r}  visible={a.is_displayed()}")
        else:
            print("  (none found)")

        # 3. Full body HTML so we can inspect the complete post-click DOM
        print(SEP + "FULL PAGE SOURCE AFTER CLICK (first 8000 chars):" + SEP)
        print(driver.page_source[:8000])

    finally:
        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
