"""
Unit tests for src/api/routers/documents.py

  GET    /real-estate/probate-leads/documents/{document_id}
  GET    /real-estate/probate-leads/documents/{document_id}/contacts
  GET    /real-estate/probate-leads/documents/{document_id}/properties
  PATCH  /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}
  DELETE /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}
  POST   /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}/links
  DELETE /real-estate/probate-leads/documents/{document_id}/contacts/{contact_id}/links/{link_id}
  PATCH  /real-estate/probate-leads/documents/{document_id}/properties/{property_id}
  DELETE /real-estate/probate-leads/documents/{document_id}/properties/{property_id}
  POST   /real-estate/probate-leads/documents/{document_id}/properties/{property_id}/links
  DELETE /real-estate/probate-leads/documents/{document_id}/properties/{property_id}/links/{link_id}
"""

import copy
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap — env vars and mock boto3 before importing
# ---------------------------------------------------------------------------
os.environ.setdefault("AWS_ENDPOINT_URL",          "http://localhost:8000")
os.environ.setdefault("AWS_ACCESS_KEY_ID",         "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY",     "local")
os.environ.setdefault("AWS_DEFAULT_REGION",        "us-east-1")
os.environ.setdefault("DOCUMENTS_TABLE_NAME",      "documents")
os.environ.setdefault("LOCATIONS_TABLE_NAME",      "locations")
os.environ.setdefault("USERS_TABLE_NAME",          "users")
os.environ.setdefault("CONTACTS_TABLE_NAME",       "contacts")
os.environ.setdefault("PROPERTIES_TABLE_NAME",     "properties")
os.environ.setdefault("LINKS_TABLE_NAME",          "links")
os.environ.setdefault("GSI_NAME",                  "recorded-date-index")
os.environ.setdefault("LOCATION_DATE_GSI",         "location-date-index")
os.environ.setdefault("STRIPE_SECRET_KEY",         "")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET",     "")
os.environ.setdefault("JWT_SECRET",                "test-secret")
os.environ.setdefault("FROM_EMAIL",                "")
os.environ.setdefault("MAGIC_LINK_BASE_URL",       "http://localhost:3000/auth/verify")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME",   "probate-api-test")
os.environ.setdefault("LOG_LEVEL",                 "WARNING")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "api"))

_mock_tracer = MagicMock()
_mock_tracer.capture_lambda_handler = lambda f: f
_mock_tracer.capture_method = lambda f: f

if "app" not in sys.modules:
    with patch("boto3.resource", return_value=MagicMock()), \
         patch("aws_lambda_powertools.Tracer", return_value=_mock_tracer):
        import app  # noqa: E402
        import db   # noqa: E402
else:
    import app  # noqa: E402
    import db   # noqa: E402


# ---------------------------------------------------------------------------
# Mock Lambda context
# ---------------------------------------------------------------------------
class MockContext:
    aws_request_id       = "test-request-id"
    function_name        = "probate-leads-api-test"
    memory_limit_in_mb   = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    log_stream_name      = "test-log-stream"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DOC_ID      = "550e8400-e29b-41d4-a716-446655440001"
CONTACT_ID  = "contact-001"
PROPERTY_ID = "property-001"
LINK_ID     = "link-001"

MOCK_DOCUMENT = {
    "document_id":       DOC_ID,
    "doc_number":        "2026000009280",
    "grantor":           "CHERRY ERIKA WOOD DECEASED ESTATE",
    "grantee":           "PUBLIC",
    "doc_type":          "PROBATE",
    "recorded_date":     "2026-01-23",
    "book_volume_page":  "--/--/--",
    "legal_description": "N/A",
    "location_code":     "CollinTx",
    "record_number":     "1",
    "page_number":       "1",
    "offset":            "0",
    "extracted_at":      "2026-01-29T20:00:15.989922",
    "processed_at":      "2026-02-20T14:09:56+00:00",
    "scrape_run_id":     "run-001",
    "pdf_url":           "https://example.com/doc.pdf",
    "doc_s3_uri":        "s3://mybucket/docs/doc.pdf",
    "doc_local_path":    "",
}

MOCK_CONTACT = {
    "contact_id":     CONTACT_ID,
    "document_id":    DOC_ID,
    "role":           "executor",
    "name":           "Robert Smith",
    "email":          "robert@example.com",
    "dob":            "",
    "dod":            "",
    "address":        "",
    "notes":          "",
    "edited_at":      "",
    "parsed_at":      "2026-03-13T00:00:00+00:00",
    "parsed_model":   "us.amazon.nova-pro-v1:0",
    "raw_response":   "{}",
    "parsed_role":    "executor",
    "parsed_name":    "Robert Smith",
    "parsed_email":   "robert@example.com",
    "parsed_dob":     "",
    "parsed_dod":     "",
    "parsed_address": "",
    "parsed_notes":   "",
}

