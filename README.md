# Probate Leads

Scrapes probate records from county public-records portals and exposes them via a REST API with magic-link auth and Stripe-backed subscriptions. Built on AWS (ECS Fargate + Lambda + DynamoDB + API Gateway + CloudFront).

Live at **[collincountyleads.com](https://collincountyleads.com)**.

## Architecture

```
EventBridge (daily cron)
    │
    ▼
ECS Fargate — Selenium scraper (Docker)
    │  writes documents + stamps locations.retrieved_at
    ▼
DynamoDB
  ├── documents      (document_id PK | location-date-index GSI)
  ├── contacts       (contact_id PK | document-contact-index GSI)
  ├── properties     (property_id PK | document-property-index GSI)
  ├── locations      (location_code PK | location-path-index GSI)
  ├── users          (user_id PK | email-index GSI)
  └── activities     (activity_id PK | user-activity-index GSI)
    │
    ▼
API Gateway (api.collincountyleads.com)
    │
    ├── Lambda ApiFunction
    │     GET  /{location_path}/documents
    │     GET  /documents/{document_id}
    │     GET  /documents/{document_id}/contacts
    │     GET  /documents/{document_id}/properties
    │     GET  /locations
    │     GET  /locations/{location_code}
    │     GET/POST/PATCH/DELETE  /users
    │     POST /auth/request-login   (magic link + inbound user creation)
    │     GET  /auth/verify          (exchange token)
    │     GET/PATCH  /auth/me        (own profile)
    │     GET  /auth/leads           (own leads)
    │     GET/PATCH/DELETE  /admin/users
    │     POST /admin/funnel/send    (send funnel emails)
    │     POST /admin/activity/log   (log activities)
    │     POST /admin/activity/query (query activities)
    │     POST /activity/track       (track funnel clicks)
    │     POST /stripe/webhook       (no API key — Stripe signature)
    │     POST /auth/unsubscribe     (funnel unsubscribe)
    │     POST /stripe/checkout      (Stripe checkout)
    │
    ├── Lambda TriggerFunction
    │     POST /{location_path}/update  → runs Fargate scrape task
    │
    └── Lambda ParseDocumentFunction
          POST /documents/{document_id}/parse-document  → Bedrock AI parsing

CloudFront (collincountyleads.com)
    └── S3 — React SPA (Vite)
```

All API paths are prefixed with `/real-estate/probate-leads/`.

## Tables

| Table | Partition key | GSI | Purpose |
|---|---|---|---|
| `documents` | `document_id` | `location-date-index` | Scraped probate filings |
| `contacts` | `contact_id` | `document-contact-index` | People parsed from documents (deceased, executors, heirs) |
| `properties` | `property_id` | `document-property-index` | Real estate assets parsed from documents |
| `locations` | `location_code` | `location-path-index` | Supported counties |
| `users` | `user_id` | `email-index` | Magic-link authenticated users |
| `activities` | `activity_id` | `user-activity-index` | User funnel activity tracking |

Documents carry a `location_code` FK. The `location-date-index` GSI (`location_code` HASH + `recorded_date` RANGE) is the primary query path.

Contacts and properties are written by `ParseDocumentFunction` after Bedrock AI analysis of the archived PDF. Each links back to its parent document via `document_id`.

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
| `/signup` | `Signup` | Funnel signup page with pricing |
| `/dashboard` | `Dashboard` | Leads table with date-range filters |
| `/documents/:documentId` | `DocumentDetail` | Filing details, parsed people (contacts), and real estate (properties) |
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
   - **New users**: Created with "inbound" status, CollinTx location, funnel email sent
   - **Existing users**: Magic link sent
2. API sends a magic link to the email (SES) or funnel email for new users
3. User clicks the link → `/auth/verify?token=<jwt>` or `/signup?token=<funnel_jwt>`
4. `AuthVerify` exchanges the token → API returns an access token stored in `localStorage`
5. Authenticated requests use `Authorization: Bearer <token>`

**User Status Flow**: `inbound` → `prospect` → `free_trial` → `active`

Tokens are short-lived JWTs signed with `JWT_SECRET`. Magic-link tokens expire in 15 minutes; access tokens expire in 7 days; funnel tokens expire in 30 days.

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

# Query documents for a county
curl "$BASE/collin-tx/documents?from_date=2026-01-01&to_date=2026-02-20&limit=10"

# Get a single document (with contacts + properties)
curl $BASE/documents/3f2ab7c4-f5d1-5e71-b650-97b7c2ff37d1

# Get contacts for a document
curl $BASE/documents/3f2ab7c4-f5d1-5e71-b650-97b7c2ff37d1/contacts

# Parse a document with Bedrock AI (requires DOCUMENTS_BUCKET + AWS credentials)
curl -X POST $BASE/documents/3f2ab7c4-f5d1-5e71-b650-97b7c2ff37d1/parse-document

# Request a magic link (token printed to stdout, email skipped locally)
curl -X POST $BASE/auth/request-login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'

# Request a magic link with name parsing
curl -X POST $BASE/auth/request-login \
  -H "Content-Type: application/json" \
  -d '{"email":"John Doe <john@example.com>"}'

# Send funnel emails to prospects (admin)
curl -X POST $BASE/admin/funnel/send \
  -H "x-api-key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"emails": ["John Doe <john@example.com>", "jane@example.com"], "lead_count": 10}'

# Query user activities (admin)
curl -X POST $BASE/admin/activity/query \
  -H "x-api-key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-uuid", "limit": 50}'

