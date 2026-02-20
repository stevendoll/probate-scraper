# Probate Leads

Scrapes probate records from county public-records portals and exposes them via a REST API with Stripe-backed subscriptions. Built on AWS (ECS Fargate + Lambda + DynamoDB + API Gateway).

## Architecture

```
EventBridge (daily cron)
    │
    ▼
ECS Fargate — Selenium scraper (Docker)
    │  writes leads + stamps locations.retrieved_at
    ▼
DynamoDB
  ├── leads          (doc_number PK | location-date-index GSI)
  ├── locations      (location_code PK | location-path-index GSI)
  └── subscribers    (subscriber_id PK | email-index GSI)
    │
    ▼
API Gateway (API key auth)
    │
    ├── Lambda ApiFunction
    │     GET  /{location_path}/leads
    │     GET  /locations
    │     GET  /locations/{location_code}
    │     GET/POST  /subscribers
    │     GET/PATCH/DELETE  /subscribers/{subscriber_id}
    │     POST /stripe/webhook  (no API key — Stripe signature)
    │
    └── Lambda TriggerFunction
          POST /{location_path}/update  → runs Fargate scrape task
```

All API paths are prefixed with `/real-estate/probate-leads/`.

## Tables

| Table | Partition key | GSI | Purpose |
|---|---|---|---|
| `leads` | `doc_number` | `recorded-date-index`, `location-date-index` | Scraped probate records |
| `locations` | `location_code` | `location-path-index` | Supported counties |
| `subscribers` | `subscriber_id` | `email-index` | Stripe-backed subscribers |

Leads carry a `location_code` FK. The `location-date-index` GSI (`location_code` HASH + `recorded_date` RANGE) is the primary query path.

## Locations

| location_code | location_path | location_name | search_url |
|---|---|---|---|
| `CollinTx` | `collin-tx` | Collin County TX | https://collin.tx.publicsearch.us |

Add new counties by inserting a row in the `locations` table and deploying a new scraper task with the matching `LOCATION_CODE` env var.

## Local Development

### Prerequisites
- Docker Desktop (for DynamoDB Local)
- Python 3.12+ with pipenv
- AWS CLI (configured with any credentials for local use)

### Start the local stack

```bash
# 1. Install Python dependencies
pipenv install

# 2. Start DynamoDB Local
make local-db-start

# 3. Create tables and seed data (locations + leads from CSV)
make local-db-seed

# 4. Start the API server on http://localhost:3000
make local-api-start
```

### Sample requests

```bash
BASE=http://localhost:3000/real-estate/probate-leads

# List locations
curl $BASE/locations

# Query leads
curl "$BASE/collin-tx/leads?from_date=2026-01-01&to_date=2026-02-20&limit=10"

# Create a subscriber
curl -X POST $BASE/subscribers \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","location_codes":["CollinTx"],"stripe_customer_id":"cus_xxx"}'

# Update subscriber locations
curl -X PATCH $BASE/subscribers/<subscriber_id> \
  -H "Content-Type: application/json" \
  -d '{"location_codes":["CollinTx"]}'
```

### Run tests

```bash
make test   # 76 unit tests, no external services needed
```

## API Reference

All routes require an `x-api-key` header except `POST /stripe/webhook`.

### Leads

#### `GET /{location_path}/leads`

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `from_date` | `YYYY-MM-DD` | — | Lower bound on `recorded_date` (inclusive) |
| `to_date` | `YYYY-MM-DD` | today | Upper bound on `recorded_date` (inclusive) |
| `doc_type` | string | `PROBATE` | Filter by document type (`ALL` to skip filter) |
| `limit` | int | `50` | Records per page (max 200) |
| `last_key` | string | — | Base64 pagination cursor from previous `nextKey` |

Response:
```json
{
  "requestId": "uuid",
  "location": { "locationCode": "CollinTx", "locationPath": "collin-tx", ... },
  "leads": [ { "docNumber": "...", "grantor": "...", "recordedDate": "...", ... } ],
  "count": 50,
  "nextKey": "base64...",
  "query": { "locationPath": "collin-tx", "fromDate": "2026-01-01", ... }
}
```

### Locations

| Method | Path | Description |
|---|---|---|
| `GET` | `/locations` | List all locations |
| `GET` | `/locations/{location_code}` | Get a single location |

### Subscribers

| Method | Path | Description |
|---|---|---|
| `GET` | `/subscribers` | List all subscribers |
| `POST` | `/subscribers` | Create a subscriber |
| `GET` | `/subscribers/{subscriber_id}` | Get a subscriber |
| `PATCH` | `/subscribers/{subscriber_id}` | Update `location_codes` and/or `status` |
| `DELETE` | `/subscribers/{subscriber_id}` | Soft-delete (status → `inactive`) |

