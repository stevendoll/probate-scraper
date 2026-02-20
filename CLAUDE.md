# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pipenv install

# Run the scraper (primary method)
jupyter notebook probate-scraper.ipynb

# Run as a plain Python script
python collin_scraper.py
```

There are no build, lint, or test commands — this is a research/notebook project.

## Architecture

This is a Selenium-based web scraper that extracts probate records from the Collin County (TX) public records portal (`collin.tx.publicsearch.us`) and exports them to CSV.

**Main entry point**: `probate-scraper.ipynb`. The configurable parameters are near the top:
```python
MAX_PAGES = 5
DELAY_BETWEEN_PAGES = 3  # seconds
```

**Data flow:**
1. `initialize_driver()` — spins up a headless Chrome session via `webdriver-manager`
2. `build_search_url(offset)` — constructs paginated URLs (50 records/page, offset-based)
3. `load_page()` — loads page and waits for DOM readiness
4. `extract_page_data()` — parses table rows using CSS selectors; falls back to alternate selectors if primary fails
5. `has_more_pages()` — detects end of results via record count or "no results" indicators
6. `process_and_export_data()` — converts to Pandas DataFrame, writes CSV to `data/` with a date-stamped filename

**Output schema** (CSV in `data/`):
```
grantor, grantee, doc_type, recorded_date, doc_number,
book_volume_page, legal_description, record_number,
extracted_at, page_number, offset, processed_at
```

**Key design decisions:**
- Selenium is used (not requests/BS4) because the target site loads records dynamically via JavaScript
- Multiple CSS selector fallbacks per field for resilience against minor DOM changes
- User-agent spoofing and configurable delays for politeness
- Missing fields default to `"N/A"`
