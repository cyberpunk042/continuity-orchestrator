"""
SMS Adapter — Send SMS messages via Twilio API.

This adapter sends SMS messages using the Twilio service.
API credentials are expected in environment variables.

## Configuration

- TWILIO_ACCOUNT_SID: Your Twilio Account SID
- TWILIO_AUTH_TOKEN: Your Twilio Auth Token
- TWILIO_FROM_NUMBER: Your Twilio phone number (e.g., +15551234567)

## Usage

SMS messages are sent to operator_sms from state.integrations.routing.

## Channels

- operator: Send to operator_sms
- custodian: (future) Send to custodian contacts

## Template Support

If a template is resolved, its plain text content is used as the message body.
The first line (if it's a header) is stripped for SMS.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from ..models.receipt import Receipt
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)

# Optional twilio import — graceful degradation
try:
    from twilio.base.exceptions import TwilioException
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    TwilioClient = None
    TwilioException = Exception


class TwilioSMSAdapter(Adapter):
    """
    SMS adapter using Twilio API.
    
    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER
    environment variables.
    """
    
    MAX_SMS_LENGTH = 160  # Standard SMS length
    MAX_CONCAT_LENGTH = 480  # Max chars before truncation (3 SMS)
    
    def __init__(self):
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = os.environ.get("TWILIO_FROM_NUMBER")
        
        self._client: Optional[TwilioClient] = None
        
        if self.account_sid and self.auth_token and TWILIO_AVAILABLE:
            try:
                self._client = TwilioClient(self.account_sid, self.auth_token)
            except Exception as e:
                logger.warning(f"Failed to initialize Twilio client: {e}")
    
    @property
    def name(self) -> str:
        return "sms"
    
    @property
    def client(self) -> Optional[TwilioClient]:
        """Lazy client access."""
        return self._client
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if Twilio is available and configured."""
        if not TWILIO_AVAILABLE:
            logger.warning("twilio package not installed, SMS adapter disabled")
            return False
        
        if not all([self.account_sid, self.auth_token, self.from_number]):
            missing = []
            if not self.account_sid:
                missing.append("TWILIO_ACCOUNT_SID")
            if not self.auth_token:
                missing.append("TWILIO_AUTH_TOKEN")
            if not self.from_number:
                missing.append("TWILIO_FROM_NUMBER")
            logger.warning(f"SMS adapter disabled, missing: {', '.join(missing)}")
            return False
        
        return context.state.integrations.enabled_adapters.sms
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate SMS can be sent."""
        to_number = self._get_recipient(context)
        
        if not to_number:
            return False, f"No phone number for channel '{context.action.channel}'"
        
        # Basic phone format check (E.164)
        if not to_number.startswith("+"):
            return False, f"Phone number must be E.164 format (start with +): {to_number}"
        
        if len(to_number) < 10:
            return False, f"Phone number too short: {to_number}"
        
        if not self.from_number:
            return False, "TWILIO_FROM_NUMBER not configured"
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Send SMS/MMS via Twilio."""
        to_number = self._get_recipient(context)
        
        if not to_number:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="no_recipient",
                error_message=f"No phone number for channel '{context.action.channel}'",
                retryable=False,
            )
        
        # Build message body + extract media URLs for MMS
        body, media_urls = self._build_message(context)
        
        # Validate media URLs are reachable before attempting MMS
        # Twilio silently drops the ENTIRE message if media_url is unreachable
        validated_media = []
        if media_urls:
            import urllib.request
            for url in media_urls:
                try:
                    req = urllib.request.Request(url, method="HEAD")
                    req.add_header("User-Agent", "continuity-orchestrator/1.0")
                    resp = urllib.request.urlopen(req, timeout=5)
                    if resp.status < 400:
                        validated_media.append(url)
                        logger.debug(f"Media URL reachable: {url} ({resp.status})")
                    else:
                        logger.warning(
                            f"Media URL returned {resp.status}, skipping: {url}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Media URL unreachable, skipping for MMS: {url} — {e}"
                    )
            
            if validated_media:
                for i, url in enumerate(validated_media):
                    logger.info(f"  MMS media [{i+1}]: {url}")
                logger.info(
                    f"Sending MMS with {len(validated_media)} media attachment(s)"
                )
            elif media_urls:
                logger.warning(
                    f"All {len(media_urls)} media URLs unreachable, "
                    f"falling back to plain SMS"
                )
        
        try:
            create_kwargs = {
                "body": body,
                "from_": self.from_number,
                "to": to_number,
            }
            
            # Only attach validated media URLs
            if validated_media:
                create_kwargs["media_url"] = validated_media
            
            message = self.client.messages.create(**create_kwargs)
            
            msg_type = "MMS" if validated_media else "SMS"
            logger.info(f"{msg_type} sent to {to_number}: {message.sid}")
            
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=message.sid,
                details={
                    "to": to_number,
                    "from": self.from_number,
                    "status": message.status,
                    "segments": self._count_segments(body),
                    "template": context.action.template,
                    "media_count": len(validated_media),
                },
            )
            
        except TwilioException as e:
            logger.exception(f"Twilio SMS failed: {e}")
            
            # Determine if retryable based on error type
            retryable = self._is_retryable_error(e)
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code=f"twilio_{getattr(e, 'code', 'error')}",
                error_message=str(e),
                retryable=retryable,
            )
        except Exception as e:
            logger.exception(f"SMS send failed: {e}")
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="sms_error",
                error_message=str(e),
                retryable=True,
            )
    
    def _get_recipient(self, context: ExecutionContext) -> Optional[str]:
        """Get the recipient phone number based on channel."""
        channel = context.action.channel
        
        if channel == "operator":
            return context.routing.operator_sms or os.environ.get("OPERATOR_SMS")
        
        # Could support custodian, etc. in future
        # if channel == "custodian":
        #     return context.routing.custodian_sms
        
        # Default to operator
        return context.routing.operator_sms or os.environ.get("OPERATOR_SMS")
    
    def _extract_media_urls(self, content: str) -> tuple:
        """
        Extract media from resolved markdown, split into MMS-embeddable
        and link-only categories.
        
        After resolve_media_uris() runs in tick.py, media:// URIs become
        public URLs like https://domain.com/media/image.webp.
        
        - Plain images  ![caption](url)       → MMS attachment (media_url)
        - Prefixed media ![video: ...](url)    → URL kept in body text
                         ![audio: ...](url)
                         ![file: ...](url)
        
        Returns:
            (mms_urls, link_entries) where link_entries = [(alt, url), ...]
        """
        import re
        media_re = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        mms_urls = []
        link_entries = []
        
        # Prefixes that indicate non-embeddable media
        NON_EMBED_PREFIXES = ("video:", "audio:", "file:")
        
        for match in media_re.finditer(content):
            alt = match.group(1).strip()
            url = match.group(2)
            
            # Skip unresolved media:// and data: URIs
            if url.startswith("media://") or url.startswith("data:"):
                continue
            
            if not (url.startswith("http://") or url.startswith("https://")):
                continue
            
            # Check if it's a non-embeddable type
            alt_lower = alt.lower()
            if any(alt_lower.startswith(p) for p in NON_EMBED_PREFIXES):
                link_entries.append((alt, url))
            else:
                # Plain image → MMS attachment
                mms_urls.append(url)
        
        return mms_urls, link_entries
    
    def _build_message(self, context: ExecutionContext) -> tuple:
        """
        Build the SMS message body and extract media URLs.
        
        Returns:
            (body_text, media_urls) tuple
        """
        template_content = context.template_content
        media_urls = []
        
        if template_content:
            # Extract media BEFORE stripping to labels
            mms_urls, link_entries = self._extract_media_urls(template_content)
            media_urls = mms_urls
            
            # Strip markdown headers and media for the text body
            body = self._strip_headers(template_content)
            
            # Append non-embeddable media as clickable URLs in the body
            if link_entries:
                for alt, url in link_entries:
                    body += f"\n{url}"
        else:
            # Default message
            stage = context.escalation.state
            minutes = context.timer.time_to_deadline_minutes
            
            if minutes > 0:
                body = f"[{stage}] Deadline in {self._format_time(minutes)}. Renew now."
            else:
                overdue = context.timer.overdue_minutes
                body = f"[{stage}] OVERDUE by {self._format_time(overdue)}. Immediate action required."
        
        # Truncate if too long
        if len(body) > self.MAX_CONCAT_LENGTH:
            body = body[:self.MAX_CONCAT_LENGTH - 3] + "..."
            logger.warning(f"SMS truncated to {self.MAX_CONCAT_LENGTH} chars")
        
        return body, media_urls
    
    def _strip_headers(self, content: str) -> str:
        """Remove markdown headers and media from content for SMS."""
        # Strip media markdown to text labels (SMS can't render images)
        from ..templates.media import strip_media_to_labels
        content = strip_media_to_labels(content)

        lines = content.strip().split("\n")
        
        # Skip leading headers
        while lines and lines[0].startswith("#"):
            lines = lines[1:]
        
        # Join and clean up
        text = "\n".join(lines).strip()
        
        # Remove multiple newlines
        import re
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text
    
    def _format_time(self, minutes: int) -> str:
        """Format minutes as human-readable time."""
        if minutes < 60:
            return f"{minutes}m"
        
        hours = minutes // 60
        mins = minutes % 60
        
        if hours < 24:
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h" if hours else f"{days}d"
    
    def _count_segments(self, body: str) -> int:
        """Count SMS segments for the message."""
        length = len(body)
        
        if length <= 160:
            return 1
        
        # Concatenated SMS uses 153 chars per segment
        return (length + 152) // 153
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if a Twilio error is retryable."""
        # Twilio error codes that indicate temporary issues
        retryable_codes = {
            20003,  # Authentication required (might be config issue)
            30002,  # Account suspended (temporary)
            30003,  # Unreachable destination
            30005,  # Unknown destination
            30006,  # Landline destination
            30007,  # Carrier violation
            30008,  # Unknown error
        }
        
        code = getattr(error, 'code', None)
        
        if code in retryable_codes:
            return True
        
        # Rate limit errors are retryable
        if "rate" in str(error).lower():
            return True
        
        return False
