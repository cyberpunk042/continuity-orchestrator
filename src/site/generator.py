"""
Site Generator — Build static site from Jinja2 templates and state.

Uses templates from templates/html/*.html and templates/css/*.css
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

from ..models.state import State

logger = logging.getLogger(__name__)


class SiteGenerator:
    """
    Static site generator using Jinja2 templates.
    
    Templates are loaded from templates/html/ directory.
    CSS files are copied from templates/css/ to public/assets/css/.
    """
    
    def __init__(
        self,
        output_dir: Path,
        template_dir: Optional[Path] = None,
    ):
        self.output_dir = Path(output_dir)
        self.template_dir = template_dir or self._default_template_dir()
        
        # Setup Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.template_dir / "html"),
            autoescape=True,
        )
    
    def _default_template_dir(self) -> Path:
        """Get default template directory."""
        return Path(__file__).parent.parent.parent / "templates"
    
    def build(
        self,
        state: State,
        audit_entries: Optional[List[Dict]] = None,
        clean: bool = True,
    ) -> Dict[str, Any]:
        """Build the complete static site."""
        import time
        build_start = time.time()
        logger.info(f"Building site to {self.output_dir} (state={state.escalation.state})")
        
        if clean and self.output_dir.exists():
            # Clean contents, not the directory itself (for Docker volume compatibility)
            for item in self.output_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except (PermissionError, OSError):
                    pass  # Skip files we can't delete
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy CSS files
        self._copy_css()
        
        # Build context
        context = self._build_context(state, audit_entries)
        
        files_generated = []
        
        # Generate pages
        files_generated.append(self._render_template("index.html", context))
        files_generated.append(self._render_template("countdown.html", context))
        files_generated.append(self._render_template("timeline.html", context))
        files_generated.append(self._render_template("status.html", context))
        files_generated.append(self._generate_feed(context))
        files_generated.append(self._generate_status_json(context))
        
        # Generate articles
        article_files = self._generate_articles(context)
        files_generated.extend(article_files)
        logger.debug(f"Generated {len(article_files)} article(s)")
        
        # Generate archive entries
        if audit_entries:
            archive_dir = self.output_dir / "archive"
            archive_dir.mkdir(exist_ok=True)
            for entry in audit_entries[-10:]:
                archive_path = self._generate_archive_entry(entry, context)
                files_generated.append(archive_path)
            logger.debug(f"Generated {min(len(audit_entries), 10)} archive entries")
        
        # Generate sitemap.xml
        sitemap_path = self._generate_sitemap(context)
        if sitemap_path:
            files_generated.append(sitemap_path)
        
        build_ms = int((time.time() - build_start) * 1000)
        logger.info(f"Site built: {len(files_generated)} files in {build_ms}ms")
        
        return {
            "success": True,
            "output_dir": str(self.output_dir),
            "files_generated": len(files_generated),
            "files": [str(f) for f in files_generated],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def _copy_css(self) -> None:
        """Copy CSS files to output assets directory."""
        css_src = self.template_dir / "css"
        css_dest = self.output_dir / "assets" / "css"
        
        if css_src.exists():
            css_dest.mkdir(parents=True, exist_ok=True)
            for css_file in css_src.glob("*.css"):
                shutil.copy(css_file, css_dest / css_file.name)
    
    def _build_context(
        self,
        state: State,
        audit_entries: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Build template context from state."""
        # Get GitHub repository
        github_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if not github_repo:
            if hasattr(state, 'integrations') and state.integrations:
                repo_from_state = getattr(state.integrations, 'github_repository', None)
                if repo_from_state and repo_from_state != "owner/repo":
                    github_repo = repo_from_state
        
        # Renewal token
        renewal_trigger_token = os.environ.get("RENEWAL_TRIGGER_TOKEN", "")
        
        # Release secret (for client-side optimistic display)
        release_secret = os.environ.get("RELEASE_SECRET", "")
        
        # Enabled adapters
        enabled_adapters = {}
        if hasattr(state, 'integrations') and state.integrations:
            if hasattr(state.integrations, 'enabled_adapters') and state.integrations.enabled_adapters:
                ea = state.integrations.enabled_adapters
                enabled_adapters = {
                    "email": getattr(ea, 'email', False),
                    "sms": getattr(ea, 'sms', False),
                    "reddit": getattr(ea, 'reddit', False),
                    "x": getattr(ea, 'x', False),
                    "github_surface": getattr(ea, 'github_surface', False),
                }
        
        enabled_adapters_list = ", ".join([k for k, v in enabled_adapters.items() if v]) or "None"
        
        # Parse integration executions from audit
        integration_executions = []
        for entry in (audit_entries or []):
            if entry.get("event_type") == "action_executed":
                integration_executions.append({
                    "action": entry.get("action", "unknown"),
                    "adapter": entry.get("adapter", "unknown"),
                    "timestamp": entry.get("timestamp", ""),
                    "success": entry.get("success", True),
                    "error": entry.get("error"),
                    "tick_id": entry.get("tick_id", ""),
                })
        
        # Stage styling
        stage = state.escalation.state
        stage_colors = {
            "OK": "#10b981",
            "REMIND_1": "#f59e0b",
            "REMIND_2": "#f97316",
            "PRE_RELEASE": "#ef4444",
            "PARTIAL": "#8b5cf6",
            "FULL": "#dc2626",
        }
        
        # Status class for index page
        if stage == "OK":
            status_class = "status-ok"
            status_message = "All systems operational. No action required."
        elif stage in ("REMIND_1", "REMIND_2"):
            status_class = "status-warning"
            status_message = "Awaiting renewal. Action may be required soon."
        elif stage == "PRE_RELEASE":
            status_class = "status-alert"
            status_message = "Final warning. Disclosure imminent if not renewed."
        elif stage == "PARTIAL":
            status_class = "status-partial"
            status_message = "Partial disclosure in progress."
        else:
            status_class = "status-full"
            status_message = "Full disclosure active."
        
        # Override display if shadow mode is active (release.triggered)
        release_triggered = state.release.triggered if hasattr(state, 'release') else False
        content_stage = stage  # Real stage for article visibility
        display_stage = stage  # Visual stage for countdown/banner
        if release_triggered:
            display_stage = "DELAYED"
            status_class = "status-delayed"
            status_message = "Release delayed. Awaiting confirmation."
        
        # Banner from manifest
        banner_html = ""
        stage_behavior = None
        nav_articles = []
        visible_articles = []
        
        try:
            from .manifest import ContentManifest
            manifest = ContentManifest.load()
            stage_behavior = manifest.get_stage_behavior(display_stage)
            nav_articles = manifest.get_nav_articles(content_stage)
            visible_articles = manifest.get_visible_articles(content_stage)
            
            if stage_behavior and stage_behavior.banner:
                banner_class = stage_behavior.banner_class or "info"
                banner_html = f'<div class="banner banner-{banner_class}">{stage_behavior.banner}</div>'
        except Exception:
            pass
        
        context = {
            "project": state.meta.project,
            "state_id": state.meta.state_id,
            "stage": display_stage,
            "stage_color": stage_colors.get(display_stage, "#6b7280"),
            "stage_entered": state.escalation.state_entered_at_iso,
            "deadline": state.timer.deadline_iso,
            "time_to_deadline": state.timer.time_to_deadline_minutes,
            "overdue_minutes": state.timer.overdue_minutes,
            "mode": state.mode.name,
            "armed": state.mode.armed,
            "last_updated": state.meta.updated_at_iso,
            "policy_version": state.meta.policy_version,
            "build_time": datetime.now(timezone.utc).isoformat(),
            "audit_entries": audit_entries or [],
            "github_repository": github_repo or "OWNER/REPO",
            "renewal_trigger_token": renewal_trigger_token,
            "enabled_adapters": enabled_adapters,
            "enabled_adapters_list": enabled_adapters_list,
            "renewal_count": state.renewal.renewal_count if hasattr(state, 'renewal') else 0,
            "last_renewal": state.renewal.last_renewal_iso if hasattr(state, 'renewal') else None,
            "integration_executions": list(reversed(integration_executions[-20:])),
            "status_class": status_class,
            "status_message": status_message,
            "banner_html": banner_html,
            "stage_behavior": stage_behavior,
            "nav_articles": nav_articles,
            "visible_articles": visible_articles,
            "release_triggered": state.release.triggered if hasattr(state, 'release') else False,
            "raw_state_json": json.dumps({
                "project": state.meta.project,
                "stage": content_stage,
                "deadline": state.timer.deadline_iso,
                "time_to_deadline": state.timer.time_to_deadline_minutes,
                "mode": state.mode.name,
                "armed": state.mode.armed,
            }, indent=2, default=str),
        }
        
        return context
    
    def _render_template(self, template_name: str, context: Dict[str, Any]) -> Path:
        """Render a Jinja2 template to the output directory."""
        template = self.jinja_env.get_template(template_name)
        html = template.render(**context)
        
        output_path = self.output_dir / template_name
        output_path.write_text(html)
        return output_path
    
    def _generate_feed(self, context: Dict[str, Any]) -> Path:
        """Generate RSS feed."""
        entries = context.get("audit_entries", [])
        
        github_repo = context.get("github_repository", "")
        if github_repo and "/" in github_repo:
            owner, repo = github_repo.split("/", 1)
            site_url = f"https://{owner}.github.io/{repo}/"
        else:
            site_url = ""
        
        items = ""
        for entry in reversed(entries[-10:]):
            items += f"""
            <item>
                <title>Stage: {entry.get('new_state', 'Unknown')}</title>
                <pubDate>{entry.get('timestamp', '')}</pubDate>
                <description>Tick {entry.get('tick_id', 'N/A')}</description>
            </item>
            """
        
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>{context['project']} — Continuity Status</title>
        <link>{site_url}</link>
        <description>Continuity orchestrator status updates</description>
        <lastBuildDate>{context['build_time']}</lastBuildDate>
        {items}
    </channel>
