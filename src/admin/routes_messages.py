"""
Admin API — Message template management endpoints.

Blueprint: messages_bp
Prefix: /api/content/messages

Routes:
    GET  /api/content/messages/list           # List all messages (from plan + templates)
    GET  /api/content/messages/templates      # List all template files on disk
    GET  /api/content/messages/<name>         # Get a single template's content
    POST /api/content/messages/save           # Create or update a message
    DELETE /api/content/messages/<name>       # Delete a message
    POST /api/content/messages/preview        # Render a real adapter preview
    GET  /api/content/messages/recipients     # Get subscriber/custodian email lists
    POST /api/content/messages/recipients     # Update subscriber/custodian email lists
    GET  /api/content/messages/variables      # Get available template variables
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Blueprint, current_app, jsonify, request

messages_bp = Blueprint("messages", __name__)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────


def _project_root() -> Path:
    return current_app.config["PROJECT_ROOT"]


def _templates_dir() -> Path:
    return _project_root() / "templates"


def _plan_path() -> Path:
    return _project_root() / "policy" / "plans" / "default.yaml"


def _state_path() -> Path:
    return _project_root() / "state" / "current.json"


# Map channel/audience to template subdirectory
CHANNEL_TO_DIR = {
    "operator": "operator",
    "custodians": "custodians",
    "subscribers": "subscribers",
    "public": "public",
}

# Adapter to file extension
ADAPTER_TO_EXT = {
    "email": ".md",
    "sms": ".txt",
    "x": ".md",
    "reddit": ".md",
    "article_publish": ".md",
    "webhook": ".md",
    "github_surface": ".md",
}

# Adapter icons for the UI
ADAPTER_ICONS = {
    "email": "📧",
    "sms": "📱",
    "x": "🐦",
    "reddit": "🤖",
    "article_publish": "📰",
    "webhook": "🔗",
    "github_surface": "📂",
}

# Valid stages
VALID_STAGES = ["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]

# Valid adapters (template-based only)
VALID_ADAPTERS = ["email", "sms", "x", "reddit"]

# Stage themes — mirrors the adapter's STAGE_THEMES for preview
STAGE_THEMES = {
    "OK": {
        "accent": "#22c55e", "bg": "#f0fdf4", "border": "#86efac",
        "icon": "✅", "label": "All Clear",
    },
    "REMIND_1": {
        "accent": "#6366f1", "bg": "#eef2ff", "border": "#a5b4fc",
        "icon": "⏰", "label": "Scheduled Reminder",
    },
    "REMIND_2": {
        "accent": "#f59e0b", "bg": "#fffbeb", "border": "#fcd34d",
        "icon": "⚠️", "label": "Urgent — Action Required",
    },
    "PRE_RELEASE": {
        "accent": "#ef4444", "bg": "#fef2f2", "border": "#fca5a5",
        "icon": "🔴", "label": "Final Warning",
    },
    "PARTIAL": {
        "accent": "#dc2626", "bg": "#fef2f2", "border": "#f87171",
        "icon": "💀", "label": "Disclosure Active",
    },
    "FULL": {
        "accent": "#991b1b", "bg": "#fef2f2", "border": "#dc2626",
        "icon": "💀", "label": "Full Disclosure",
    },
}


def _load_plan() -> dict:
    """Load the default plan YAML as a raw dict."""
    plan_file = _plan_path()
    if not plan_file.exists():
        return {}
    return yaml.safe_load(plan_file.read_text(encoding="utf-8")) or {}


def _save_plan(plan_data: dict) -> None:
    """Write the plan dict back to YAML."""
    plan_file = _plan_path()
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        yaml.dump(plan_data, default_flow_style=False, sort_keys=False,
                  allow_unicode=True),
        encoding="utf-8",
    )


def _find_template_file(template_name: str) -> Optional[Path]:
    """
    Find a template file by name, searching all subdirectories.
    Mirrors the logic in TemplateResolver.resolve().
    """
    templates_dir = _templates_dir()
    search_dirs = ["operator", "custodians", "subscribers", "public", "articles", ""]
    extensions = [".md", ".txt", ".html"]

    for subdir in search_dirs:
        base = templates_dir / subdir if subdir else templates_dir
        if not base.exists():
            continue
        for ext in extensions:
            path = base / f"{template_name}{ext}"
            if path.exists():
                return path

    return None


def _template_dir_for_channel(channel: str) -> str:
    """Get the template subdirectory for a channel."""
    return CHANNEL_TO_DIR.get(channel, "operator")


def _generate_action_id(adapter: str, channel: str, template_name: str) -> str:
    """Generate a deterministic action ID from message properties."""
    return f"{adapter}_{channel}_{template_name}"


def _load_state() -> dict:
    """Load the current state JSON."""
    state_file = _state_path()
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text(encoding="utf-8"))


def _save_state(state_data: dict) -> None:
    """Write the state dict back to JSON."""
    state_file = _state_path()
    state_file.write_text(
        json.dumps(state_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _get_template_variables() -> List[dict]:
    """
    Return the list of available template variables with descriptions.
    These come from build_template_context() in src/templates/context.py.
    """
    return [
        {"name": "project", "description": "Project name"},
        {"name": "plan_id", "description": "Plan ID"},
        {"name": "tick_id", "description": "Current tick ID"},
        {"name": "now_iso", "description": "Current timestamp (ISO)"},
        {"name": "stage", "description": "Current escalation stage"},
        {"name": "stage_entered_at", "description": "When current stage started"},
        {"name": "time_to_deadline_minutes", "description": "Minutes to deadline"},
        {"name": "time_to_deadline_hours", "description": "Hours to deadline"},
        {"name": "overdue_minutes", "description": "Minutes overdue"},
        {"name": "overdue_hours", "description": "Hours overdue"},
        {"name": "mode", "description": "Operating mode"},
        {"name": "armed", "description": "Whether system is armed"},
        {"name": "action_id", "description": "Current action ID"},
        {"name": "action_channel", "description": "Target channel"},
    ]


def _build_sample_context() -> dict:
    """Build a sample context for preview rendering, using real state data."""
    state = _load_state()
    meta = state.get("meta", {})
    timer = state.get("timer", {})
    escalation = state.get("escalation", {})
    mode = state.get("mode", {})

    ttd = timer.get("time_to_deadline_minutes") or 120
    overdue = timer.get("overdue_minutes") or 0

    return {
        "project": meta.get("project", "my-project"),
        "plan_id": meta.get("plan_id", "default"),
        "tick_id": "T-PREVIEW",
        "now_iso": timer.get("now_iso", "2026-01-01T00:00:00"),
        "stage": escalation.get("state", "REMIND_1"),
        "stage_entered_at": escalation.get("state_entered_at_iso", "2026-01-01T00:00:00"),
        "time_to_deadline_minutes": ttd,
        "time_to_deadline_hours": ttd // 60,
        "overdue_minutes": overdue,
        "overdue_hours": overdue // 60,
        "mode": mode.get("name", "renewable_countdown"),
        "armed": str(mode.get("armed", True)).lower(),
        "action_id": "preview_action",
        "action_channel": "operator",
    }


def _render_variables(content: str, context: dict) -> str:
    """Substitute ${{variable}} placeholders in content."""
    rendered = content
    for key, value in context.items():
        rendered = rendered.replace(f"${{{{{key}}}}}", str(value))
    return rendered


def _markdown_to_html(text: str) -> str:
    """
    Convert markdown to email-safe HTML.
    Mirrors ResendEmailAdapter._markdown_to_html().
    """
    html = text

    # Headers
    html = re.sub(
        r'^### (.+)$',
        r'<h3 style="font-size:14px;font-weight:700;color:#1e293b;margin:16px 0 8px;">\1</h3>',
        html, flags=re.MULTILINE,
    )
    html = re.sub(
        r'^## (.+)$',
        r'<h2 style="font-size:16px;font-weight:700;color:#1e293b;margin:18px 0 8px;">\1</h2>',
        html, flags=re.MULTILINE,
    )
    html = re.sub(
        r'^# (.+)$',
        r'<h1 style="font-size:18px;font-weight:700;color:#1e293b;margin:20px 0 10px;">\1</h1>',
        html, flags=re.MULTILINE,
    )

    # Bold and italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # Links
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" style="color:#6366f1;">\1</a>', html)

    # Horizontal rules
    html = re.sub(
        r'^---+$',
        '<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">',
        html, flags=re.MULTILINE,
    )

    # Paragraphs
    html = re.sub(r'\n\n', '</p><p style="margin:0 0 12px;">', html)
    html = f'<p style="margin:0 0 12px;">{html}</p>'

    # Line breaks
    html = html.replace('\n', '<br>')

    return html


def _parse_template_content(content: str, stage: str) -> tuple:
    """
    Parse template content into subject and body.
    Mirrors ResendEmailAdapter._parse_template().
    """
    if not content:
        return f"[{stage}] Continuity Alert", ""

    lines = content.strip().split("\n")

    if lines[0].startswith("# "):
        subject = lines[0][2:].strip()
        body = "\n".join(lines[1:]).strip()
    elif lines[0].startswith("## "):
        subject = lines[0][3:].strip()
        body = "\n".join(lines[1:]).strip()
    else:
        subject = f"[{stage}] Continuity Alert"
        body = content

    return subject, body


def _build_email_preview_html(content: str, stage: str, context: dict) -> str:
    """
    Build a full styled HTML email preview.
    Mirrors ResendEmailAdapter._build_styled_email() exactly.
    """
    subject, body_md = _parse_template_content(content, stage)
    theme = STAGE_THEMES.get(stage, STAGE_THEMES["REMIND_1"])
    body_html = _markdown_to_html(body_md)

    project = context.get("project", "my-project")
    tick_id = context.get("tick_id", "T-PREVIEW")

    ttd = context.get("time_to_deadline_minutes", 120)
    if ttd > 0:
        hours = ttd // 60
        mins = ttd % 60
        time_display = f"{hours}h {mins}m remaining"
    else:
        overdue = context.get("overdue_minutes", 0)
        time_display = f"⚠️ {overdue}m overdue"

    if ttd > 360:
        bar_pct = 100
    elif ttd > 0:
        bar_pct = max(5, int((ttd / 360) * 100))
    else:
        bar_pct = 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

        <!-- Header -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{theme['bg']};border-radius:12px 12px 0 0;border-top:4px solid {theme['accent']};">
            <tr><td style="padding:24px 28px 16px;">
              <div style="font-size:28px;line-height:1;">{theme['icon']}</div>
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:{theme['accent']};font-weight:700;margin-top:8px;">{theme['label']}</div>
              <div style="font-size:20px;font-weight:700;color:#1a1a2e;margin-top:6px;line-height:1.3;">{subject}</div>
            </td></tr>
          </table>
        </td></tr>

        <!-- Urgency bar -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;">
            <tr><td style="padding:12px 28px;">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600;">{time_display}</div>
              <div style="background:#e2e8f0;border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:{theme['accent']};width:{bar_pct}%;height:6px;border-radius:4px;transition:width 0.3s;"></div>
              </div>
            </td></tr>
          </table>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
            <tr><td style="padding:24px 28px;color:#334155;font-size:15px;line-height:1.7;">
              {body_html}
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:0 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;border-radius:0 0 12px 12px;">
            <tr><td style="padding:16px 28px;">
              <div style="font-size:11px;color:#94a3b8;line-height:1.6;">
                Automated message from <strong>{project}</strong><br>
                Tick {tick_id} • Stage {stage}<br>
                This is a system notification — do not reply.
              </div>
            </td></tr>
          </table>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_sms_preview(content: str) -> dict:
    """Build an SMS preview with segment counting."""
    # Strip markdown headers for SMS
    lines = content.strip().split("\n")
    while lines and lines[0].startswith("#"):
        lines = lines[1:]
    plain = "\n".join(lines).strip()

    char_count = len(plain)
    if char_count <= 160:
        segments = 1
    else:
        segments = (char_count + 152) // 153  # UDH header reduces per-segment

    return {
        "plain_text": plain,
        "char_count": char_count,
        "segments": segments,
        "over_limit": char_count > 480,  # 3 segments max for Twilio
    }


def _build_x_preview(content: str) -> dict:
    """Build an X/Twitter preview with char counting."""
    # Strip headers, take first meaningful text
    lines = content.strip().split("\n")
    while lines and lines[0].startswith("#"):
        lines = lines[1:]
    text = "\n".join(lines).strip()

    return {
        "text": text,
        "char_count": len(text),
        "over_limit": len(text) > 280,
    }


def _build_reddit_preview(content: str) -> dict:
    """Build a Reddit preview with title/body split."""
    lines = content.strip().split("\n")
    title = ""
    body_lines = []

    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body_lines = lines[1:]
    elif lines and lines[0].startswith("## "):
        title = lines[0][3:].strip()
        body_lines = lines[1:]
    else:
        title = lines[0] if lines else "(no title)"
        body_lines = lines[1:]

    return {
        "title": title,
        "body": "\n".join(body_lines).strip(),
    }


# ── Routes ───────────────────────────────────────────────────────


@messages_bp.route("/list", methods=["GET"])
def api_list_messages():
    """
    List all messages derived from the policy plan + template files.
    """
    plan = _load_plan()
    stages = plan.get("stages", {})

    messages = []

    for stage_name in VALID_STAGES:
        stage_data = stages.get(stage_name, {})
        actions = stage_data.get("actions", [])

        for action in actions:
            template_name = action.get("template")
            adapter = action.get("adapter", "unknown")

            if not template_name:
                # Non-template actions (webhook payloads, artifacts)
                if adapter not in VALID_ADAPTERS:
                    continue

            channel = action.get("channel", "operator")

            # Check if template file exists
            template_file = (
                _find_template_file(template_name) if template_name else None
            )
            content_exists = template_file is not None and template_file.exists()

            # Determine file path relative to templates dir
            rel_path = None
            if template_file and template_file.exists():
                try:
                    rel_path = str(template_file.relative_to(_templates_dir()))
                except ValueError:
                    rel_path = template_file.name

            messages.append({
                "action_id": action.get("id", ""),
                "stage": stage_name,
                "adapter": adapter,
                "channel": channel,
                "template": template_name or "",
                "content_exists": content_exists,
                "file_path": rel_path,
                "icon": ADAPTER_ICONS.get(adapter, "📄"),
                "constraints": action.get("constraints", {}),
            })

    return jsonify({"messages": messages})


@messages_bp.route("/templates", methods=["GET"])
def api_list_templates():
    """
    List all template files on disk, regardless of whether they're in the plan.

    Returns files grouped by subdirectory, excluding html/ and css/
    (those are site templates and styles, not message templates).
    """
    templates_dir = _templates_dir()
    result = []
    excluded_dirs = {"html", "css"}  # site templates, not messages

    # Scan subdirectories
    for child in sorted(templates_dir.iterdir()):
        if child.is_dir():
            if child.name in excluded_dirs:
                continue
            for f in sorted(child.iterdir()):
                if f.is_file() and f.suffix in {".md", ".txt"}:
                    result.append({
                        "name": f.stem,
                        "path": str(f.relative_to(templates_dir)),
                        "dir": child.name,
                        "ext": f.suffix,
                    })
        elif child.is_file() and child.suffix in {".md", ".txt"}:
            # Root-level file (e.g., README.md) — skip README
            if child.stem.lower() == "readme":
                continue
            result.append({
                "name": child.stem,
                "path": child.name,
                "dir": "",
                "ext": child.suffix,
            })

    return jsonify({"templates": result})


@messages_bp.route("/<name>", methods=["GET"])
def api_get_message(name: str):
    """Get a template's content by name."""
    template_file = _find_template_file(name)

    if not template_file or not template_file.exists():
        return jsonify({"error": f"Template '{name}' not found"}), 404

    content = template_file.read_text(encoding="utf-8")

    try:
        rel_path = str(template_file.relative_to(_templates_dir()))
    except ValueError:
        rel_path = template_file.name

    return jsonify({
        "name": name,
        "content": content,
        "file_path": rel_path,
        "extension": template_file.suffix,
    })


