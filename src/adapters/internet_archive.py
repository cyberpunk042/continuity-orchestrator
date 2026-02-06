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
from typing import Optional, Tuple
import urllib.request
import urllib.parse
import json
import re

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
        
        try:
            # Submit URL for archiving
            save_url = f"{self.SAVE_ENDPOINT}{url}"
            
            headers = {
                "User-Agent": "ContinuityOrchestrator/1.0 (Resilience Tool; +https://github.com/cyberpunk042/continuity-orchestrator)"
            }
            
            # Add authentication if available
            access_key = os.environ.get("ARCHIVE_ACCESS_KEY")
            secret_key = os.environ.get("ARCHIVE_SECRET_KEY")
            if access_key and secret_key:
                import base64
                credentials = base64.b64encode(f"{access_key}:{secret_key}".encode()).decode()
                headers["Authorization"] = f"LOW {credentials}"
            
            request = urllib.request.Request(save_url, headers=headers, method="GET")
            
            with urllib.request.urlopen(request, timeout=30) as response:
                # The response contains the archived URL in various forms
                response_url = response.geturl()
                response_headers = dict(response.headers)
                
                # Extract the archive link from Content-Location or response URL
                archive_url = response_headers.get("Content-Location")
                if not archive_url:
                    # Fallback: construct from timestamp pattern in URL
                    # Response URL format: https://web.archive.org/web/20240206123456/https://example.com
                    archive_url = response_url
                
                # Make sure we have a full archive URL
                if archive_url and not archive_url.startswith("http"):
                    archive_url = f"https://web.archive.org{archive_url}"
                
                return Receipt.success(
                    adapter=self.name,
                    action_id=context.action.id,
                    message=f"Archived to Wayback Machine",
                    details={
                        "original_url": url,
                        "archive_url": archive_url,
                        "response_url": response_url,
                        "timestamp": time.strftime("%Y%m%d%H%M%S"),
                    }
                )
                
        except urllib.error.HTTPError as e:
            # 429 = rate limited, 523 = temporarily unavailable
            error_msg = f"HTTP {e.code}: {e.reason}"
            if e.code == 429:
                error_msg = "Rate limited by archive.org (max 3/min for anonymous)"
            return Receipt.failure(
                adapter=self.name,
                action_id=context.action.id,
                error=error_msg,
                details={"url": url, "error_code": e.code}
            )
        except urllib.error.URLError as e:
            return Receipt.failure(
                adapter=self.name,
                action_id=context.action.id,
                error=f"Network error: {e.reason}",
                details={"url": url}
            )
        except Exception as e:
            return Receipt.failure(
                adapter=self.name,
                action_id=context.action.id,
                error=str(e),
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


def archive_url_now(url: str, custom_archive_url: str = None) -> dict:
    """
    Standalone function to archive a URL immediately.
    
    Args:
        url: The URL to archive
        custom_archive_url: Optional custom archive base URL (for testing)
        
    Returns:
        dict with 'success', 'archive_url', and 'error' keys
    """
    try:
        save_url = f"https://web.archive.org/save/{url}"
        
        headers = {
            "User-Agent": "ContinuityOrchestrator/1.0 (Resilience Tool)"
        }
        
        request = urllib.request.Request(save_url, headers=headers, method="GET")
        
        with urllib.request.urlopen(request, timeout=30) as response:
            response_url = response.geturl()
            archive_url = response.headers.get("Content-Location")
            if archive_url and not archive_url.startswith("http"):
                archive_url = f"https://web.archive.org{archive_url}"
            else:
                archive_url = response_url
            
            return {
                "success": True,
                "archive_url": archive_url,
                "original_url": url,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "archive_url": None,
            "original_url": url,
            "error": f"HTTP {e.code}: {e.reason}",
        }
    except Exception as e:
        return {
            "success": False,
            "archive_url": None,
            "original_url": url,
            "error": str(e),
        }
