"""
Scaffold content — default articles regenerated after factory reset.

The templates here define the "How It Works" and "Full Disclosure Statement"
articles that ship with every new instance. They use the same Editor.js JSON
format as user-created articles.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Template definitions ───────────────────────────────────────────

def _timestamp_ms() -> int:
    """Current UTC timestamp in milliseconds (Editor.js format)."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _about_template() -> dict:
    """How It Works article template."""
    return {
        "time": _timestamp_ms(),
        "version": "2.28.2",
        "blocks": [
            {
                "type": "paragraph",
                "data": {
                    "text": "This project implements a continuity orchestration system "
                            "designed for scheduled operations with escalating disclosure."
                }
            },
            {
                "type": "header",
                "data": {"text": "How It Works", "level": 2}
            },
            {
                "type": "paragraph",
                "data": {
                    "text": "The system operates on a simple principle: maintain regular "
                            "check-ins to confirm continuity. If check-ins stop, the system "
                            "escalates through defined stages."
                }
            },
            {
                "type": "list",
                "data": {
                    "style": "ordered",
                    "items": [
                        "<b>OK</b> — Normal operation. All systems go.",
                        "<b>REMIND</b> — Deadline approaching. Reminders sent.",
                        "<b>PRE_RELEASE</b> — Final warning before escalation.",
                        "<b>PARTIAL</b> — Limited disclosure begins.",
                        "<b>FULL</b> — Complete disclosure activated.",
                    ]
                }
            },
            {
                "type": "header",
                "data": {"text": "Renewal Process", "level": 2}
            },
            {
                "type": "paragraph",
                "data": {
                    "text": "To extend the deadline and reset the timer, use the Check In "
                            "feature on the countdown page. You will need your renewal code "
                            "and can choose how many hours to extend."
                }
            },
        ],
    }


def _full_disclosure_template() -> dict:
    """Full Disclosure Statement article template."""
    return {
        "time": _timestamp_ms(),
        "version": "2.28.0",
        "blocks": [
            {
                "type": "header",
                "data": {"text": "Full Disclosure Statement", "level": 1}
            },
            {
                "type": "paragraph",
                "data": {
                    "text": "This document constitutes a complete disclosure of the information "
                            "held by the continuity orchestrator system. The automated release "
                            "has been triggered due to the expiration of the renewal deadline."
                }
            },
            {
                "type": "header",
                "data": {"text": "Background", "level": 2}
            },
            {
                "type": "paragraph",
                "data": {
                    "text": "The continuity system is designed to ensure the preservation and "
                            "eventual release of important information in cases where the "
                            "original custodian is unable to maintain control."
                }
            },
            {
                "type": "list",
                "data": {
                    "style": "unordered",
                    "items": [
                        "Automated deadlines ensure timely action",
                        "Multiple reminder stages allow for intervention",
                        "Full transparency is the ultimate goal",
                    ]
                }
            },
            {
                "type": "header",
                "data": {"text": "Timeline of Events", "level": 2}
            },
            {
                "type": "paragraph",
                "data": {"text": "The escalation followed the standard protocol:"}
            },
            {
                "type": "table",
                "data": {
                    "withHeadings": True,
                    "content": [
                        ["Stage", "Action", "Timing"],
                        ["REMIND_1", "Email notification", "T-6 hours"],
                        ["REMIND_2", "SMS alert", "T-1 hour"],
                        ["PRE_RELEASE", "Final warning", "T-15 minutes"],
                        ["PARTIAL", "Initial disclosure", "T+0"],
                        ["FULL", "Complete release", "T+24 hours"],
                    ]
                }
            },
            {
                "type": "quote",
                "data": {
                    "text": "The truth will set you free, but first it will make you uncomfortable.",
                    "caption": "Gloria Steinem",
                }
            },
            {
                "type": "warning",
                "data": {
                    "title": "Important Notice",
                    "message": "This content is released automatically. The original author "
                               "may no longer have the ability to provide additional context.",
                }
            },
            {"type": "delimiter", "data": {}},
            {
                "type": "paragraph",
                "data": {
                    "text": "<i>This document was generated by the Continuity Orchestrator.</i>"
                }
            },
        ],
    }