#### `POST /subscribers` body

```json
{
  "email": "user@example.com",
  "location_codes": ["CollinTx"],
  "stripe_customer_id": "cus_...",
  "stripe_subscription_id": "sub_...",
  "status": "active"
}
```

`location_codes` must be a non-empty list of valid `location_code` values.

Subscriber statuses: `active` | `inactive` | `canceled` | `past_due` | `trialing`

### Stripe webhook

#### `POST /stripe/webhook`

No API key required. Verified by `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET`.

Handled events:

| Event | Status set |
|---|---|
| `customer.subscription.created` | `active` |
| `customer.subscription.updated` | mirrors Stripe status |
| `customer.subscription.deleted` | `canceled` |
| `invoice.payment_failed` | `past_due` |

Subscribers are matched by `stripe_customer_id`.

## Stripe Integration

### Setup (test mode)

1. Create a [Stripe account](https://dashboard.stripe.com) and grab your test keys from **Developers → API keys**.
2. Register the webhook endpoint in **Developers → Webhooks → Add endpoint**:
   - URL: `https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/real-estate/probate-leads/stripe/webhook`
   - Events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
3. Copy the signing secret (`whsec_...`).

### Local testing with Stripe CLI

```bash
# Install
brew install stripe/stripe-cli/stripe

# Authenticate
stripe login

# Forward Stripe events to local server (prints a webhook secret)
stripe listen \
  --forward-to localhost:3000/real-estate/probate-leads/stripe/webhook

# Trigger test events in a second terminal
stripe trigger customer.subscription.created
stripe trigger customer.subscription.deleted
stripe trigger invoice.payment_failed
```

Start the local API server with the webhook secret the CLI printed:

```bash
STRIPE_WEBHOOK_SECRET=whsec_... make local-api-start
```

> **Without `STRIPE_WEBHOOK_SECRET`** signature verification is skipped, so plain `curl` works for quick local testing (see [Local Development](#local-development) above).

### Typical subscriber flow

```
1.  User subscribes via your frontend (Stripe Checkout / Elements)
2.  Frontend gets stripe_customer_id + stripe_subscription_id from Stripe
3.  Frontend calls POST /subscribers with those IDs + desired location_codes
4.  Stripe sends webhook events → API auto-updates subscriber status
5.  Your app checks subscriber.status before granting access to leads
```

## Deployment

### First deploy

```bash
# 1. Create ECR repo and push the scraper image
make ecr-create
make build-push

# 2. Fill in samconfig.toml: VpcId, SubnetIds, ScraperImageUri

# 3. Add Stripe keys (or leave empty to skip verification)
# Edit samconfig.toml parameter_overrides:
#   StripeSecretKey=sk_live_...
#   StripeWebhookSecret=whsec_...

# 4. Deploy
make deploy
```

### Subsequent deploys

```bash
make deploy          # sam build + sam deploy
make build-push      # rebuild + push scraper Docker image
```

### Useful operations

```bash
make run-task        # manually trigger a Fargate scrape
make logs-scraper    # tail ECS CloudWatch logs
make logs-api        # tail Lambda logs
make get-api-key     # print the API Gateway key
```

> ⚠️ **Data migration note:** the `leads` table was renamed from `probate-scraper-collin-tx`. CloudFormation will replace it on first deploy — export any data you need to keep before deploying.

## Project Structure

```
src/
  api/
    app.py              # Lambda handler — all API routes
    stripe_helpers.py   # Stripe webhook signature verification
    requirements.txt
  scraper/
    app.py              # ECS entrypoint
    scraper.py          # Selenium scraper
    dynamo.py           # DynamoDB batch writer + location updater
    Dockerfile
    requirements.txt
  trigger/
    app.py              # Lambda — starts Fargate scrape task
    requirements.txt
scripts/
  seed_local.py         # Create tables + seed locations locally
  local_api_server.py   # Dev HTTP server wrapping the Lambda handler
tests/
  fixtures/             # Mock leads, locations, subscribers
  events/               # SAM local invoke payloads
  test_api.py           # Leads endpoint tests
  test_locations.py     # Locations endpoint tests
  test_subscribers.py   # Subscribers + Stripe webhook tests
template.yaml           # SAM / CloudFormation
samconfig.toml          # Deploy configuration
docker-compose.yml      # DynamoDB Local
Makefile
```
