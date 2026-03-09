"""
reset_production_db.py — delete all data from production tables and seed initial data.

Resets all tables: documents, contacts, properties, locations, users, events
Seeds initial data: 1 location (CollinTx), 1 admin user (admin@collincountyleads.com)

Production:
    make aws-db-reset
    # or directly:
    pipenv run python3 scripts/reset_production_db.py

WARNING: This will permanently delete ALL production data!
"""

import os
import boto3
import uuid
from datetime import datetime, timezone

def reset_table(ddb, table_name, key_name="id"):
    """Reset a single table by scanning and deleting all items."""
    print(f"Scanning '{table_name}' for all keys...")
    
    try:
        # Get table description to find primary key
        desc = ddb.describe_table(TableName=table_name)
        table_key = None
        for key in desc['Table']['KeySchema']:
            if key['KeyType'] == 'HASH':
                table_key = key['AttributeName']
                break
        
        if not table_key:
            print(f"  ERROR: Could not determine primary key for {table_name}")
            return False
            
        paginator = ddb.get_paginator("scan")
        delete_requests = []
        
        for page in paginator.paginate(TableName=table_name, ProjectionExpression=table_key):
            for item in page.get("Items", []):
                delete_requests.append(
                    {"DeleteRequest": {"Key": {table_key: item[table_key]}}}
                )
        
        if not delete_requests:
            print(f"  Table '{table_name}' is already empty.")
            return True
            
        total = len(delete_requests)
        print(f"  Deleting {total} item(s) in batches of 25...")
        deleted = 0
        
        for i in range(0, total, 25):
            chunk = delete_requests[i:i + 25]
            resp = ddb.batch_write_item(RequestItems={table_name: chunk})
            unprocessed = resp.get("UnprocessedItems", {}).get(table_name, [])
            deleted += len(chunk) - len(unprocessed)
            if unprocessed:
                print(f"  WARNING: {len(unprocessed)} items not deleted in batch {i // 25}")
        
        print(f"  {deleted}/{total} items deleted from '{table_name}'.")
        return True
        
    except ddb.exceptions.ResourceNotFoundException:
        print(f"  Table '{table_name}' does not exist.")
        return True
    except Exception as e:
        print(f"  ERROR resetting {table_name}: {e}")
        return False

def seed_location(ddb):
    """Seed the CollinTx location."""
    print("Seeding CollinTx location...")
    
    location_item = {
        "location_code": {"S": "CollinTx"},
        "location_path": {"S": "collin-tx"}, 
        "location_name": {"S": "Collin County TX"},
        "search_url": {"S": "https://collin.tx.publicsearch.us"},
        "retrieved_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    try:
        ddb.put_item(TableName="locations", Item=location_item)
        print("  ✅ CollinTx location created.")
        return True
    except Exception as e:
        print(f"  ❌ Failed to create location: {e}")
        return False

def seed_admin_user(ddb):
    """Seed the admin user."""
    print("Seeding admin user...")
    
    admin_user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    user_item = {
        "user_id": {"S": admin_user_id},
        "email": {"S": "admin@collincountyleads.com"},
        "first_name": {"S": "Admin"},
        "last_name": {"S": "User"},
        "role": {"S": "admin"},
        "status": {"S": "active"},
        "location_codes": {"SS": ["COLLIN_TX"]},
        "offered_price": {"N": "0"},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }
    
    try:
        ddb.put_item(TableName="users", Item=user_item)
        print(f"  ✅ Admin user created (ID: {admin_user_id}).")
        return True
    except Exception as e:
        print(f"  ❌ Failed to create admin user: {e}")
        return False

def seed_initial_data(ddb):
    """Seed initial data after reset."""
    print("=== SEEDING INITIAL DATA ===")
    
    success_count = 0
    
    # Seed location first (users may reference it)
    if seed_location(ddb):
        success_count += 1
    
    # Seed admin user
    if seed_admin_user(ddb):
        success_count += 1
    
    print(f"\nSeeded {success_count}/2 items successfully.")
    return success_count == 2

def main():
    """Reset all production tables and seed initial data."""
    print("=== PRODUCTION DATABASE RESET ===")
    print("WARNING: This will permanently delete ALL production data!")
    print("")
    
    # Confirm before proceeding
    response = input("Type 'RESET' to confirm: ")
    if response != "RESET":
        print("Reset cancelled.")
        return
    
    print("Proceeding with reset...")
    print("")
    
    # Initialize DynamoDB client
    session = boto3.Session(
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    ddb = session.client("dynamodb")
    
    # Tables to reset (in safe order - no foreign key dependencies)
    tables_to_reset = [
        "events",        # Event tracking
        "users",         # User accounts
        "contacts",      # Parsed contacts
        "properties",    # Parsed properties
        "documents",     # Scraped documents
        "locations",     # Location metadata
    ]
    
    success_count = 0
    
    for table_name in tables_to_reset:
        if reset_table(ddb, table_name):
            success_count += 1
        print("")
    
    print("=== RESET SUMMARY ===")
    print(f"Tables reset: {success_count}/{len(tables_to_reset)}")
    
    if success_count == len(tables_to_reset):
        print("✅ All production tables reset successfully!")
        print("")
        
        # Seed initial data
        if seed_initial_data(ddb):
            print("✅ Initial data seeded successfully!")
        else:
            print("❌ Some initial data failed to seed.")
        
        print("")
        print("Next steps:")
        print("1. Run 'make deploy' to recreate infrastructure")
        print("2. Test admin login: admin@collincountyleads.com")
        print("3. Verify CollinTx location is available")
    else:
        print("❌ Some tables failed to reset. Check logs above.")

if __name__ == "__main__":
    main()