# Track funnel link click (public)
curl -X POST $BASE/activity/track \
  -H "Content-Type: application/json" \
  -d '{"token": "funnel.jwt.token", "activity_type": "subscribe_clicked"}'

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

### Documents

#### `GET /{location_path}/documents`

List documents for a county, newest first.

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `from_date` | `YYYY-MM-DD` | — | Lower bound on `recorded_date` (inclusive) |
| `to_date` | `YYYY-MM-DD` | — | Upper bound on `recorded_date` (inclusive) |
| `doc_type` | string | `PROBATE` | Filter by document type (`ALL` to skip filter) |
| `limit` | int | `50` | Records per page (max 200) |
| `last_key` | string | — | Base64 pagination cursor from previous `nextKey` |

Response:
```json
{
  "requestId": "uuid",
  "location": { "locationCode": "CollinTx", "locationPath": "collin-tx", ... },
  "documents": [ { "documentId": "...", "docNumber": "...", "grantor": "...", "recordedDate": "...", ... } ],
  "count": 50,
  "nextKey": "base64...",
  "query": { "locationPath": "collin-tx", "fromDate": "2026-01-01", ... }
}
```

#### `GET /documents/{document_id}`

Fetch a single document along with its parsed contacts and properties.

Response:
```json
{
  "requestId": "uuid",
  "document": {
    "documentId": "...",
    "docNumber": "2026000028265",
    "grantor": "CIATTI, CESARE FRED",
    "grantee": "SHANNON CIATTI ET AL",
    "recordedDate": "2026-01-15",
    "locationCode": "CollinTx",
    "pdfUrl": "https://...",
    "docS3Uri": "s3://bucket/documents/CollinTx/2026000028265.pdf"
  },
  "contacts": [
    { "contactId": "...", "documentId": "...", "role": "deceased", "name": "Cesare Fred Ciatti", "dod": "2025-12-01", ... },
    { "contactId": "...", "documentId": "...", "role": "executor", "name": "Shannon Ciatti", ... }
  ],
  "properties": [
    { "propertyId": "...", "documentId": "...", "address": "301 Oregonfly Drive", "city": "Prosper", "state": "TX", ... }
  ]
}
```

Returns `404` if the document is not found.

#### `GET /documents/{document_id}/contacts`

Returns the contacts array only (same items as in the full document response above).

#### `GET /documents/{document_id}/properties`

Returns the properties array only.

#### `POST /documents/{document_id}/parse-document`

Trigger Bedrock AI parsing of the archived PDF. Requires `doc_s3_uri` to be set on the document (run the scraper with `DOCUMENTS_BUCKET` set, or use the backfill script).

Returns `{ contactsWritten, propertiesWritten }` on success.

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

User statuses: `inbound` | `prospect` | `free_trial` | `active` | `inactive` | `canceled` | `past_due`

### Auth

