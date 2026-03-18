"""
REMOVED — SES event processor.

This Lambda (SesEventsFunction) has been deleted from template.yaml as part
of the SES → Resend migration.  Email delivery events are now received via
the Resend webhook at:

  POST /real-estate/probate-leads/resend/webhook

handled by src/api/routers/resend_webhook.py.
"""