@messages_bp.route("/save", methods=["POST"])
def api_save_message():
    """
    Create or update a message (template + plan action).

    Body: {
        "template": "my_template_name",
        "stage": "REMIND_1",
        "adapter": "email",
        "channel": "operator",
        "content": "# Subject line\n\nBody text here...",
        "action_id": "optional_custom_id"
    }
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    template_name = body.get("template", "").strip()
    stage = body.get("stage", "").strip()
    adapter = body.get("adapter", "").strip()
    channel = body.get("channel", "").strip()
    content = body.get("content", "")
    action_id = body.get("action_id", "").strip()

    # Validation
    if not template_name:
        return jsonify({"error": "Template name is required"}), 400
    if stage not in VALID_STAGES:
        return jsonify({"error": f"Invalid stage: {stage}"}), 400
    if adapter not in VALID_ADAPTERS:
        return jsonify({"error": f"Invalid adapter: {adapter}"}), 400
    if not channel:
        return jsonify({"error": "Channel is required"}), 400

    # Sanitize template name
    if not re.match(r'^[a-zA-Z0-9_]+$', template_name):
        return jsonify({"error": "Template name must be alphanumeric with underscores"}), 400

    # Determine file path
    subdir = _template_dir_for_channel(channel)
    ext = ADAPTER_TO_EXT.get(adapter, ".md")
    template_dir = _templates_dir() / subdir
    template_dir.mkdir(parents=True, exist_ok=True)
    template_file = template_dir / f"{template_name}{ext}"

    # Write template content
    template_file.write_text(content, encoding="utf-8")
    logger.info(f"Saved template: {template_file}")

    # Generate action ID if not provided
    if not action_id:
        action_id = _generate_action_id(adapter, channel, template_name)

    # Update the policy plan
    plan = _load_plan()
    stages_data = plan.setdefault("stages", {})
    stage_data = stages_data.setdefault(
        stage, {"description": f"{stage} stage.", "actions": []}
    )
    actions = stage_data.setdefault("actions", [])

    # Find existing action by ID or create new
    existing = None
    for a in actions:
        if a.get("id") == action_id:
            existing = a
            break

    if existing:
        existing["adapter"] = adapter
        existing["channel"] = channel
        existing["template"] = template_name
    else:
        actions.append({
            "id": action_id,
            "adapter": adapter,
            "channel": channel,
            "template": template_name,
        })

    _save_plan(plan)
    logger.info(f"Updated plan: stage={stage}, action_id={action_id}")

    return jsonify({
        "success": True,
        "template": template_name,
        "action_id": action_id,
        "stage": stage,
        "file_path": f"{subdir}/{template_name}{ext}",
    })


@messages_bp.route("/<name>", methods=["DELETE"])
def api_delete_message(name: str):
    """Delete a message (template file + plan action)."""
    action_id = request.args.get("action_id", "")

    # Find and delete template file
    template_file = _find_template_file(name)
    file_deleted = False
    if template_file and template_file.exists():
        template_file.unlink()
        file_deleted = True
        logger.info(f"Deleted template file: {template_file}")

    # Remove action from plan
    action_removed = False
    if action_id:
        plan = _load_plan()
        for stage_name, stage_data in plan.get("stages", {}).items():
            actions = stage_data.get("actions", [])
            original_len = len(actions)
            stage_data["actions"] = [
                a for a in actions if a.get("id") != action_id
            ]
            if len(stage_data["actions"]) < original_len:
                action_removed = True
                logger.info(
                    f"Removed action '{action_id}' from stage '{stage_name}'"
                )

        if action_removed:
            _save_plan(plan)

    return jsonify({
        "success": file_deleted or action_removed,
        "template_deleted": file_deleted,
        "action_removed": action_removed,
    })


@messages_bp.route("/preview", methods=["POST"])
def api_preview_message():
    """
    Render a REAL adapter-specific preview.

    Body: { "content": "...", "adapter": "email", "stage": "REMIND_1" }

    Returns:
    - For email: { rendered, html, subject, adapter }
    - For sms:   { rendered, plain_text, char_count, segments, adapter }
    - For x:     { rendered, text, char_count, over_limit, adapter }
    - For reddit: { rendered, title, body, adapter }
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    content = body.get("content", "")
    adapter = body.get("adapter", "email")
    stage = body.get("stage", "REMIND_1")

    # Build context and render variables
    context = _build_sample_context()
    # Override stage in context to match what the user selected
    context["stage"] = stage
    rendered = _render_variables(content, context)

    result = {
        "rendered": rendered,
        "adapter": adapter,
        "stage": stage,
    }

    if adapter == "email":
        subject, _ = _parse_template_content(rendered, stage)
        html = _build_email_preview_html(rendered, stage, context)
        result["html"] = html
        result["subject"] = subject

    elif adapter == "sms":
        sms = _build_sms_preview(rendered)
        result.update(sms)

    elif adapter == "x":
        x_data = _build_x_preview(rendered)
        result.update(x_data)

    elif adapter == "reddit":
        reddit_data = _build_reddit_preview(rendered)
        result.update(reddit_data)

    return jsonify(result)


