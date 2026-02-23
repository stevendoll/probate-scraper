"""
Mock HTML for Collin County probate search results
(https://collin.tx.publicsearch.us/results).

Used as the reference source for mock Selenium elements in scraper tests.
The structure mirrors the live page's table layout and CSS selectors used
in extract_page_data():
  td.col-3  — grantor
  td.col-4  — grantee
  td.col-5  — doc_type   (inside <em>)
  td.col-6  — recorded_date
  td.col-7  — doc_number  (+ optional <a> document link)
  td.col-8  — book_volume_page
  td.col-9  — legal_description
"""

MOCK_PAGE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Search Results — Collin County Clerk</title></head>
<body>
  <div class="results-header">
    <span aria-label="Search Result Totals">1-50 of 6,720 results</span>
  </div>

  <table>
    <!-- Row 0: header (skipped by extract_page_data) -->
    <tr>
      <th></th><th></th>
      <th>Grantor</th><th>Grantee</th><th>Doc Type</th>
      <th>Recorded Date</th><th>Doc Number</th><th>Book/Vol Page</th>
      <th>Legal Description</th>
    </tr>
    <!-- Row 1: spacer (skipped by extract_page_data) -->
    <tr class="spacer-row"><td colspan="9">&nbsp;</td></tr>

    <!-- Row 2: data row WITH an inline document link -->
    <tr class="data-row">
      <td class="col-1"></td>
      <td class="col-2"></td>
      <td class="col-3" column="[object Object]"><span>SMITH JOHN A</span></td>
      <td class="col-4" column="[object Object]"><span>JONES MARY B</span></td>
      <td class="col-5" column="[object Object]"><span><em>PROBATE</em></span></td>
      <td class="col-6" column="[object Object]"><span>01/15/2024</span></td>
      <td class="col-7" column="[object Object]">
        <span>20240001234</span>
        <a href="https://collin.tx.publicsearch.us/doc/20240001234">
          <img src="/icons/pdf.svg" alt="View document" />
        </a>
      </td>
      <td class="col-8" column="[object Object]"><span></span></td>
      <td class="col-9">LOT 5 BLK 3 SUNNY ACRES PH 1</td>
    </tr>

    <!-- Row 3: data row WITHOUT an inline link (requires clicking) -->
    <tr class="data-row">
      <td class="col-1"></td>
      <td class="col-2"></td>
      <td class="col-3" column="[object Object]"><span>DOE JANE E</span></td>
      <td class="col-4" column="[object Object]"><span>DOE JOHN E</span></td>
      <td class="col-5" column="[object Object]"><span><em>PROBATE</em></span></td>
      <td class="col-6" column="[object Object]"><span>02/20/2024</span></td>
      <td class="col-7" column="[object Object]"><span>20240005678</span></td>
      <td class="col-8" column="[object Object]"><span></span></td>
      <td class="col-9">LOT 12 BLK 7 HERITAGE PARK</td>
    </tr>
  </table>

  <!-- Detail panel — hidden until a row is clicked -->
  <div class="document-detail" style="display:none">
    <h2>Document Detail</h2>
    <a href="https://collin.tx.publicsearch.us/doc/20240005678">
      View Document
    </a>
    <button class="close-panel">Close</button>
  </div>
</body>
</html>
"""

# Expected parsed values matching the HTML above
ROW_WITH_PDF = {
    "grantor":           "SMITH JOHN A",
    "grantee":           "JONES MARY B",
    "doc_type":          "PROBATE",
    "recorded_date":     "01/15/2024",
    "doc_number":        "20240001234",
    "book_volume_page":  "",
    "legal_description": "LOT 5 BLK 3 SUNNY ACRES PH 1",
    "pdf_url":           "https://collin.tx.publicsearch.us/doc/20240001234",
}

ROW_WITHOUT_PDF_INLINE = {
    "grantor":           "DOE JANE E",
    "grantee":           "DOE JOHN E",
    "doc_type":          "PROBATE",
    "recorded_date":     "02/20/2024",
    "doc_number":        "20240005678",
    "book_volume_page":  "",
    "legal_description": "LOT 12 BLK 7 HERITAGE PARK",
    "pdf_url":           "https://collin.tx.publicsearch.us/doc/20240005678",  # found via click
}
