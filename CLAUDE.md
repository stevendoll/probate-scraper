# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pipenv install

# Run tests (no external services needed)
make test

# Local dev stack
make local-db-start    # start DynamoDB Local (Docker required)
make local-db-seed     # create tables + seed CollinTx location
make local-api-start   # HTTP server on localhost:3000

# Build & deploy
make build-push        # rebuild + push scraper Docker image to ECR
make deploy            # sam build + sam deploy

# Operate
make run-task          # manually trigger a Fargate scrape
make logs-scraper      # tail ECS CloudWatch logs
make logs-api          # tail Lambda logs
make get-api-key       # print the API Gateway key value
```

There are no lint commands. Tests use stdlib `unittest` — run with `make test` or `pipenv run python -m unittest discover -s tests -p "test_*.py" -v`.

## Architecture

AWS SAM application: ECS Fargate scraper + Lambda API + DynamoDB + API Gateway.

**DynamoDB tables:**
- `leads` — scraped probate records (PK: `doc_number`; GSIs: `recorded-date-index`, `location-date-index`)
- `locations` — supported counties (PK: `location_code`; GSI: `location-path-index`)
- `subscribers` — Stripe-backed subscribers (PK: `subscriber_id`; GSI: `email-index`)

**Lambda functions:**
- `ApiFunction` (`src/api/`) — handles all REST routes
- `TriggerFunction` (`src/trigger/`) — starts a Fargate scrape task on POST

**Scraper** (`src/scraper/`) — Docker container running on ECS Fargate; reads `LOCATION_CODE` env var, writes leads to DynamoDB, stamps `locations.retrieved_at` on completion.

**All API paths** are prefixed with `/real-estate/probate-leads/`:

```
GET  /{location_path}/leads               leads for a county (location-date-index GSI)
GET  /locations                           list all locations
GET  /locations/{location_code}           single location
GET  /subscribers                         list all subscribers
POST /subscribers                         create subscriber (validates location_codes)
GET  /subscribers/{subscriber_id}         get subscriber
PATCH /subscribers/{subscriber_id}        update location_codes / status
DELETE /subscribers/{subscriber_id}       soft-delete (status → inactive)
POST /stripe/webhook                      Stripe lifecycle events (no API key)
POST /{location_path}/update              trigger Fargate scrape (TriggerFunction)
```

## Key source files

| File | Purpose |
|---|---|
| `template.yaml` | SAM/CloudFormation — all infra |
| `src/api/app.py` | All Lambda routes; field maps; helpers |
| `src/api/stripe_helpers.py` | Stripe webhook signature verification; skips verification when `STRIPE_WEBHOOK_SECRET` is unset (local dev) |
| `src/scraper/scraper.py` | Selenium scrape loop — `scrape_all(scrape_run_id, location_code)` |
| `src/scraper/dynamo.py` | `write_records()` (batch writer) + `update_location_retrieved_at()` |
| `src/scraper/app.py` | ECS entrypoint — reads env vars, calls scraper, stamps location |
| `src/trigger/app.py` | Lambda — resolves `location_path` → `location_code`, calls `ecs.run_task()` |
| `scripts/seed_local.py` | Creates all 3 tables + seeds CollinTx |
| `scripts/local_api_server.py` | Thin HTTP wrapper around the Lambda handler for local dev |

## Stripe integration

- Subscribers link to Stripe via `stripe_customer_id` + `stripe_subscription_id` stored in DynamoDB.
- The webhook at `POST /stripe/webhook` is excluded from API key auth in `template.yaml` (`Auth: ApiKeyRequired: false`).
- `stripe_helpers.construct_stripe_event()` verifies the `Stripe-Signature` header. When `STRIPE_WEBHOOK_SECRET` is empty it skips verification (safe for local dev/tests).
- Subscriber statuses set by webhooks: `active`, `canceled`, `past_due`, plus any raw Stripe status string on `customer.subscription.updated`.
- **Local testing**: `stripe listen --forward-to localhost:3000/real-estate/probate-leads/stripe/webhook` then `stripe trigger <event>`.

## Environment variables

| Variable | Where used | Default | Notes |
|---|---|---|---|
| `DYNAMO_TABLE_NAME` | api, scraper | `leads` | |
| `LOCATIONS_TABLE_NAME` | api, scraper, trigger | `locations` | |
| `SUBSCRIBERS_TABLE_NAME` | api | `subscribers` | |
| `GSI_NAME` | api | `recorded-date-index` | legacy GSI |
| `LOCATION_DATE_GSI` | api | `location-date-index` | primary query GSI |
| `LOCATION_CODE` | scraper | `CollinTx` | injected by ECS task override |
| `STRIPE_SECRET_KEY` | api | `""` | |
| `STRIPE_WEBHOOK_SECRET` | api | `""` | empty = skip signature check |
| `SCRAPER_USERNAME` | scraper | `""` | login email; leave blank to skip login |
| `SCRAPER_PASSWORD` | scraper | `""` | login password |
| `DOCUMENTS_BUCKET` | scraper | `""` | S3 bucket for document archiving; leave blank to skip |
| `DOWNLOAD_DIR` | scraper | `/tmp/scraper_downloads` | local dir for Chrome downloads |
| `CHROME_BIN` | scraper | `/usr/bin/chromium` | set in Dockerfile |
| `CHROMEDRIVER_PATH` | scraper | `/usr/bin/chromedriver` | set in Dockerfile |

To run the scraper locally (outside Docker), first start DynamoDB Local, then:
```bash
make local-db-start   # start DynamoDB Local (Docker required)
make local-db-seed    # create tables + seed CollinTx location (first time only)

CHROMEDRIVER_PATH=/opt/homebrew/bin/chromedriver \
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
DYNAMO_TABLE_NAME=leads \
LOCATIONS_TABLE_NAME=locations \
LOCATION_CODE=CollinTx \
SCRAPER_USERNAME=your@email.com \
SCRAPER_PASSWORD='your-password' \
pipenv run python src/scraper/app.py
```

> Single-quote the password so shell special characters (e.g. `!`) are not interpreted.
> Omit `SCRAPER_USERNAME` / `SCRAPER_PASSWORD` entirely to skip login (public access only).

**Deploying with credentials** — add to `samconfig.toml` `parameter_overrides`:
```
ScraperUsername=your@email.com
ScraperPassword=your-password
```
`ScraperPassword` has `NoEcho: true` so it won't appear in the CloudFormation console.
Alternatively use an SSM reference: `ScraperPassword=/probate-scraper/password`

## Adding a new county

1. Insert a row in the `locations` table: `location_code`, `location_path`, `location_name`, `search_url`.
2. Update `SEARCH_PARAMS` in `src/scraper/scraper.py` if the new site has a different URL structure (or parameterize `BASE_URL`).
3. Deploy a second ECS task definition (or use task overrides) with `LOCATION_CODE=<new_code>`.
4. Add a new EventBridge rule to schedule the scrape.

## Data migration note

The leads table was renamed from `probate-leads-collin-tx` to `leads`. CloudFormation will **replace** (delete + recreate) the table on first deploy of this branch — export any production data before deploying.