MOCK_CONTACT_LINK = {
    "link_id":     LINK_ID,
    "parent_id":   CONTACT_ID,
    "parent_type": "contact",
    "document_id": DOC_ID,
    "label":       "Zillow",
    "url":         "https://www.zillow.com/homes/123-main-st_rb/",
    "link_type":   "zillow",
    "notes":       "",
    "created_at":  "2026-03-13T00:00:00+00:00",
}

MOCK_PROPERTY_LINK = {
    "link_id":     "link-002",
    "parent_id":   PROPERTY_ID,
    "parent_type": "property",
    "document_id": DOC_ID,
    "label":       "Redfin",
    "url":         "https://www.redfin.com/search?q=123+Main",
    "link_type":   "redfin",
    "notes":       "",
    "created_at":  "2026-03-13T00:00:00+00:00",
}

MOCK_PROPERTY = {
    "property_id":              PROPERTY_ID,
    "document_id":              DOC_ID,
    "address":                  "123 Main St",
    "legal_description":        "",
    "parcel_id":                "",
    "city":                     "Plano",
    "state":                    "TX",
    "zip":                      "75001",
    "notes":                    "",
    "edited_at":                "",
    "is_verified":              True,
    "parsed_at":                "2026-03-13T00:00:00+00:00",
    "parsed_model":             "us.amazon.nova-pro-v1:0",
    "raw_response":             "{}",
    "parsed_address":           "123 Main St",
    "parsed_legal_description": "",
    "parsed_parcel_id":         "",
    "parsed_city":              "Plano",
    "parsed_state":             "TX",
    "parsed_zip":               "75001",
    "parsed_notes":             "",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(method, path, path_params, body=None, qs=None):
    event = {
        "httpMethod":            method,
        "path":                  path,
        "pathParameters":        path_params,
        "headers":               {"x-api-key": "test-key"},
        "queryStringParameters": qs,
        "body":                  json.dumps(body) if body is not None else None,
        "isBase64Encoded":       False,
    }
    return app.handler(event, MockContext())


def _body(resp):
    return json.loads(resp["body"])


def _get_document(doc_id=DOC_ID):
    return _call("GET",
                 f"/real-estate/probate-leads/documents/{doc_id}",
                 {"document_id": doc_id})


def _get_contacts(doc_id=DOC_ID):
    return _call("GET",
                 f"/real-estate/probate-leads/documents/{doc_id}/contacts",
                 {"document_id": doc_id})


def _get_properties(doc_id=DOC_ID):
    return _call("GET",
                 f"/real-estate/probate-leads/documents/{doc_id}/properties",
                 {"document_id": doc_id})


def _patch_contact(doc_id=DOC_ID, contact_id=CONTACT_ID, body=None):
    return _call("PATCH",
                 f"/real-estate/probate-leads/documents/{doc_id}/contacts/{contact_id}",
                 {"document_id": doc_id, "contact_id": contact_id},
                 body=body or {})


def _delete_contact(doc_id=DOC_ID, contact_id=CONTACT_ID):
    return _call("DELETE",
                 f"/real-estate/probate-leads/documents/{doc_id}/contacts/{contact_id}",
                 {"document_id": doc_id, "contact_id": contact_id})


def _patch_property(doc_id=DOC_ID, property_id=PROPERTY_ID, body=None):
    return _call("PATCH",
                 f"/real-estate/probate-leads/documents/{doc_id}/properties/{property_id}",
                 {"document_id": doc_id, "property_id": property_id},
                 body=body or {})


def _delete_property(doc_id=DOC_ID, property_id=PROPERTY_ID):
    return _call("DELETE",
                 f"/real-estate/probate-leads/documents/{doc_id}/properties/{property_id}",
                 {"document_id": doc_id, "property_id": property_id})


def _post_contact_link(doc_id=DOC_ID, contact_id=CONTACT_ID, body=None):
    return _call("POST",
                 f"/real-estate/probate-leads/documents/{doc_id}/contacts/{contact_id}/links",
                 {"document_id": doc_id, "contact_id": contact_id},
                 body=body or {})


def _delete_contact_link(doc_id=DOC_ID, contact_id=CONTACT_ID, link_id=LINK_ID):
    return _call("DELETE",
                 f"/real-estate/probate-leads/documents/{doc_id}/contacts/{contact_id}/links/{link_id}",
                 {"document_id": doc_id, "contact_id": contact_id, "link_id": link_id})


def _post_property_link(doc_id=DOC_ID, property_id=PROPERTY_ID, body=None):
    return _call("POST",
                 f"/real-estate/probate-leads/documents/{doc_id}/properties/{property_id}/links",
                 {"document_id": doc_id, "property_id": property_id},
                 body=body or {})


def _delete_property_link(doc_id=DOC_ID, property_id=PROPERTY_ID, link_id=LINK_ID):
    return _call("DELETE",
                 f"/real-estate/probate-leads/documents/{doc_id}/properties/{property_id}/links/{link_id}",
                 {"document_id": doc_id, "property_id": property_id, "link_id": link_id})


# ---------------------------------------------------------------------------
# GET /documents/{document_id}
# ---------------------------------------------------------------------------

class TestGetDocument(unittest.TestCase):

    def setUp(self):
        self.mock_docs       = MagicMock()
        self.mock_contacts   = MagicMock()
        self.mock_properties = MagicMock()
        self.mock_links      = MagicMock()
        db.documents_table   = self.mock_docs
        db.contacts_table    = self.mock_contacts
        db.properties_table  = self.mock_properties
        db.links_table       = self.mock_links

        self.mock_docs.get_item.return_value    = {"Item": MOCK_DOCUMENT}
        self.mock_contacts.query.return_value   = {"Items": [MOCK_CONTACT]}
        self.mock_properties.query.return_value = {"Items": [MOCK_PROPERTY]}
        self.mock_links.query.return_value      = {"Items": []}

    def test_returns_200(self):
        resp = _get_document()
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_document(self):
        body = _body(_get_document())
        self.assertEqual(body["document"]["documentId"], DOC_ID)
        self.assertEqual(body["document"]["docNumber"], "2026000009280")

    def test_response_includes_contacts(self):
        body = _body(_get_document())
        self.assertEqual(len(body["contacts"]), 1)
        self.assertEqual(body["contacts"][0]["contactId"], CONTACT_ID)
        self.assertEqual(body["contacts"][0]["role"], "executor")

    def test_response_includes_properties(self):
        body = _body(_get_document())
        self.assertEqual(len(body["properties"]), 1)
        self.assertEqual(body["properties"][0]["propertyId"], PROPERTY_ID)

    def test_contact_includes_parsed_fields(self):
        body = _body(_get_document())
        c = body["contacts"][0]
        self.assertEqual(c["parsedRole"],  "executor")
        self.assertEqual(c["parsedName"],  "Robert Smith")
        self.assertEqual(c["parsedEmail"], "robert@example.com")

    def test_property_includes_parsed_fields(self):
        body = _body(_get_document())
        p = body["properties"][0]
        self.assertEqual(p["parsedAddress"], "123 Main St")
        self.assertTrue(p["isVerified"])

    def test_returns_404_when_not_found(self):
        self.mock_docs.get_item.return_value = {}
        resp = _get_document()
        self.assertEqual(resp["statusCode"], 404)
        self.assertIn("not found", _body(resp)["error"].lower())

    def test_returns_404_when_item_is_none(self):
        self.mock_docs.get_item.return_value = {"Item": None}
        resp = _get_document()
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_500_on_db_error(self):
        self.mock_docs.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _get_document()
        self.assertEqual(resp["statusCode"], 500)

    def test_contacts_gsi_error_returns_empty_list(self):
        """Contacts table failure should not prevent returning the document."""
        self.mock_contacts.query.side_effect = Exception("GSI error")
        body = _body(_get_document())
        self.assertEqual(resp := _get_document(), resp)  # re-call to get fresh resp
        self.assertIsInstance(_body(_get_document())["contacts"], list)
        self.assertEqual(_body(_get_document())["contacts"], [])

    def test_properties_gsi_error_returns_empty_list(self):
        """Properties table failure should not prevent returning the document."""
        self.mock_properties.query.side_effect = Exception("GSI error")
        body = _body(_get_document())
        self.assertIsInstance(body["properties"], list)
        self.assertEqual(body["properties"], [])

    def test_response_has_request_id(self):
        body = _body(_get_document())
        self.assertIn("requestId", body)
        self.assertTrue(body["requestId"])

    def test_contacts_include_empty_links_list_when_no_links(self):
        """Each contact always has a 'links' key, empty list when no links exist."""
        body = _body(_get_document())
        self.assertIn("links", body["contacts"][0])
        self.assertEqual(body["contacts"][0]["links"], [])

    def test_links_attached_to_correct_contact(self):
        """A link whose parent_id matches a contact's contactId is attached to that contact."""
        self.mock_links.query.return_value = {"Items": [MOCK_CONTACT_LINK]}
        body = _body(_get_document())
        links = body["contacts"][0]["links"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["linkId"],   LINK_ID)
        self.assertEqual(links[0]["linkType"], "zillow")
        self.assertEqual(links[0]["url"],      MOCK_CONTACT_LINK["url"])

    def test_links_gsi_error_returns_empty_links(self):
        """Links table failure must not prevent the document from being returned."""
        self.mock_links.query.side_effect = Exception("GSI error")
        resp = _get_document()
        self.assertEqual(resp["statusCode"], 200)
        body = _body(resp)
        self.assertEqual(body["contacts"][0]["links"], [])


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/contacts
# ---------------------------------------------------------------------------

class TestGetDocumentContacts(unittest.TestCase):

    def setUp(self):
        self.mock_contacts = MagicMock()
        db.contacts_table  = self.mock_contacts
        self.mock_contacts.query.return_value = {"Items": [MOCK_CONTACT]}

    def test_returns_200(self):
        resp = _get_contacts()
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_contacts_list(self):
        body = _body(_get_contacts())
        self.assertEqual(len(body["contacts"]), 1)
        self.assertEqual(body["contacts"][0]["contactId"], CONTACT_ID)

    def test_returns_parsed_fields(self):
        c = _body(_get_contacts())["contacts"][0]
        self.assertEqual(c["parsedRole"],    "executor")
        self.assertEqual(c["parsedName"],    "Robert Smith")
        self.assertEqual(c["parsedEmail"],   "robert@example.com")
        self.assertEqual(c["parsedAddress"], "")
        self.assertEqual(c["parsedNotes"],   "")

    def test_returns_count(self):
        body = _body(_get_contacts())
        self.assertEqual(body["count"], 1)

    def test_returns_document_id(self):
        body = _body(_get_contacts())
        self.assertEqual(body["documentId"], DOC_ID)

    def test_returns_empty_list_when_no_contacts(self):
        self.mock_contacts.query.return_value = {"Items": []}
        body = _body(_get_contacts())
        self.assertEqual(body["contacts"], [])
        self.assertEqual(body["count"], 0)

    def test_returns_500_on_db_error(self):
        self.mock_contacts.query.side_effect = Exception("GSI error")
        resp = _get_contacts()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/properties
# ---------------------------------------------------------------------------

class TestGetDocumentProperties(unittest.TestCase):

    def setUp(self):
        self.mock_properties = MagicMock()
        db.properties_table  = self.mock_properties
        self.mock_properties.query.return_value = {"Items": [MOCK_PROPERTY]}

    def test_returns_200(self):
        resp = _get_properties()
        self.assertEqual(resp["statusCode"], 200)

    def test_returns_properties_list(self):
        body = _body(_get_properties())
        self.assertEqual(len(body["properties"]), 1)
        self.assertEqual(body["properties"][0]["propertyId"], PROPERTY_ID)

    def test_returns_parsed_fields(self):
        p = _body(_get_properties())["properties"][0]
        self.assertEqual(p["parsedAddress"],           "123 Main St")
        self.assertEqual(p["parsedCity"],              "Plano")
        self.assertEqual(p["parsedState"],             "TX")
        self.assertEqual(p["parsedZip"],               "75001")
        self.assertEqual(p["parsedLegalDescription"],  "")
        self.assertEqual(p["parsedParcelId"],          "")

    def test_returns_is_verified(self):
        p = _body(_get_properties())["properties"][0]
        self.assertTrue(p["isVerified"])

    def test_returns_count(self):
        body = _body(_get_properties())
        self.assertEqual(body["count"], 1)

    def test_returns_document_id(self):
        body = _body(_get_properties())
        self.assertEqual(body["documentId"], DOC_ID)

    def test_returns_empty_list_when_no_properties(self):
        self.mock_properties.query.return_value = {"Items": []}
        body = _body(_get_properties())
        self.assertEqual(body["properties"], [])
        self.assertEqual(body["count"], 0)

    def test_returns_500_on_db_error(self):
        self.mock_properties.query.side_effect = Exception("GSI error")
        resp = _get_properties()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# PATCH /documents/{document_id}/contacts/{contact_id}
# ---------------------------------------------------------------------------

class TestUpdateContact(unittest.TestCase):

    def setUp(self):
        self.mock_contacts = MagicMock()
        db.contacts_table  = self.mock_contacts
        self.mock_contacts.get_item.return_value = {"Item": MOCK_CONTACT}
        updated = {**MOCK_CONTACT, "role": "heir", "edited_at": "2026-03-13T00:01:00+00:00"}
        self.mock_contacts.update_item.return_value = {"Attributes": updated}

    def test_returns_200(self):
        resp = _patch_contact(body={"role": "heir"})
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_updated_contact(self):
        body = _body(_patch_contact(body={"role": "heir"}))
        self.assertEqual(body["contact"]["role"], "heir")
        self.assertIn("requestId", body)

    def test_stamps_edited_at(self):
        """PATCH must always write edited_at regardless of what fields were provided."""
        _patch_contact(body={"role": "heir"})
        call_kwargs = self.mock_contacts.update_item.call_args.kwargs
        self.assertIn("#edited_at", call_kwargs["ExpressionAttributeNames"])
        self.assertIn(":edited_at", call_kwargs["ExpressionAttributeValues"])
        # edited_at value must be a non-empty ISO timestamp string
        self.assertTrue(call_kwargs["ExpressionAttributeValues"][":edited_at"])

    def test_only_mutable_fields_written(self):
        """role, name, email, dob, dod, address, notes — but not parsed_* fields."""
        _patch_contact(body={"name": "Jane Doe"})
        call_kwargs = self.mock_contacts.update_item.call_args.kwargs
        self.assertIn("#name", call_kwargs["ExpressionAttributeNames"])

    def test_parsed_fields_are_rejected(self):
        """parsed_* snapshot fields must be silently ignored by the PATCH handler."""
        _patch_contact(body={"role": "heir", "parsed_role": "OTHER"})
        call_kwargs = self.mock_contacts.update_item.call_args.kwargs
        self.assertNotIn("#parsed_role", call_kwargs["ExpressionAttributeNames"])

    def test_returns_400_when_no_mutable_fields(self):
        resp = _patch_contact(body={"unknown_field": "value"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("updatable fields", _body(resp)["error"].lower())

    def test_returns_400_on_invalid_json_body(self):
        event = {
            "httpMethod":            "PATCH",
            "path":                  f"/real-estate/probate-leads/documents/{DOC_ID}/contacts/{CONTACT_ID}",
            "pathParameters":        {"document_id": DOC_ID, "contact_id": CONTACT_ID},
            "headers":               {"x-api-key": "test-key"},
            "queryStringParameters": None,
            "body":                  "not-json{{{",
            "isBase64Encoded":       False,
        }
        resp = app.handler(event, MockContext())
        self.assertEqual(resp["statusCode"], 400)

    def test_returns_404_when_contact_not_found(self):
        self.mock_contacts.get_item.return_value = {"Item": None}
        resp = _patch_contact(body={"role": "heir"})
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_403_when_wrong_document(self):
        wrong_contact = {**MOCK_CONTACT, "document_id": "different-doc"}
        self.mock_contacts.get_item.return_value = {"Item": wrong_contact}
        resp = _patch_contact(body={"role": "heir"})
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_500_on_get_item_failure(self):
        self.mock_contacts.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _patch_contact(body={"role": "heir"})
        self.assertEqual(resp["statusCode"], 500)

    def test_returns_500_on_update_item_failure(self):
        self.mock_contacts.update_item.side_effect = Exception("ProvisionedThroughputExceeded")
        resp = _patch_contact(body={"role": "heir"})
        self.assertEqual(resp["statusCode"], 500)

    def test_multiple_fields_updated_in_one_call(self):
        updated = {**MOCK_CONTACT, "role": "heir", "name": "Jane Doe"}
        self.mock_contacts.update_item.return_value = {"Attributes": updated}
        resp = _patch_contact(body={"role": "heir", "name": "Jane Doe"})
        self.assertEqual(resp["statusCode"], 200)
        call_kwargs = self.mock_contacts.update_item.call_args.kwargs
        self.assertIn("#role", call_kwargs["ExpressionAttributeNames"])
        self.assertIn("#name", call_kwargs["ExpressionAttributeNames"])


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}/contacts/{contact_id}
# ---------------------------------------------------------------------------

class TestDeleteContact(unittest.TestCase):

    def setUp(self):
        self.mock_contacts = MagicMock()
        db.contacts_table  = self.mock_contacts
        self.mock_contacts.get_item.return_value = {"Item": MOCK_CONTACT}
        self.mock_contacts.delete_item.return_value = {}

    def test_returns_200(self):
        resp = _delete_contact()
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_deleted_id(self):
        body = _body(_delete_contact())
        self.assertEqual(body["deleted"], CONTACT_ID)

    def test_calls_delete_item(self):
        _delete_contact()
        self.mock_contacts.delete_item.assert_called_once_with(
            Key={"contact_id": CONTACT_ID}
        )

    def test_returns_404_when_not_found(self):
        self.mock_contacts.get_item.return_value = {"Item": None}
        resp = _delete_contact()
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_403_when_wrong_document(self):
        wrong_contact = {**MOCK_CONTACT, "document_id": "different-doc"}
        self.mock_contacts.get_item.return_value = {"Item": wrong_contact}
        resp = _delete_contact()
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_500_on_get_item_failure(self):
        self.mock_contacts.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_contact()
        self.assertEqual(resp["statusCode"], 500)

    def test_returns_500_on_delete_item_failure(self):
        self.mock_contacts.delete_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_contact()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# PATCH /documents/{document_id}/properties/{property_id}
# ---------------------------------------------------------------------------

class TestUpdateProperty(unittest.TestCase):

    def setUp(self):
        self.mock_properties = MagicMock()
        db.properties_table  = self.mock_properties
        self.mock_properties.get_item.return_value = {"Item": MOCK_PROPERTY}
        updated = {**MOCK_PROPERTY, "address": "456 Oak Ave", "edited_at": "2026-03-13T00:01:00+00:00"}
        self.mock_properties.update_item.return_value = {"Attributes": updated}

    def test_returns_200(self):
        resp = _patch_property(body={"address": "456 Oak Ave"})
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_updated_property(self):
        body = _body(_patch_property(body={"address": "456 Oak Ave"}))
        self.assertEqual(body["property"]["address"], "456 Oak Ave")
        self.assertIn("requestId", body)

    def test_stamps_edited_at(self):
        _patch_property(body={"address": "456 Oak Ave"})
        call_kwargs = self.mock_properties.update_item.call_args.kwargs
        self.assertIn("#edited_at", call_kwargs["ExpressionAttributeNames"])
        self.assertTrue(call_kwargs["ExpressionAttributeValues"][":edited_at"])

    def test_address_change_clears_is_verified(self):
        """Patching address must set is_verified=False (address not re-verified)."""
        _patch_property(body={"address": "456 Oak Ave"})
        call_kwargs = self.mock_properties.update_item.call_args.kwargs
        self.assertIn("#is_verified", call_kwargs["ExpressionAttributeNames"])
        self.assertFalse(call_kwargs["ExpressionAttributeValues"][":is_verified"])

    def test_non_address_change_does_not_clear_is_verified(self):
        """Patching city/zip without touching address must NOT clear is_verified."""
        _patch_property(body={"city": "Allen"})
        call_kwargs = self.mock_properties.update_item.call_args.kwargs
        self.assertNotIn("#is_verified", call_kwargs["ExpressionAttributeNames"])

    def test_parsed_fields_are_rejected(self):
        _patch_property(body={"address": "456 Oak Ave", "parsed_address": "OTHER"})
        call_kwargs = self.mock_properties.update_item.call_args.kwargs
        self.assertNotIn("#parsed_address", call_kwargs["ExpressionAttributeNames"])

    def test_returns_400_when_no_mutable_fields(self):
        resp = _patch_property(body={"unknown_field": "value"})
        self.assertEqual(resp["statusCode"], 400)

    def test_returns_400_on_invalid_json_body(self):
        event = {
            "httpMethod":            "PATCH",
            "path":                  f"/real-estate/probate-leads/documents/{DOC_ID}/properties/{PROPERTY_ID}",
            "pathParameters":        {"document_id": DOC_ID, "property_id": PROPERTY_ID},
            "headers":               {"x-api-key": "test-key"},
            "queryStringParameters": None,
            "body":                  "not-json{{{",
            "isBase64Encoded":       False,
        }
        resp = app.handler(event, MockContext())
        self.assertEqual(resp["statusCode"], 400)

    def test_returns_404_when_not_found(self):
        self.mock_properties.get_item.return_value = {"Item": None}
        resp = _patch_property(body={"address": "456 Oak Ave"})
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_403_when_wrong_document(self):
        wrong_prop = {**MOCK_PROPERTY, "document_id": "different-doc"}
        self.mock_properties.get_item.return_value = {"Item": wrong_prop}
        resp = _patch_property(body={"address": "456 Oak Ave"})
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_500_on_get_item_failure(self):
        self.mock_properties.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _patch_property(body={"address": "456 Oak Ave"})
        self.assertEqual(resp["statusCode"], 500)

    def test_returns_500_on_update_item_failure(self):
        self.mock_properties.update_item.side_effect = Exception("ProvisionedThroughputExceeded")
        resp = _patch_property(body={"address": "456 Oak Ave"})
        self.assertEqual(resp["statusCode"], 500)

    def test_all_mutable_fields_accepted(self):
        payload = {
            "address":           "456 Oak Ave",
            "legal_description": "Lot 7, Block 3",
            "parcel_id":         "0001234",
            "city":              "Plano",
            "state":             "TX",
            "zip":               "75001",
            "notes":             "Updated note",
        }
        updated = {**MOCK_PROPERTY, **payload}
        self.mock_properties.update_item.return_value = {"Attributes": updated}
        resp = _patch_property(body=payload)
        self.assertEqual(resp["statusCode"], 200)


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}/properties/{property_id}
# ---------------------------------------------------------------------------

class TestDeleteProperty(unittest.TestCase):

    def setUp(self):
        self.mock_properties = MagicMock()
        db.properties_table  = self.mock_properties
        self.mock_properties.get_item.return_value = {"Item": MOCK_PROPERTY}
        self.mock_properties.delete_item.return_value = {}

    def test_returns_200(self):
        resp = _delete_property()
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_deleted_id(self):
        body = _body(_delete_property())
        self.assertEqual(body["deleted"], PROPERTY_ID)

    def test_calls_delete_item(self):
        _delete_property()
        self.mock_properties.delete_item.assert_called_once_with(
            Key={"property_id": PROPERTY_ID}
        )

    def test_returns_404_when_not_found(self):
        self.mock_properties.get_item.return_value = {"Item": None}
        resp = _delete_property()
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_403_when_wrong_document(self):
        wrong_prop = {**MOCK_PROPERTY, "document_id": "different-doc"}
        self.mock_properties.get_item.return_value = {"Item": wrong_prop}
        resp = _delete_property()
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_500_on_get_item_failure(self):
        self.mock_properties.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_property()
        self.assertEqual(resp["statusCode"], 500)

    def test_returns_500_on_delete_item_failure(self):
        self.mock_properties.delete_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_property()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/contacts/{contact_id}/links
# ---------------------------------------------------------------------------

_GOOD_LINK_BODY = {
    "label":     "Zillow",
    "url":       "https://www.zillow.com/homes/123-main-st_rb/",
    "link_type": "zillow",
    "notes":     "",
}


class TestCreateContactLink(unittest.TestCase):

    def setUp(self):
        self.mock_links = MagicMock()
        db.links_table  = self.mock_links
        self.mock_links.put_item.return_value = {}

    def test_returns_201(self):
        resp = _post_contact_link(body=_GOOD_LINK_BODY)
        self.assertEqual(resp["statusCode"], 201)

    def test_response_includes_link(self):
        body = _body(_post_contact_link(body=_GOOD_LINK_BODY))
        self.assertIn("link", body)
        self.assertEqual(body["link"]["label"],    "Zillow")
        self.assertEqual(body["link"]["linkType"], "zillow")
        self.assertEqual(body["link"]["url"],      _GOOD_LINK_BODY["url"])
        self.assertEqual(body["link"]["parentId"], CONTACT_ID)
        self.assertIn("linkId", body["link"])

    def test_url_is_required(self):
        resp = _post_contact_link(body={"label": "Missing URL"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("url", _body(resp)["error"].lower())

    def test_empty_url_rejected(self):
        resp = _post_contact_link(body={"url": "  "})
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_link_type_rejected(self):
        resp = _post_contact_link(body={**_GOOD_LINK_BODY, "link_type": "unknown"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("link_type", _body(resp)["error"].lower())

    def test_all_valid_link_types_accepted(self):
        valid_types = ["zillow", "realtor", "redfin", "google_maps",
                       "county_record", "obituary", "legacy", "findagrave", "other"]
        for lt in valid_types:
            with self.subTest(link_type=lt):
                resp = _post_contact_link(body={**_GOOD_LINK_BODY, "link_type": lt})
                self.assertEqual(resp["statusCode"], 201, f"Expected 201 for link_type={lt!r}")

    def test_default_link_type_is_other(self):
        body_no_type = {"url": "https://example.com"}
        resp = _post_contact_link(body=body_no_type)
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(_body(resp)["link"]["linkType"], "other")

    def test_parent_type_set_to_contact(self):
        _post_contact_link(body=_GOOD_LINK_BODY)
        item = self.mock_links.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["parent_type"], "contact")
        self.assertEqual(item["parent_id"],   CONTACT_ID)
        self.assertEqual(item["document_id"], DOC_ID)

    def test_returns_400_on_invalid_json(self):
        event = {
            "httpMethod":            "POST",
            "path":                  f"/real-estate/probate-leads/documents/{DOC_ID}/contacts/{CONTACT_ID}/links",
            "pathParameters":        {"document_id": DOC_ID, "contact_id": CONTACT_ID},
            "headers":               {"x-api-key": "test-key"},
            "queryStringParameters": None,
            "body":                  "not-json",
            "isBase64Encoded":       False,
        }
        resp = app.handler(event, MockContext())
        self.assertEqual(resp["statusCode"], 400)

    def test_returns_500_on_db_error(self):
        self.mock_links.put_item.side_effect = Exception("ProvisionedThroughputExceeded")
        resp = _post_contact_link(body=_GOOD_LINK_BODY)
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}/contacts/{contact_id}/links/{link_id}
# ---------------------------------------------------------------------------

class TestDeleteContactLink(unittest.TestCase):

    def setUp(self):
        self.mock_links = MagicMock()
        db.links_table  = self.mock_links
        self.mock_links.get_item.return_value  = {"Item": MOCK_CONTACT_LINK}
        self.mock_links.delete_item.return_value = {}

    def test_returns_200(self):
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_deleted_id(self):
        body = _body(_delete_contact_link())
        self.assertEqual(body["deleted"], LINK_ID)

    def test_calls_delete_item_with_correct_key(self):
        _delete_contact_link()
        self.mock_links.delete_item.assert_called_once_with(Key={"link_id": LINK_ID})

    def test_returns_404_when_not_found(self):
        self.mock_links.get_item.return_value = {"Item": None}
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 404)

    def test_returns_403_when_wrong_document(self):
        wrong_link = {**MOCK_CONTACT_LINK, "document_id": "other-doc"}
        self.mock_links.get_item.return_value = {"Item": wrong_link}
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_403_when_wrong_parent(self):
        wrong_link = {**MOCK_CONTACT_LINK, "parent_id": "other-contact"}
        self.mock_links.get_item.return_value = {"Item": wrong_link}
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_500_on_get_item_failure(self):
        self.mock_links.get_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 500)

    def test_returns_500_on_delete_failure(self):
        self.mock_links.delete_item.side_effect = Exception("DynamoDB unavailable")
        resp = _delete_contact_link()
        self.assertEqual(resp["statusCode"], 500)


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/properties/{property_id}/links
# ---------------------------------------------------------------------------

class TestCreatePropertyLink(unittest.TestCase):

    def setUp(self):
        self.mock_links = MagicMock()
        db.links_table  = self.mock_links
        self.mock_links.put_item.return_value = {}

    def test_returns_201(self):
        resp = _post_property_link(body={**_GOOD_LINK_BODY, "link_type": "redfin"})
        self.assertEqual(resp["statusCode"], 201)

    def test_parent_type_set_to_property(self):
        _post_property_link(body=_GOOD_LINK_BODY)
        item = self.mock_links.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["parent_type"], "property")
        self.assertEqual(item["parent_id"],   PROPERTY_ID)

    def test_url_required(self):
        resp = _post_property_link(body={"label": "No URL"})
        self.assertEqual(resp["statusCode"], 400)


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}/properties/{property_id}/links/{link_id}
# ---------------------------------------------------------------------------

