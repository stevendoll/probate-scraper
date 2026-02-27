"""
ParseDocumentFunction — Lambda handler.

Route (registered in template.yaml):
  POST /real-estate/probate-leads/leads/{lead_id}/parse-document

Flow:
  1. Look up the lead by doc_number (lead_id) in DynamoDB.
  2. Verify it has a doc_s3_uri pointing to the stored PDF.
  3. Fetch the PDF bytes from S3.
  4. Send the PDF to Amazon Bedrock (Claude 3 Haiku) via the Converse API
     together with a structured-extraction prompt.
  5. Parse the JSON response from Bedrock.
  6. Persist the extracted fields back to the leads table via UpdateItem.
  7. Return the updated lead as JSON.

Environment variables:
  DYNAMO_TABLE_NAME   — leads table (default: leads)
  DOCUMENTS_BUCKET    — S3 bucket where PDFs are stored
  BEDROCK_MODEL_ID    — Bedrock model ID (default: anthropic.claude-3-haiku-20240307-v1:0)
  AWS_DEFAULT_REGION  — AWS region (injected by Lambda runtime)
"""

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

from prompt import SYSTEM_PROMPT, USER_PROMPT

logger = Logger(service="parse-document")
api    = APIGatewayRestResolver()

# ---------------------------------------------------------------------------
# AWS clients (module-level so they are reused across warm invocations)
# ---------------------------------------------------------------------------

_region       = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_table_name   = os.environ.get("DYNAMO_TABLE_NAME", "leads")
_bucket_name  = os.environ.get("DOCUMENTS_BUCKET", "")
_model_id     = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0",
)

_dynamodb = boto3.resource("dynamodb", region_name=_region)
_table    = _dynamodb.Table(_table_name)
_s3       = boto3.client("s3", region_name=_region)
_bedrock  = boto3.client("bedrock-runtime", region_name=_region)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s3_uri_to_bucket_key(s3_uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key`` into ``(bucket, key)``."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Not an S3 URI: {s3_uri!r}")
    bucket = parsed.netloc
    key    = parsed.path.lstrip("/")
    return bucket, key


def _fetch_pdf_bytes(s3_uri: str) -> bytes:
    """Download the PDF from S3 and return its raw bytes."""
    bucket, key = _s3_uri_to_bucket_key(s3_uri)
    response = _s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _call_bedrock(pdf_bytes: bytes) -> dict:
    """
    Send the PDF to Bedrock via the Converse API and return the parsed JSON dict.

    Uses a document block with Amazon Nova Pro, which supports document blocks
    natively via its cross-region inference profile.  Anthropic Claude models
    (Haiku, Sonnet, etc.) silently ignore the document bytes even when the API
    call succeeds, returning "no document attached" responses.

    The model is expected to return a single JSON object — no markdown fences.
    If the response contains a fenced code block we strip the fences first.
    """
    response = _bedrock.converse(
        modelId=_model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "document": {
                            "format": "pdf",
                            "name":   "probate-filing",
                            "source": {"bytes": pdf_bytes},
                        },
                    },
                    {"text": USER_PROMPT},
                ],
            }
        ],
        inferenceConfig={
            "maxTokens": 2048,
            "temperature": 0,
        },
    )

    raw_text = response["output"]["message"]["content"][0]["text"].strip()

    # 1. Try parsing as-is (ideal: model returned pure JSON)
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # 2. Strip optional ```json ... ``` fences then retry
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw_text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Slice from the first '{' to the last '}' — handles preamble/postamble prose
    start = raw_text.find("{")
    end   = raw_text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw_text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON in model response: {raw_text[:300]!r}")


def _persist_parsed_fields(lead_id: str, parsed: dict, model_id: str, error: str = "") -> None:
    """
    Write the extracted fields (and metadata) back to the leads table.
    Uses UpdateItem so we only touch the parsed columns.
    """
    now = _now_iso()
    _table.update_item(
        Key={"doc_number": lead_id},
        UpdateExpression=(
            "SET parsed_at = :pa, parsed_model = :pm, parse_error = :pe,"
            " deceased_name = :dn, deceased_dob = :db, deceased_dod = :dd,"
            " deceased_last_address = :da, people = :pp,"
            " real_property = :rp, summary = :su"
        ),
        ExpressionAttributeValues={
            ":pa": now,
            ":pm": model_id,
            ":pe": error,
            ":dn": parsed.get("deceased_name") or "",
            ":db": parsed.get("deceased_dob")  or "",
            ":dd": parsed.get("deceased_dod")  or "",
            ":da": parsed.get("deceased_last_address") or "",
            ":pp": parsed.get("people")        or [],
            ":rp": parsed.get("real_property") or [],
            ":su": parsed.get("summary")       or "",
        },
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@api.post("/real-estate/probate-leads/leads/<lead_id>/parse-document")
def parse_document(lead_id: str):
    # 1. Fetch the lead
    result = _table.get_item(Key={"doc_number": lead_id})
    item   = result.get("Item")
    if not item:
        return {"error": f"Lead not found: {lead_id!r}"}, 404

    doc_s3_uri = item.get("doc_s3_uri", "")
    if not doc_s3_uri:
        return {
            "error": (
                f"Lead {lead_id!r} has no doc_s3_uri. "
                "The document must be scraped and uploaded to S3 first."
            )
        }, 422

    # 2. Fetch the PDF from S3
    try:
        pdf_bytes = _fetch_pdf_bytes(doc_s3_uri)
    except Exception as exc:
        logger.error("S3 fetch failed: %s", exc)
        err_msg = f"S3 fetch failed: {exc}"
        _persist_parsed_fields(lead_id, {}, _model_id, error=err_msg)
        return {"error": err_msg}, 500

    # 3. Call Bedrock
    try:
        parsed = _call_bedrock(pdf_bytes)
    except Exception as exc:
        logger.error("Bedrock call failed: %s", exc)
        err_msg = f"Bedrock call failed: {exc}"
        _persist_parsed_fields(lead_id, {}, _model_id, error=err_msg)
        return {"error": err_msg}, 500

    # 4. Persist parsed fields
    try:
        _persist_parsed_fields(lead_id, parsed, _model_id)
    except Exception as exc:
        logger.error("DynamoDB update failed: %s", exc)
        return {"error": f"DynamoDB update failed: {exc}"}, 500

    # 5. Return the updated lead
    updated = _table.get_item(Key={"doc_number": lead_id}).get("Item", item)

    return {
        "docNumber":           updated.get("doc_number", ""),
        "docS3Uri":            updated.get("doc_s3_uri", ""),
        "parsedAt":            updated.get("parsed_at", ""),
        "parsedModel":         updated.get("parsed_model", ""),
        "deceasedName":        updated.get("deceased_name", ""),
        "deceasedDob":         updated.get("deceased_dob", ""),
        "deceasedDod":         updated.get("deceased_dod", ""),
        "deceasedLastAddress": updated.get("deceased_last_address", ""),
        "people":              updated.get("people", []),
        "realProperty":        updated.get("real_property", []),
        "summary":             updated.get("summary", ""),
        "parseError":          updated.get("parse_error", ""),
    }, 200


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@logger.inject_lambda_context(log_event=False)
def handler(event: dict, context: LambdaContext) -> dict:
    return api.resolve(event, context)
