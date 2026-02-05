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
        
        # Countdown page (live timer + renewal form)
        countdown_path = self._generate_countdown(context)
        files_generated.append(countdown_path)
        
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
        
        # Generate status.json for auto-refresh polling
        status_json_path = self._generate_status_json(context)
        files_generated.append(status_json_path)
        
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
        # Get github repository - try multiple sources
        github_repo = None
        
        # 1. From environment variable (e.g., in GitHub Actions)
        github_repo = os.environ.get("GITHUB_REPOSITORY")
        
        # 2. From state config
        if not github_repo:
            if hasattr(state, 'integrations') and state.integrations:
                routing = getattr(state.integrations, 'routing', None)
                if routing and hasattr(routing, 'github_repository'):
                    repo_from_state = routing.github_repository
                    if repo_from_state and repo_from_state != "owner/repo":
                        github_repo = repo_from_state
        
        # 3. Auto-detect from git remote
        if not github_repo:
            import subprocess
            try:
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    url = result.stdout.strip()
                    # Parse: git@github.com:owner/repo.git or https://github.com/owner/repo.git
                    if "github.com" in url:
                        if url.startswith("git@"):
                            github_repo = url.split(":")[-1].replace(".git", "")
                        else:
                            github_repo = "/".join(url.split("/")[-2:]).replace(".git", "")
            except Exception:
                pass
        
        # Get renewal trigger token if configured (fine-grained PAT with only actions:write)
        renewal_trigger_token = os.environ.get("RENEWAL_TRIGGER_TOKEN", "")
        
        # Warn if token is set locally but we're not in CI (user might forget to add GitHub secret)
        if renewal_trigger_token and not os.environ.get("GITHUB_ACTIONS"):
            import logging
            logging.getLogger(__name__).warning(
                "RENEWAL_TRIGGER_TOKEN is set locally. "
                "Make sure to also add it as a GitHub secret for the deployed site to work: "
                "Settings → Secrets → Actions → RENEWAL_TRIGGER_TOKEN"
            )
        
        context = {
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
            "github_repository": github_repo or "OWNER/REPO",
            "renewal_trigger_token": renewal_trigger_token,  # For direct API renewal
        }
        
        # Load content manifest for stage-based visibility
        try:
            from .manifest import ContentManifest
            manifest = ContentManifest.load()
            context["manifest"] = manifest
            context["stage_behavior"] = manifest.get_stage_behavior(state.escalation.state)
            context["visible_articles"] = manifest.get_visible_articles(state.escalation.state)
            context["nav_articles"] = manifest.get_nav_articles(state.escalation.state)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load manifest: {e}")
            context["manifest"] = None
            context["stage_behavior"] = None
            context["visible_articles"] = []
            context["nav_articles"] = []
        
        return context
    
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
                    <a href="countdown.html">Countdown</a>
                    <a href="timeline.html">Timeline</a>
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
    
    def _generate_status_json(self, context: Dict[str, Any]) -> Path:
        """Generate status.json for client-side auto-refresh polling."""
        import json
        
        status = {
            "deadline": context.get("deadline", ""),
            "stage": context.get("stage", ""),
            "time_to_deadline": context.get("time_to_deadline", 0),
            "build_time": context.get("build_time", ""),
            "project": context.get("project", ""),
        }
        
        output_path = self.output_dir / "status.json"
        output_path.write_text(json.dumps(status, indent=2))
        return output_path
    
    def _generate_countdown(self, context: Dict[str, Any]) -> Path:
        """Generate the countdown page with live timer and renewal form."""
        stage = context["stage"]
        deadline = context["deadline"]
        project = context["project"]
        github_repo = context.get("github_repository", "OWNER/REPO")
        renewal_token = context.get("renewal_trigger_token", "")
        
        # Stage styling
        stage_colors = {
            "OK": "#10b981",
            "REMIND_1": "#f59e0b",
            "REMIND_2": "#f97316",
            "PRE_RELEASE": "#ef4444",
            "PARTIAL": "#8b5cf6",
            "FULL": "#dc2626",
        }
        stage_color = stage_colors.get(stage, "#6b7280")
        
        # Stage behavior from manifest
        stage_behavior = context.get("stage_behavior")
        banner_html = ""
        if stage_behavior and stage_behavior.banner:
            banner_class = stage_behavior.banner_class or "info"
            banner_html = f'<div class="banner banner-{banner_class}">{stage_behavior.banner}</div>'
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Countdown — {project}</title>
    <style>
        :root {{
            --color-bg: #0d1117;
            --color-surface: #161b22;
            --color-border: #30363d;
            --color-text: #c9d1d9;
            --color-text-muted: #8b949e;
            --color-accent: #58a6ff;
            --color-stage: {stage_color};
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background: var(--color-bg);
            color: var(--color-text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }}
        
        .container {{
            max-width: 600px;
            width: 100%;
            text-align: center;
        }}
        
        h1 {{
            font-size: 1.5rem;
            margin-bottom: 2rem;
            color: var(--color-text-muted);
        }}
        
        .stage-badge {{
            display: inline-block;
            background: var(--color-stage);
            color: white;
            padding: 0.5rem 1.5rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 1rem;
            margin-bottom: 2rem;
        }}
        
        .countdown {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 16px;
            padding: 3rem 2rem;
            margin-bottom: 2rem;
        }}
        
        .countdown-label {{
            font-size: 0.875rem;
            color: var(--color-text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 1rem;
        }}
        
        .countdown-timer {{
            font-size: 4rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.02em;
        }}
        
        .countdown-timer.overdue {{
            color: #ef4444;
        }}
        
        .countdown-timer.ok {{
            color: #10b981;
        }}
        
        .countdown-timer.warning {{
            color: #f59e0b;
        }}
        
        .countdown-timer.critical {{
            color: #ef4444;
            animation: pulse 1s ease-in-out infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        
        .deadline-info {{
            margin-top: 1rem;
            font-size: 0.875rem;
            color: var(--color-text-muted);
        }}
        
        .renewal-section {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 16px;
            padding: 2rem;
        }}
        
        .renewal-section h2 {{
            font-size: 1rem;
            margin-bottom: 1rem;
            color: var(--color-text);
        }}
        
        .renewal-status {{
            margin-top: 1rem;
            padding: 0.75rem;
            border-radius: 8px;
            display: none;
        }}
        
        .renewal-status.success {{
            display: block;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid #10b981;
            color: #10b981;
        }}
        
        .renewal-status.error {{
            display: block;
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            color: #ef4444;
        }}
        
        .banner {{
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            font-weight: 500;
        }}
        
        .banner-info {{
            background: rgba(88, 166, 255, 0.1);
            border: 1px solid var(--color-accent);
            color: var(--color-accent);
        }}
        
        .banner-warning {{
            background: rgba(245, 158, 11, 0.1);
            border: 1px solid #f59e0b;
            color: #f59e0b;
        }}
        
        .banner-alert {{
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid #8b5cf6;
            color: #8b5cf6;
        }}
        
        .banner-critical {{
            background: rgba(220, 38, 38, 0.1);
            border: 1px solid #dc2626;
            color: #dc2626;
        }}
        
        .renewal-desc {{
            font-size: 0.875rem;
            color: var(--color-text-muted);
            margin-bottom: 1rem;
        }}
        
        .renewal-form {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }}
        
        .renewal-form input {{
            flex: 1;
            padding: 0.75rem 1rem;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            background: var(--color-bg);
            color: var(--color-text);
            font-size: 1rem;
        }}
        
        .renewal-form input:focus {{
            outline: none;
            border-color: var(--color-accent);
        }}
        
        .renewal-form button {{
            padding: 0.75rem 1rem;
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            cursor: pointer;
            font-size: 1rem;
            transition: border-color 0.2s;
        }}
        
        .renewal-form button:hover {{
            border-color: var(--color-accent);
        }}
        
        .github-action-btn {{
            display: block;
            width: 100%;
            padding: 1rem 1.5rem;
            background: linear-gradient(135deg, #238636 0%, #2ea043 100%);
            color: white;
            text-decoration: none;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 1rem;
            text-align: center;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            margin-bottom: 1rem;
        }}
        
        .github-action-btn:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(46, 160, 67, 0.3);
        }}
        
        .github-action-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        
        .renewal-form select {{
            padding: 0.75rem 0.5rem;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            background: var(--color-bg);
            color: var(--color-text);
            font-size: 0.875rem;
            cursor: pointer;
        }}
        
        .hidden {{
            display: none !important;
        }}
        
        .renewal-instructions {{
            background: var(--color-bg);
            border: 1px solid var(--color-accent);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            text-align: left;
            animation: slideIn 0.3s ease-out;
        }}
        
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(-10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        .instruction-card {{
            display: flex;
            align-items: flex-start;
            gap: 1rem;
            padding: 0.75rem 0;
        }}
        
        .instruction-card:not(:last-child) {{
            border-bottom: 1px solid var(--color-border);
        }}
        
        .step-number {{
            width: 28px;
            height: 28px;
            background: var(--color-accent);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 0.875rem;
            flex-shrink: 0;
        }}
        
        .step-content {{
            flex: 1;
        }}
        
        .step-content p {{
            color: var(--color-text-muted);
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }}
        
        .step-content ol {{
            margin-left: 1.25rem;
            margin-top: 0.5rem;
            font-size: 0.875rem;
        }}
        
        .step-content li {{
            margin-bottom: 0.25rem;
        }}
        
        .step-check {{
            color: #10b981;
            font-size: 1.5rem;
        }}
        
        .code-inline {{
            background: var(--color-surface);
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.8em;
            border: 1px solid var(--color-border);
        }}
        
        .link-btn {{
            width: 100%;
            padding: 0.75rem;
            background: transparent;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            color: var(--color-accent);
            font-size: 0.875rem;
            cursor: pointer;
            margin-top: 1rem;
        }}
        
        .link-btn:hover {{
            background: var(--color-surface);
        }}
        
        .alt-method {{
            margin-top: 1.5rem;
            font-size: 0.875rem;
            color: var(--color-text-muted);
        }}
        
        .alt-method summary {{
            cursor: pointer;
            padding: 0.5rem;
        }}
        
        .alt-method summary:hover {{
            color: var(--color-text);
        }}
        
        .alt-content {{
            padding: 1rem;
            background: var(--color-bg);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            margin-top: 0.5rem;
        }}
        
        .alt-content ol {{
            margin-left: 1.5rem;
            margin-top: 0.5rem;
        }}
        
        .alt-content li {{
            margin-bottom: 0.25rem;
        }}
        
        .alt-content a {{
            color: var(--color-accent);
        }}
        
        .nav {{
            margin-top: 2rem;
        }}
        
        .nav a {{
            color: var(--color-accent);
            text-decoration: none;
            margin: 0 0.5rem;
        }}
        
        .nav a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{project}</h1>
        
        {banner_html}
        
        <span class="stage-badge">{stage}</span>
        
        <div class="countdown">
            <div class="countdown-label">Time Remaining</div>
            <div class="countdown-timer" id="timer">--:--:--</div>
            <div class="deadline-info">
                Deadline: <span id="deadline">{deadline}</span>
            </div>
        </div>
        
        <div class="renewal-section">
            <h2>🔐 Check In</h2>
            <p class="renewal-desc">Enter your renewal code to extend the deadline.</p>
            
            <div class="renewal-form">
                <input type="password" id="renewal-code" placeholder="Enter renewal code" autocomplete="off">
                <select id="extend-hours" title="Hours to extend">
                    <option value="24">+24h</option>
                    <option value="48" selected>+48h</option>
                    <option value="72">+72h</option>
                    <option value="168">+1 week</option>
                </select>
            </div>
            
            <button type="button" class="github-action-btn" id="renew-btn" onclick="handleRenewal()">
                🚀 Renew Now
            </button>
            
            <div id="renewal-instructions" class="renewal-instructions hidden">
                <div class="instruction-card">
                    <div class="step-number">1</div>
                    <div class="step-content">
                        <strong>Code copied to clipboard!</strong>
                        <p>Your renewal code is ready to paste.</p>
                    </div>
                    <div class="step-check" id="step1-check">✓</div>
                </div>
                
                <div class="instruction-card">
                    <div class="step-number">2</div>
                    <div class="step-content">
                        <strong>On GitHub:</strong>
                        <ol>
                            <li>Click <span class="code-inline">Run workflow</span></li>
                            <li>Paste your code in <span class="code-inline">Renewal code</span></li>
                            <li>Click <span class="code-inline">Run workflow</span> (green button)</li>
                        </ol>
                    </div>
                </div>
                
                <button type="button" class="link-btn" onclick="openGitHub()">
                    Didn't open? Click here to go to GitHub →
                </button>
            </div>
            
            <div class="renewal-status" id="renewal-status"></div>
            
            <details class="alt-method">
                <summary>Alternative: Manual renewal</summary>
                <div class="alt-content">
                    <p>If the button doesn't work, you can renew manually:</p>
                    <ol>
                        <li>Go to <a href="https://github.com/{github_repo}/actions/workflows/renew.yml" target="_blank">Renew Workflow →</a></li>
                        <li>Click "Run workflow"</li>
                        <li>Enter your renewal code</li>
                        <li>Choose hours to extend</li>
                        <li>Click "Run workflow"</li>
                    </ol>
                </div>
            </details>
        </div>
        
        <nav class="nav">
            <a href="index.html">Status</a>
            <a href="timeline.html">Timeline</a>
            <a href="articles/">Articles</a>
        </nav>
    </div>
    
    <script>
        // Countdown configuration
        const deadline = new Date("{deadline}");
        const timerEl = document.getElementById("timer");
        
        function updateCountdown() {{
            const now = new Date();
            const diff = deadline - now;
            
            if (diff <= 0) {{
                // Overdue
                const overdue = Math.abs(diff);
                const hours = Math.floor(overdue / (1000 * 60 * 60));
                const mins = Math.floor((overdue % (1000 * 60 * 60)) / (1000 * 60));
                const secs = Math.floor((overdue % (1000 * 60)) / 1000);
                
                timerEl.textContent = `-${{String(hours).padStart(2, '0')}}:${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
                timerEl.className = "countdown-timer overdue";
            }} else {{
                const days = Math.floor(diff / (1000 * 60 * 60 * 24));
                const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                const secs = Math.floor((diff % (1000 * 60)) / 1000);
                
                if (days > 0) {{
                    timerEl.textContent = `${{days}}d ${{String(hours).padStart(2, '0')}}:${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
                }} else {{
                    timerEl.textContent = `${{String(hours).padStart(2, '0')}}:${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
                }}
                
                // Color based on time remaining
                const totalMins = diff / (1000 * 60);
                if (totalMins > 60 * 24) {{
                    timerEl.className = "countdown-timer ok";
                }} else if (totalMins > 60) {{
                    timerEl.className = "countdown-timer warning";
                }} else {{
                    timerEl.className = "countdown-timer critical";
                }}
            }}
        }}
        
        // Update every second
        updateCountdown();
        setInterval(updateCountdown, 1000);
        
        // Renewal functionality
        const GITHUB_REPO = "{github_repo}";
        const GITHUB_WORKFLOW_URL = "https://github.com/" + GITHUB_REPO + "/actions/workflows/renew.yml";
        const TRIGGER_TOKEN = "{renewal_token}";  // Fine-grained PAT with only actions:write
        
        async function handleRenewal() {{
            const codeInput = document.getElementById("renewal-code");
            const hoursSelect = document.getElementById("extend-hours");
            const statusEl = document.getElementById("renewal-status");
            const instructionsEl = document.getElementById("renewal-instructions");
            const renewBtn = document.getElementById("renew-btn");
            const code = codeInput.value.trim();
            const hours = hoursSelect.value;
            
            if (!code) {{
                showStatus("Please enter your renewal code", "error");
                codeInput.focus();
                return;
            }}
            
            // If we have a trigger token, use direct API!
            if (TRIGGER_TOKEN) {{
                renewBtn.disabled = true;
                renewBtn.textContent = "⏳ Sending...";
                
                try {{
                    const response = await fetch(
                        `https://api.github.com/repos/${{GITHUB_REPO}}/actions/workflows/renew.yml/dispatches`,
                        {{
                            method: "POST",
                            headers: {{
                                "Accept": "application/vnd.github+json",
                                "Authorization": `Bearer ${{TRIGGER_TOKEN}}`,
                                "X-GitHub-Api-Version": "2022-11-28",
                                "Content-Type": "application/json",
                            }},
                            body: JSON.stringify({{
                                ref: "main",
                                inputs: {{
                                    renewal_code: code,
                                    extend_hours: hours
                                }}
                            }})
                        }}
                    );
                    
                    if (response.status === 204) {{
                        showStatus("✅ Renewal triggered! Check GitHub Actions for status.", "success");
                        renewBtn.textContent = "✓ Sent!";
                        renewBtn.classList.add("success");
                        
                        // Show link to check status
                        instructionsEl.innerHTML = `
                            <div class="instruction-card">
                                <div class="step-number">✓</div>
                                <div class="step-content">
                                    <strong>Renewal request sent!</strong>
                                    <p>The workflow is now running. Your deadline will be extended if the code is correct.</p>
                                </div>
                            </div>
                            <a href="${{GITHUB_WORKFLOW_URL}}" target="_blank" class="link-btn">
                                View workflow status on GitHub →
                            </a>
                        `;
                        instructionsEl.classList.remove("hidden");
                        
                        setTimeout(() => {{
                            renewBtn.textContent = "🚀 Renew Now";
                            renewBtn.disabled = false;
                            renewBtn.classList.remove("success");
                        }}, 5000);
                    }} else if (response.status === 401 || response.status === 403) {{
                        showStatus("⚠️ Token expired or invalid. Using manual flow.", "error");
                        fallbackToManual(code);
                    }} else {{
                        const error = await response.text();
                        console.error("API error:", response.status, error);
                        showStatus("⚠️ API error. Using manual flow.", "error");
                        fallbackToManual(code);
                    }}
                }} catch (err) {{
                    console.error("Network error:", err);
                    showStatus("⚠️ Network error. Using manual flow.", "error");
                    fallbackToManual(code);
                }}
                
                renewBtn.disabled = false;
                if (renewBtn.textContent === "⏳ Sending...") {{
                    renewBtn.textContent = "🚀 Renew Now";
                }}
            }} else {{
                // No token - use manual flow
                fallbackToManual(code);
            }}
        }}
        
        async function fallbackToManual(code) {{
            const instructionsEl = document.getElementById("renewal-instructions");
            
            // Copy to clipboard
            try {{
                await navigator.clipboard.writeText(code);
            }} catch (err) {{
                const codeInput = document.getElementById("renewal-code");
                codeInput.select();
                document.execCommand('copy');
            }}
            
            // Show instructions
            instructionsEl.classList.remove("hidden");
            
            // Open GitHub in new tab
            window.open(GITHUB_WORKFLOW_URL, "_blank");
        }}
        
        function openGitHub() {{
            window.open(GITHUB_WORKFLOW_URL, "_blank");
        }}
        
        function showStatus(message, type) {{
            const statusEl = document.getElementById("renewal-status");
            statusEl.textContent = message;
            statusEl.className = `renewal-status ${{type}}`;
            
            // Auto-hide success messages
            if (type === "success") {{
                setTimeout(() => {{
                    statusEl.className = "renewal-status";
                }}, 5000);
            }}
        }}
        
        // Auto-refresh: poll status.json for state changes
        const CURRENT_DEADLINE = "{deadline}";
        const CURRENT_STAGE = "{stage}";
        const POLL_INTERVAL = 15000; // 15 seconds
        
        async function checkForStateChange() {{
            try {{
                const response = await fetch("status.json?t=" + Date.now(), {{
                    cache: "no-store"
                }});
                if (response.ok) {{
                    const status = await response.json();
                    // Reload if deadline or stage changed
                    if (status.deadline !== CURRENT_DEADLINE || status.stage !== CURRENT_STAGE) {{
                        console.log("State changed, reloading...");
                        showStatus("🔄 State updated! Refreshing...", "success");
                        setTimeout(() => location.reload(), 1000);
                    }}
                }}
            }} catch (e) {{
                // Silent fail - status.json might not exist or network issue
                console.debug("State check failed:", e);
            }}
        }}
        
        // Start polling (but not too aggressively)
        setInterval(checkForStateChange, POLL_INTERVAL);
        
        // Also check immediately after page becomes visible (user switches tabs back)
        document.addEventListener("visibilitychange", () => {{
            if (!document.hidden) {{
                checkForStateChange();
            }}
        }});
    </script>
