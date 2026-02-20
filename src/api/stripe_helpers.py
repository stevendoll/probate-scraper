"""
Stripe webhook verification helper.

Keeps the Stripe import isolated so tests can mock it without pulling in
the full Stripe SDK.

construct_stripe_event(payload, sig_header) -> (event_dict | None, error_str | None)
"""

import json
import logging
import os

log = logging.getLogger(__name__)


def construct_stripe_event(
    payload: bytes,
    sig_header: str,
) -> tuple[dict | None, str | None]:
    """
    Verify and deserialize a Stripe webhook payload.

    Returns (event, None) on success or (None, error_message) on failure.

    If STRIPE_WEBHOOK_SECRET is not set (local dev / unit tests), signature
    verification is skipped and the raw payload is parsed as JSON.
    """
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        log.warning(
            "STRIPE_WEBHOOK_SECRET not set — skipping signature verification "
            "(set this in production)"
        )
        try:
            return json.loads(payload), None
        except (json.JSONDecodeError, TypeError) as exc:
            return None, f"Invalid JSON payload: {exc}"

    try:
        import stripe  # noqa: PLC0415

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return dict(event), None
    except Exception as exc:  # stripe.error.SignatureVerificationError + others
        return None, str(exc)
