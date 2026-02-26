"""
Diagnostic script: open the site, click Sign In, dump HTML around the login form.

Run from the project root (DynamoDB Local does NOT need to be running):

    CHROMEDRIVER_PATH=/opt/homebrew/bin/chromedriver \
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    pipenv run python scripts/debug_login.py

Saves screenshots and an HTML snippet to /tmp/debug_login_*.
"""

import os
import sys
import time

# Allow import of scraper module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

# Stub dynamo / s3 so scraper.py imports cleanly without DynamoDB env vars
from unittest.mock import MagicMock
sys.modules.setdefault("dynamo", MagicMock())
sys.modules.setdefault("s3", MagicMock())

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

import scraper

OUT = "/tmp"

def save_screenshot(driver, name):
    path = os.path.join(OUT, f"debug_login_{name}.png")
    driver.save_screenshot(path)
    print(f"  Screenshot → {path}")

def dump_inputs(driver, label):
    """Print all visible input fields on the page."""
    inputs = driver.find_elements(By.TAG_NAME, "input")
    print(f"\n  [{label}] input fields ({len(inputs)} found):")
    for el in inputs:
        try:
            print(f"    type={el.get_attribute('type')!r:12s} "
                  f"name={el.get_attribute('name')!r:20s} "
                  f"id={el.get_attribute('id')!r:20s} "
                  f"class={el.get_attribute('class')!r:40s} "
                  f"placeholder={el.get_attribute('placeholder')!r}")
        except Exception as e:
            print(f"    (error reading field: {e})")

def dump_buttons(driver, label):
    """Print all buttons on the page."""
    buttons = driver.find_elements(By.TAG_NAME, "button")
    print(f"\n  [{label}] buttons ({len(buttons)} found):")
    for el in buttons:
        try:
            print(f"    text={el.text.strip()!r:20s} "
                  f"type={el.get_attribute('type')!r:10s} "
                  f"class={el.get_attribute('class')!r}")
        except Exception as e:
            print(f"    (error reading button: {e})")

def dump_links(driver, label, keyword="sign"):
    """Print links whose text or href contain keyword."""
    links = driver.find_elements(By.TAG_NAME, "a")
    matches = []
    for el in links:
        try:
            text = el.text.strip().lower()
            href = (el.get_attribute("href") or "").lower()
            if keyword in text or keyword in href:
                matches.append(el)
        except Exception:
            pass
    print(f"\n  [{label}] links containing '{keyword}' ({len(matches)} found):")
    for el in matches:
        try:
            print(f"    text={el.text.strip()!r:20s} "
                  f"href={el.get_attribute('href')!r:50s} "
                  f"class={el.get_attribute('class')!r}")
        except Exception as e:
            print(f"    (error: {e})")

def dump_html_around(driver, label, max_chars=4000):
    """Dump the inner HTML of the body (truncated)."""
    html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
    path = os.path.join(OUT, f"debug_login_{label}.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"\n  [{label}] Full HTML → {path}")
    # Print a short snippet
    print(f"  First {max_chars} chars of body HTML:")
    print(html[:max_chars])

def main():
    print("=== Starting diagnostic driver ===")
    driver = scraper.initialize_driver()

    try:
        # ── Step 1: Home page ──────────────────────────────────────────────
        print(f"\n[1] Loading {scraper.BASE_URL}")
        driver.get(scraper.BASE_URL)
        time.sleep(4)
        save_screenshot(driver, "1_home")
        print(f"  Title: {driver.title!r}")
        print(f"  URL:   {driver.current_url!r}")

        dump_links(driver, "home", keyword="sign")
        dump_links(driver, "home", keyword="log")
        dump_links(driver, "home", keyword="login")
        dump_buttons(driver, "home")
        dump_inputs(driver, "home")

        # Check already-logged-in
        logged_in = scraper._is_logged_in(driver)
        print(f"\n  _is_logged_in → {logged_in}")

        # ── Step 2: Click Sign In trigger ─────────────────────────────────
        print("\n[2] Attempting _click_sign_in_trigger()")
        clicked = scraper._click_sign_in_trigger(driver)
        print(f"  _click_sign_in_trigger → {clicked}")
        time.sleep(2)
        save_screenshot(driver, "2_after_trigger_click")
        print(f"  URL after click: {driver.current_url!r}")

        dump_inputs(driver, "after_trigger")
        dump_buttons(driver, "after_trigger")
        dump_links(driver, "after_trigger", keyword="sign")

        # ── Step 3: Dump full HTML to file ────────────────────────────────
        print("\n[3] Saving full page HTML")
        dump_html_around(driver, "3_after_trigger", max_chars=2000)

        # ── Step 4: Try each email selector manually ───────────────────────
        print("\n[4] Testing _LOGIN_EMAIL_SELECTORS:")
        for sel in scraper._LOGIN_EMAIL_SELECTORS:
            try:
                el = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                print(f"  FOUND  {sel!r}  →  type={el.get_attribute('type')!r} "
                      f"name={el.get_attribute('name')!r} id={el.get_attribute('id')!r}")
            except Exception:
                print(f"  miss   {sel!r}")

        print("\n[5] Testing _LOGIN_PASSWORD_SELECTORS:")
        for sel in scraper._LOGIN_PASSWORD_SELECTORS:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                print(f"  FOUND  {sel!r}  →  name={el.get_attribute('name')!r} "
                      f"id={el.get_attribute('id')!r}")
            except Exception:
                print(f"  miss   {sel!r}")

        print("\n[6] Testing _SIGN_IN_TRIGGER_SELECTORS (retrospective check):")
        for sel in scraper._SIGN_IN_TRIGGER_SELECTORS:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                print(f"  FOUND  {sel!r}  →  text={el.text.strip()!r} "
                      f"href={el.get_attribute('href')!r}")
            except Exception:
                print(f"  miss   {sel!r}")

    finally:
        driver.quit()
        print("\n=== Driver closed ===")


if __name__ == "__main__":
    main()
