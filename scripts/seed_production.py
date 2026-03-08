"""
seed_production.py — create all DynamoDB tables and seed initial data in production.

Creates tables if they don't exist, then seeds:
- 1 CollinTx location
- 1 admin user (admin@collincountyleads.com)

Production:
    make seed-prod
    # or directly:
    pipenv run python3 scripts/seed_production.py
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeSerializer

# Environment variables
DYNAMO_TABLE_NAME       = os.environ.get("DYNAMO_TABLE_NAME", "leads")
LOCATIONS_TABLE_NAME    = os.environ.get("LOCATIONS_TABLE_NAME", "locations")
USERS_TABLE_NAME        = os.environ.get("USERS_TABLE_NAME", "users")
EVENTS_TABLE_NAME      = os.environ.get("EVENTS_TABLE_NAME", "events")
REGION                 = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# Index names
GSI_NAME          = os.environ.get("GSI_NAME", "recorded-date-index")
LOCATION_DATE_GSI = os.environ.get("LOCATION_DATE_GSI", "location-date-index")
USER_EVENT_GSI    = os.environ.get("USER_EVENT_GSI", "user-event-index")

def table_exists(dynamodb, table_name: str) -> bool:
    """Check if table exists."""
    try:
        dynamodb.describe_table(TableName=table_name)
        return True
    except dynamodb.exceptions.ResourceNotFoundException:
        return False

def wait_for_table(dynamodb, table_name: str):
    """Wait for table to become active."""
    waiter = dynamodb.get_waiter('table_exists')
    waiter.wait(TableName=table_name)

def create_leads_table(dynamodb):
    """Create leads table with GSIs."""
    print(f"Creating table '{DYNAMO_TABLE_NAME}'...")
    
    if table_exists(dynamodb, DYNAMO_TABLE_NAME):
        print(f"  Table '{DYNAMO_TABLE_NAME}' already exists.")
        return
    
    dynamodb.create_table(
        TableName=DYNAMO_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "lead_id",       "AttributeType": "S"},
            {"AttributeName": "doc_type",      "AttributeType": "S"},
            {"AttributeName": "recorded_date", "AttributeType": "S"},
            {"AttributeName": "location_code", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "lead_id", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI_NAME,
                "KeySchema": [
                    {"AttributeName": "doc_type",      "KeyType": "HASH"},
                    {"AttributeName": "recorded_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": LOCATION_DATE_GSI,
                "KeySchema": [
                    {"AttributeName": "location_code", "KeyType": "HASH"},
                    {"AttributeName": "recorded_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    wait_for_table(dynamodb, DYNAMO_TABLE_NAME)
    print(f"  '{DYNAMO_TABLE_NAME}' ready.")

def create_locations_table(dynamodb):
    """Create locations table with GSI."""
    print(f"Creating table '{LOCATIONS_TABLE_NAME}'...")
    
    if table_exists(dynamodb, LOCATIONS_TABLE_NAME):
        print(f"  Table '{LOCATIONS_TABLE_NAME}' already exists.")
        return
    
    dynamodb.create_table(
        TableName=LOCATIONS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "location_code", "AttributeType": "S"},
            {"AttributeName": "location_path", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "location_code", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "location-path-index",
                "KeySchema": [
                    {"AttributeName": "location_path", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    wait_for_table(dynamodb, LOCATIONS_TABLE_NAME)
    print(f"  '{LOCATIONS_TABLE_NAME}' ready.")

def create_users_table(dynamodb):
    """Create users table with GSI."""
    print(f"Creating table '{USERS_TABLE_NAME}'...")
    
    if table_exists(dynamodb, USERS_TABLE_NAME):
        print(f"  Table '{USERS_TABLE_NAME}' already exists.")
        return
    
    dynamodb.create_table(
        TableName=USERS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "email",   "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "email-index",
                "KeySchema": [
                    {"AttributeName": "email", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    wait_for_table(dynamodb, USERS_TABLE_NAME)
    print(f"  '{USERS_TABLE_NAME}' ready.")

def create_events_table(dynamodb):
    """Create events table with GSI."""
    print(f"Creating table '{EVENTS_TABLE_NAME}'...")

    if table_exists(dynamodb, EVENTS_TABLE_NAME):
        print(f"  Table '{EVENTS_TABLE_NAME}' already exists.")
        return

    dynamodb.create_table(
        TableName=EVENTS_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "event_id",  "AttributeType": "S"},
            {"AttributeName": "user_id",   "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "event_id", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": USER_EVENT_GSI,
                "KeySchema": [
                    {"AttributeName": "user_id",   "KeyType": "HASH"},
                    {"AttributeName": "timestamp",  "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    wait_for_table(dynamodb, EVENTS_TABLE_NAME)
    print(f"  '{EVENTS_TABLE_NAME}' ready.")

def seed_locations(dynamodb):
    """Seed CollinTx location."""
    print(f"Seeding '{LOCATIONS_TABLE_NAME}'...")
    
    # Check if CollinTx already exists
    try:
        result = dynamodb.get_item(
            TableName=LOCATIONS_TABLE_NAME,
            Key={"location_code": {"S": "CollinTx"}}
        )
        if result.get("Item"):
            print("  CollinTx location already exists.")
            return True
    except Exception:
        pass
    
    location_item = {
        "location_code": {"S": "CollinTx"},
        "location_path": {"S": "collin-tx"}, 
        "location_name": {"S": "Collin County TX"},
        "search_url": {"S": "https://collin.tx.publicsearch.us"},
        "retrieved_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    try:
        dynamodb.put_item(TableName=LOCATIONS_TABLE_NAME, Item=location_item)
        print("  ✅ CollinTx location created.")
        return True
    except Exception as e:
        print(f"  ❌ Failed to create location: {e}")
        return False

def seed_admin_user(dynamodb):
    """Seed admin user."""
    print(f"Seeding '{USERS_TABLE_NAME}'...")
    
    # Check if admin user already exists
    try:
        result = dynamodb.query(
            TableName=USERS_TABLE_NAME,
            IndexName="email-index",
            KeyConditionExpression={"email": {"S": "admin@collincountyleads.com"}},
            Limit=1
        )
        if result.get("Items"):
            print("  Admin user already exists.")
            return True
    except Exception:
        pass
    
    admin_user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    user_item = {
        "user_id": {"S": admin_user_id},
        "email": {"S": "admin@collincountyleads.com"},
        "first_name": {"S": "Admin"},
        "last_name": {"S": "User"},
        "role": {"S": "admin"},
        "status": {"S": "active"},
        "location_codes": {"SS": ["CollinTx"]},
        "offered_price": {"N": "0"},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }
    
    try:
        dynamodb.put_item(TableName=USERS_TABLE_NAME, Item=user_item)
        print(f"  ✅ Admin user created (ID: {admin_user_id}).")
        return True
    except Exception as e:
        print(f"  ❌ Failed to create admin user: {e}")
        return False

def main():
    """Create all tables and seed initial data."""
    print("=== PRODUCTION DATABASE SETUP ===")
    print("Creating tables and seeding initial data...")
    print("")
    
    # Initialize DynamoDB client
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    
    # Create all tables
    print("=== CREATING TABLES ===")
    # create_leads_table(dynamodb)
    create_locations_table(dynamodb)
    create_users_table(dynamodb)
    create_events_table(dynamodb)
    print("")
    
    # Seed initial data
    print("=== SEEDING INITIAL DATA ===")
    success_count = 0
    
    if seed_locations(dynamodb):
        success_count += 1
    
    if seed_admin_user(dynamodb):
        success_count += 1
    
    print("")
    print("=== SETUP SUMMARY ===")
    print(f"Items seeded: {success_count}/2")
    
    if success_count == 2:
        print("✅ Production database setup complete!")
        print("")
        print("Next steps:")
        print("1. Run 'make deploy' to deploy infrastructure")
        print("2. Test admin login: admin@collincountyleads.com")
        print("3. Verify CollinTx location is available")
    else:
        print("❌ Some setup steps failed. Check logs above.")

if __name__ == "__main__":
    main()
