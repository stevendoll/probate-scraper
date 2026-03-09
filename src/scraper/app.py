"""
ECS Fargate entrypoint for the Collin County probate scraper.

Runs as a plain Python script (not a Lambda handler).
ECS marks the task as SUCCEEDED on exit code 0, FAILED on non-zero.

Environment variables:
  DOCUMENTS_TABLE_NAME  — DynamoDB documents table (required)
  CHROME_BIN            — Chromium binary path (set in Dockerfile)
  CHROMEDRIVER_PATH     — ChromeDriver binary path (set in Dockerfile)
  LOCATIONS_TABLE_NAME  — DynamoDB locations table (default: locations)
  LOCATION_CODE         — location key (default: CollinTx)
  SCRAPE_RUN_ID         — unique run ID injected by ECS; defaults to UTC timestamp
"""

import logging
import os
import sys
from datetime import datetime, timezone

import dynamo
import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def main():
    # Validate required env vars before starting Chrome
    table_name = os.environ.get("DOCUMENTS_TABLE_NAME")
    if not table_name:
        log.error("DOCUMENTS_TABLE_NAME is not set — cannot write results")
        sys.exit(1)

    location_code = os.environ.get("LOCATION_CODE", "CollinTx")
    locations_table_name = os.environ.get("LOCATIONS_TABLE_NAME", "locations")

    run_id = os.environ.get(
        "SCRAPE_RUN_ID",
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )

    log.info(
        "Starting scrape run — id=%s table=%s location=%s",
        run_id, table_name, location_code,
    )

    try:
        total = scraper.scrape_all(scrape_run_id=run_id, location_code=location_code)
        log.info(
            "Scrape run complete — %d records written (run_id=%s location=%s)",
            total, run_id, location_code,
        )
    except Exception as exc:
        log.error("Unhandled exception during scrape run: %s", exc)
        sys.exit(1)

    # Stamp the location with the completion time (best-effort)
    dynamo.update_location_retrieved_at(locations_table_name, location_code)

    sys.exit(0)


if __name__ == "__main__":
    main()
