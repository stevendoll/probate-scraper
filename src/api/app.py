"""
Probate Leads API — Lambda handler.

Routes (all under /real-estate/probate-leads/):
  GET  /{location_path}/leads               — leads for a location (date-range query)
  GET  /locations                           — list all locations
  GET  /locations/{location_code}           — get a single location
  GET  /subscribers                         — list all subscribers
  POST /subscribers                         — create a subscriber
  GET  /subscribers/{subscriber_id}         — get a subscriber
  PATCH /subscribers/{subscriber_id}        — update subscriber (locations, status)
  DELETE /subscribers/{subscriber_id}       — soft-delete subscriber (status → inactive)
  POST /stripe/webhook                      — Stripe event webhook (no API key)

Environment variables:
  DYNAMO_TABLE_NAME       — leads table
  LOCATIONS_TABLE_NAME    — locations table
  SUBSCRIBERS_TABLE_NAME  — subscribers table
  GSI_NAME                — legacy leads GSI (recorded-date-index)
  LOCATION_DATE_GSI       — new leads GSI (location-date-index)
  STRIPE_SECRET_KEY       — Stripe secret key
  STRIPE_WEBHOOK_SECRET   — Stripe webhook signing secret
"""

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

import db  # noqa: F401 — imported so tests can patch db.table etc.
from models import Lead, Location, Subscriber
from utils import (
    decode_key as _decode_key,
    encode_key as _encode_key,
    normalize_timestamp as _normalize_timestamp,
    now_iso as _now_iso,
    parse_date as _parse_date,
)
from routers import leads, locations, subscribers, stripe

logger = Logger(service="probate-api")
tracer = Tracer(service="probate-api")
api    = APIGatewayRestResolver()

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

api.include_router(leads.router)
api.include_router(locations.router)
api.include_router(subscribers.router)
api.include_router(stripe.router)

# ---------------------------------------------------------------------------
# Backward-compatible transform shims (used by TestHelpers in test_api.py)
# ---------------------------------------------------------------------------

def _transform_lead(item: dict) -> dict:
    return Lead.from_dynamo(item).to_dict()


def _transform_location(item: dict) -> dict:
    return Location.from_dynamo(item).to_dict()


def _transform_subscriber(item: dict) -> dict:
    return Subscriber.from_dynamo(item).to_dict()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
