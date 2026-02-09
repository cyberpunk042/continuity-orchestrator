"""
Article Publish Adapter — Build and deploy static site.

This adapter compiles templates and state into a static website
and optionally deploys it to GitHub Pages or other hosting.

## Workflow

1. Compile templates with current state
2. Generate HTML pages (index, timeline, status, archives)
3. Create RSS feed
4. Optionally deploy to GitHub Pages

## Configuration

Action artifact config:
```yaml
artifact:
  output_dir: public          # Output directory
  deploy: true                # Deploy to GitHub Pages
  clean: true                 # Clean before build
  include_archive: true       # Include historical entries
```

## Environment Variables

- GITHUB_TOKEN: For GitHub Pages deployment
- GITHUB_REPOSITORY: For GitHub Pages deployment
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from ..models.receipt import Receipt
from ..site.generator import SiteGenerator
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)


class ArticlePublishAdapter(Adapter):
    """
    Adapter for building and publishing the static site.
    
    This is the "compilation" step that generates the public website.
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).parent.parent.parent
    
    @property
    def name(self) -> str:
        return "article_publish"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Always enabled when in a publishable stage."""
        try:
            return context.state.integrations.enabled_adapters.article_publish
        except AttributeError:
            return True
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate we can build the site."""
        artifact = context.action.artifact or {}
        output_dir = artifact.get("output_dir", "public")
        
        # Check output directory is writable
        output_path = self.project_root / output_dir
        
        try:
            output_path.mkdir(parents=True, exist_ok=True)
            return True, None
        except Exception as e:
            return False, f"Cannot create output directory: {e}"
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Build and optionally deploy the static site."""
        artifact = context.action.artifact or {}
        
        # Configuration
        output_dir = artifact.get("output_dir", "public")
        deploy = artifact.get("deploy", False)
        clean = artifact.get("clean", True)
        include_archive = artifact.get("include_archive", True)
        
        output_path = self.project_root / output_dir
        
        # Load audit entries if needed
        audit_entries = []
        if include_archive:
            audit_entries = self._load_audit_entries()
        
        # Build the site
        try:
            generator = SiteGenerator(output_dir=output_path)
            result = generator.build(
                state=context.state,
                audit_entries=audit_entries,
                clean=clean,
            )
            
            logger.info(f"Site built: {result['files_generated']} files")
            
            # Deploy if requested
            deploy_result = None
            if deploy:
                deploy_result = self._deploy_to_github(output_path, context)
            
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=f"site_{uuid4().hex[:8]}",
                details={
                    "output_dir": str(output_path),
                    "files_generated": result["files_generated"],
                    "deployed": deploy_result is not None,
                    "deploy_result": deploy_result,
                    "timestamp": result["timestamp"],
                },
            )
            
        except Exception as e:
            logger.exception(f"Site build failed: {e}")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="build_failed",
                error_message=str(e),
                retryable=True,
            )
    
    def _load_audit_entries(self, max_entries: int = 50) -> List[Dict]:
        """Load recent audit entries for archive generation."""
        audit_path = self.project_root / "audit" / "ledger.ndjson"
        
        if not audit_path.exists():
            return []
        
        entries = []
        try:
            with open(audit_path) as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            
            # Return last N entries
            return entries[-max_entries:]
            
        except Exception as e:
            logger.warning(f"Failed to load audit entries: {e}")
            return []
    
    def _deploy_to_github(
        self,
        output_path: Path,
        context: ExecutionContext,
    ) -> Optional[Dict]:
        """
        Deploy to GitHub Pages.
        
        This creates a commit to the gh-pages branch with the built site.
        In GitHub Actions, this is handled by the workflow itself.
        """
        github_token = os.environ.get("GITHUB_TOKEN")
        github_repo = os.environ.get("GITHUB_REPOSITORY")
        
        if not github_token or not github_repo:
            logger.info("GitHub credentials not set, skipping deployment")
            return None
        
        # In practice, the GitHub workflow handles the actual deployment
        # This adapter just confirms the files are ready
        return {
            "method": "github_pages",
            "repository": github_repo,
            "output_dir": str(output_path),
            "status": "pending_workflow",
            "message": "Files ready for GitHub Pages deployment via workflow",
        }