# ── Scaffold article registry ─────────────────────────────────────

SCAFFOLD_ARTICLES: Dict[str, dict] = {}
"""slug → {template_fn, manifest_entry}"""


def _register(slug: str, title: str, template_fn, *, min_stage: str = "FULL",
              include_in_nav: bool = True, description: str = "",
              tags: Optional[List[str]] = None):
    SCAFFOLD_ARTICLES[slug] = {
        "template_fn": template_fn,
        "manifest": {
            "slug": slug,
            "title": title,
            "visibility": {
                "min_stage": min_stage,
                "include_in_nav": include_in_nav,
                "pin_to_top": False,
            },
            "meta": {
                "description": description,
                "author": "System",
                "tags": tags or [],
            },
        },
    }


_register(
    "about",
    "How It Works",
    _about_template,
    min_stage="OK",
    description="Project overview and objectives",
    tags=["info"],
)

_register(
    "full_disclosure",
    "Full Disclosure Statement",
    _full_disclosure_template,
    min_stage="FULL",
    description="Template disclosure document",
    tags=["disclosure"],
)


# ── Public API ─────────────────────────────────────────────────────

def generate_scaffold(
    root: Path,
    *,
    encrypt: bool = True,
    overwrite: bool = False,
) -> Dict[str, str]:
    """
    Generate scaffold articles in content/articles/.

    Args:
        root: Project root directory.
        encrypt: If True and CONTENT_ENCRYPTION_KEY is set, encrypt articles.
        overwrite: If True, overwrite existing articles with same slug.

    Returns:
        {"created": [...], "skipped": [...]}
    """
    import yaml

    articles_dir = root / "content" / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "content" / "manifest.yaml"

    # Load encryption key if available
    passphrase = None
    if encrypt:
        try:
            from .crypto import get_encryption_key
            passphrase = get_encryption_key()
        except Exception:
            pass

    # Load existing manifest
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text()) or {}
    else:
        manifest = {"version": 1}
    existing_articles = manifest.get("articles", [])
    existing_slugs = {a["slug"] for a in existing_articles}

    created = []
    skipped = []

    for slug, info in SCAFFOLD_ARTICLES.items():
        dest = articles_dir / f"{slug}.json"

        if dest.exists() and not overwrite:
            skipped.append(slug)
            continue

        # Generate content
        content = info["template_fn"]()

        # Encrypt if key available
        if passphrase:
            try:
                from .crypto import encrypt_content
                content = encrypt_content(content, passphrase)
            except Exception as e:
                logger.warning(f"Could not encrypt scaffold article {slug}: {e}")

        # Write article file
        dest.write_text(json.dumps(content, indent=4) + "\n")

        # Add to manifest if not already there
        if slug not in existing_slugs:
            existing_articles.append(info["manifest"])
            existing_slugs.add(slug)

        created.append(slug)
        logger.info(f"Scaffold article created: {slug}")

    # Save updated manifest
    manifest["articles"] = existing_articles
    if "defaults" not in manifest:
        manifest["defaults"] = {
            "visibility": {"min_stage": "FULL", "include_in_nav": False}
        }
    if "stages" not in manifest:
        manifest["stages"] = {
            "OK": {"show_countdown": False},
            "REMIND_1": {"banner": "⏰ Reminder: Deadline approaching", "banner_class": "warning", "show_countdown": True},
            "REMIND_2": {"banner": "⚠️ Final warning: Action required", "banner_class": "warning", "show_countdown": True},
            "PRE_RELEASE": {"banner": "🔴 Pre-release mode active", "banner_class": "alert", "show_countdown": True},
            "PARTIAL": {"banner": "📢 Partial disclosure in effect", "banner_class": "critical", "show_countdown": True},
            "FULL": {"banner": "🚨 Full disclosure mode", "banner_class": "critical", "show_countdown": False},
        }
    manifest_path.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))

    return {"created": created, "skipped": skipped}
