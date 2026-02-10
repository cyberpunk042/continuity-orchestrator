"""
X (Twitter) Adapter — Post tweets via Twitter API v2.

This adapter posts tweets using the Twitter/X API v2.
OAuth 1.0a credentials are expected in environment variables.

## Configuration

- X_API_KEY: Twitter API Key (Consumer Key)
- X_API_SECRET: Twitter API Secret (Consumer Secret)
- X_ACCESS_TOKEN: OAuth Access Token
- X_ACCESS_SECRET: OAuth Access Token Secret

## Usage

Tweets are posted to the account associated with the access token.

## Template Support

If a template is resolved, its content is used as the tweet body.
The first line (if it's a header) is used as the main message.
Content is truncated to fit Twitter's character limit.

## Constraints

- Max 280 characters per tweet
- No media attachments (text only)
- Rate limiting applies
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
from typing import Any, Dict, Optional
from uuid import uuid4

from ..models.receipt import Receipt
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)

# Optional httpx import for making requests
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None


class XAdapter(Adapter):
    """
    X (Twitter) adapter using Twitter API v2.
    
    Requires OAuth 1.0a credentials in environment variables:
    - X_API_KEY
    - X_API_SECRET
    - X_ACCESS_TOKEN
    - X_ACCESS_SECRET
    """
    
    MAX_TWEET_LENGTH = 280
    API_BASE = "https://api.twitter.com"
    TWEET_ENDPOINT = "/2/tweets"
    
    def __init__(self):
        self.api_key = os.environ.get("X_API_KEY")
        self.api_secret = os.environ.get("X_API_SECRET")
        self.access_token = os.environ.get("X_ACCESS_TOKEN")
        self.access_secret = os.environ.get("X_ACCESS_SECRET")
        
        self._client: Optional[httpx.Client] = None
        
        if HTTPX_AVAILABLE and self._is_configured():
            self._client = httpx.Client(timeout=30.0)
    
    @property
    def name(self) -> str:
        return "x"
    
    def _is_configured(self) -> bool:
        """Check if all required credentials are present."""
        return all([
            self.api_key,
            self.api_secret,
            self.access_token,
            self.access_secret,
        ])
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if httpx is available and credentials are configured."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx package not installed, X adapter disabled")
            return False
        
        if not self._is_configured():
            missing = []
            if not self.api_key:
                missing.append("X_API_KEY")
            if not self.api_secret:
                missing.append("X_API_SECRET")
            if not self.access_token:
                missing.append("X_ACCESS_TOKEN")
            if not self.access_secret:
                missing.append("X_ACCESS_SECRET")
            logger.warning(f"X adapter disabled, missing: {', '.join(missing)}")
            return False
        
        return context.state.integrations.enabled_adapters.x
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate tweet can be posted."""
        if not self._is_configured():
            return False, "X API credentials not configured"
        
        # Check that we have content to post
        message = self._build_tweet(context)
        
        if not message or len(message.strip()) == 0:
            return False, "Empty tweet content"
        
        if len(message) > self.MAX_TWEET_LENGTH:
            # Will be truncated, but that's okay
            logger.warning(f"Tweet will be truncated from {len(message)} to {self.MAX_TWEET_LENGTH} chars")
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Post tweet via Twitter API v2."""
        # Build tweet content
        message = self._build_tweet(context)
        
        if not message:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="empty_content",
                error_message="No content to tweet",
                retryable=False,
            )
        
        # Truncate if needed
        if len(message) > self.MAX_TWEET_LENGTH:
            message = message[:self.MAX_TWEET_LENGTH - 3] + "..."
            logger.warning(f"Tweet truncated to {self.MAX_TWEET_LENGTH} chars")
        
        try:
            # Build OAuth 1.0a headers
            url = f"{self.API_BASE}{self.TWEET_ENDPOINT}"
            auth_header = self._build_oauth_header("POST", url)
            
            response = self._client.post(
                url,
                json={"text": message},
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code == 201:
                data = response.json()
                tweet_id = data.get("data", {}).get("id", "unknown")
                
                logger.info(f"Tweet posted: {tweet_id}")
                
                return Receipt.ok(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    delivery_id=tweet_id,
                    details={
                        "message_length": len(message),
                        "template": context.action.template,
                        "tweet_url": f"https://x.com/i/status/{tweet_id}",
                    },
                )
            
            # Handle error responses
            error_data = response.json() if response.content else {}
            error_msg = self._extract_error_message(error_data, response.status_code)
            retryable = self._is_retryable_status(response.status_code)
            
            logger.error(f"Twitter API error {response.status_code}: {error_msg}")
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code=f"twitter_{response.status_code}",
                error_message=error_msg,
                retryable=retryable,
            )
            
        except httpx.TimeoutException as e:
            logger.exception(f"Twitter API timeout: {e}")
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="timeout",
                error_message=str(e),
                retryable=True,
            )
        except Exception as e:
            logger.exception(f"Twitter post failed: {e}")
            
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="x_error",
                error_message=str(e),
                retryable=True,
            )
    
    def _build_tweet(self, context: ExecutionContext) -> str:
        """Build the tweet content."""
        template_content = context.template_content
        
        if template_content:
            # Parse template - use first paragraph after any headers
            return self._parse_template(template_content)
        
        # Default tweet format
        stage = context.escalation.state
        project = context.meta.project
        minutes = context.timer.time_to_deadline_minutes
        
        if minutes > 0:
            time_str = self._format_time(minutes)
            return f"⏰ [{project}] Status: {stage}\nDeadline in {time_str}\n\n#continuity #automated"
        else:
            overdue = context.timer.overdue_minutes
            time_str = self._format_time(overdue)
            return f"🚨 [{project}] Status: {stage}\nOVERDUE by {time_str}\n\n#continuity #automated"
    
    def _parse_template(self, content: str) -> str:
        """Parse template content for tweet."""
        import re

        # Resolve media:// URIs to public URLs (instead of stripping to labels)
        from ..templates.media import resolve_media_uris
        content = resolve_media_uris(content)

        # Convert remaining ![alt](url) → plain URL
        # X auto-generates link cards/previews for URLs in tweets
        content = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', r'\1', content)

        lines = content.strip().split("\n")

        # Skip markdown headers
        while lines and lines[0].startswith("#"):
            lines = lines[1:]

        # Join remaining content
        text = "\n".join(lines).strip()

        # Clean up multiple newlines
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
    
    def _build_oauth_header(self, method: str, url: str, body_params: Optional[Dict] = None) -> str:
        """
        Build OAuth 1.0a Authorization header.
        
        This implements the OAuth 1.0a signature for Twitter API v2.
        """
        # OAuth parameters
        oauth_params = {
            "oauth_consumer_key": self.api_key,
            "oauth_nonce": uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.access_token,
            "oauth_version": "1.0",
        }
        
        # Combine all params for signature base
        all_params = {**oauth_params}
        if body_params:
            all_params.update(body_params)
        
        # Create parameter string (sorted, encoded)
        param_string = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(all_params.items())
        )
        
        # Create signature base string
        signature_base = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(param_string, safe=""),
        ])
        
        # Create signing key
        signing_key = f"{urllib.parse.quote(self.api_secret, safe='')}&{urllib.parse.quote(self.access_secret, safe='')}"
        
        # Generate signature
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode(),
                signature_base.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()
        
        oauth_params["oauth_signature"] = signature
        
        # Build Authorization header
        auth_header = "OAuth " + ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        
        return auth_header
    
    def _extract_error_message(self, error_data: Dict[str, Any], status_code: int) -> str:
        """Extract human-readable error message from Twitter API response."""
        # Twitter API v2 error format
        if "detail" in error_data:
            return error_data["detail"]
        
        if "errors" in error_data and error_data["errors"]:
            return error_data["errors"][0].get("message", "Unknown error")
        
        if "title" in error_data:
            return error_data["title"]
        
        # Fallback
        status_messages = {
            400: "Bad request",
            401: "Authentication failed",
            403: "Forbidden - check app permissions",
            404: "Endpoint not found",
            429: "Rate limit exceeded",
            500: "Twitter server error",
            503: "Twitter service unavailable",
        }
        
        return status_messages.get(status_code, f"HTTP {status_code}")
    
    def _is_retryable_status(self, status_code: int) -> bool:
        """Determine if the HTTP status code indicates a retryable error."""
        # Retryable: rate limits, server errors
        retryable_codes = {429, 500, 502, 503, 504}
        return status_code in retryable_codes
    
    def __del__(self):
        """Cleanup HTTP client."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
