"""
Marketing funnel routes (no API key required for public endpoints):

  POST /real-estate/probate-leads/admin/funnel/send   — admin Bearer required
  POST /real-estate/probate-leads/auth/unsubscribe    — public, funnel JWT in body
  POST /real-estate/probate-leads/stripe/checkout     — public, funnel JWT in body
"""

import os
import uuid

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.api_gateway import Router
from boto3.dynamodb.conditions import Key

import db
from auth_helpers import (
    create_funnel_token,
    get_bearer_payload,
    send_funnel_email,
    verify_token,
)
from models import Lead, User
from utils import now_iso

logger = Logger(service="probate-api")
router = Router()

# Round-robin price ladder for new free-trial users (dollars/month)
_PRICE_LADDER = [19, 39, 59, 79]

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
UI_BASE_URL       = os.environ.get("UI_BASE_URL", "http://localhost:3001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_name(name_part: str) -> tuple[str, str]:
    """Parse various name formats and return (first_name, last_name) with proper capitalization.
    
    Handles formats like:
    - "John Doe"
    - "john T. Doe"
    - "Martin Van Buren"
    - "Ann D'Souza"
    - "Mary-Jane O'Connor"
    - "Dr. John Smith Jr."
    """
    if not name_part:
        return "", ""
    
    # Remove common prefixes and suffixes
    prefixes = ["Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Sir", "Madam"]
    suffixes = ["Jr.", "Sr.", "II", "III", "IV", "Ph.D.", "M.D."]
    
    # Clean up name
    for prefix in prefixes:
        if name_part.startswith(prefix):
            name_part = name_part[len(prefix):].strip()
    
    for suffix in suffixes:
        if name_part.endswith(suffix):
            name_part = name_part[:-len(suffix)].strip()
    
    # Split into parts
    parts = name_part.split()
    if not parts:
        return "", ""
    
    if len(parts) == 1:
        # Single name
        return _capitalize_name(parts[0]), ""
    
    if len(parts) == 2:
        # First Last
        return _capitalize_name(parts[0]), _capitalize_name(parts[1])
    
    # Multiple parts - handle various cases
    # Common patterns for multi-part names:
    # - First Middle Last (3 parts)
    # - First Middle Middle Last (4+ parts)
    # - Compound last names (Van Buren, D'Souza, O'Connor)
    
    # Check for common compound last name patterns
    compound_indicators = ["van", "von", "de", "da", "del", "della", "di", "du", "la", "le", "mc", "mac", "o'"]
    
    first_name = _capitalize_name(parts[0])
    
    # For simple cases (3 parts or fewer), use standard logic
    if len(parts) <= 3:
        # Check if middle part is an initial or compound indicator
        middle_part = parts[1].lower() if len(parts) > 2 else ""
        last_part = parts[-1].lower()
        
        # If middle is an initial, treat as simple first+last
        if len(middle_part) == 2 and middle_part.endswith('.'):
            return first_name, _capitalize_name(parts[-1])
        
        # If middle part is a compound indicator, include it in last name
        if middle_part in compound_indicators and len(parts) == 3:
            return first_name, f"{_capitalize_name(parts[1])} {_capitalize_name(parts[2])}"
        
        # Otherwise, first + last
        return first_name, _capitalize_name(parts[-1])
    
    # For complex cases (4+ parts), look for compound last name patterns
    last_name_parts = []
    found_compound = False
    
    # Work backwards to identify last name parts
    for i in range(len(parts) - 1, 0, -1):
        part = parts[i].lower()
        # Check if this part should be included in last name
        # Exclude initials with periods from compound detection
        is_initial = len(part) == 2 and part.endswith('.')
        should_include = (
            i == len(parts) - 1 or  # Always include the last part
            (not is_initial and (
                part in compound_indicators or  # Include compound indicators
                "'" in part or  # Include apostrophe parts
                "-" in part  # Include hyphenated parts
            ))
        )
        
        if should_include:
            last_name_parts.insert(0, _capitalize_name(parts[i]))
            if not is_initial and (part in compound_indicators or "'" in part or "-" in part):
                found_compound = True
        elif found_compound:
            # We've found the compound pattern, continue including
            continue
        else:
            # No compound pattern found, stop at first non-last part
            break
    
    if not last_name_parts:
        last_name_parts = [_capitalize_name(parts[-1])]
    
    last_name = " ".join(last_name_parts)
    
    return first_name, last_name


def _capitalize_name(name: str) -> str:
    """Capitalize name properly, handling special cases like O'Connor, D'Souza, Mary-Jane."""
    if not name:
        return ""
    
    # Handle hyphenated names
    if "-" in name:
        parts = name.split("-")
        return "-".join(_capitalize_single_name(part) for part in parts)
    
    # Handle apostrophe names
    if "'" in name:
        parts = name.split("'")
        return "'".join(_capitalize_single_name(part) for part in parts)
    
    return _capitalize_single_name(name)


def _capitalize_single_name(name: str) -> str:
    """Capitalize a single name part."""
    if not name:
        return ""
    
    # Handle initials with periods (T., J., etc.)
    if len(name) == 2 and name.endswith('.'):
        return name.upper()
    
    # Handle single letters
    if len(name) == 1:
        return name.upper()
    
    return name.capitalize()


def _require_admin(event: dict) -> dict | None:
    """Verify the request carries a valid admin-role access token."""
    payload = get_bearer_payload(event)
    if not payload:
        return None
    if payload.get("type") != "access":
        return None
    if payload.get("role") != "admin":
        return None
    return payload


def _get_user_by_email(email: str) -> dict | None:
    """Query the email-index GSI.  Returns the raw DynamoDB item or None."""
    try:
        result = db.users_table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
            Limit=1,
        )
        items = result.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        logger.error("users email-index query failed: %s", exc)
        return None