</rss>
"""
        
        output_path = self.output_dir / "feed.xml"
        output_path.write_text(feed)
        return output_path
    
    def _generate_status_json(self, context: Dict[str, Any]) -> Path:
        """Generate status.json for auto-refresh."""
        status = {
            "deadline": context.get("deadline", ""),
            "stage": context.get("stage", ""),
            "time_to_deadline": context.get("time_to_deadline", 0),
            "build_time": context.get("build_time", ""),
            "project": context.get("project", ""),
            "release_triggered": context.get("release_triggered", False),
        }
        
        output_path = self.output_dir / "status.json"
        output_path.write_text(json.dumps(status, indent=2))
        return output_path
    
    def _generate_archive_entry(
        self,
        entry: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Path:
        """Generate an archive page for an event."""
        tick_id = entry.get("tick_id", "unknown")
        timestamp = entry.get("timestamp", "")
        safe_id = tick_id.replace(":", "-").replace(" ", "_")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Event {tick_id}</title>
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/status.css">
</head>
<body class="page-status">
    <header>
        <h1>Event Record</h1>
        <a href="../timeline.html">← Timeline</a>
    </header>
    
    <main>
        <section>
            <h2>{tick_id}</h2>
            <p>Timestamp: {timestamp}</p>
            <pre>{json.dumps(entry, indent=2, default=str)}</pre>
        </section>
    </main>
</body>
</html>
"""
        
        output_path = self.output_dir / "archive" / f"{safe_id}.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_articles(self, context: Dict[str, Any]) -> List[Path]:
        """Generate article pages from Editor.js JSON files."""
        files_generated = []
        stage = context.get("stage", "OK")
        visible_articles = context.get("visible_articles", [])
        
        if not visible_articles:
            return files_generated
        
        articles_dir = self.output_dir / "articles"
        articles_dir.mkdir(exist_ok=True)
        
        articles_data = []
        
        for article_meta in visible_articles:
            slug = getattr(article_meta, "slug", "")
            title = getattr(article_meta, "title", slug)
            description = getattr(article_meta, "description", "")
            
            # Load article content (transparently decrypts encrypted articles)
            content_path = Path(__file__).parent.parent.parent / "content" / "articles" / f"{slug}.json"
            if content_path.exists():
                try:
                    from ..content.crypto import load_article
                    from .editorjs import EditorJSRenderer
                    article_data = load_article(content_path)
                    renderer = EditorJSRenderer()
                    content_html = renderer.render(article_data)
                except ValueError as e:
                    # Encrypted but no key available
                    logger.warning(f"Skipping encrypted article '{slug}': {e}")
                    content_html = "<p>🔒 This article is encrypted. Decryption key required.</p>"
                except Exception as e:
                    logger.error(f"Failed to load article '{slug}': {e}")
                    content_html = "<p>Failed to load article content.</p>"
            else:
                content_html = "<p>Article content not found.</p>"
            
            article_context = {
                **context,
                "base_path": "../",  # Articles are in subdirectory
                "article": {
                    "title": title,
                    "slug": slug,
                    "content": content_html,
                    "description": description,
                }
            }
            
            articles_data.append({
                "title": title,
                "slug": slug,
                "description": description,
            })
            
            # Render article page
            template = self.jinja_env.get_template("article.html")
            html = template.render(**article_context)
            
            output_path = articles_dir / f"{slug}.html"
            output_path.write_text(html)
            files_generated.append(output_path)
        
        # Render article index
        index_context = {
            **context,
            "base_path": "../",  # Articles are in subdirectory
            "articles": articles_data,
        }
        template = self.jinja_env.get_template("articles_index.html")
        html = template.render(**index_context)
        
        index_path = articles_dir / "index.html"
        index_path.write_text(html)
        files_generated.append(index_path)
        
        return files_generated
    
    def _generate_sitemap(self, context: Dict[str, Any]) -> Optional[Path]:
        """Generate sitemap.xml for search engines and Wayback Machine."""
        github_repo = context.get("github_repository", "")
        if not github_repo or "/" not in github_repo or github_repo == "OWNER/REPO":
            logger.debug("Skipping sitemap — no valid GITHUB_REPOSITORY")
            return None
        
        owner, repo = github_repo.split("/", 1)
        base_url = f"https://{owner}.github.io/{repo}"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        
        # Core pages
        pages = [
            ("", "1.0", "hourly"),        # index
            ("countdown.html", "0.8", "hourly"),
            ("timeline.html", "0.7", "daily"),
            ("status.html", "0.6", "hourly"),
        ]
        
        # Articles
        visible_articles = context.get("visible_articles", [])
        if visible_articles:
            pages.append(("articles/", "0.9", "daily"))
            for article_meta in visible_articles:
                slug = getattr(article_meta, "slug", "")
                if slug:
                    pages.append((f"articles/{slug}.html", "0.9", "weekly"))
        
        # Build XML
        urls_xml = ""
        for path, priority, changefreq in pages:
            loc = f"{base_url}/{path}" if path else f"{base_url}/"
            urls_xml += f"""  <url>
    <loc>{loc}</loc>
    <lastmod>{now_iso}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>
"""
        
        sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}</urlset>
"""
        
        output_path = self.output_dir / "sitemap.xml"
        output_path.write_text(sitemap)
        return output_path
    
    @staticmethod
    def get_archivable_paths(output_dir: Path) -> List[str]:
        """Return relative paths of key pages for multi-URL archiving.
        
        Used by the archive adapter to archive all important pages,
        not just the index.
        """
        paths = [""]  # root index
        
        # Core pages
        for page in ["countdown.html", "timeline.html", "status.html"]:
            if (Path(output_dir) / page).exists():
                paths.append(page)
        
        # Articles
        articles_dir = Path(output_dir) / "articles"
        if articles_dir.exists():
            paths.append("articles/")
            for article_file in sorted(articles_dir.glob("*.html")):
                if article_file.name != "index.html":
                    paths.append(f"articles/{article_file.name}")
        
        return paths
