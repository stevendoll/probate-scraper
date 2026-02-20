"""Mock location records for use in tests."""

MOCK_LOCATIONS = [
    {
        "location_code": "CollinTx",
        "location_path": "collin-tx",
        "location_name": "Collin County TX",
        "search_url":    "https://collin.tx.publicsearch.us",
        "retrieved_at":  "2026-02-20T06:00:00+00:00",
    },
    {
        "location_code": "DallasTx",
        "location_path": "dallas-tx",
        "location_name": "Dallas County TX",
        "search_url":    "https://dallas.tx.publicsearch.us",
        "retrieved_at":  "",
    },
]

COLLIN_TX = MOCK_LOCATIONS[0]