No API key required. All auth routes are public.

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/request-login` | Send a magic link to the given email (creates inbound users) |
| `GET` | `/auth/verify?token=<jwt>` | Exchange magic token for access token |
| `GET` | `/auth/me` | Get own user profile (Bearer token) |
| `PATCH` | `/auth/me` | Update own email (Bearer token) |
| `GET` | `/auth/leads` | Get own leads (Bearer token, active users only) |
| `POST` | `/auth/unsubscribe` | Unsubscribe via funnel JWT (no API key) |

### Funnel

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/admin/funnel/send` | API key | Send funnel emails to prospects |
| `POST` | `/stripe/checkout` | No key | Create Stripe checkout session |

### Activity Tracking

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/admin/activity/log` | API key | Log user activity manually |
| `POST` | `/admin/activity/query` | API key | Query user activities |
| `POST` | `/activity/track` | No key | Track funnel link clicks (token-based) |

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

## Activity Tracking

The system tracks the complete user funnel journey for analytics and optimization:

### Activity Types
- `email_sent` - When funnel emails are sent
- `magic_link_sent` - When login magic links are sent  
- `subscribe_clicked` - When subscribe links in emails are clicked
- `unsubscribe_clicked` - When unsubscribe links are clicked
- `signup_started` - When user begins signup process
- `signup_completed` - When user completes signup
- `payment_completed` - When payment succeeds

### Tracking Data
```json
{
  "activity_id": "uuid",
  "user_id": "uuid", 
  "activity_type": "email_sent",
  "timestamp": "2026-03-05T12:00:00Z",
  "email_template": "prospect_email_v1.html",
  "from_name": "John Smith",
  "subject_line": "Your probate leads are ready",
  "funnel_token": "jwt.token.here",
  "metadata": {
    "to_email": "user@example.com",
    "price": 19,
    "lead_count": 10,
    "personalized": true,
    "user_agent": "Mozilla/5.0...",
    "ip": "192.168.1.1"
  }
}
```

### Frontend Integration
```javascript
// Track link clicks in emails
fetch('/real-estate/probate-leads/activity/track', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    token: funnelToken,
    activity_type: 'subscribe_clicked'
  })
});
```

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
      Landing.tsx            # Marketing landing page
      Login.tsx              # Magic-link sign-in
      AuthVerify.tsx         # Token exchange + redirect
      Signup.tsx             # Funnel signup with pricing
      Dashboard.tsx          # Documents table (own leads)
      DocumentDetail.tsx     # Single document: filing details, people, real estate
      Account.tsx            # User profile
      admin/
        Users.tsx            # Admin user list
        UserDetail.tsx       # Admin user detail
    components/
      leads-table.tsx        # Filterable documents table with links to detail page
      login-form.tsx         # Email form
      user-nav.tsx           # Avatar dropdown
    lib/
      api.ts                 # Typed API client
      auth.ts                # Token storage helpers
      types.ts               # Shared TypeScript types (Document, Contact, Property, …)
      utils.ts               # cn() and other utilities
src/
  api/
    app.py                   # Lambda handler — all API routes
    routers/                 # documents, locations, users, auth, admin, stripe, funnel, activity
    auth_helpers.py          # JWT helpers + email sending + activity tracking
    models.py                # Document, Contact, Property, Location, User dataclasses
    stripe_helpers.py        # Stripe webhook signature verification
    requirements.txt
  scraper/
    app.py                   # ECS entrypoint
    scraper.py               # Selenium scraper
    dynamo.py                # DynamoDB batch writer + location updater
    s3.py                    # S3 upload helpers
    Dockerfile
    requirements.txt
  trigger/
    app.py                   # Lambda — starts Fargate scrape task
    requirements.txt
  parse_document/
    app.py                   # Lambda — Bedrock AI parsing → writes contacts + properties
    prompt.py                # System/user prompts for the Bedrock model
scripts/
  seed_local.py              # Create tables + seed locations locally
  local_api_server.py        # Dev HTTP server wrapping the Lambda handler
  backfill_s3_uris.py        # Back-fill doc_s3_uri in AWS DynamoDB from S3 bucket
  backfill_s3_uris_local.py  # Same, targeting DynamoDB Local
  smoke_test.py              # End-to-end smoke tests against deployed API
tests/
  test_api.py
  test_auth.py
  test_funnel.py
  test_locations.py
  test_users.py
  test_dynamo.py
  test_scraper.py
  test_s3.py
template.yaml               # SAM / CloudFormation
samconfig.toml              # Deploy configuration
docker-compose.yml          # DynamoDB Local
Makefile
```
