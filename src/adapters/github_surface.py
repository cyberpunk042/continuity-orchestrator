"""
GitHub Surface Adapter — Publish artifacts to GitHub.

This adapter creates and updates GitHub artifacts such as:
- Repository files (markdown documents)
- Gists
- Releases
- Discussions

## Configuration

- GITHUB_TOKEN: Personal access token or GitHub App token
- GITHUB_REPOSITORY: owner/repo format

## Modes

1. **File Mode**: Create/update a file in the repository
2. **Gist Mode**: Create a public or secret gist
3. **Release Mode**: Create a GitHub release

## Usage in Plans

```yaml
actions:
  - id: publish_status
    adapter: github_surface
    channel: public
    artifact:
      mode: file
      path: docs/status.md
      branch: main
      message: "Update continuity status"
```
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt

logger = logging.getLogger(__name__)

# Optional httpx import
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None


class GitHubSurfaceAdapter(Adapter):
    """
    Real GitHub adapter for publishing artifacts.
    
    Uses the GitHub REST API to create/update files, gists, and releases.
    """
    
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.repo = os.environ.get("GITHUB_REPOSITORY")
        self.api_base = "https://api.github.com"
    
    @property
    def name(self) -> str:
        return "github_surface"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if httpx available and GitHub configured."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not installed, GitHub adapter disabled")
            return False
        
        if not self.token:
            logger.warning("GITHUB_TOKEN not set, GitHub adapter disabled")
            return False
        
        return context.integrations.enabled_adapters.github_surface
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate GitHub action can execute."""
        artifact = context.action.artifact
        
        if not artifact:
            return False, "No artifact configuration"
        
        mode = artifact.get("mode", "file")
        if mode not in ("file", "gist", "release"):
            return False, f"Unknown mode: {mode}"
        
        if mode == "file" and not self.repo:
            return False, "GITHUB_REPOSITORY not set for file mode"
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Execute GitHub operation."""
        artifact = context.action.artifact
        mode = artifact.get("mode", "file")
        
        if mode == "file":
            return self._create_or_update_file(context)
        elif mode == "gist":
            return self._create_gist(context)
        elif mode == "release":
            return self._create_release(context)
        else:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="unknown_mode",
                error_message=f"Unknown mode: {mode}",
            )
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "continuity-orchestrator/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    
    def _create_or_update_file(self, context: ExecutionContext) -> Receipt:
        """Create or update a file in the repository."""
        artifact = context.action.artifact
        file_path = artifact.get("path", "docs/continuity-status.md")
        branch = artifact.get("branch", "main")
        message = artifact.get("message", f"Continuity update: {context.escalation.state}")
        
        # Get content from template or generate
        content = context.template_content or self._generate_status_content(context)
        content_b64 = base64.b64encode(content.encode()).decode()
        
        # Check if file exists (to get SHA for update)
        url = f"{self.api_base}/repos/{self.repo}/contents/{file_path}"
        
        try:
            # Get existing file SHA
            existing_sha = None
            resp = httpx.get(url, headers=self._get_headers(), params={"ref": branch})
            if resp.status_code == 200:
                existing_sha = resp.json().get("sha")
            
            # Create or update
            body = {
                "message": message,
                "content": content_b64,
                "branch": branch,
            }
            if existing_sha:
                body["sha"] = existing_sha
            
            resp = httpx.put(url, headers=self._get_headers(), json=body, timeout=30)
            
            if resp.status_code in (200, 201):
                result = resp.json()
                commit_sha = result.get("commit", {}).get("sha", "unknown")
                
                logger.info(f"GitHub file updated: {file_path} (commit: {commit_sha[:8]})")
                
                return Receipt.ok(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    delivery_id=f"github_file_{commit_sha[:12]}",
                    details={
                        "mode": "file",
                        "path": file_path,
                        "branch": branch,
                        "commit_sha": commit_sha,
                        "url": result.get("content", {}).get("html_url"),
                    },
                )
            else:
                logger.error(f"GitHub API error: {resp.status_code} {resp.text}")
                return Receipt.failed(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    error_code=f"github_{resp.status_code}",
                    error_message=resp.text[:200],
                    retryable=resp.status_code >= 500,
                )
                
        except httpx.TimeoutException:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="timeout",
                error_message="GitHub API request timed out",
                retryable=True,
            )
        except Exception as e:
            logger.exception(f"GitHub file operation failed: {e}")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="exception",
                error_message=str(e),
                retryable=True,
            )
    
    def _create_gist(self, context: ExecutionContext) -> Receipt:
        """Create a GitHub Gist."""
        artifact = context.action.artifact
        filename = artifact.get("filename", "continuity-status.md")
        description = artifact.get("description", f"Continuity Status: {context.escalation.state}")
        public = artifact.get("public", False)
        
        content = context.template_content or self._generate_status_content(context)
        
        url = f"{self.api_base}/gists"
        body = {
            "description": description,
            "public": public,
            "files": {
                filename: {"content": content}
            },
        }
        
        try:
            resp = httpx.post(url, headers=self._get_headers(), json=body, timeout=30)
            
            if resp.status_code == 201:
                result = resp.json()
                gist_id = result.get("id")
                gist_url = result.get("html_url")
                
                logger.info(f"Gist created: {gist_url}")
                
                return Receipt.ok(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    delivery_id=f"gist_{gist_id}",
                    details={
                        "mode": "gist",
                        "gist_id": gist_id,
                        "url": gist_url,
                        "public": public,
                    },
                )
            else:
                return Receipt.failed(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    error_code=f"github_{resp.status_code}",
                    error_message=resp.text[:200],
                    retryable=resp.status_code >= 500,
                )
                
        except Exception as e:
            logger.exception(f"Gist creation failed: {e}")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="exception",
                error_message=str(e),
                retryable=True,
            )
    
    def _create_release(self, context: ExecutionContext) -> Receipt:
        """Create a GitHub Release."""
        artifact = context.action.artifact
        tag_name = artifact.get("tag", f"continuity-{context.tick_id}")
        name = artifact.get("name", f"Continuity Event: {context.escalation.state}")
        prerelease = artifact.get("prerelease", True)
        
        content = context.template_content or self._generate_status_content(context)
        
        if not self.repo:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="missing_repo",
                error_message="GITHUB_REPOSITORY not set",
            )
        
        url = f"{self.api_base}/repos/{self.repo}/releases"
        body = {
            "tag_name": tag_name,
            "name": name,
            "body": content,
            "prerelease": prerelease,
        }
        
        try:
            resp = httpx.post(url, headers=self._get_headers(), json=body, timeout=30)
            
            if resp.status_code == 201:
                result = resp.json()
                release_id = result.get("id")
                release_url = result.get("html_url")
                
                logger.info(f"Release created: {release_url}")
                
                return Receipt.ok(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    delivery_id=f"release_{release_id}",
                    details={
                        "mode": "release",
                        "release_id": release_id,
                        "tag": tag_name,
                        "url": release_url,
                    },
                )
            else:
                return Receipt.failed(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    error_code=f"github_{resp.status_code}",
                    error_message=resp.text[:200],
                    retryable=resp.status_code >= 500,
                )
                
        except Exception as e:
            logger.exception(f"Release creation failed: {e}")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="exception",
                error_message=str(e),
                retryable=True,
            )
    
    def _generate_status_content(self, context: ExecutionContext) -> str:
        """Generate default status content."""
        now = datetime.now(timezone.utc).isoformat()
        
        return f"""# Continuity Status

**Stage**: {context.escalation.state}  
**Generated**: {now}  
**Tick ID**: {context.tick_id}

## Status

| Field | Value |
|-------|-------|
| Project | {context.meta.project} |
| State ID | {context.meta.state_id} |
| Deadline | {context.timer.deadline_iso} |
| Time to Deadline | {context.timer.time_to_deadline_minutes} minutes |
| Overdue | {context.timer.overdue_minutes} minutes |
| Mode | {context.state.mode.name} |
| Armed | {context.state.mode.armed} |

---

*This document was automatically generated by the continuity orchestrator.*
"""
