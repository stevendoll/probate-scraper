"""Mock user records for use in tests."""

MOCK_USERS = [
    {
        "user_id":                "user-uuid-001",
        "email":                  "alice@example.com",
        "role":                   "user",
        "stripe_customer_id":     "cus_alice123",
        "stripe_subscription_id": "sub_alice456",
        "status":                 "active",
        "location_codes":         {"CollinTx"},
        "created_at":             "2026-02-01T00:00:00+00:00",
        "updated_at":             "2026-02-01T00:00:00+00:00",
    },
    {
        "user_id":                "user-uuid-002",
        "email":                  "bob@example.com",
        "role":                   "user",
        "stripe_customer_id":     "cus_bob789",
        "stripe_subscription_id": "sub_bob012",
        "status":                 "active",
        "location_codes":         {"CollinTx", "DallasTx"},
        "created_at":             "2026-02-10T00:00:00+00:00",
        "updated_at":             "2026-02-10T00:00:00+00:00",
    },
]

ALICE = MOCK_USERS[0]
BOB   = MOCK_USERS[1]
