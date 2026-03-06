"""
data_helpers.py — shared data utilities: user lookup and name parsing.

Centralises helpers that were previously duplicated across routers/auth.py
and routers/funnel.py.
"""

import logging

from boto3.dynamodb.conditions import Key

import db

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User lookup
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> dict | None:
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
        log.error("users email-index query failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------

_PREFIXES = {"Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Sir", "Madam"}
_SUFFIXES = {"Jr.", "Sr.", "II", "III", "IV", "Ph.D.", "M.D."}
_COMPOUND_INDICATORS = {"van", "von", "de", "da", "del", "della", "di", "du", "la", "le", "mc", "mac", "o'"}


def capitalize_name(name: str) -> str:
    """Capitalize a name, handling hyphens (Mary-Jane) and apostrophes (O'Connor)."""
    if not name:
        return ""
    if "-" in name:
        return "-".join(_capitalize_single(part) for part in name.split("-"))
    if "'" in name:
        return "'".join(_capitalize_single(part) for part in name.split("'"))
    return _capitalize_single(name)


def _capitalize_single(name: str) -> str:
    if not name:
        return ""
    if len(name) == 2 and name.endswith("."):  # initial like "T."
        return name.upper()
    if len(name) == 1:
        return name.upper()
    return name.capitalize()


def parse_name(name_part: str) -> tuple[str, str]:
    """Parse a name string and return (first_name, last_name) with proper capitalisation.

    Handles prefixes (Dr., Mr., …), suffixes (Jr., Sr., …), initials,
    compound last names (Van Buren, D'Souza, O'Connor), and hyphenated names.
    """
    if not name_part:
        return "", ""

    # Strip prefixes and suffixes (case-sensitive — inputs should be title-cased
    # or the caller should normalise before calling)
    for prefix in _PREFIXES:
        if name_part.startswith(prefix):
            name_part = name_part[len(prefix):].strip()
            break

    for suffix in _SUFFIXES:
        if name_part.endswith(suffix):
            name_part = name_part[: -len(suffix)].strip()
            break

    parts = name_part.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return capitalize_name(parts[0]), ""
    if len(parts) == 2:
        return capitalize_name(parts[0]), capitalize_name(parts[1])

    first_name = capitalize_name(parts[0])

    if len(parts) == 3:
        middle = parts[1].lower()
        # Middle initial → ignore it, take last part as last name
        if len(middle) == 2 and middle.endswith("."):
            return first_name, capitalize_name(parts[2])
        # Compound indicator in middle → "First Van Buren" style
        if middle in _COMPOUND_INDICATORS:
            return first_name, f"{capitalize_name(parts[1])} {capitalize_name(parts[2])}"
        return first_name, capitalize_name(parts[2])

    # 4+ parts — work backwards to collect compound last name
    last_name_parts = []
    found_compound = False
    for i in range(len(parts) - 1, 0, -1):
        part_lower = parts[i].lower()
        is_initial = len(part_lower) == 2 and part_lower.endswith(".")
        is_last = i == len(parts) - 1
        is_compound = not is_initial and (
            part_lower in _COMPOUND_INDICATORS or "'" in part_lower or "-" in part_lower
        )
        if is_last or is_compound or found_compound:
            last_name_parts.insert(0, capitalize_name(parts[i]))
            if is_compound:
                found_compound = True
        else:
            break

    if not last_name_parts:
        last_name_parts = [capitalize_name(parts[-1])]

    return first_name, " ".join(last_name_parts)


def parse_email_input(email_input: str) -> tuple[str, str, str]:
    """Parse an email input that may include a display name.

    Accepts:
      "john@example.com"               → ("john@example.com", "", "")
      "John Doe <john@example.com>"    → ("john@example.com", "John", "Doe")

    The input is lowercased before parsing; parse_name re-capitalises names.
    Returns (clean_email, first_name, last_name).
    """
    email_input = email_input.strip().lower()
    if "<" in email_input and ">" in email_input:
        name_part  = email_input.split("<")[0].strip()
        clean_email = email_input.split("<")[1].split(">")[0].strip()
        first_name, last_name = parse_name(name_part) if name_part else ("", "")
        return clean_email, first_name, last_name
    return email_input, "", ""