@messages_bp.route("/recipients", methods=["GET"])
def api_get_recipients():
    """Get the subscriber and custodian email lists from state routing."""
    state = _load_state()
    routing = state.get("integrations", {}).get("routing", {})

    return jsonify({
        "subscriber_emails": routing.get("subscriber_emails", []),
        "custodian_emails": routing.get("custodian_emails", []),
        "operator_email": routing.get("operator_email", ""),
    })


@messages_bp.route("/recipients", methods=["POST"])
def api_update_recipients():
    """Update subscriber and/or custodian email lists in state routing."""
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    state = _load_state()
    if not state:
        return jsonify({"error": "State file not found"}), 404

    routing = state.setdefault("integrations", {}).setdefault("routing", {})

    updated = []

    if "subscriber_emails" in body:
        emails = body["subscriber_emails"]
        if not isinstance(emails, list):
            return jsonify({"error": "subscriber_emails must be a list"}), 400
        clean = [e.strip() for e in emails if isinstance(e, str) and "@" in e.strip()]
        routing["subscriber_emails"] = clean
        updated.append(f"subscriber_emails ({len(clean)})")

    if "custodian_emails" in body:
        emails = body["custodian_emails"]
        if not isinstance(emails, list):
            return jsonify({"error": "custodian_emails must be a list"}), 400
        clean = [e.strip() for e in emails if isinstance(e, str) and "@" in e.strip()]
        routing["custodian_emails"] = clean
        updated.append(f"custodian_emails ({len(clean)})")

    _save_state(state)
    logger.info(f"Updated recipients: {', '.join(updated)}")

    return jsonify({
        "success": True,
        "updated": updated,
        "subscriber_emails": routing.get("subscriber_emails", []),
        "custodian_emails": routing.get("custodian_emails", []),
    })


@messages_bp.route("/variables", methods=["GET"])
def api_get_variables():
    """Return the list of available template variables."""
    return jsonify({"variables": _get_template_variables()})
