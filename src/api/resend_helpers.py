"""
Resend webhook verification helper.

Mirrors stripe_helpers.py — keeps the resend import isolated so tests can
mock it without pulling in the full SDK.

construct_resend_event(payload, headers) -> (event_dict | None, error_str | None)
"""

import json
import logging
import os

log = logging.getLogger(__name__)


def construct_resend_event(
    payload: bytes,
    headers: dict,
) -> tuple[dict | None, str | None]:
    """
    Verify and deserialize a Resend webhook payload.

    Returns (event, None) on success or (None, error_message) on failure.

    If RESEND_WEBHOOK_SECRET is not set (local dev / unit tests), signature
    verification is skipped and the raw payload is parsed as JSON.

    Resend uses svix for webhook signatures; the relevant headers are:
      svix-id, svix-timestamp, svix-signature
    """
    webhook_secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")

    if not webhook_secret:
        log.warning(
            "RESEND_WEBHOOK_SECRET not set — skipping signature verification "
            "(set this in production)"
        )
        try:
            return json.loads(payload), None
        except (json.JSONDecodeError, TypeError) as exc:
            return None, f"Invalid JSON payload: {exc}"

    try:
        from svix.webhooks import Webhook, WebhookVerificationError  # noqa: PLC0415

        wh  = Webhook(webhook_secret)
        msg = wh.verify(payload, headers)
        # svix returns the parsed dict directly
        if isinstance(msg, (bytes, str)):
            msg = json.loads(msg)
        return dict(msg), None
    except Exception as exc:
        return None, str(exc)
