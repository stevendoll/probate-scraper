"""
S3 helpers for the probate scraper.

Responsibilities:
  - doc_key(): build a deterministic S3 object key for a scraped document.
  - upload_local_file(): upload a file already on the local filesystem to S3.
  - fetch_and_upload(): download a document URL (honouring the Selenium session
    cookies for sites that require authentication) and upload it to S3.
    Returns the S3 URI on success or None on failure.

Key format: documents/{location_code}/{doc_number}{ext}
  e.g.      documents/CollinTx/20240001234.pdf
"""

import logging
import mimetypes
import os
from urllib.parse import urlparse

import boto3
import requests

log = logging.getLogger(__name__)

_s3 = boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

_FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Explicit content-type → extension overrides (mimetypes.guess_extension can
# return surprising values on different platforms, e.g. ".pdf2" instead of ".pdf")
_CT_OVERRIDE: dict[str, str] = {
    "application/pdf":   ".pdf",
    "image/jpeg":        ".jpg",
    "image/jpg":         ".jpg",
    "image/png":         ".png",
    "image/tiff":        ".tif",
    "image/gif":         ".gif",
    "image/webp":        ".webp",
    # application/octet-stream is intentionally excluded so the URL path
    # extension fallback can be tried before defaulting to ".bin"
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ext_from_response(resp: "requests.Response", url: str) -> str:
    """
    Infer a file extension from the HTTP response Content-Type header.

    Resolution order:
      1. Known content-type override (_CT_OVERRIDE) — highest confidence.
      2. URL path extension — often more specific than stdlib mimetypes for
         generic types like application/octet-stream.
      3. stdlib mimetypes.guess_extension.
      4. Hard-coded '.bin' fallback.
    """
    ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()

    # 1. Explicit override
    if ct in _CT_OVERRIDE:
        return _CT_OVERRIDE[ct]

    # 2. URL path extension (tried before mimetypes so that a URL like
    #    ".../record.tif" beats mimetypes' guess for octet-stream)
    url_ext = os.path.splitext(urlparse(url).path)[1].lower()
    if url_ext and len(url_ext) <= 5:
        return url_ext

    # 3. stdlib guess
    guessed = mimetypes.guess_extension(ct, strict=False) if ct else None
    if guessed and len(guessed) <= 5:
        return guessed

    return ".bin"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def doc_key(location_code: str, doc_number: str, ext: str = ".pdf") -> str:
    """
    Return the S3 object key for a document.

    Format:  documents/{location_code}/{safe_doc_number}{ext}
    Example: documents/CollinTx/20240001234.pdf
    """
    safe_doc = doc_number.replace("/", "-").replace(" ", "_")
    return f"documents/{location_code}/{safe_doc}{ext}"


def upload_local_file(
    local_path: str,
    bucket: str,
    location_code: str,
    doc_number: str,
) -> str | None:
    """
    Upload a file already present on the local filesystem to *bucket*.

    Uses the file extension of *local_path* to build the S3 key and guesses the
    Content-Type via stdlib mimetypes.

    Returns ``s3://{bucket}/{key}`` on success, or None on any failure.
    Returns None immediately when *bucket* is empty or *local_path* is not a file.
    """
    if not bucket:
        return None
    if not os.path.isfile(local_path):
        log.warning("upload_local_file: path not found: %s", local_path)
        return None

    ext = os.path.splitext(local_path)[1].lower() or ".bin"
    key = doc_key(location_code, doc_number, ext)
    content_type, _ = mimetypes.guess_type(local_path)
    content_type = content_type or "application/octet-stream"

    try:
        with open(local_path, "rb") as fh:
            _s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=fh.read(),
                ContentType=content_type,
            )
    except Exception as exc:
        log.warning(
            "S3 upload of local file failed for %s → s3://%s/%s: %s",
            local_path, bucket, key, exc,
        )
        return None

    s3_uri = f"s3://{bucket}/{key}"
    log.info("Local file uploaded: %s → %s", local_path, s3_uri)
    return s3_uri


def fetch_and_upload(
    pdf_url: str,
    bucket: str,
    location_code: str,
    doc_number: str,
    selenium_cookies: list | None = None,
    timeout: int = 30,
) -> str | None:
    """
    Download *pdf_url* (forwarding the Selenium session cookies for auth) and
    upload the content to *bucket* under the key from doc_key().

    Returns ``s3://{bucket}/{key}`` on success, or None on any failure.
    Returns None immediately when *bucket* is empty (S3 upload not configured).

    Args:
        pdf_url:          Absolute URL of the document to download.
        bucket:           S3 bucket name (DOCUMENTS_BUCKET env var).
        location_code:    Location FK used in the S3 key prefix.
        doc_number:       Document identifier used as the S3 object name.
        selenium_cookies: List of cookie dicts from driver.get_cookies().
                          Each dict must have at least "name" and "value" keys.
        timeout:          HTTP request timeout in seconds.
    """
    if not bucket:
        return None

    cookies = {c["name"]: c["value"] for c in (selenium_cookies or [])}
    headers = {"User-Agent": _FALLBACK_USER_AGENT}

    try:
        resp = requests.get(
            pdf_url,
            cookies=cookies,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Document download failed for %s: %s", pdf_url, exc)
        return None

    ext = _ext_from_response(resp, pdf_url)
    key = doc_key(location_code, doc_number, ext)
    content_type = (
        resp.headers.get("Content-Type", "application/octet-stream")
        .split(";")[0]
        .strip()
    )

    try:
        _s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=resp.content,
            ContentType=content_type,
        )
    except Exception as exc:
        log.warning("S3 upload failed for %s → s3://%s/%s: %s", pdf_url, bucket, key, exc)
        return None

    s3_uri = f"s3://{bucket}/{key}"
    log.info("Document uploaded: %s → %s (%d bytes)", pdf_url, s3_uri, len(resp.content))
    return s3_uri
