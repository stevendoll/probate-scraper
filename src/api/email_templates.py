"""
Advanced email template system using Jinja2 for customer journey emails.

Supports multiple email templates for different customer journeys:
- coming_soon: waitlist invitation and confirmation emails
- prospect: existing prospect lead emails
- free_trial: trial invitation and expiration emails
"""

import logging
import os
import random
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, Template

log = logging.getLogger(__name__)

FROM_EMAIL = os.environ.get("FROM_EMAIL", "")
UI_BASE_URL = os.environ.get("UI_BASE_URL", "http://localhost:3001")
SES_CONFIGURATION_SET = os.environ.get("SES_CONFIGURATION_SET", "")

# Template directory
TEMPLATES_DIR = Path(__file__).parent / "templates" / "journeys"


class EmailTemplateManager:
    """Manages Jinja2 email templates for customer journeys."""

    def __init__(self, templates_dir: Path = TEMPLATES_DIR):
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=True,
        )

    def _load_random_line(self, filename: str) -> str:
        """Load a random line from a text file in templates directory."""
        try:
            file_path = self.templates_dir / filename
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                return random.choice(lines) if lines else ""
        except FileNotFoundError:
            log.error("Template file not found: %s", filename)
            return ""

    def get_template_context(
        self,
        journey_type: str,
        journey_step: str,
        user_data: Dict,
        **kwargs
    ) -> Dict:
        """Build template context for a specific journey step."""
        # Base context available to all templates
        context = {
            "user": user_data,
            "ui_base_url": UI_BASE_URL,
            "journey_type": journey_type,
            "journey_step": journey_step,
        }

        # Add any additional context
        context.update(kwargs)

        # Journey-specific context
        if journey_type == "coming_soon":
            if journey_step == "invited_to_waitlist":
                context.update({
                    "waitlist_signup_url": f"{UI_BASE_URL}/waitlist/signup",
                    "cta_text": "Join Our Waitlist",
                })
            elif journey_step == "accepted_waitlist":
                context.update({
                    "success_message": "You're on the waitlist! We'll notify you when we launch.",
                    "countdown_days": 15,  # Default countdown
                })
            elif journey_step == "invited_to_join":
                context.update({
                    "subscribe_url": kwargs.get("subscribe_url", ""),
                    "price": user_data.get("offered_price", 19),
                })

        elif journey_type == "free_trial":
            if journey_step == "invited_to_trial":
                context.update({
                    "trial_signup_url": kwargs.get("trial_signup_url", ""),
                    "trial_days": 14,  # Default trial length
                })
            elif journey_step == "trialing":
                context.update({
                    "trial_expires_on": user_data.get("trial_expires_on", ""),
                    "subscribe_url": kwargs.get("subscribe_url", ""),
                    "price": user_data.get("offered_price", 19),
                })
            elif journey_step == "trial_expired":
                context.update({
                    "subscribe_url": kwargs.get("subscribe_url", ""),
                    "price": user_data.get("offered_price", 19),
                })

        elif journey_type == "prospect":
            # Existing prospect journey
            context.update({
                "leads": kwargs.get("leads", []),
                "subscribe_url": kwargs.get("subscribe_url", ""),
                "unsubscribe_url": kwargs.get("unsubscribe_url", ""),
                "price": user_data.get("offered_price", 19),
            })

        return context

    def get_email_metadata(self, journey_type: str, journey_step: str) -> Dict:
        """Get email metadata (subject, from name, etc.) for a journey step."""
        metadata = {}

        # Load subject line based on journey
        if journey_type == "coming_soon":
            if journey_step == "invited_to_waitlist":
                metadata["subject"] = self._load_random_line("subjects/coming_soon_invite.txt")
            elif journey_step == "accepted_waitlist":
                metadata["subject"] = self._load_random_line("subjects/coming_soon_accepted.txt")
            elif journey_step == "invited_to_join":
                metadata["subject"] = self._load_random_line("subjects/coming_soon_launch.txt")

        elif journey_type == "free_trial":
            if journey_step == "invited_to_trial":
                metadata["subject"] = self._load_random_line("subjects/free_trial_invite.txt")
            elif journey_step == "trialing":
                metadata["subject"] = self._load_random_line("subjects/free_trial_reminder.txt")
            elif journey_step == "trial_expired":
                metadata["subject"] = self._load_random_line("subjects/free_trial_expired.txt")

        elif journey_type == "prospect":
            metadata["subject"] = self._load_random_line("subjects/prospect.txt")

        # Common metadata
        metadata.update({
            "from_name": self._load_random_line("from_names.txt"),
            "preheader": self._load_random_line("preheaders.txt"),
        })

        return metadata

    def render_email(
        self,
        journey_type: str,
        journey_step: str,
        user_data: Dict,
        template_variant: str = "default",
        **kwargs
    ) -> Dict[str, str]:
        """Render HTML and text email for a journey step.

        Returns:
            Dict with keys: html_body, text_body, subject, from_name
        """
        # Get template context
        context = self.get_template_context(journey_type, journey_step, user_data, **kwargs)

        # Get email metadata
        metadata = self.get_email_metadata(journey_type, journey_step)

        # Apply personalization to subject if first name available
        subject = metadata.get("subject", "")
        if context["user"].get("first_name") and "{first_name}" in subject:
            subject = subject.replace("{first_name}", context["user"]["first_name"])

        # Add metadata to context
        context.update(metadata)

        # Template paths
        html_template_path = f"{journey_type}/{journey_step}_{template_variant}.html"
        text_template_path = f"{journey_type}/{journey_step}_{template_variant}.txt"

        try:
            # Render HTML template
            html_template = self.env.get_template(html_template_path)
            html_body = html_template.render(context)

            # Render text template (fallback to basic text if not found)
            try:
                text_template = self.env.get_template(text_template_path)
                text_body = text_template.render(context)
            except Exception:
                # Fallback to simple text version
                text_body = self._generate_fallback_text(context)

            return {
                "html_body": html_body,
                "text_body": text_body,
                "subject": subject,
                "from_name": metadata.get("from_name", ""),
                "preheader": metadata.get("preheader", ""),
            }

        except Exception as exc:
            log.error("Failed to render email template %s/%s: %s", journey_type, journey_step, exc)
            raise

    def _generate_fallback_text(self, context: Dict) -> str:
        """Generate a simple text email when template is not found."""
        journey_type = context.get("journey_type", "")
        journey_step = context.get("journey_step", "")
        user = context.get("user", {})

        if journey_type == "coming_soon":
            if journey_step == "invited_to_waitlist":
                return (f"We're launching soon!\n\n"
                       f"Join our waitlist to be notified when we launch.\n\n"
                       f"Sign up: {context.get('waitlist_signup_url', '')}")

        elif journey_type == "free_trial":
            if journey_step == "invited_to_trial":
                return (f"Try Collin County Probate Leads free for 14 days!\n\n"
                       f"Start your trial: {context.get('trial_signup_url', '')}")

        elif journey_type == "prospect":
            leads = context.get("leads", [])
            price = context.get("price", 19)
            lead_text = ""
            for lead in leads[:5]:  # Show first 5 leads
                grantor = lead.get("grantor", "")
                date = lead.get("recordedDate", "")
                lead_text += f"• {grantor} - {date}\n"

            return (f"Collin County Probate Leads\n\n"
                   f"Recent probate leads:\n{lead_text}\n"
                   f"Subscribe for ${price}/month: {context.get('subscribe_url', '')}")

        return f"Email for {journey_type} {journey_step}"