class TestDeletePropertyLink(unittest.TestCase):

    def setUp(self):
        self.mock_links = MagicMock()
        db.links_table  = self.mock_links
        self.mock_links.get_item.return_value    = {"Item": MOCK_PROPERTY_LINK}
        self.mock_links.delete_item.return_value = {}

    def test_returns_200(self):
        resp = _delete_property_link(link_id=MOCK_PROPERTY_LINK["link_id"])
        self.assertEqual(resp["statusCode"], 200)

    def test_response_includes_deleted_id(self):
        lid = MOCK_PROPERTY_LINK["link_id"]
        body = _body(_delete_property_link(link_id=lid))
        self.assertEqual(body["deleted"], lid)

    def test_returns_403_when_wrong_document(self):
        wrong_link = {**MOCK_PROPERTY_LINK, "document_id": "other-doc"}
        self.mock_links.get_item.return_value = {"Item": wrong_link}
        resp = _delete_property_link(link_id=MOCK_PROPERTY_LINK["link_id"])
        self.assertEqual(resp["statusCode"], 403)

    def test_returns_403_when_wrong_parent(self):
        wrong_link = {**MOCK_PROPERTY_LINK, "parent_id": "other-property"}
        self.mock_links.get_item.return_value = {"Item": wrong_link}
        resp = _delete_property_link(link_id=MOCK_PROPERTY_LINK["link_id"])
        self.assertEqual(resp["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
