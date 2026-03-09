"""
Shared DynamoDB table references, configuration constants, and common queries.

Imported as ``import db`` so callers can write ``db.documents_table``.
Tests replace ``db.documents_table``, ``db.locations_table``, ``db.users_table``,
``db.contacts_table``, ``db.properties_table``, and ``db.events_table``
in setUp to inject mocks.
"""

import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

log = logging.getLogger(__name__)

_dynamodb = boto3.resource("dynamodb")

_documents_table_name  = os.environ.get("DOCUMENTS_TABLE_NAME", "documents")
_locations_table_name  = os.environ.get("LOCATIONS_TABLE_NAME", "locations")
_users_table_name      = os.environ.get("USERS_TABLE_NAME", "users")
_contacts_table_name   = os.environ.get("CONTACTS_TABLE_NAME", "contacts")
_properties_table_name = os.environ.get("PROPERTIES_TABLE_NAME", "properties")
_events_table_name     = os.environ.get("EVENTS_TABLE_NAME", "events")

# Index names
gsi_name          = os.environ.get("GSI_NAME", "recorded-date-index")
location_date_gsi = os.environ.get("LOCATION_DATE_GSI", "location-date-index")
user_event_gsi    = os.environ.get("USER_EVENT_GSI", "user-event-index")

# DynamoDB Table objects — reassignable by tests
documents_table  = _dynamodb.Table(_documents_table_name)
locations_table  = _dynamodb.Table(_locations_table_name)
users_table      = _dynamodb.Table(_users_table_name)
contacts_table   = _dynamodb.Table(_contacts_table_name)
properties_table = _dynamodb.Table(_properties_table_name)
events_table     = _dynamodb.Table(_events_table_name)

# Query limits
MAX_LIMIT     = 200
DEFAULT_LIMIT = 50


def get_user_by_email(email: str) -> dict | None:
    """Query the email-index GSI.  Returns the raw DynamoDB item or None."""
    try:
        result = users_table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        log.error("users email-index query failed: %s", exc)
        return None
