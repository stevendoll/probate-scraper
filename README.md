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
  ├── links          (link_id PK | document-link-index GSI)
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
    │     POST/DELETE  /documents/{document_id}/contacts/{contact_id}/links
    │     GET  /documents/{document_id}/properties
    │     POST/DELETE  /documents/{document_id}/properties/{property_id}/links
    │     GET  /locations
    │     GET  /locations/{location_code}
    │     GET/POST/PATCH/DELETE  /users
    │     POST /auth/request-login   (magic link + inbound user creation)
    │     GET  /auth/verify          (exchange token)
    │     GET/PATCH  /auth/me        (own profile)
    │     GET  /auth/leads           (own leads)
    │     GET/PATCH/DELETE  /admin/users
    │     POST /stripe/webhook       (no API key — Stripe signature)
    │     POST /stripe/checkout      (Stripe checkout)
    │
    ├── Lambda TriggerFunction
    │     POST /{location_path}/update  → runs Fargate scrape task
    │
    └── Lambda ParseDocumentFunction
          POST /documents/{document_id}/parse-document  → Bedrock AI parsing,
                                                           name capitalisation,
                                                           contact deduplication

CloudFront (collincountyleads.com)
    └── S3 — React SPA (Vite)
```

All API paths are prefixed with `/real-estate/probate-leads/`.

## Tables

| Table | Partition key | GSI | Purpose |
|---|---|---|---|
| `documents` | `document_id` | `location-date-index` | Scraped probate filings |
| `contacts` | `contact_id` | `document-contact-index` | People parsed from documents (deceased, executors, heirs, etc.) |
| `properties` | `property_id` | `document-property-index` | Real estate assets parsed from documents |
| `links` | `link_id` | `document-link-index` | Reference URLs attached to a contact or property (Zillow, obituary, etc.) |
| `locations` | `location_code` | `location-path-index` | Supported counties |
| `users` | `user_id` | `email-index` | Magic-link authenticated users |
| `activities` | `activity_id` | `user-activity-index` | User funnel activity tracking |

Documents carry a `location_code` FK. The `location-date-index` GSI (`location_code` HASH + `recorded_date` RANGE) is the primary query path.

Contacts and properties are written by `ParseDocumentFunction` after Bedrock AI analysis of the archived PDF. Each links back to its parent document via `document_id`. The parse Lambda also capitalises ALL-CAPS probate names to Title Case and deduplicates people who appear with multiple roles, keeping the highest-priority role and merging the rest into `notes`.

Links (`links` table) are manually curated through the UI and attach to either a contact or a property via `parent_id` / `parent_type`. A single `document-link-index` GSI on `document_id` lets `GET /documents/{id}` fetch all links in one query and distribute them to the correct contact/property.

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
| `/signup` | `Signup` | Prospect signup page with pricing (existing journey) |
| `/dashboard` | `Dashboard` | Leads table with date-range filters + trial countdown banner |
| `/documents/:documentId` | `DocumentDetail` | Filing details, parsed contacts and properties, editable links per row |
| `/account` | `Account` | Edit email, view subscription status |
| `/waitlist/signup` | `WaitlistSignup` | Join waitlist for coming soon journey |
| `/waitlist/success` | `WaitlistSuccess` | Waitlist confirmation with countdown |
| `/trial/signup` | `TrialSignup` | Free trial invitation signup |
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

**User Status Flow**: Multiple customer journeys supported:

1. **Coming Soon Journey**: `invited_to_waitlist` → `accepted_waitlist` → `invited_to_join` → `subscribed`
2. **Prospect Journey**: `inbound` → `prospect` → `active`
3. **Free Trial Journey**: `invited_to_trial` → `trialing` → `active` | `trial_expired`

Tokens are short-lived JWTs signed with `JWT_SECRET`. Magic-link tokens expire in 15 minutes; access tokens expire in 7 days; prospect tokens expire in 30 days.

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
    "docS3Uri": "s3://bucket/documents/CollinTx/2026000028265.pdf",
    "parsedAt": "2026-03-13T12:00:00.000Z",
    "summary": "Estate of Cesare Fred Ciatti …"
  },
  "contacts": [
    {
      "contactId": "...", "role": "deceased", "name": "Cesare Fred Ciatti", "dod": "2025-12-01",
      "links": []
    },
    {
      "contactId": "...", "role": "executor", "name": "Shannon Ciatti",
      "links": [
        { "linkId": "...", "parentId": "...", "parentType": "contact",
          "label": "Legacy.com", "url": "https://www.legacy.com/search?name=Shannon+Ciatti",
          "linkType": "legacy", "createdAt": "..." }
      ]
    }
  ],
  "properties": [
    {
      "propertyId": "...", "address": "301 Oregonfly Drive", "city": "Prosper", "state": "TX",
      "isVerified": true,
      "links": [
        { "linkId": "...", "parentType": "property", "label": "Zillow",
          "url": "https://www.zillow.com/homes/...", "linkType": "zillow", "createdAt": "..." }
      ]
    }
  ]
}
```

