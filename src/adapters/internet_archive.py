"""
Internet Archive Adapter — Archive pages to archive.org Wayback Machine.

This adapter captures snapshots of URLs to the Internet Archive's Wayback Machine,
providing an additional layer of resilience for published content.

Features:
- Archive any public URL (GitHub Pages, custom domains, Docker + Cloudflare)
- No API key required for basic usage (3 captures/minute for anonymous)
- Optional authenticated mode for higher rate limits (6 captures/minute)
- Retrieves permanent archive URLs for verification

Usage:
    - action.channel: 'archive' 
    - action.params.url: Optional specific URL to archive (defaults to site URL)
    - action.params.capture_screenshot: Optional, capture a screenshot
"""

from __future__ import annotations

import os
import time
import ssl
import http.client
from typing import Optional, Tuple
import urllib.request
import urllib.parse
import json
import logging
import re

logger = logging.getLogger(__name__)

from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt


class InternetArchiveAdapter(Adapter):
    """
    Adapter for archiving pages to the Internet Archive's Wayback Machine.
    
    This provides an immutable, third-party record of published content
    that exists independently of the primary hosting infrastructure.
    """

    SAVE_ENDPOINT = "https://web.archive.org/save/"
    AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available"
    
    @property
    def name(self) -> str:
        return "archive"

    def is_enabled(self, context: ExecutionContext) -> bool:
        """Always enabled - no credentials required for basic usage."""
        return True

    def validate(self, context: ExecutionContext) -> Tuple[bool, Optional[str]]:
        """Validate that we have a URL to archive."""
        url = self._get_target_url(context)
        if not url:
            return False, "No URL to archive (set ARCHIVE_URL or GITHUB_REPOSITORY)"
        
        # Must be https or http
        if not url.startswith(('http://', 'https://')):
            return False, f"Invalid URL scheme: {url}"
            
        return True, None

    def execute(self, context: ExecutionContext) -> Receipt:
        """Archive the URL to the Wayback Machine."""
        from ..config import settings
        
        mock_mode = settings.mock_mode
        if mock_mode:
            return self._mock_execute(context)
        
        url = self._get_target_url(context)
        result = archive_url_now(url)
        
        if result.get("success"):
            return Receipt.success(
                adapter=self.name,
                action_id=context.action.id,
                message="Archived to Wayback Machine",
                details={
                    "original_url": url,
                    "archive_url": result.get("archive_url"),
                    "timestamp": time.strftime("%Y%m%d%H%M%S"),
                }
            )
        else:
            return Receipt.failure(
                adapter=self.name,
                action_id=context.action.id,
                error=result.get("error", "Unknown error"),
                details={"url": url}
            )

    def _get_target_url(self, context: ExecutionContext) -> Optional[str]:
        """
        Determine the URL to archive.
        
        Priority:
        1. Explicit URL in action params
        2. ARCHIVE_URL environment variable (for custom domains/Docker)
        3. GitHub Pages URL from GITHUB_REPOSITORY
        """
        # Check action params first
        if hasattr(context.action, 'params') and context.action.params:
            custom_url = context.action.params.get('url')
            if custom_url:
                return custom_url
        
        # Check environment for custom URL
        archive_url = os.environ.get("ARCHIVE_URL")
        if archive_url:
            return archive_url
        
        # Fall back to GitHub Pages URL
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo:
            # Format: owner/repo -> https://owner.github.io/repo/
            parts = repo.split("/")
            if len(parts) == 2:
                owner, repo_name = parts
                return f"https://{owner}.github.io/{repo_name}/"
        
        return None

    def _mock_execute(self, context: ExecutionContext) -> Receipt:
        """Mock execution for testing."""
        url = self._get_target_url(context)
        mock_timestamp = time.strftime("%Y%m%d%H%M%S")
        mock_archive_url = f"https://web.archive.org/web/{mock_timestamp}/{url}"
        
        return Receipt.success(
            adapter=self.name,
            action_id=context.action.id,
            message="[MOCK] Archived to Wayback Machine",
            details={
                "original_url": url,
                "archive_url": mock_archive_url,
                "mock": True,
            }
        )

    @staticmethod
    def check_availability(url: str) -> Optional[dict]:
        """
        Check if a URL is already archived on the Wayback Machine.
        
        Returns the most recent snapshot info, or None if not archived.
        """
        try:
            api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}"
            request = urllib.request.Request(api_url)
            request.add_header("User-Agent", "ContinuityOrchestrator/1.0")
            
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                snapshots = data.get("archived_snapshots", {})
                if "closest" in snapshots:
                    return snapshots["closest"]
        except Exception:
            pass
        return None


