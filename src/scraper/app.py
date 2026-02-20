"""
ECS Fargate entrypoint for the Collin County probate scraper.

Runs as a plain Python script (not a Lambda handler).
ECS marks the task as SUCCEEDED on exit code 0, FAILED on non-zero.

Environment variables required:
  DYNAMO_TABLE_NAME   — DynamoDB table to write results into
  CHROME_BIN          — path to the Chromium binary (set in Dockerfile)
  CHROMEDRIVER_PATH   — path to the ChromeDriver binary (set in Dockerfile)

Optional:
  SCRAPE_RUN_ID       — unique ID for this run (injected by ECS task override);
                        defaults to a UTC ISO timestamp
  DELAY_BETWEEN_PAGES — seconds to wait between page loads (default: 3)
"""

import logging
import os
import sys
from datetime import datetime, timezone

import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def main():
    # Validate required env vars before starting Chrome
    table_name = os.environ.get("DYNAMO_TABLE_NAME")
    if not table_name:
        log.error("DYNAMO_TABLE_NAME is not set — cannot write results")
        sys.exit(1)

    run_id = os.environ.get(
        "SCRAPE_RUN_ID",
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )

    log.info("Starting scrape run — id=%s table=%s", run_id, table_name)

    try:
        total = scraper.scrape_all(scrape_run_id=run_id)
        log.info("Scrape run complete — %d records written (run_id=%s)", total, run_id)
        sys.exit(0)
    except Exception as exc:
        log.exception("Unhandled exception during scrape run: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