Returns `404` if the document is not found.

#### `GET /documents/{document_id}/contacts`

Returns the contacts array only (no `links` field — use the full document endpoint for links).

#### `GET /documents/{document_id}/properties`

Returns the properties array only (no `links` field).

#### `POST /documents/{document_id}/parse-document`

Trigger Bedrock AI parsing of the archived PDF. Requires `doc_s3_uri` to be set on the document (run the scraper with `DOCUMENTS_BUCKET` set, or use the backfill script).

- Clears any existing contacts and properties for the document before writing new results.
- Names are capitalised to Title Case (handles hyphenated names and apostrophes).
- Duplicate people are collapsed: the highest-priority role is kept (`executor > attorney > trustee > guardian > beneficiary > heir > spouse > other`), secondary roles are appended to `notes`.

Returns `{ contactsWritten, propertiesWritten }` on success.

#### `POST /documents/{document_id}/contacts/{contact_id}/links`

Add a link to a contact (Zillow, obituary, etc.).

Request body:

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | ✓ | Full URL |
| `label` | string | — | Display label (e.g. `"Legacy.com"`) |
| `link_type` | string | — | One of `zillow` \| `realtor` \| `redfin` \| `google_maps` \| `county_record` \| `obituary` \| `legacy` \| `findagrave` \| `other` (default `other`) |
| `notes` | string | — | Free-text notes |

Returns `201` with `{ link: { linkId, parentId, parentType, documentId, label, url, linkType, notes, createdAt } }`.

#### `DELETE /documents/{document_id}/contacts/{contact_id}/links/{link_id}`

Remove a link from a contact. Returns `{ deleted: link_id }`.

#### `POST /documents/{document_id}/properties/{property_id}/links`

Same schema as the contact link endpoint. Returns `201` with the created link.

#### `DELETE /documents/{document_id}/properties/{property_id}/links/{link_id}`

Remove a link from a property. Returns `{ deleted: link_id }`.

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

### Customer Journeys

Bearer token required for admin endpoints; public endpoints for user actions.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/journeys/invite-to-waitlist` | Admin | Send waitlist invitations |
| `POST` | `/journeys/accept-waitlist` | Public | Accept waitlist signup |
| `POST` | `/journeys/invite-to-join-from-waitlist` | Admin | Send launch invitations to waitlist users |
| `POST` | `/journeys/invite-to-trial` | Admin | Send free trial invitations |
| `POST` | `/journeys/start-trial` | Public | Start free trial with prospect JWT |
| `GET` | `/journeys/trial-status/{user_id}` | Bearer | Get trial status for UI banners |

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
      Landing.tsx            # Marketing landing page
      Login.tsx              # Magic-link sign-in
      AuthVerify.tsx         # Token exchange + redirect
      Signup.tsx             # Prospect signup with pricing (existing journey)
      Dashboard.tsx          # Documents table (own leads) + trial countdown banner
      DocumentDetail.tsx     # Single document: filing details, people, real estate
      Account.tsx            # User profile
      WaitlistSignup.tsx     # Join waitlist for coming soon journey
      WaitlistSuccess.tsx    # Waitlist confirmation with countdown
      TrialSignup.tsx        # Free trial invitation signup
      admin/
        Users.tsx            # Admin user list
        UserDetail.tsx       # Admin user detail
    components/
      leads-table.tsx        # Filterable documents table with links to detail page
      login-form.tsx         # Email form
      user-nav.tsx           # Avatar dropdown
      trial-banner.tsx       # Free trial countdown banner
      waitlist-form.tsx      # Waitlist signup form component
    lib/
      api.ts                 # Typed API client (incl. createLink / deleteLink)
      auth.ts                # Token storage helpers
      types.ts               # Shared TypeScript types (Document, Contact, Property, Link, …)
      utils.ts               # cn() and other utilities
src/
  api/
    app.py                   # Lambda handler — all API routes
    routers/                 # documents, locations, users, auth, admin, stripe, customer_journeys
    auth_helpers.py          # JWT helpers + email sending + activity tracking
    email_templates.py       # Jinja2-based email template system for customer journeys
    models.py                # Document, Contact, Property, Link, Location, User dataclasses (+ journey fields)
    stripe_helpers.py        # Stripe webhook signature verification
    templates/
      journeys/              # Customer journey email templates
        coming_soon/         # Waitlist invitation, acceptance confirmation
        prospect/            # Enhanced prospect email templates
        free_trial/          # Trial invitation templates
        subjects/            # Subject line variations by journey type
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
    app.py                   # Lambda — Bedrock AI parsing → clears old records, writes contacts
    #                          + properties; capitalises names; deduplicates people by role priority
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
  test_documents.py          # contact/property CRUD + link CRUD routes
  test_parse_document.py     # parse Lambda, _capitalize_name, _deduplicate_people
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
