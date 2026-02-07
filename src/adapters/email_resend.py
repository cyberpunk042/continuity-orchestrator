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

import json
import logging
import os
import re
from typing import Optional
from uuid import uuid4

from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt

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
        to_email = context.routing.operator_email
        
        if not to_email:
            return False, "No operator_email configured"
        
        # Basic email format check
        if "@" not in to_email:
            return False, f"Invalid email format: {to_email}"
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Send email via Resend."""
        to_email = context.routing.operator_email
        
        # Extract subject and body from template
        subject, body = self._parse_template(context)
        
        try:
            result = resend.Emails.send({
                "from": self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": self._markdown_to_html(body),
                "text": body,
                "headers": {
                    "X-Continuity-Tick-ID": context.tick_id,
                    "X-Continuity-Stage": context.escalation.state,
                    "X-Continuity-Action": context.action.id,
                },
            })
            
            # Resend returns {"id": "email-id"} on success
            email_id = result.get("id") if isinstance(result, dict) else str(result)
            
            logger.info(f"Email sent to {to_email}: {email_id}")
            
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=email_id,
                details={
                    "to": to_email,
                    "subject": subject,
                    "template": context.action.template,
                },
            )
            
        except Exception as e:
            logger.exception(f"Resend email failed: {e}")
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="resend_error",
                error_message=str(e),
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
    
    def _markdown_to_html(self, markdown: str) -> str:
        """
        Very basic markdown to HTML conversion.
        
        For a real implementation, use a proper markdown library.
        """
        html = markdown
        
        # Headers
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        
        # Bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Links
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
        
        # Paragraphs
        html = re.sub(r'\n\n', '</p><p>', html)
        html = f'<p>{html}</p>'
        
        # Line breaks
        html = html.replace('\n', '<br>')
        
        return html
