"""
Probate Leads API — Lambda handler.

Routes (all under /real-estate/probate-leads/):
  GET  /{location_path}/leads               — leads for a location (date-range query)
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
  POST /admin/activity/log                  — log user activity (admin Bearer token)
  POST /admin/activity/query                — query user activities (admin Bearer token)
  POST /activity/track                     — track funnel link clicks (public, token-based)
  POST /stripe/checkout                     — create Stripe Checkout Session (no API key)

Environment variables:
  DYNAMO_TABLE_NAME       — leads table
  LOCATIONS_TABLE_NAME    — locations table
  USERS_TABLE_NAME        — users table
  ACTIVITIES_TABLE_NAME  — activities table
  GSI_NAME                — legacy leads GSI (recorded-date-index)
  LOCATION_DATE_GSI       — new leads GSI (location-date-index)
  USER_ACTIVITY_GSI       — activities GSI (user-activity-index)
  STRIPE_SECRET_KEY       — Stripe secret key
  STRIPE_WEBHOOK_SECRET   — Stripe webhook signing secret
  JWT_SECRET              — HMAC-SHA256 secret for magic + access tokens
  MAGIC_LINK_BASE_URL     — base URL for magic link emails
  UI_BASE_URL             — base URL for prospect subscribe/unsubscribe links
  FROM_EMAIL              — SES verified sender; leave blank to skip sending (local dev)
"""

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from aws_lambda_powertools.utilities.typing import LambdaContext

import db  # noqa: F401 — imported so tests can patch db.table etc.
from models import Lead, Location, User
from utils import (
    decode_key as _decode_key,
    encode_key as _encode_key,
    normalize_timestamp as _normalize_timestamp,
    now_iso as _now_iso,
    parse_date as _parse_date,
)
from routers import leads, locations, users, stripe, auth, admin, prospect, activity

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

api.include_router(leads.router)
api.include_router(locations.router)
api.include_router(users.router)
api.include_router(stripe.router)
api.include_router(auth.router)
api.include_router(admin.router)
api.include_router(prospect.router)
api.include_router(activity.router)

# ---------------------------------------------------------------------------
# Backward-compatible transform shims (used by TestHelpers in test_api.py)
# ---------------------------------------------------------------------------

def _transform_lead(item: dict) -> dict:
    return Lead.from_dynamo(item).to_dict()


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
