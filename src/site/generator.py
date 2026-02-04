"""
Site Generator — Build static site from templates and state.

This module compiles markdown templates into a static HTML site
that can be deployed to GitHub Pages or any static hosting.

## Output Structure

public/
├── index.html          # Current status page
├── timeline.html       # Escalation timeline
├── archive/            # Historical entries
│   └── YYYY-MM-DD.html
├── assets/
│   └── style.css       # Compiled styles
└── feed.xml            # RSS/Atom feed

## Usage

    from src.site.generator import SiteGenerator
    
    generator = SiteGenerator(output_dir="public")
    generator.build(state, policy)
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.state import State


class SiteGenerator:
    """
    Static site generator for public disclosure.
    
    Compiles templates + state into a deployable static site.
    """
    
    def __init__(
        self,
        output_dir: Path,
        template_dir: Optional[Path] = None,
        assets_dir: Optional[Path] = None,
    ):
        self.output_dir = Path(output_dir)
        self.template_dir = template_dir or self._default_template_dir()
        self.assets_dir = assets_dir or self._default_assets_dir()
    
    def _default_template_dir(self) -> Path:
        """Get default template directory."""
        return Path(__file__).parent.parent.parent / "templates"
    
    def _default_assets_dir(self) -> Path:
        """Get default assets directory."""
        return Path(__file__).parent.parent.parent / "assets"
    
    def build(
        self,
        state: State,
        audit_entries: Optional[List[Dict]] = None,
        clean: bool = True,
    ) -> Dict[str, Any]:
        """
        Build the complete static site.
        
        Args:
            state: Current system state
            audit_entries: Optional audit log entries for timeline
            clean: Whether to clean output directory first
        
        Returns:
            Build result with file counts and paths
        """
        if clean and self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build context for templates
        context = self._build_context(state, audit_entries)
        
        # Generate pages
        files_generated = []
        
        # Index page
        index_path = self._generate_index(context)
        files_generated.append(index_path)
        
        # Timeline page
        timeline_path = self._generate_timeline(context)
        files_generated.append(timeline_path)
        
        # Status page (current state summary)
        status_path = self._generate_status(context)
        files_generated.append(status_path)
        
        # RSS feed
        feed_path = self._generate_feed(context)
        files_generated.append(feed_path)
        
        # Generate articles from Editor.js content
        article_paths = self._generate_articles(context)
        files_generated.extend(article_paths)
        
        # Copy assets
        self._copy_assets()
        
        # Generate archive entries if we have audit data
        if audit_entries:
            archive_dir = self.output_dir / "archive"
            archive_dir.mkdir(exist_ok=True)
            for entry in audit_entries[-10:]:  # Last 10 entries
                archive_path = self._generate_archive_entry(entry, context)
                files_generated.append(archive_path)
        
        return {
            "success": True,
            "output_dir": str(self.output_dir),
            "files_generated": len(files_generated),
            "files": [str(f) for f in files_generated],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def _build_context(
        self,
        state: State,
        audit_entries: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Build template context from state."""
        return {
            "project": state.meta.project,
            "state_id": state.meta.state_id,
            "stage": state.escalation.state,
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
        }
    
    def _generate_index(self, context: Dict[str, Any]) -> Path:
        """Generate the main index page."""
        stage = context["stage"]
        
        # Determine message based on stage
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
        else:  # FULL
            status_class = "status-full"
            status_message = "Full disclosure active."
        
        html = self._render_html_page(
            title=f"Continuity Status — {context['project']}",
            content=f"""
            <header>
                <h1>Continuity Status</h1>
                <p class="subtitle">{context['project']}</p>
            </header>
            
            <main>
                <section class="status-card {status_class}">
                    <h2>Current Stage: {stage}</h2>
                    <p class="status-message">{status_message}</p>
                    <p class="timestamp">Last updated: {context['last_updated']}</p>
                </section>
                
                <section class="details">
                    <h3>Details</h3>
                    <table>
                        <tr><td>Deadline</td><td>{context['deadline']}</td></tr>
                        <tr><td>Time Remaining</td><td>{context['time_to_deadline']} minutes</td></tr>
                        <tr><td>Mode</td><td>{context['mode']}</td></tr>
                        <tr><td>Armed</td><td>{'Yes' if context['armed'] else 'No'}</td></tr>
                    </table>
                </section>
                
                <nav>
                    <a href="timeline.html">View Timeline</a>
                    <a href="articles/">Articles</a>
                    <a href="status.html">Full Status</a>
                    <a href="feed.xml">RSS Feed</a>
                </nav>
            </main>
            
            <footer>
                <p>Generated by Continuity Orchestrator</p>
                <p>Build: {context['build_time']}</p>
            </footer>
            """,
            context=context,
        )
        
        output_path = self.output_dir / "index.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_timeline(self, context: Dict[str, Any]) -> Path:
        """Generate the timeline page."""
        entries = context.get("audit_entries", [])
        
        if entries:
            timeline_items = "\n".join(
                f"""
                <li class="timeline-item">
                    <span class="time">{e.get('timestamp', 'Unknown')}</span>
                    <span class="event">{e.get('event_type', 'tick')}</span>
                    <span class="state">{e.get('new_state', 'N/A')}</span>
                </li>
                """
                for e in reversed(entries[-20:])
            )
        else:
            timeline_items = "<li>No timeline entries available.</li>"
        
        html = self._render_html_page(
            title=f"Timeline — {context['project']}",
            content=f"""
            <header>
                <h1>Escalation Timeline</h1>
                <a href="index.html">← Back to Status</a>
            </header>
            
            <main>
                <ul class="timeline">
                    {timeline_items}
                </ul>
            </main>
            
            <footer>
                <p>Generated: {context['build_time']}</p>
            </footer>
            """,
            context=context,
        )
        
        output_path = self.output_dir / "timeline.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_status(self, context: Dict[str, Any]) -> Path:
        """Generate detailed status page."""
        html = self._render_html_page(
            title=f"Full Status — {context['project']}",
            content=f"""
            <header>
                <h1>Full System Status</h1>
                <a href="index.html">← Back</a>
            </header>
            
            <main>
                <section>
                    <h2>State Information</h2>
                    <pre>{json.dumps(context, indent=2, default=str)}</pre>
                </section>
            </main>
            
            <footer>
                <p>Generated: {context['build_time']}</p>
            </footer>
            """,
            context=context,
        )
        
        output_path = self.output_dir / "status.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_feed(self, context: Dict[str, Any]) -> Path:
        """Generate RSS/Atom feed."""
        entries = context.get("audit_entries", [])
        
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
        <link>https://example.com/</link>
        <description>Continuity orchestrator status updates</description>
        <lastBuildDate>{context['build_time']}</lastBuildDate>
        {items}
    </channel>
