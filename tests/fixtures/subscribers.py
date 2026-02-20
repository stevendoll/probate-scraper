"""Mock subscriber records for use in tests."""

MOCK_SUBSCRIBERS = [
    {
        "subscriber_id":          "sub-uuid-001",
        "email":                  "alice@example.com",
        "stripe_customer_id":     "cus_alice123",
        "stripe_subscription_id": "sub_alice456",
        "status":                 "active",
        "location_codes":         {"CollinTx"},
        "created_at":             "2026-02-01T00:00:00+00:00",
        "updated_at":             "2026-02-01T00:00:00+00:00",
    },
    {
        "subscriber_id":          "sub-uuid-002",
        "email":                  "bob@example.com",
        "stripe_customer_id":     "cus_bob789",
        "stripe_subscription_id": "sub_bob012",
        "status":                 "active",
        "location_codes":         {"CollinTx", "DallasTx"},
        "created_at":             "2026-02-10T00:00:00+00:00",
        "updated_at":             "2026-02-10T00:00:00+00:00",
    },
]

ALICE = MOCK_SUBSCRIBERS[0]
BOB   = MOCK_SUBSCRIBERS[1]