</body>
</html>"""
        
        output_path = self.output_dir / "countdown.html"
        output_path.write_text(html)
        return output_path
    
    def _generate_articles(self, context: Dict[str, Any]) -> List[Path]:
        """
        Generate article pages from Editor.js JSON files.
        
        Articles are filtered by the content manifest based on current stage.
        Only articles visible at the current stage are generated.
        """
        try:
            from .editorjs import ContentManager
        except ImportError:
            return []
        
        content_dir = Path(__file__).parent.parent.parent / "content" / "articles"
        if not content_dir.exists():
            return []
        
        content_manager = ContentManager(content_dir)
        all_articles = content_manager.list_articles()
        
        if not all_articles:
            return []
        
        # Get manifest for visibility filtering
        manifest = context.get("manifest")
        current_stage = context.get("stage", "OK")
        
        # Create articles directory
        articles_dir = self.output_dir / "articles"
        articles_dir.mkdir(exist_ok=True)
        
        generated_paths = []
        published_articles = []
        skipped_articles = []
        
        for article_meta in all_articles:
            slug = article_meta["slug"]
            
            # Check visibility via manifest
            if manifest:
                # Simple check: is this article visible at current stage?
                if not manifest.is_article_visible(slug, current_stage):
                    skipped_articles.append(slug)
                    continue
            
            article = content_manager.get_article(slug)
            if not article:
                continue
            
            # Get manifest metadata if available
            manifest_entry = manifest.get_article(slug) if manifest else None
            is_pinned = manifest_entry.visibility.pin_to_top if manifest_entry else False
            
            published_articles.append({
                "slug": slug,
                "title": article["title"],
                "pinned": is_pinned,
            })
            
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
        
        # Log visibility filtering results
        if skipped_articles:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Skipped {len(skipped_articles)} articles not visible at stage {current_stage}: "
                f"{', '.join(skipped_articles)}"
            )
        
        # Also generate an articles index (using published_articles, not all)
        if generated_paths:
            index_html = self._generate_articles_index(published_articles, context)
            index_path = articles_dir / "index.html"
            index_path.write_text(index_html)
            generated_paths.append(index_path)
        
        return generated_paths
    
    def _generate_articles_index(
        self,
        articles: List[Dict],
        context: Dict[str, Any],
    ) -> str:
        """Generate index page listing all visible articles."""
        # Sort: pinned first, then by title
        sorted_articles = sorted(
            articles,
            key=lambda a: (not a.get("pinned", False), a.get("title", ""))
        )
        
        article_items = "\n".join(
            f'''<li class="{'pinned' if a.get('pinned') else ''}">
                <a href="{a['slug']}.html">{a['title']}</a>
                {'<span class="pin-badge">📌</span>' if a.get('pinned') else ''}
            </li>'''
            for a in sorted_articles
        )
        
        stage = context.get("stage", "OK")
        stage_behavior = context.get("stage_behavior")
        banner_html = ""
        if stage_behavior and stage_behavior.banner:
            banner_class = stage_behavior.banner_class or "info"
            banner_html = f'<div class="banner banner-{banner_class}">{stage_behavior.banner}</div>'
        
        return self._render_html_page(
            title=f"Articles — {context['project']}",
            content=f"""
            <header>
                <h1>Articles</h1>
                <a href="../index.html">← Back to Status</a>
            </header>
            
            {banner_html}
            
            <main>
                <ul class="article-list">
                    {article_items if sorted_articles else '<li class="empty">No articles available at this stage.</li>'}
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