def _fetch_recent_leads(lead_count: int) -> list:
    """Return up to lead_count recent leads across all known locations.

    Queries the location-date-index GSI for each location, merges results,
    sorts by recorded_date descending, and returns the top lead_count items.
    """
    # Scan all locations to get their location_codes
    try:
        loc_result = db.locations_table.scan(ProjectionExpression="location_code")
        location_codes = [item["location_code"] for item in loc_result.get("Items", [])]
    except Exception as exc:
        logger.error("locations scan failed: %s", exc)
        return []

    all_items: list = []
    for location_code in location_codes:
        try:
            result = db.table.query(
                IndexName=db.location_date_gsi,
                KeyConditionExpression=Key("location_code").eq(location_code),
                ScanIndexForward=False,
                Limit=lead_count,
            )
            all_items.extend(result.get("Items", []))
        except Exception as exc:
            logger.error("leads query for %s failed: %s", location_code, exc)

    # Sort merged results descending by recorded_date, take top lead_count
    all_items.sort(key=lambda x: x.get("recorded_date", ""), reverse=True)
    return all_items[:lead_count]


# ---------------------------------------------------------------------------
# POST /admin/funnel/send
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/admin/funnel/send")
def admin_funnel_send():
    """Create free-trial users and send them a leads email with a subscribe link.

    Request body (JSON):
      emails      (list[str], required) — prospect email addresses
      lead_count  (int, optional, default 10) — number of sample leads to include

    Returns per-email results: sent | skipped | error.
    """
    if not _require_admin(router.current_event.raw_event):
        return {"error": "Forbidden"}, 403

    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    raw_emails = body.get("emails") or []
    if not isinstance(raw_emails, list) or not raw_emails:
        return {"error": "'emails' must be a non-empty list"}, 400

    lead_count = int(body.get("lead_count") or 10)
    lead_count = max(1, min(lead_count, 50))  # clamp to [1, 50]

    # Fetch sample leads once, shared across all emails
    leads_raw  = _fetch_recent_leads(lead_count)
    leads_dicts = [Lead.from_dynamo(item).to_dict() for item in leads_raw]

    # Count existing free_trial users so we can continue the round-robin correctly
    try:
        count_result = db.users_table.scan(
            FilterExpression="attribute_exists(offered_price)",
            Select="COUNT",
        )
        existing_count = count_result.get("Count", 0)
    except Exception:
        existing_count = 0

    results = []
    now     = now_iso()

    for idx, raw_email in enumerate(raw_emails):
        email = (raw_email or "").strip().lower()
        if not email:
            results.append({"email": raw_email, "status": "skipped", "message": "empty email"})
            continue

        # Parse email to extract names
        first_name = None
        last_name = None
        clean_email = email  # Default to original email
        
        if "<" in email and ">" in email:
            # Format: "John Doe <john@email.com>"
            name_part = email.split("<")[0].strip()
            clean_email = email.split("<")[1].split(">")[0].strip()
            
            if name_part:
                first_name, last_name = _parse_name(name_part)
        
        price = _PRICE_LADDER[(existing_count + idx) % len(_PRICE_LADDER)]

        # Upsert user: create new or update existing
        existing = _get_user_by_email(clean_email)
        if existing:
            user_id = existing["user_id"]
            try:
                update_expr = (
                    "SET #status = :status, offered_price = :price, updated_at = :updated_at"
                )
                if first_name:
                    update_expr += ", first_name = :first_name"
                if last_name:
                    update_expr += ", last_name = :last_name"
                
                # Add CollinTx location if user doesn't have any locations
                if not existing.get("location_codes"):
                    update_expr += ", location_codes = :location_codes"
                
                expr_attrs = {
                    ":status":     "prospect",
                    ":price":      price,
                    ":updated_at": now,
                }
                if first_name:
                    expr_attrs[":first_name"] = first_name
                if last_name:
                    expr_attrs[":last_name"] = last_name
                if not existing.get("location_codes"):
                    expr_attrs[":location_codes"] = {"CollinTx"}
                
                result = db.users_table.update_item(
                    Key={"user_id": user_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues=expr_attrs,
                    ReturnValues="ALL_NEW",
                )
                user_item = result["Attributes"]
            except Exception as exc:
                logger.error("users update_item (funnel) for %s failed: %s", clean_email, exc)
                results.append({"email": clean_email, "status": "error", "message": "database error"})
                continue
        else:
            user_id = str(uuid.uuid4())
            user_item = {
                "user_id":                user_id,
                "email":                  clean_email,
                "first_name":             first_name or "",
                "last_name":              last_name or "",
                "role":                   "user",
                "stripe_customer_id":     "",
                "stripe_subscription_id": "",
                "status":                 "prospect",
                "location_codes":         {"CollinTx"},
                "offered_price":          price,
                "created_at":             now,
                "updated_at":             now,
            }
            try:
                db.users_table.put_item(Item=user_item)
            except Exception as exc:
                logger.error("users put_item (funnel) for %s failed: %s", email, exc)
                results.append({"email": email, "status": "error", "message": "database error"})
                continue

        # Create funnel token and send email
        token = create_funnel_token(user_id, clean_email, price)
        try:
            send_funnel_email(
                clean_email, token, leads_dicts, price, first_name, last_name, user_id
            )
            results.append({
                "email":  clean_email,
                "status": "sent",
                "userId": user_id,
                "price":  price,
            })
        except Exception as exc:
            logger.error("send_funnel_email failed for %s: %s", email, exc)
            results.append({"email": email, "status": "error", "message": "email send failed"})

    return {
        "requestId": str(uuid.uuid4()),
        "results":   results,
        "count":     len(results),
    }


# ---------------------------------------------------------------------------
# POST /auth/unsubscribe
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/auth/unsubscribe")
def auth_unsubscribe():
    """Set the user's status to 'unsubscribed' using a funnel JWT.

    Request body (JSON):
      token  (str, required) — funnel JWT from the marketing email
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    token = (body.get("token") or "").strip()
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "funnel":
        return {"error": "Invalid or expired token"}, 401

    user_id = payload.get("sub", "")
    if not user_id:
        return {"error": "Invalid token: missing user"}, 401

    try:
        db.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status":     "unsubscribed",
                ":updated_at": now_iso(),
            },
        )
    except Exception as exc:
        logger.error("users update_item (unsubscribe) failed: %s", exc)
        return {"error": "Failed to update status"}, 500

    logger.info("User %s unsubscribed via funnel token", user_id)
    return {"message": "You have been unsubscribed."}


# ---------------------------------------------------------------------------
# POST /stripe/checkout
# ---------------------------------------------------------------------------

@router.post("/real-estate/probate-leads/stripe/checkout")
def stripe_checkout():
    """Create a Stripe Checkout Session for a funnel prospect.

    Request body (JSON):
      token  (str, required) — funnel JWT from the marketing email

    Returns:
      { url: <stripe_checkout_url> }
    """
    try:
        body = router.current_event.json_body or {}
    except Exception:
        return {"error": "Invalid JSON body"}, 400

    token = (body.get("token") or "").strip()
    if not token:
        return {"error": "'token' is required"}, 400

    payload = verify_token(token)
    if not payload or payload.get("type") != "funnel":
        return {"error": "Invalid or expired token"}, 401

    user_id = payload.get("sub", "")
    email   = payload.get("email", "")
    price   = int(payload.get("price", 0) or 0)

    if not user_id or not email or not price:
        return {"error": "Invalid token: missing required claims"}, 401

    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe is not configured"}, 503

    try:
        import stripe  # noqa: PLC0415 — local for testability
        stripe.api_key = STRIPE_SECRET_KEY

        cancel_url = f"{UI_BASE_URL}/signup?token={token}"
        success_url = f"{UI_BASE_URL}/dashboard?checkout=success"

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": price * 100,
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": "Collin County Probate Leads",
                    },
                },
                "quantity": 1,
            }],
            client_reference_id=user_id,
            customer_email=email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        return {"error": "Failed to create checkout session"}, 500

    logger.info("Stripe checkout session created for user %s price=%s", user_id, price)
    return {"url": session.url}
