"""
Unit tests for src/scraper/s3.py

All external calls (boto3, requests) are mocked — no AWS credentials or
network access required.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Make the scraper package importable and stub out boto3 before import
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scraper"))

# Stub out boto3 so no real AWS client is created at module-import time
boto3_mock = MagicMock()
sys.modules.setdefault("boto3", boto3_mock)

import s3 as s3_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(
    status_code: int = 200,
    content: bytes = b"%PDF-1.4 test",
    content_type: str = "application/pdf",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# doc_key
# ---------------------------------------------------------------------------

class TestDocKey(unittest.TestCase):

    def test_standard_format(self):
        key = s3_mod.doc_key("CollinTx", "20240001234", ".pdf")
        self.assertEqual(key, "documents/CollinTx/20240001234.pdf")

    def test_default_extension_is_pdf(self):
        key = s3_mod.doc_key("CollinTx", "20240001234")
        self.assertTrue(key.endswith(".pdf"))

    def test_slashes_in_doc_number_replaced(self):
        key = s3_mod.doc_key("CollinTx", "2024/001", ".pdf")
        self.assertNotIn("/001", key)
        self.assertIn("-001", key)

    def test_spaces_in_doc_number_replaced(self):
        key = s3_mod.doc_key("CollinTx", "2024 001", ".pdf")
        self.assertIn("_001", key)

    def test_location_code_in_prefix(self):
        key = s3_mod.doc_key("DallasTx", "999", ".pdf")
        self.assertTrue(key.startswith("documents/DallasTx/"))


# ---------------------------------------------------------------------------
# _ext_from_response
# ---------------------------------------------------------------------------

class TestExtFromResponse(unittest.TestCase):

    def _resp(self, ct: str) -> MagicMock:
        r = MagicMock()
        r.headers = {"Content-Type": ct}
        return r

    def test_pdf(self):
        ext = s3_mod._ext_from_response(self._resp("application/pdf"), "https://x.com/doc")
        self.assertEqual(ext, ".pdf")

    def test_jpeg(self):
        ext = s3_mod._ext_from_response(self._resp("image/jpeg"), "https://x.com/img")
        self.assertEqual(ext, ".jpg")

    def test_png(self):
        ext = s3_mod._ext_from_response(self._resp("image/png"), "https://x.com/img")
        self.assertEqual(ext, ".png")

    def test_content_type_with_charset_stripped(self):
        ext = s3_mod._ext_from_response(
            self._resp("application/pdf; charset=utf-8"), "https://x.com/doc"
        )
        self.assertEqual(ext, ".pdf")

    def test_fallback_to_url_extension(self):
        r = MagicMock()
        r.headers = {"Content-Type": "application/octet-stream"}
        ext = s3_mod._ext_from_response(r, "https://x.com/record.tif")
        self.assertEqual(ext, ".tif")

    def test_final_fallback_is_bin(self):
        r = MagicMock()
        r.headers = {}
        ext = s3_mod._ext_from_response(r, "https://x.com/nodothere")
        self.assertEqual(ext, ".bin")


# ---------------------------------------------------------------------------
# fetch_and_upload
# ---------------------------------------------------------------------------

class TestFetchAndUpload(unittest.TestCase):

    def setUp(self):
        # Reset the module-level _s3 client to a fresh mock before each test
        self._s3_client = MagicMock()
        s3_mod._s3 = self._s3_client
        # test_scraper.py replaces sys.modules["s3"] with a MagicMock at load
        # time (before scraper.py can import it).  That makes @patch("s3.requests.get")
        # patch the wrong object.  Restore the real module here so the patch
        # decorator resolves against the real module during every test method.
        sys.modules["s3"] = s3_mod

    @patch("s3.requests.get")
    def test_returns_s3_uri_on_success(self, mock_get):
        mock_get.return_value = _mock_response()

        result = s3_mod.fetch_and_upload(
            "https://site.com/doc/123",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="20240001234",
        )

        self.assertEqual(result, "s3://my-bucket/documents/CollinTx/20240001234.pdf")
        self._s3_client.put_object.assert_called_once()

    @patch("s3.requests.get")
    def test_correct_s3_key_used(self, mock_get):
        mock_get.return_value = _mock_response(content_type="image/jpeg")

        s3_mod.fetch_and_upload(
            "https://site.com/img/456",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="456",
        )

        call_kwargs = self._s3_client.put_object.call_args[1]
        self.assertEqual(call_kwargs["Key"], "documents/CollinTx/456.jpg")
        self.assertEqual(call_kwargs["Bucket"], "my-bucket")

    @patch("s3.requests.get")
    def test_forwards_selenium_cookies(self, mock_get):
        mock_get.return_value = _mock_response()

        cookies = [
            {"name": "session", "value": "abc123"},
            {"name": "token",   "value": "xyz"},
        ]
        s3_mod.fetch_and_upload(
            "https://site.com/doc/789",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="789",
            selenium_cookies=cookies,
        )

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["cookies"], {"session": "abc123", "token": "xyz"})

    @patch("s3.requests.get")
    def test_returns_none_when_bucket_is_empty(self, mock_get):
        result = s3_mod.fetch_and_upload(
            "https://site.com/doc/123",
            bucket="",
            location_code="CollinTx",
            doc_number="123",
        )
        self.assertIsNone(result)
        mock_get.assert_not_called()

    @patch("s3.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        mock_get.return_value = _mock_response(status_code=403)

        result = s3_mod.fetch_and_upload(
            "https://site.com/doc/403",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="403",
        )
        self.assertIsNone(result)
        self._s3_client.put_object.assert_not_called()

    @patch("s3.requests.get")
    def test_returns_none_on_network_error(self, mock_get):
        mock_get.side_effect = ConnectionError("unreachable")

        result = s3_mod.fetch_and_upload(
            "https://site.com/doc/net",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="net",
        )
        self.assertIsNone(result)

    @patch("s3.requests.get")
    def test_returns_none_on_s3_upload_error(self, mock_get):
        mock_get.return_value = _mock_response()
        self._s3_client.put_object.side_effect = Exception("S3 unavailable")

        result = s3_mod.fetch_and_upload(
            "https://site.com/doc/s3err",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="s3err",
        )
        self.assertIsNone(result)

    @patch("s3.requests.get")
    def test_no_cookies_when_none_provided(self, mock_get):
        mock_get.return_value = _mock_response()

        s3_mod.fetch_and_upload(
            "https://site.com/doc/nocookies",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="nocookies",
            selenium_cookies=None,
        )

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["cookies"], {})

    @patch("s3.requests.get")
    def test_content_type_set_on_upload(self, mock_get):
        mock_get.return_value = _mock_response(content_type="image/png")

        s3_mod.fetch_and_upload(
            "https://site.com/img/ct",
            bucket="my-bucket",
            location_code="CollinTx",
            doc_number="ct",
        )

        call_kwargs = self._s3_client.put_object.call_args[1]
        self.assertEqual(call_kwargs["ContentType"], "image/png")


if __name__ == "__main__":
    unittest.main()
