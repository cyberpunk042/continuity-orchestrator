"""
Email Adapter — Send emails via Resend API.

This adapter sends transactional emails using the Resend service.
API keys are expected in environment variables.

## Configuration

- RESEND_API_KEY: Your Resend API key
- RESEND_FROM_EMAIL: The sender email (must be verified in Resend)

## Usage

Emails are sent to operator_email from state.integrations.routing.

## Template Support

If a template is resolved, its content is used as the email body.
The first line of the template (if it starts with #) is used as subject.
"""

from __future__ import annotations

import logging
import os
import re

from ..models.receipt import Receipt
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)

# Optional resend import — graceful degradation
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    resend = None


class ResendEmailAdapter(Adapter):
    """
    Real email adapter using Resend API.
    
    Requires RESEND_API_KEY environment variable.
    """
    
    def __init__(self):
        self.api_key = os.environ.get("RESEND_API_KEY")
        self.from_email = os.environ.get("RESEND_FROM_EMAIL", "noreply@continuity.local")
        
        if self.api_key and RESEND_AVAILABLE:
            resend.api_key = self.api_key
    
    @property
    def name(self) -> str:
        return "email"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if Resend is available and configured."""
        if not RESEND_AVAILABLE:
            logger.warning("resend package not installed, email adapter disabled")
            return False
        
        if not self.api_key:
            logger.warning("RESEND_API_KEY not set, email adapter disabled")
            return False
        
        try:
            return context.state.integrations.enabled_adapters.email
        except AttributeError:
            return True
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate email can be sent."""
        recipients = self._get_recipients(context)

        if not recipients:
            channel = context.action.channel
            return False, f"No email recipients for channel '{channel}'"

        # Basic format check on all recipients
        for email in recipients:
            if "@" not in email:
                return False, f"Invalid email format: {email}"

        return True, None

    def _get_recipients(self, context: ExecutionContext) -> list:
        """
        Resolve recipient list based on action channel.

        - operator    → [operator_email]
        - custodians  → custodian_emails list
        - subscribers → subscriber_emails list
        - anything else → [operator_email] (safe fallback)
        """
        channel = context.action.channel

        if channel == "custodians":
            return [e for e in (context.routing.custodian_emails or []) if e]
        elif channel == "subscribers":
            return [e for e in (context.routing.subscriber_emails or []) if e]
        else:
            # "operator" or any unrecognized channel → operator
            email = context.routing.operator_email
            return [email] if email else []

    def execute(self, context: ExecutionContext) -> Receipt:
        """Send email via Resend to all resolved recipients."""
        recipients = self._get_recipients(context)

        if not recipients:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="no_recipients",
                error_message=f"No email recipients for channel '{context.action.channel}'",
                retryable=False,
            )

        # Extract subject and body from template
        subject, body = self._parse_template(context)

        # Build styled HTML
        stage = context.escalation.state
        html_body = self._build_styled_email(subject, body, stage, context)

        sent_ids = []
        errors = []

        for to_email in recipients:
            try:
                result = resend.Emails.send({
                    "from": self.from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                    "text": body,
                    "headers": {
                        "X-Continuity-Tick-ID": context.tick_id,
                        "X-Continuity-Stage": stage,
                        "X-Continuity-Action": context.action.id,
                        # Anti-spam: mark as automated/transactional
                        "Precedence": "bulk",
                        "X-Auto-Response-Suppress": "All",
                    },
                })

                email_id = result.get("id") if isinstance(result, dict) else str(result)
                sent_ids.append({"to": to_email, "id": email_id})
                logger.info(f"Email sent to {to_email}: {email_id}")

            except Exception as e:
                logger.error(f"Resend email failed for {to_email}: {e}")
                errors.append({"to": to_email, "error": str(e)})

        # Determine result
        if sent_ids and not errors:
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=sent_ids[0]["id"] if len(sent_ids) == 1 else "multi",
                details={
                    "recipients": sent_ids,
                    "subject": subject,
                    "template": context.action.template,
                },
            )
        elif sent_ids and errors:
            # Partial success — still mark as OK (some delivered)
            logger.warning(f"Partial email delivery: {len(sent_ids)} ok, {len(errors)} failed")
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id="partial",
                details={
                    "recipients": sent_ids,
                    "errors": errors,
                    "subject": subject,
                    "template": context.action.template,
                },
            )
        else:
            # All failed
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="resend_error",
                error_message=f"All {len(errors)} sends failed: {errors[0]['error']}",
                retryable=True,
            )

    def _parse_template(self, context: ExecutionContext) -> tuple:
        """
        Parse template content into subject and body.

        If template starts with a # header, use it as subject.
        Otherwise, generate a default subject.

        Returns: (subject, body)
        """
        template_content = context.template_content

        if not template_content:
            # No template, generate default content
            subject = f"[{context.escalation.state}] Continuity Alert"
            body = f"Escalation stage: {context.escalation.state}\n"
            body += f"Time to deadline: {context.timer.time_to_deadline_minutes} minutes\n"
            return subject, body

        lines = template_content.strip().split("\n")

        # Check if first line is a markdown header
        if lines[0].startswith("# "):
            subject = lines[0][2:].strip()
            body = "\n".join(lines[1:]).strip()
        elif lines[0].startswith("## "):
            subject = lines[0][3:].strip()
            body = "\n".join(lines[1:]).strip()
        else:
            # No header, use default subject
            subject = f"[{context.escalation.state}] Continuity Alert"
            body = template_content

        return subject, body

    # ── Stage-aware visual themes ──────────────────────────────────
    STAGE_THEMES = {
        "OK": {
            "accent": "#22c55e",
            "bg": "#f0fdf4",
            "border": "#86efac",
            "icon": "✅",
            "label": "All Clear",
        },
        "REMIND_1": {
            "accent": "#6366f1",
            "bg": "#eef2ff",
            "border": "#a5b4fc",
            "icon": "⏰",
            "label": "Scheduled Reminder",
        },
        "REMIND_2": {
            "accent": "#f59e0b",
            "bg": "#fffbeb",
            "border": "#fcd34d",
            "icon": "⚠️",
            "label": "Urgent — Action Required",
        },
        "PRE_RELEASE": {
            "accent": "#ef4444",
            "bg": "#fef2f2",
            "border": "#fca5a5",
            "icon": "🔴",
            "label": "Final Warning",
        },
        "PARTIAL": {
            "accent": "#dc2626",
            "bg": "#fef2f2",
            "border": "#f87171",
            "icon": "💀",
            "label": "Disclosure Active",
        },
        "FULL": {
            "accent": "#991b1b",
            "bg": "#fef2f2",
            "border": "#dc2626",
            "icon": "💀",
            "label": "Full Disclosure",
        },
    }

    def _build_styled_email(
        self,
        subject: str,
        body_markdown: str,
        stage: str,
        context: ExecutionContext,
    ) -> str:
        """Build a complete, styled HTML email with stage-aware theming."""
        theme = self.STAGE_THEMES.get(stage, self.STAGE_THEMES["REMIND_1"])
        body_html = self._markdown_to_html(body_markdown)

        # Time display
        ttd = context.timer.time_to_deadline_minutes or 0
        if ttd > 0:
            hours = ttd // 60
            mins = ttd % 60
            time_display = f"{hours}h {mins}m remaining"
        else:
            overdue = context.timer.overdue_minutes or 0
            time_display = f"⚠️ {overdue}m overdue"

        # Urgency bar width (visual indicator)
        if ttd > 360:
            bar_pct = 100
        elif ttd > 0:
            bar_pct = max(5, int((ttd / 360) * 100))
        else:
            bar_pct = 0

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

        <!-- Header -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{theme['bg']};border-radius:12px 12px 0 0;border-top:4px solid {theme['accent']};">
            <tr><td style="padding:24px 28px 16px;">
              <div style="font-size:28px;line-height:1;">{theme['icon']}</div>
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:{theme['accent']};font-weight:700;margin-top:8px;">{theme['label']}</div>
              <div style="font-size:20px;font-weight:700;color:#1a1a2e;margin-top:6px;line-height:1.3;">{subject}</div>
            </td></tr>
          </table>
        </td></tr>

        <!-- Urgency bar -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;">
            <tr><td style="padding:12px 28px;">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600;">{time_display}</div>
              <div style="background:#e2e8f0;border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:{theme['accent']};width:{bar_pct}%;height:6px;border-radius:4px;transition:width 0.3s;"></div>
              </div>
            </td></tr>
          </table>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
            <tr><td style="padding:24px 28px;color:#334155;font-size:15px;line-height:1.7;">
              {body_html}
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;border-radius:0 0 12px 12px;">
            <tr><td style="padding:16px 28px;">
              <div style="font-size:11px;color:#94a3b8;line-height:1.6;">
                Automated message from <strong>{context.state.meta.project}</strong><br>
                Tick {context.tick_id} • Stage {stage}<br>
                This is a system notification — do not reply.
              </div>
            </td></tr>
          </table>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    def _markdown_to_html(self, markdown: str) -> str:
        """
        Convert markdown to email-safe HTML.
        """
        html = markdown

        # Headers
        html = re.sub(r'^### (.+)$', r'<h3 style="font-size:14px;font-weight:700;color:#1e293b;margin:16px 0 8px;">\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2 style="font-size:16px;font-weight:700;color:#1e293b;margin:18px 0 8px;">\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1 style="font-size:18px;font-weight:700;color:#1e293b;margin:20px 0 10px;">\1</h1>', html, flags=re.MULTILINE)

        # Bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

        # Links
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" style="color:#6366f1;">\1</a>', html)

        # Horizontal rules
        html = re.sub(r'^---+$', '<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">', html, flags=re.MULTILINE)

        # Paragraphs
        html = re.sub(r'\n\n', '</p><p style="margin:0 0 12px;">', html)
        html = f'<p style="margin:0 0 12px;">{html}</p>'

        # Line breaks
        html = html.replace('\n', '<br>')

        return html

