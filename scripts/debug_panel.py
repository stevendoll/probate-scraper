"""
Debug script: log in, load search results, click the first row, dump the
detail panel HTML so we can identify the correct CSS selectors for the
panel container, PDF link, and Download button.

Run from repo root:
    CHROMEDRIVER_PATH=/opt/homebrew/bin/chromedriver \
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    pipenv run python scripts/debug_panel.py

Saves screenshots and HTML to /tmp/debug_panel_*.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

from unittest.mock import MagicMock
sys.modules.setdefault("dynamo", MagicMock())
sys.modules.setdefault("s3", MagicMock())

import scraper
from selenium.webdriver.common.by import By

OUT = "/tmp"
SEP = "\n" + "=" * 80 + "\n"


def save(name, content, mode="w"):
    path = os.path.join(OUT, f"debug_panel_{name}")
    with open(path, mode) as f:
        f.write(content)
    print(f"  → saved {path}")


def main():
    driver = scraper.initialize_driver()
    try:
        # ── 1. Login ──────────────────────────────────────────────────────────
        print("=== Login ===")
        ok = scraper.login(driver)
        print(f"  login() → {ok}")
        driver.save_screenshot(os.path.join(OUT, "debug_panel_1_after_login.png"))

        # ── 2. Load search results page ───────────────────────────────────────
        print("\n=== Loading search page ===")
        url = scraper.build_search_url(scraper.SEARCH_PARAMS, offset=0)
        scraper.load_page(driver, url)
        driver.save_screenshot(os.path.join(OUT, "debug_panel_2_results.png"))

        # ── 3. Find first data row ────────────────────────────────────────────
        tables = driver.find_elements(By.TAG_NAME, "table")
        first_row = None
        for table in tables:
            rows = table.find_elements(By.TAG_NAME, "tr")
            if len(rows) > 2:
                first_row = rows[2]
                break

        if first_row is None:
            print("ERROR: no data rows found")
            return

        print(SEP + "FIRST ROW outerHTML:" + SEP)
        row_html = first_row.get_attribute("outerHTML")
        print(row_html[:2000])
        save("3_first_row.html", row_html)

        # Links directly in the row
        links = first_row.find_elements(By.TAG_NAME, "a")
        print(f"\nLinks in row ({len(links)} found):")
        for i, a in enumerate(links):
            print(f"  [{i}] href={a.get_attribute('href')!r}  text={a.text!r}")

        # ── 4. Click the row ──────────────────────────────────────────────────
        print(SEP + "Clicking first row..." + SEP)
        first_row.click()
        time.sleep(scraper.DETAIL_WAIT + 2)
        driver.save_screenshot(os.path.join(OUT, "debug_panel_4_after_click.png"))

        # ── 5. Find candidate panel elements ─────────────────────────────────
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
            snippet = (el.get_attribute("outerHTML") or "")[:600]
            print(f"\n  [{i}] <{tag} class={classes!r}> visible={visible}")
            print(f"  {snippet}")

        # ── 6. All buttons on page after click ───────────────────────────────
        print(SEP + "ALL BUTTONS AFTER CLICK:" + SEP)
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            classes = btn.get_attribute("class") or ""
            aria = btn.get_attribute("aria-label") or ""
            title = btn.get_attribute("title") or ""
            data_action = btn.get_attribute("data-action") or ""
            visible = btn.is_displayed()
            text = btn.text.strip()
            if visible:
                print(f"  text={text!r:20s} class={classes!r:50s} "
                      f"aria-label={aria!r} title={title!r} data-action={data_action!r}")

        # ── 7. All links after click ──────────────────────────────────────────
        print(SEP + "ALL VISIBLE <a> TAGS AFTER CLICK:" + SEP)
        all_links = driver.find_elements(By.TAG_NAME, "a")
        for a in all_links:
            href = a.get_attribute("href") or ""
            text = a.text.strip()
            classes = a.get_attribute("class") or ""
            visible = a.is_displayed()
            if visible and (href or text):
                print(f"  href={href!r:60s} text={text!r:20s} class={classes!r}")

        # ── 8. Full page HTML after click ─────────────────────────────────────
        print(SEP + "Saving full page HTML after click..." + SEP)
        save("5_after_click.html", driver.page_source)
        print(driver.page_source[:4000])

    finally:
        driver.quit()
        print("\n=== Driver closed ===")


if __name__ == "__main__":
    main()