</rss>
"""
        
        output_path = self.output_dir / "feed.xml"
        output_path.write_text(feed)
        return output_path
    
    def _generate_archive_entry(
        self,
        entry: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Path:
        """Generate an archive page for a single event."""
        tick_id = entry.get("tick_id", "unknown")
        timestamp = entry.get("timestamp", "unknown")
        
        # Clean tick_id for filename
        safe_id = re.sub(r"[^a-zA-Z0-9-]", "_", tick_id)
        
        html = self._render_html_page(
            title=f"Event {tick_id}",
            content=f"""
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
            """,
            context=context,
        )
        
        output_path = self.output_dir / "archive" / f"{safe_id}.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_articles(self, context: Dict[str, Any]) -> List[Path]:
        """
        Generate article pages from Editor.js JSON files.
        
        Articles are stored in content/articles/*.json
        """
        try:
            from .editorjs import ContentManager
        except ImportError:
            return []
        
        content_dir = Path(__file__).parent.parent.parent / "content" / "articles"
        if not content_dir.exists():
            return []
        
        content_manager = ContentManager(content_dir)
        articles = content_manager.list_articles()
        
        if not articles:
            return []
        
        # Create articles directory
        articles_dir = self.output_dir / "articles"
        articles_dir.mkdir(exist_ok=True)
        
        generated_paths = []
        
        for article_meta in articles:
            article = content_manager.get_article(article_meta["slug"])
            if not article:
                continue
            
            # Generate article page
            html = self._render_html_page(
                title=f"{article['title']} — {context['project']}",
                content=f"""
                <header>
                    <h1>{article['title']}</h1>
                    <a href="../index.html">← Back to Status</a>
                </header>
                
                <main>
                    <article class="editor-content">
                        {article['html']}
                    </article>
                </main>
                
                <footer>
                    <p>Generated: {context['build_time']}</p>
                </footer>
                """,
                context=context,
            )
            
            output_path = articles_dir / f"{article['slug']}.html"
            output_path.write_text(html)
            generated_paths.append(output_path)
        
        # Also generate an articles index
        if generated_paths:
            index_html = self._generate_articles_index(articles, context)
            index_path = articles_dir / "index.html"
            index_path.write_text(index_html)
            generated_paths.append(index_path)
        
        return generated_paths
    
    def _generate_articles_index(
        self,
        articles: List[Dict],
        context: Dict[str, Any],
    ) -> str:
        """Generate index page listing all articles."""
        article_items = "\n".join(
            f'''<li>
                <a href="{a['slug']}.html">{a['title']}</a>
            </li>'''
            for a in articles
        )
        
        return self._render_html_page(
            title=f"Articles — {context['project']}",
            content=f"""
            <header>
                <h1>Articles</h1>
                <a href="../index.html">← Back to Status</a>
            </header>
            
            <main>
                <ul class="article-list">
                    {article_items}
                </ul>
            </main>
            
            <footer>
                <p>Generated: {context['build_time']}</p>
            </footer>
            """,
            context=context,
        )
    
    def _render_html_page(
        self,
        title: str,
        content: str,
        context: Dict[str, Any],
    ) -> str:
        """Render a complete HTML page with styles."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="alternate" type="application/rss+xml" title="RSS Feed" href="feed.xml">
    <style>
        :root {{
            --color-bg: #0d1117;
            --color-surface: #161b22;
            --color-border: #30363d;
            --color-text: #c9d1d9;
            --color-text-muted: #8b949e;
            --color-ok: #238636;
            --color-warning: #d29922;
            --color-alert: #f85149;
            --color-partial: #a371f7;
            --color-full: #ff7b72;
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background: var(--color-bg);
            color: var(--color-text);
            line-height: 1.6;
            padding: 2rem;
            max-width: 800px;
            margin: 0 auto;
        }}
        
        header {{
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--color-border);
        }}
        
        h1 {{ font-size: 2rem; font-weight: 600; }}
        h2 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
        h3 {{ font-size: 1.2rem; margin: 1rem 0 0.5rem; }}
        
        .subtitle {{ color: var(--color-text-muted); }}
        
        .status-card {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            padding: 1.5rem;
            margin: 1rem 0;
        }}
        
        .status-ok {{ border-left: 4px solid var(--color-ok); }}
        .status-warning {{ border-left: 4px solid var(--color-warning); }}
        .status-alert {{ border-left: 4px solid var(--color-alert); }}
        .status-partial {{ border-left: 4px solid var(--color-partial); }}
        .status-full {{ border-left: 4px solid var(--color-full); }}
        
        .status-message {{ margin: 0.5rem 0; }}
        .timestamp {{ color: var(--color-text-muted); font-size: 0.9rem; }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}
        
        td {{
            padding: 0.5rem;
            border-bottom: 1px solid var(--color-border);
        }}
        
        td:first-child {{ color: var(--color-text-muted); width: 40%; }}
        
        nav {{
            display: flex;
            gap: 1rem;
            margin: 1.5rem 0;
        }}
        
        a {{
            color: #58a6ff;
            text-decoration: none;
        }}
        
        a:hover {{ text-decoration: underline; }}
        
        .timeline {{
            list-style: none;
            padding-left: 1rem;
            border-left: 2px solid var(--color-border);
        }}
        
        .timeline-item {{
            padding: 0.75rem 0 0.75rem 1rem;
            border-bottom: 1px solid var(--color-border);
            display: flex;
            gap: 1rem;
        }}
        
        .timeline-item .time {{
            color: var(--color-text-muted);
            font-size: 0.85rem;
            min-width: 200px;
        }}
        
        pre {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 6px;
            padding: 1rem;
            overflow-x: auto;
            font-size: 0.85rem;
        }}
        
        footer {{
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid var(--color-border);
            color: var(--color-text-muted);
            font-size: 0.85rem;
        }}
        
        /* Editor.js content styles */
        .editor-content p {{ margin: 1rem 0; }}
        .editor-content h1 {{ margin: 2rem 0 1rem; font-size: 2rem; }}
        .editor-content h2 {{ margin: 1.5rem 0 1rem; font-size: 1.5rem; }}
        .editor-content h3 {{ margin: 1.25rem 0 0.75rem; font-size: 1.25rem; }}
        .editor-content ul, .editor-content ol {{ margin: 1rem 0; padding-left: 2rem; }}
        .editor-content li {{ margin: 0.5rem 0; }}
        .editor-content blockquote {{
            border-left: 4px solid var(--color-border);
            padding-left: 1rem;
            margin: 1rem 0;
            color: var(--color-text-muted);
            font-style: italic;
        }}
        .editor-content blockquote cite {{
            display: block;
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }}
        .editor-content .warning {{
            background: rgba(210, 153, 34, 0.1);
            border-left: 4px solid var(--color-warning);
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 4px;
        }}
        .editor-content .warning strong {{
            color: var(--color-warning);
        }}
        .editor-content table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}
        .editor-content th, .editor-content td {{
            padding: 0.75rem;
            border: 1px solid var(--color-border);
            text-align: left;
        }}
        .editor-content th {{
            background: var(--color-surface);
            font-weight: 600;
        }}
        .editor-content hr.delimiter {{
            border: none;
            border-top: 2px solid var(--color-border);
            margin: 2rem auto;
            width: 60%;
        }}
        .editor-content figure {{ margin: 1.5rem 0; text-align: center; }}
        .editor-content figure img {{ max-width: 100%; height: auto; border-radius: 6px; }}
        .editor-content figcaption {{ color: var(--color-text-muted); font-size: 0.9rem; margin-top: 0.5rem; }}
        .editor-content code {{ 
            background: var(--color-surface); 
            padding: 0.2em 0.4em; 
            border-radius: 3px; 
            font-size: 0.9em;
        }}
        .article-list {{ list-style: none; }}
        .article-list li {{ padding: 0.75rem 0; border-bottom: 1px solid var(--color-border); }}
        .article-list a {{ font-size: 1.1rem; }}
    </style>
</head>
<body>
    {content}
</body>
</html>
"""
    
    def _copy_assets(self) -> None:
        """Copy static assets to output directory."""
        assets_output = self.output_dir / "assets"
        
        if self.assets_dir.exists():
            if assets_output.exists():
                shutil.rmtree(assets_output)
            shutil.copytree(self.assets_dir, assets_output)
