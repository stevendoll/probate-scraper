"""
Probate Leads API — Lambda handler.

Routes (all under /real-estate/probate-leads/):
  GET  /{location_path}/documents           — documents for a location (date-range query)
  GET  /documents/{document_id}/contacts    — contacts for a document
  GET  /documents/{document_id}/properties  — properties for a document
  GET  /locations                           — list all locations
  GET  /locations/{location_code}           — get a single location
  GET  /users                               — list all users
  POST /users                               — create a user
  GET  /users/{user_id}                     — get a user
  PATCH /users/{user_id}                    — update user (locations, status)
  DELETE /users/{user_id}                   — soft-delete user (status → inactive)
  POST /stripe/webhook                      — Stripe event webhook (no API key)
  POST /stripe/checkout                     — create Stripe Checkout Session (no API key)
  POST /auth/request-login                  — request magic-link email
  GET  /auth/verify                         — exchange magic token for access token
  GET  /auth/me                             — own profile (Bearer token)
  PATCH /auth/me                            — update own email (Bearer token)
  GET  /auth/leads                          — own leads (Bearer token, active only)
  GET  /admin/users                         — list all users (admin Bearer token)
  GET  /admin/users/{user_id}               — get user (admin Bearer token)
  PATCH /admin/users/{user_id}              — update user (admin Bearer token)
  DELETE /admin/users/{user_id}             — soft-delete user (admin Bearer token)
  POST /admin/prospect/send                 — send prospect emails (admin Bearer token)
  POST /auth/unsubscribe                    — unsubscribe via prospect JWT (no API key)
  POST /events                              — track prospect-initiated events (prospect JWT)
  GET  /events                              — query events for a user (admin Bearer token, ?user_id=&limit=)

Environment variables:
  DOCUMENTS_TABLE_NAME    — documents table
  CONTACTS_TABLE_NAME     — contacts table
  PROPERTIES_TABLE_NAME   — properties table
  LOCATIONS_TABLE_NAME    — locations table
  USERS_TABLE_NAME        — users table
  EVENTS_TABLE_NAME       — events table
  GSI_NAME                — legacy documents GSI (recorded-date-index)
  LOCATION_DATE_GSI       — primary documents GSI (location-date-index)
  USER_EVENT_GSI          — events GSI (user-event-index)
  STRIPE_SECRET_KEY       — Stripe secret key
  STRIPE_WEBHOOK_SECRET   — Stripe webhook signing secret
  JWT_SECRET              — HMAC-SHA256 secret for magic + access tokens
  MAGIC_LINK_BASE_URL     — base URL for magic link emails
  UI_BASE_URL             — base URL for prospect subscribe/unsubscribe links
  FROM_EMAIL              — SES verified sender; leave blank to skip sending (local dev)
  SES_CONFIGURATION_SET  — SES configuration set name for event publishing
"""

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from aws_lambda_powertools.utilities.typing import LambdaContext

import db  # noqa: F401 — imported so tests can patch db.documents_table etc.
from models import Document, Location, User
from utils import (
    decode_key as _decode_key,
    encode_key as _encode_key,
    normalize_timestamp as _normalize_timestamp,
    now_iso as _now_iso,
    parse_date as _parse_date,
)
from routers import documents, locations, users, stripe, auth, admin, prospect, event

logger = Logger(service="probate-api")
tracer = Tracer(service="probate-api")
api    = APIGatewayRestResolver(cors=CORSConfig(
    allow_origin="*",
    allow_headers=["Content-Type", "Authorization", "x-api-key"],
    max_age=3000,
))

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

api.include_router(documents.router)
api.include_router(locations.router)
api.include_router(users.router)
api.include_router(stripe.router)
api.include_router(auth.router)
api.include_router(admin.router)
api.include_router(prospect.router)
api.include_router(event.router)

# ---------------------------------------------------------------------------
# Backward-compatible transform shims (used by TestHelpers in test_api.py)
# ---------------------------------------------------------------------------

def _transform_document(item: dict) -> dict:
    return Document.from_dynamo(item).to_dict()


def _transform_location(item: dict) -> dict:
    return Location.from_dynamo(item).to_dict()


def _transform_user(item: dict) -> dict:
    return User.from_dynamo(item).to_dict()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
