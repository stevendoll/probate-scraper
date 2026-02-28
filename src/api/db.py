"""
Shared DynamoDB table references and configuration constants.

Imported as ``import db`` so callers can write ``db.table``.
Tests replace ``db.table``, ``db.locations_table``, and
``db.users_table`` in setUp to inject mocks.
"""

import os

import boto3

_dynamodb = boto3.resource("dynamodb")

_table_name           = os.environ.get("DYNAMO_TABLE_NAME", "leads")
_locations_table_name = os.environ.get("LOCATIONS_TABLE_NAME", "locations")
_users_table_name     = os.environ.get("USERS_TABLE_NAME", "users")

# Index names
gsi_name          = os.environ.get("GSI_NAME", "recorded-date-index")
location_date_gsi = os.environ.get("LOCATION_DATE_GSI", "location-date-index")

# DynamoDB Table objects — reassignable by tests
table           = _dynamodb.Table(_table_name)
locations_table = _dynamodb.Table(_locations_table_name)
users_table     = _dynamodb.Table(_users_table_name)

# Query limits
MAX_LIMIT     = 200
DEFAULT_LIMIT = 50
