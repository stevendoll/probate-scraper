"""
Domain models for the probate-leads API.

Each model exposes two entry points:
  - ``Model.from_dynamo(item)``  — build from a raw DynamoDB attribute dict
  - ``instance.to_dict()``       — serialize to the camelCase JSON shape the API returns
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Timestamp helper (used by Lead.to_dict)
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
# Lead
# ---------------------------------------------------------------------------

@dataclass
class Lead:
    lead_id:               str  = ""
    doc_number:            str  = ""
    grantor:               str  = ""
    grantee:               str  = ""
    doc_type:              str  = ""
    recorded_date:         str  = ""
    book_volume_page:      str  = ""
    legal_description:     str  = ""
    record_number:         int  = 0
    page_number:           int  = 0
    extracted_at:          str  = ""
    processed_at:          str  = ""
    scrape_run_id:         str  = ""
    location_code:         str  = ""
    offset:                int  = 0
    pdf_url:               str  = ""
    doc_s3_uri:            str  = ""
    # --- Parsed fields (populated by ParseDocumentFunction) ------------------
    parsed_at:             str  = ""
    parsed_model:          str  = ""
    deceased_name:         str  = ""
    deceased_dob:          str  = ""
    deceased_dod:          str  = ""
    deceased_last_address: str  = ""
    people:                list = field(default_factory=list)
    real_property:         list = field(default_factory=list)
    summary:               str  = ""
    parse_error:           str  = ""

    @classmethod
    def from_dynamo(cls, item: dict) -> "Lead":
        return cls(
            lead_id=               item.get("lead_id", ""),
            doc_number=            item.get("doc_number", ""),
            grantor=               item.get("grantor", ""),
            grantee=               item.get("grantee", ""),
            doc_type=              item.get("doc_type", ""),
            recorded_date=         item.get("recorded_date", ""),
            book_volume_page=      item.get("book_volume_page", ""),
            legal_description=     item.get("legal_description", ""),
            record_number=         int(item.get("record_number", 0) or 0),
            page_number=           int(item.get("page_number", 0) or 0),
            extracted_at=          str(item.get("extracted_at", "")),
            processed_at=          str(item.get("processed_at", "")),
            scrape_run_id=         item.get("scrape_run_id", ""),
            location_code=         item.get("location_code", ""),
            offset=                int(item.get("offset", 0) or 0),
            pdf_url=               item.get("pdf_url", ""),
            doc_s3_uri=            item.get("doc_s3_uri", ""),
            parsed_at=             item.get("parsed_at", ""),
            parsed_model=          item.get("parsed_model", ""),
            deceased_name=         item.get("deceased_name", ""),
            deceased_dob=          item.get("deceased_dob", ""),
            deceased_dod=          item.get("deceased_dod", ""),
            deceased_last_address= item.get("deceased_last_address", ""),
            people=                list(item.get("people", []) or []),
            real_property=         list(item.get("real_property", []) or []),
            summary=               item.get("summary", ""),
            parse_error=           item.get("parse_error", ""),
        )

    def to_dict(self) -> dict:
        return {
            "leadId":              self.lead_id,
            "docNumber":           self.doc_number,
            "grantor":             self.grantor,
            "grantee":             self.grantee,
            "docType":             self.doc_type,
            "recordedDate":        self.recorded_date,
            "bookVolumePage":      self.book_volume_page,
            "legalDescription":    self.legal_description,
            "recordNumber":        self.record_number,
            "pageNumber":          self.page_number,
            "extractedAt":         _normalize_timestamp(self.extracted_at),
            "processedAt":         _normalize_timestamp(self.processed_at),
            "scrapeRunId":         self.scrape_run_id,
            "locationCode":        self.location_code,
            "offset":              self.offset,
            "pdfUrl":              self.pdf_url,
            "docS3Uri":            self.doc_s3_uri,
            "parsedAt":            _normalize_timestamp(self.parsed_at),
            "parsedModel":         self.parsed_model,
            "deceasedName":        self.deceased_name,
            "deceasedDob":         self.deceased_dob,
            "deceasedDod":         self.deceased_dod,
            "deceasedLastAddress": self.deceased_last_address,
            "people":              self.people,
            "realProperty":        self.real_property,
            "summary":             self.summary,
            "parseError":          self.parse_error,
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
# User
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
