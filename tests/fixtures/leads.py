"""Mock probate lead records for use in tests."""

import uuid

# Must match _LEAD_NS in src/scraper/dynamo.py
_LEAD_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _lead_id(doc_number: str) -> str:
    return str(uuid.uuid5(_LEAD_NS, doc_number))


MOCK_LEADS = [
    {
        "lead_id":           _lead_id("2026000009280"),
        "doc_number":        "2026000009280",
        "grantor":           "CHERRY ERIKA WOOD DECEASED ESTATE",
        "grantee":           "PUBLIC",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-23",
        "book_volume_page":  "--/--/--",
        "legal_description": "N/A",
        "location_code":     "CollinTx",
        "record_number":     "2",
        "page_number":       "1",
        "offset":            "0",
        "extracted_at":      "2026-01-29T20:00:15.989922",
        "processed_at":      "2026-02-20T14:09:56+00:00",
        "scrape_run_id":     "seed-local",
        "pdf_url":           "https://collin.tx.publicsearch.us/doc/2026000009280",
    },
    {
        "lead_id":           _lead_id("2026000009450"),
        "doc_number":        "2026000009450",
        "grantor":           "GOYAL MADAN DECEASED ESTATE",
        "grantee":           "PUBLIC",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-23",
        "book_volume_page":  "--/--/--",
        "legal_description": "N/A",
        "location_code":     "CollinTx",
        "record_number":     "1",
        "page_number":       "1",
        "offset":            "0",
        "extracted_at":      "2026-01-29T20:00:15.944810",
        "processed_at":      "2026-02-20T14:09:56+00:00",
        "scrape_run_id":     "seed-local",
        "pdf_url":           "https://collin.tx.publicsearch.us/doc/2026000009450",
    },
    {
        "lead_id":           _lead_id("2026000008491"),
        "doc_number":        "2026000008491",
        "grantor":           "KING L M JR DECEASED ESTATE",
        "grantee":           "PUBLIC",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-21",
        "book_volume_page":  "--/--/--",
        "legal_description": "N/A",
        "location_code":     "CollinTx",
        "record_number":     "3",
        "page_number":       "1",
        "offset":            "0",
        "extracted_at":      "2026-01-29T20:00:16.036722",
        "processed_at":      "2026-02-20T14:09:56+00:00",
        "scrape_run_id":     "seed-local",
        "pdf_url":           "https://collin.tx.publicsearch.us/doc/2026000008491",
    },
    {
        "lead_id":           _lead_id("2026000007100"),
        "doc_number":        "2026000007100",
        "grantor":           "PATEL ANITA DECEASED ESTATE",
        "grantee":           "PUBLIC",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-15",
        "book_volume_page":  "--/--/--",
        "legal_description": "N/A",
        "location_code":     "CollinTx",
        "record_number":     "4",
        "page_number":       "1",
        "offset":            "0",
        "extracted_at":      "2026-01-29T20:00:16.100000",
        "processed_at":      "2026-02-20T14:09:56+00:00",
        "scrape_run_id":     "seed-local",
        "pdf_url":           "",
    },
    {
        "lead_id":           _lead_id("2026000006200"),
        "doc_number":        "2026000006200",
        "grantor":           "SMITH JOHN DECEASED ESTATE",
        "grantee":           "PUBLIC",
        "doc_type":          "PROBATE",
        "recorded_date":     "2026-01-10",
        "book_volume_page":  "--/--/--",
        "legal_description": "N/A",
        "location_code":     "CollinTx",
        "record_number":     "5",
        "page_number":       "1",
        "offset":            "0",
        "extracted_at":      "2026-01-29T20:00:16.200000",
        "processed_at":      "2026-02-20T14:09:56+00:00",
        "scrape_run_id":     "seed-local",
        "pdf_url":           "",
    },
]

# DynamoDB LastEvaluatedKey shape for location-date-index GSI queries.
# Includes the table PK (lead_id) + both GSI keys (location_code, recorded_date).
PAGINATION_KEY = {
    "lead_id":       _lead_id("2026000008491"),
    "recorded_date": "2026-01-21",
    "location_code": "CollinTx",
}
