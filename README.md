# Collin County Public Records Scraper

A comprehensive web scraper for extracting probate records from Collin County's public search portal.

## Files Created

- `collin_scraper.py` - Main scraping script (can be run directly or converted to Jupyter notebook)
- `requirements.txt` - Python dependencies
- `README.md` - This documentation

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the Scraper

**Option 1: Direct Python execution**
```bash
python collin_scraper.py
```

**Option 2: Convert to Jupyter notebook**
```bash
pip install jupyter
jupyter nbconvert --to notebook collin_scraper.py --output collin_scraper.ipynb
jupyter notebook collin_scraper.ipynb
```

## Features

- **Dynamic Content Handling**: Uses Selenium to handle JavaScript-loaded content
- **Robust Data Extraction**: Multiple fallback selectors for different page structures
- **Pagination Support**: Automatically navigates through multiple pages
- **Data Export**: Exports to CSV, JSON, and Excel formats
- **Error Handling**: Comprehensive error handling and logging
- **Rate Limiting**: Configurable delays to respect server limits

## Configuration

Key parameters you can adjust:

```python
# In collin_scraper.py
MAX_PAGES = 5  # Number of pages to scrape
DELAY_BETWEEN_PAGES = 3  # Seconds between requests
SEARCH_PARAMS = {
    "searchValue": "probate",  # Change search term
    "limit": "50",  # Results per page
    # ... other parameters
}
```

## Output Files

The scraper generates timestamped files:
- `collin_county_probate_YYYYMMDD_HHMMSS.csv`
- `collin_county_probate_YYYYMMDD_HHMMSS.json`
- `collin_county_probate_YYYYMMDD_HHMMSS.xlsx`

## Target URL

The scraper targets:
```
https://collin.tx.publicsearch.us/results?department=RP&keywordSearch=false&limit=50&offset=0&recordedDateRange=18930107%2C20260123&searchOcrText=false&searchType=quickSearch&searchValue=probate&sort=desc&sortBy=recordedDate
```

## Troubleshooting

### No Data Extracted
- The website structure may have changed
- Try running with `headless=False` to see what's happening
- Check the CSS selectors in the `extract_page_data()` function

### Getting Blocked
- Increase `DELAY_BETWEEN_PAGES`
- Try running during off-peak hours
- The site may require CAPTCHA for extensive scraping

### WebDriver Issues
- Ensure Chrome browser is installed
- Update webdriver-manager: `pip install --upgrade webdriver-manager`

## Legal Considerations

- This scraper is for educational and legitimate research purposes
- Always respect website terms of service
- Use appropriate rate limiting to avoid overwhelming the server
- Be aware of any data usage restrictions

## Data Fields Extracted

The scraper attempts to extract:
- Date recorded
- Instrument type
- Grantor/Seller
- Grantee/Buyer
- Book/Page references
- Description
- Raw text (fallback)

## Advanced Usage

### Custom Search Parameters
Modify `SEARCH_PARAMS` in the script:

```python
SEARCH_PARAMS = {
    "department": "RP",
    "searchValue": "deed",  # Change from "probate"
    "recordedDateRange": "20200101,20231231",  # Custom date range
    # ... other parameters
}
```

### Custom Selectors
If the website structure changes, update the selectors in:
- `extract_record_data()` - For individual record fields
- `extract_page_data()` - For record containers
- Pagination functions - For navigation elements

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Verify all dependencies are installed
3. Test with a smaller number of pages first
4. Examine the browser output when running with `headless=False`
