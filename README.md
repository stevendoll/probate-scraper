# Probate Leads

Scrapes probate records from county public-records portals and exposes them via a REST API with magic-link auth and Stripe-backed subscriptions. Built on AWS (ECS Fargate + Lambda + DynamoDB + API Gateway + CloudFront).

Live at **[collincountyleads.com](https://collincountyleads.com)**.

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
  └── users          (user_id PK | email-index GSI)
    │
    ▼
API Gateway (api.collincountyleads.com)
    │
    ├── Lambda ApiFunction
    │     GET  /{location_path}/leads
    │     GET  /locations
    │     GET  /locations/{location_code}
    │     GET/POST/PATCH/DELETE  /users
    │     POST /auth/request-login   (magic link)
    │     GET  /auth/verify          (exchange token)
    │     GET/PATCH  /auth/me        (own profile)
    │     GET  /auth/leads           (own leads)
    │     GET/PATCH/DELETE  /admin/users
    │     POST /stripe/webhook       (no API key — Stripe signature)
    │
    └── Lambda TriggerFunction
          POST /{location_path}/update  → runs Fargate scrape task

CloudFront (collincountyleads.com)
    └── S3 — React SPA (Vite)
```

All API paths are prefixed with `/real-estate/probate-leads/`.

## Tables

| Table | Partition key | GSI | Purpose |
|---|---|---|---|
| `leads` | `doc_number` | `recorded-date-index`, `location-date-index` | Scraped probate records |
| `locations` | `location_code` | `location-path-index` | Supported counties |
| `users` | `user_id` | `email-index` | Magic-link authenticated users |

Leads carry a `location_code` FK. The `location-date-index` GSI (`location_code` HASH + `recorded_date` RANGE) is the primary query path.

## Locations

| location_code | location_path | location_name | search_url |
|---|---|---|---|
| `CollinTx` | `collin-tx` | Collin County TX | https://collin.tx.publicsearch.us |

Add new counties by inserting a row in the `locations` table and deploying a new scraper task with the matching `LOCATION_CODE` env var.

## UI

The React SPA lives in `ui/` and is built with Vite + React + TailwindCSS + shadcn/ui.

### Pages

| Route | Component | Description |
|---|---|---|
| `/` | `Landing` | Marketing landing page |
| `/login` | `Login` | Magic-link sign-in form |
| `/auth/verify` | `AuthVerify` | Exchanges magic token for access token, redirects to dashboard |
| `/dashboard` | `Dashboard` | Leads table with date-range filters and CSV export |
| `/account` | `Account` | Edit email, view subscription status |
| `/admin/users` | `admin/Users` | Admin: list and manage all users |
| `/admin/users/:id` | `admin/UserDetail` | Admin: view and edit a single user |

### Key libraries

| Library | Purpose |
|---|---|
| `react-router-dom` | Client-side routing |
| `@tanstack/react-query` | Server state, caching, and request deduplication |
| `react-hook-form` + `zod` | Form validation |
| `@radix-ui/*` | Accessible UI primitives (via shadcn/ui) |
| `lucide-react` | Icons |

### Auth flow

1. User submits email on `/login` → `POST /auth/request-login`
2. API sends a magic link to the email (SES)
3. User clicks the link → `/auth/verify?token=<jwt>`
4. `AuthVerify` exchanges the token → API returns an access token stored in `localStorage`
5. Authenticated requests use `Authorization: Bearer <token>`

Tokens are short-lived JWTs signed with `JWT_SECRET`. Magic-link tokens expire in 15 minutes; access tokens expire in 7 days.

### Local development

```bash
# 1. Start the backend (DynamoDB + API)
make local-db-start
make local-db-seed   # first time only
make local-api-start # http://localhost:3000

# 2. Start the UI dev server
cd ui
npm install
npm run dev          # http://localhost:3001
```

The UI dev server reads `ui/.env.local`:

```env
VITE_API_URL=http://localhost:3000/real-estate/probate-leads
VITE_API_KEY=                     # leave blank for local (no key required)
```

Magic links are printed to the local API server stdout (SES is skipped when `FROM_EMAIL` is unset).

### Production build

The CI/CD pipeline builds the UI automatically on push to `main`:

```bash
cd ui
VITE_API_URL=https://api.collincountyleads.com/real-estate/probate-leads \
VITE_API_KEY=<api-gateway-key> \
npm run build
# Output: ui/dist/
```

To deploy the UI manually:

```bash
make deploy-ui   # sync ui/dist/ to S3 + invalidate CloudFront
```

## Local Development

### Prerequisites
- Docker Desktop (for DynamoDB Local)
- Python 3.12+ with pipenv
- Node.js 18+ (for the UI)
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

# Request a magic link (token printed to stdout, email skipped locally)
curl -X POST $BASE/auth/request-login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'

# Create a user (admin)
curl -X POST $BASE/users \
  -H "x-api-key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","location_codes":["CollinTx"]}'
```

### Run tests

```bash
make test   # unit tests, no external services needed
```

## API Reference

All routes require an `x-api-key` header except `/auth/*` and `POST /stripe/webhook`.

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

### Users

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/users` | API key | List all users |
| `POST` | `/users` | API key | Create a user |
| `GET` | `/users/{user_id}` | API key | Get a user |
| `PATCH` | `/users/{user_id}` | API key | Update `location_codes` and/or `status` |
| `DELETE` | `/users/{user_id}` | API key | Soft-delete (status → `inactive`) |

User statuses: `active` | `inactive` | `canceled` | `past_due`

### Auth

No API key required. All auth routes are public.

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/request-login` | Send a magic link to the given email |
| `GET` | `/auth/verify?token=<jwt>` | Exchange magic token for access token |
| `GET` | `/auth/me` | Get own user profile (Bearer token) |
| `PATCH` | `/auth/me` | Update own email (Bearer token) |
| `GET` | `/auth/leads` | Get own leads (Bearer token, active users only) |

### Admin

Bearer token required, user must have `role: admin`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/users` | List all users |
| `GET` | `/admin/users/{user_id}` | Get a user |
| `PATCH` | `/admin/users/{user_id}` | Update user |
| `DELETE` | `/admin/users/{user_id}` | Soft-delete user |

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

Users are matched by `stripe_customer_id`.

## Stripe Integration

### Setup (test mode)

1. Create a [Stripe account](https://dashboard.stripe.com) and grab your test keys from **Developers → API keys**.
2. Register the webhook endpoint in **Developers → Webhooks → Add endpoint**:
   - URL: `https://api.collincountyleads.com/real-estate/probate-leads/stripe/webhook`
   - Events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
3. Copy the signing secret (`whsec_...`).

### Local testing with Stripe CLI

```bash
stripe listen \
  --forward-to localhost:3000/real-estate/probate-leads/stripe/webhook

# In a second terminal
stripe trigger customer.subscription.created
stripe trigger invoice.payment_failed
```

Start the local API server with the webhook secret the CLI printed:

```bash
STRIPE_WEBHOOK_SECRET=whsec_... make local-api-start
```

> **Without `STRIPE_WEBHOOK_SECRET`** signature verification is skipped, so plain `curl` works for quick local testing.

## Deployment

### First deploy

```bash
# 1. Create ECR repo and push the scraper image
make ecr-create
make build-push

# 2. Fill in samconfig.toml: VpcId, SubnetIds, ScraperImageUri

# 3. Deploy infrastructure
make deploy

# 4. Build and deploy the UI
make deploy-ui
```

### Subsequent deploys

Push to `main` — GitHub Actions runs `ci.yml` (tests) then `deploy.yml` (SAM deploy + UI build + S3 sync).

```bash
make deploy          # manual: sam build + sam deploy
make build-push      # rebuild + push scraper Docker image
make deploy-ui       # manual: sync ui/dist/ to S3 + CloudFront invalidation
```

### Useful operations

```bash
make run-task        # manually trigger a Fargate scrape
make logs-scraper    # tail ECS CloudWatch logs
make logs-api        # tail Lambda logs
make get-api-key     # print the API Gateway key
```

### Custom domain (collincountyleads.com)

Infrastructure is configured for:

| Record | Target |
|---|---|
| `collincountyleads.com` | CloudFront distribution (UI) |
| `www.collincountyleads.com` | CloudFront distribution (UI) |
| `api.collincountyleads.com` | API Gateway edge custom domain |

All Cloudflare DNS records must be **DNS only (gray cloud)** — CloudFront handles SSL termination using the ACM certificate.

SES is configured to send from `hello@collincountyleads.com`. The domain must be verified in SES (DKIM CNAMEs in Cloudflare) and the account must be out of SES sandbox before magic-link emails will deliver.

## Project Structure

```
ui/
  src/
    pages/
      Landing.tsx         # Marketing landing page
      Login.tsx           # Magic-link sign-in
      AuthVerify.tsx      # Token exchange + redirect
      Dashboard.tsx       # Leads table
      Account.tsx         # User profile
      admin/
        Users.tsx         # Admin user list
        UserDetail.tsx    # Admin user detail
    components/
      leads-table.tsx     # Sortable/filterable leads table
      login-form.tsx      # Email form
      user-nav.tsx        # Avatar dropdown
    lib/
      api.ts              # Typed API client
      auth.ts             # Token storage helpers
      types.ts            # Shared TypeScript types
      utils.ts            # cn() and other utilities
src/
  api/
    app.py                # Lambda handler — all API routes
    routers/              # leads, locations, users, auth, admin, stripe
    stripe_helpers.py     # Stripe webhook signature verification
    requirements.txt
  scraper/
    app.py                # ECS entrypoint
    scraper.py            # Selenium scraper
    dynamo.py             # DynamoDB batch writer + location updater
    Dockerfile
    requirements.txt
  trigger/
    app.py                # Lambda — starts Fargate scrape task
    requirements.txt
  parse_document/
    app.py                # Lambda — Bedrock document parsing
scripts/
  seed_local.py           # Create tables + seed locations locally
  local_api_server.py     # Dev HTTP server wrapping the Lambda handler
  smoke_test.py           # End-to-end smoke tests against deployed API
tests/
  test_api.py
  test_auth.py
  test_locations.py
  test_users.py
  test_dynamo.py
  test_scraper.py
  test_s3.py
template.yaml             # SAM / CloudFormation
samconfig.toml            # Deploy configuration
docker-compose.yml        # DynamoDB Local
Makefile
```