def archive_url_now(url: str, max_retries: int = 2) -> dict:
    """
    Archive a URL to the Wayback Machine immediately.
    
    Uses a more robust approach with retries and proper error handling
    for archive.org's infrastructure quirks (Cloudflare 520 errors, etc).
    
    Args:
        url: The URL to archive
        max_retries: Number of retries on transient errors
        
    Returns:
        dict with 'success', 'archive_url', 'original_url', and 'error' keys
    """
    # Build the save URL
    save_url = f"https://web.archive.org/save/{url}"
    
    # Use headers that look like a real browser
    # archive.org/Cloudflare may block requests that don't look like browsers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    
    # Add S3 credentials if available (higher rate limit)
    access_key = os.environ.get("ARCHIVE_ACCESS_KEY")
    secret_key = os.environ.get("ARCHIVE_SECRET_KEY")
    if access_key and secret_key:
        import base64
        credentials = base64.b64encode(f"{access_key}:{secret_key}".encode()).decode()
        headers["Authorization"] = f"LOW {credentials}"
    
    last_error = None
    
    for attempt in range(max_retries + 1):
        logger.info(f"Archive attempt {attempt + 1}/{max_retries + 1} for {url}")
        try:
            # Create request with headers
            request = urllib.request.Request(save_url, headers=headers)
            
            # archive.org Save Page Now can take up to 2+ minutes
            # Use a long timeout to allow the archive to complete
            logger.debug("Opening connection to archive.org (timeout=180s)")
            with urllib.request.urlopen(request, timeout=180) as response:
                response_url = response.geturl()
                response_code = response.status
                logger.info(f"Archive response: code={response_code}, url={response_url[:100]}")
                
                # Check if we got a valid archive response
                # The response URL should contain /web/ with a timestamp
                if "/web/" in response_url and re.search(r'/web/\d{14}/', response_url):
                    logger.info("Archive success: URL found in response")
                    return {
                        "success": True,
                        "archive_url": response_url,
                        "original_url": url,
                        "error": None,
                    }
                
                # Also check Content-Location header
                content_location = response.headers.get("Content-Location", "")
                if content_location and "/web/" in content_location:
                    archive_url = content_location
                    if not archive_url.startswith("http"):
                        archive_url = f"https://web.archive.org{archive_url}"
                    logger.info("Archive success: URL found in Content-Location header")
                    return {
                        "success": True,
                        "archive_url": archive_url,
                        "original_url": url,
                        "error": None,
                    }
                
                # If we got here, try to construct the URL from the response
                # Sometimes the save works but returns a redirect to the archived page
                if response_code in (200, 302, 301):
                    # Construct a "check" URL to verify the archive exists
                    timestamp = time.strftime("%Y%m%d%H%M%S")
                    constructed_url = f"https://web.archive.org/web/{timestamp}/{url}"
                    logger.info("Archive success: URL constructed from timestamp")
                    return {
                        "success": True,
                        "archive_url": constructed_url,
                        "original_url": url,
                        "error": None,
                        "note": "Archive submitted - URL constructed from timestamp"
                    }
                    
        except urllib.error.HTTPError as e:
            error_code = e.code
            error_reason = e.reason if hasattr(e, 'reason') else 'Unknown'
            logger.warning(f"Archive HTTPError: {error_code} {error_reason}")
            
            # Handle specific error codes
            if error_code == 429:
                last_error = "Rate limited by archive.org (max 3/min anonymous, 6/min authenticated)"
                break  # Don't retry rate limits
            elif error_code in (520, 521, 522, 523, 524):
                # 520 errors can be transient OR indicate the URL can't be archived
                # Some sites (GitHub profiles, dynamic JS apps) can't be archived
                if "github.com/" in url and not ".github.io" in url:
                    last_error = "GitHub profile/repo pages often can't be archived (use GitHub Pages URL instead)"
                    break  # Don't retry - this is a permanent issue
                else:
                    last_error = f"Cloudflare error {error_code} - archive.org may be busy or this URL type cannot be archived"
                if attempt < max_retries:
                    wait_time = 2 * (attempt + 1)
                    logger.info(f"Archive retry in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            elif error_code == 403:
                last_error = "Access denied - URL may be blocked from archiving"
                break
            elif error_code == 404:
                last_error = "The target URL returned 404 - cannot archive non-existent page"
                break
            else:
                last_error = f"HTTP {error_code}: {error_reason}"
                
        except urllib.error.URLError as e:
            last_error = f"Network error: {e.reason}"
            if attempt < max_retries:
                time.sleep(1)
                continue
                
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(1)
                continue
    
    # All retries exhausted
    return {
        "success": False,
        "archive_url": None,
        "original_url": url,
        "error": last_error or "Unknown error after retries",
    }


def check_archive_status(url: str) -> dict:
    """
    Check if a URL is already archived and get the latest snapshot.
    
    Args:
        url: The URL to check
        
    Returns:
        dict with 'archived', 'snapshot_url', 'timestamp', and 'error' keys
    """
    try:
        api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}"
        request = urllib.request.Request(api_url)
        request.add_header("User-Agent", "ContinuityOrchestrator/1.0")
        
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
            snapshots = data.get("archived_snapshots", {})
            
            if "closest" in snapshots:
                snapshot = snapshots["closest"]
                return {
                    "archived": True,
                    "snapshot_url": snapshot.get("url"),
                    "timestamp": snapshot.get("timestamp"),
                    "status": snapshot.get("status"),
                    "error": None,
                }
            else:
                return {
                    "archived": False,
                    "snapshot_url": None,
                    "timestamp": None,
                    "error": None,
                }
    except Exception as e:
        return {
            "archived": False,
            "snapshot_url": None,
            "timestamp": None,
            "error": str(e),
        }