def send_journey_email(
    to_email: str,
    journey_type: str,
    journey_step: str,
    user_data: Dict,
    token: Optional[str] = None,
    leads: Optional[List] = None,
    template_variant: str = "default",
    **kwargs
) -> None:
    """Send a customer journey email.

    Args:
        to_email: Recipient email address
        journey_type: Type of journey (coming_soon, prospect, free_trial)
        journey_step: Current step in journey
        user_data: User data dict (from User.to_dict())
        token: JWT token for tracking links
        leads: List of lead dicts (for prospect emails)
        template_variant: Template variant (default, a, b, etc.)
        **kwargs: Additional context for templates
    """
    template_manager = EmailTemplateManager()

    # Build context
    context_kwargs = kwargs.copy()
    if token:
        context_kwargs.update({
            "subscribe_url": f"{UI_BASE_URL}/signup?token={token}",
            "unsubscribe_url": f"{UI_BASE_URL}/unsubscribe?token={token}",
        })
    if leads:
        context_kwargs["leads"] = leads

    # Render email
    try:
        rendered = template_manager.render_email(
            journey_type=journey_type,
            journey_step=journey_step,
            user_data=user_data,
            template_variant=template_variant,
            **context_kwargs
        )
    except Exception as exc:
        log.error("Failed to render journey email for %s %s: %s", journey_type, journey_step, exc)
        raise

    # Skip sending if FROM_EMAIL not configured (local dev)
    if not FROM_EMAIL:
        log.info(
            "Journey email (FROM_EMAIL unset — not sent via SES) to=%s journey=%s/%s",
            to_email, journey_type, journey_step
        )
        return

    # Send via SES
    import boto3  # Import only when needed
    ses = boto3.client("ses")
    from_name = rendered["from_name"]
    source_email = f"{from_name} <{FROM_EMAIL}>" if from_name else FROM_EMAIL

    send_kwargs = {
        "Source": source_email,
        "Destination": {"ToAddresses": [to_email]},
        "Message": {
            "Subject": {"Data": rendered["subject"]},
            "Body": {
                "Text": {"Data": rendered["text_body"]},
                "Html": {"Data": rendered["html_body"]},
            },
        },
    }

    if SES_CONFIGURATION_SET:
        send_kwargs["ConfigurationSetName"] = SES_CONFIGURATION_SET
        send_kwargs["Tags"] = [
            {"Name": "user_id", "Value": user_data.get("userId", "")},
            {"Name": "journey_type", "Value": journey_type},
            {"Name": "journey_step", "Value": journey_step},
            {"Name": "template_variant", "Value": template_variant},
        ]

    try:
        ses.send_email(**send_kwargs)
        log.info("Journey email sent to %s: %s/%s", to_email, journey_type, journey_step)
    except Exception as exc:
        log.error("SES send_email failed for %s: %s", to_email, exc)
        raise

    # Log event after successful send
    if user_data.get("userId"):
        from auth_helpers import log_event  # Avoid circular import
        log_event(
            user_id=user_data["userId"],
            event_type="email_sent",
            variant=template_variant,
            email_template=f"{journey_type}_{journey_step}_{template_variant}.html",
            from_name=from_name,
            subject_line=rendered["subject"],
            prospect_token=token or "",
            metadata={
                "to_email": to_email,
                "journey_type": journey_type,
                "journey_step": journey_step,
                "template_variant": template_variant,
            },
        )
