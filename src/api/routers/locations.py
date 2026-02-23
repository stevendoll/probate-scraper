"""
Routes:
  GET /real-estate/probate-leads/locations
  GET /real-estate/probate-leads/locations/{location_code}
"""

import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router

import db
from models import Location

logger = Logger(service="probate-api")
router = Router()


@router.get("/real-estate/probate-leads/locations")
def list_locations():
    """Return all locations, sorted by name."""
    try:
        result = db.locations_table.scan()
    except Exception as exc:
        logger.exception("locations scan failed", exc_info=exc)
        return {"error": "Database scan failed"}, 500

    items = [Location.from_dynamo(item).to_dict() for item in result.get("Items", [])]
    items.sort(key=lambda x: x.get("locationName", ""))
    return {
        "requestId": str(uuid.uuid4()),
        "locations": items,
        "count": len(items),
    }


@router.get("/real-estate/probate-leads/locations/<location_code>")
def get_location(location_code: str):
    """Return a single location by location_code."""
    try:
        result = db.locations_table.get_item(Key={"location_code": location_code})
    except Exception as exc:
        logger.exception("locations get_item failed", exc_info=exc)
        return {"error": "Database query failed"}, 500

    item = result.get("Item")
    if item is None:
        return {"error": f"Location not found: {location_code!r}"}, 404

    return {
        "requestId": str(uuid.uuid4()),
        "location": Location.from_dynamo(item).to_dict(),
    }
