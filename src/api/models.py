"""
Domain models for the probate-leads API.

Each model exposes two entry points:
  - ``Model.from_dynamo(item)``  — build from a raw DynamoDB attribute dict
  - ``instance.to_dict()``       — serialize to the camelCase JSON shape the API returns
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Timestamp helper (used by Document.to_dict)
# ---------------------------------------------------------------------------

def _normalize_timestamp(ts: str) -> str:
    """Normalize any ISO timestamp to 3-decimal-millisecond UTC with Z suffix."""
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return ts


# ---------------------------------------------------------------------------
# Document (formerly Lead)
# ---------------------------------------------------------------------------

@dataclass
class Document:
    document_id:       str = ""
    doc_number:        str = ""
    grantor:           str = ""
    grantee:           str = ""
    doc_type:          str = ""
    recorded_date:     str = ""
    book_volume_page:  str = ""
    legal_description: str = ""
    record_number:     int = 0
    page_number:       int = 0
    extracted_at:      str = ""
    processed_at:      str = ""
    scrape_run_id:     str = ""
    location_code:     str = ""
    offset:            int = 0
    pdf_url:           str = ""
    doc_s3_uri:        str = ""
    doc_local_path:    str = ""
    # Parse fields — populated by the parse-document Lambda
    parsed_at:         str = ""
    parsed_model:      str = ""
    parse_error:       str = ""
    summary:           str = ""
    raw_response:      str = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "Document":
        return cls(
            document_id=       item.get("document_id", ""),
            doc_number=        item.get("doc_number", ""),
            grantor=           item.get("grantor", ""),
            grantee=           item.get("grantee", ""),
            doc_type=          item.get("doc_type", ""),
            recorded_date=     item.get("recorded_date", ""),
            book_volume_page=  item.get("book_volume_page", ""),
            legal_description= item.get("legal_description", ""),
            record_number=     int(item.get("record_number", 0) or 0),
            page_number=       int(item.get("page_number", 0) or 0),
            extracted_at=      str(item.get("extracted_at", "")),
            processed_at=      str(item.get("processed_at", "")),
            scrape_run_id=     item.get("scrape_run_id", ""),
            location_code=     item.get("location_code", ""),
            offset=            int(item.get("offset", 0) or 0),
            pdf_url=           item.get("pdf_url", ""),
            doc_s3_uri=        item.get("doc_s3_uri", ""),
            doc_local_path=    item.get("doc_local_path", ""),
            parsed_at=         item.get("parsed_at", ""),
            parsed_model=      item.get("parsed_model", ""),
            parse_error=       item.get("parse_error", ""),
            summary=           item.get("summary", ""),
            raw_response=      item.get("raw_response", ""),
        )

    def to_dict(self) -> dict:
        return {
            "documentId":       self.document_id,
            "docNumber":        self.doc_number,
            "grantor":          self.grantor,
            "grantee":          self.grantee,
            "docType":          self.doc_type,
            "recordedDate":     self.recorded_date,
            "bookVolumePage":   self.book_volume_page,
            "legalDescription": self.legal_description,
            "recordNumber":     self.record_number,
            "pageNumber":       self.page_number,
            "extractedAt":      _normalize_timestamp(self.extracted_at),
            "processedAt":      _normalize_timestamp(self.processed_at),
            "scrapeRunId":      self.scrape_run_id,
            "locationCode":     self.location_code,
            "offset":           self.offset,
            "pdfUrl":           self.pdf_url,
            "docS3Uri":         self.doc_s3_uri,
            "docLocalPath":     self.doc_local_path,
            "parsedAt":         self.parsed_at,
            "parsedModel":      self.parsed_model,
            "parseError":       self.parse_error,
            "summary":          self.summary,
            "rawResponse":      self.raw_response,
        }


# ---------------------------------------------------------------------------
# Contact (people parsed from documents)
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    contact_id:    str = ""
    document_id:   str = ""
    # ── Editable (ground-truth / golden) fields ────────────────────────────
    role:          str = ""   # deceased / executor / beneficiary / heir / attorney / other
    name:          str = ""
    email:         str = ""
    dob:           str = ""
    dod:           str = ""
    address:       str = ""
    notes:         str = ""
    edited_at:     str = ""   # ISO timestamp of last human edit; "" = never edited
    # ── Parse metadata ─────────────────────────────────────────────────────
    parsed_at:     str = ""
    parsed_model:  str = ""
    raw_response:  str = ""   # full Bedrock JSON response (updated on every re-parse)
    # ── Bedrock snapshot (set on first parse; preserved across re-parses) ──
    # Diff parsed_* vs editable fields to build the golden training dataset.
    parsed_role:    str = ""
    parsed_name:    str = ""
    parsed_email:   str = ""
    parsed_dob:     str = ""
    parsed_dod:     str = ""
    parsed_address: str = ""
    parsed_notes:   str = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "Contact":
        return cls(
            contact_id=     item.get("contact_id", ""),
            document_id=    item.get("document_id", ""),
            role=           item.get("role", ""),
            name=           item.get("name", ""),
            email=          item.get("email", ""),
            dob=            item.get("dob", ""),
            dod=            item.get("dod", ""),
            address=        item.get("address", ""),
            notes=          item.get("notes", ""),
            edited_at=      item.get("edited_at", ""),
            parsed_at=      item.get("parsed_at", ""),
            parsed_model=   item.get("parsed_model", ""),
            raw_response=   item.get("raw_response", ""),
            parsed_role=    item.get("parsed_role", ""),
            parsed_name=    item.get("parsed_name", ""),
            parsed_email=   item.get("parsed_email", ""),
            parsed_dob=     item.get("parsed_dob", ""),
            parsed_dod=     item.get("parsed_dod", ""),
            parsed_address= item.get("parsed_address", ""),
            parsed_notes=   item.get("parsed_notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "contactId":     self.contact_id,
            "documentId":    self.document_id,
            "role":          self.role,
            "name":          self.name,
            "email":         self.email,
            "dob":           self.dob,
            "dod":           self.dod,
            "address":       self.address,
            "notes":         self.notes,
            "editedAt":      self.edited_at,
            "parsedAt":      self.parsed_at,
            "parsedModel":   self.parsed_model,
            "rawResponse":   self.raw_response,
            "parsedRole":    self.parsed_role,
            "parsedName":    self.parsed_name,
            "parsedEmail":   self.parsed_email,
            "parsedDob":     self.parsed_dob,
            "parsedDod":     self.parsed_dod,
            "parsedAddress": self.parsed_address,
            "parsedNotes":   self.parsed_notes,
        }


# ---------------------------------------------------------------------------
# Property (real estate assets in the estate)
# ---------------------------------------------------------------------------

@dataclass
class Property:
    property_id:               str = ""
    document_id:               str = ""
    # ── Editable (ground-truth / golden) fields ────────────────────────────
    address:                   str = ""
    legal_description:         str = ""
    parcel_id:                 str = ""
    city:                      str = ""
    state:                     str = ""
    zip:                       str = ""
    notes:                     str = ""
    edited_at:                 str = ""   # ISO timestamp of last human edit; "" = never edited
    is_verified:               bool = False  # True when address components validated by usaddress
    # ── Parse metadata ─────────────────────────────────────────────────────
    parsed_at:                 str = ""
    parsed_model:              str = ""
    raw_response:              str = ""   # full Bedrock JSON response (updated on every re-parse)
    # ── Bedrock snapshot (set on first parse; preserved across re-parses) ──
    parsed_address:            str = ""
    parsed_legal_description:  str = ""
    parsed_parcel_id:          str = ""
    parsed_city:               str = ""
    parsed_state:              str = ""
    parsed_zip:                str = ""
    parsed_notes:              str = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "Property":
        return cls(
            property_id=              item.get("property_id", ""),
            document_id=              item.get("document_id", ""),
            address=                  item.get("address", ""),
            legal_description=        item.get("legal_description", ""),
            parcel_id=                item.get("parcel_id", ""),
            city=                     item.get("city", ""),
            state=                    item.get("state", ""),
            zip=                      item.get("zip", ""),
            notes=                    item.get("notes", ""),
            edited_at=                item.get("edited_at", ""),
            is_verified=              bool(item.get("is_verified", False)),
            parsed_at=                item.get("parsed_at", ""),
            parsed_model=             item.get("parsed_model", ""),
            raw_response=             item.get("raw_response", ""),
            parsed_address=           item.get("parsed_address", ""),
            parsed_legal_description= item.get("parsed_legal_description", ""),
            parsed_parcel_id=         item.get("parsed_parcel_id", ""),
            parsed_city=              item.get("parsed_city", ""),
            parsed_state=             item.get("parsed_state", ""),
            parsed_zip=               item.get("parsed_zip", ""),
            parsed_notes=             item.get("parsed_notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "propertyId":              self.property_id,
            "documentId":              self.document_id,
            "address":                 self.address,
            "legalDescription":        self.legal_description,
            "parcelId":                self.parcel_id,
            "city":                    self.city,
            "state":                   self.state,
            "zip":                     self.zip,
            "notes":                   self.notes,
            "editedAt":                self.edited_at,
            "isVerified":              self.is_verified,
            "parsedAt":                self.parsed_at,
            "parsedModel":             self.parsed_model,
            "rawResponse":             self.raw_response,
            "parsedAddress":           self.parsed_address,
            "parsedLegalDescription":  self.parsed_legal_description,
            "parsedParcelId":          self.parsed_parcel_id,
            "parsedCity":              self.parsed_city,
            "parsedState":             self.parsed_state,
            "parsedZip":               self.parsed_zip,
            "parsedNotes":             self.parsed_notes,
        }


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

@dataclass
class Location:
    location_code: str = ""
    location_path: str = ""
    location_name: str = ""
    search_url:    str = ""
    retrieved_at:  str = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "Location":
        return cls(
            location_code= item.get("location_code", ""),
            location_path= item.get("location_path", ""),
            location_name= item.get("location_name", ""),
            search_url=    item.get("search_url", ""),
            retrieved_at=  item.get("retrieved_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "locationCode": self.location_code,
            "locationPath": self.location_path,
            "locationName": self.location_name,
            "searchUrl":    self.search_url,
            "retrievedAt":  self.retrieved_at,
        }


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """User event tracking for prospect journey."""
    event_id:       str = ""
    user_id:        str = ""
    event_type:     str = ""  # email_sent, email_open, email_bounce, email_complaint, link_clicked, subscribe_clicked, unsubscribe_clicked, signup_completed
    timestamp:      str = ""
    variant:        str = ""  # A/B test variant name
    email_template: str = ""  # template file used
    from_name:      str = ""  # from name used
    subject_line:   str = ""  # subject line used
    prospect_token: str = ""  # prospect token for tracking
    metadata:       dict = field(default_factory=dict)  # additional data

    @classmethod
    def from_dynamo(cls, item: dict) -> "Event":
        return cls(
            event_id=       item.get("event_id", ""),
            user_id=        item.get("user_id", ""),
            event_type=     item.get("event_type", ""),
            timestamp=      item.get("timestamp", ""),
            variant=        item.get("variant", ""),
            email_template= item.get("email_template", ""),
            from_name=      item.get("from_name", ""),
            subject_line=   item.get("subject_line", ""),
            prospect_token= item.get("prospect_token", ""),
            metadata=       item.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        return {
            "eventId":       self.event_id,
            "userId":        self.user_id,
            "eventType":     self.event_type,
            "timestamp":     self.timestamp,
            "variant":       self.variant,
            "emailTemplate": self.email_template,
            "fromName":      self.from_name,
            "subjectLine":   self.subject_line,
            "prospectToken": self.prospect_token,
            "metadata":      self.metadata,
        }


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

@dataclass
class User:
    user_id:                str = ""
    email:                  str = ""
    first_name:             str = ""
    last_name:              str = ""
    role:                   str = "user"
    stripe_customer_id:     str = ""
    stripe_subscription_id: str = ""
    status:                 str = "active"
    location_codes:         set = field(default_factory=set)
    offered_price:          int = 0
    created_at:             str = ""
    updated_at:             str = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "User":
        raw_codes = item.get("location_codes", set())
        return cls(
            user_id=                item.get("user_id", ""),
            email=                  item.get("email", ""),
            first_name=             item.get("first_name", ""),
            last_name=              item.get("last_name", ""),
            role=                   item.get("role", "user"),
            stripe_customer_id=     item.get("stripe_customer_id", ""),
            stripe_subscription_id= item.get("stripe_subscription_id", ""),
            status=                 item.get("status", "active"),
            location_codes=         set(raw_codes) if raw_codes else set(),
            offered_price=          int(item.get("offered_price", 0) or 0),
            created_at=             item.get("created_at", ""),
            updated_at=             item.get("updated_at", ""),
        )

    def to_dict(self) -> dict:
        codes = self.location_codes
        return {
            "userId":                self.user_id,
            "email":                 self.email,
            "firstName":             self.first_name,
            "lastName":              self.last_name,
            "role":                  self.role,
            "stripeCustomerId":      self.stripe_customer_id,
            "stripeSubscriptionId":  self.stripe_subscription_id,
            "status":                self.status,
            "locationCodes":         sorted(codes) if isinstance(codes, (set, frozenset)) else sorted(codes),
            "offeredPrice":          self.offered_price,
            "createdAt":             self.created_at,
            "updatedAt":             self.updated_at,
        }
