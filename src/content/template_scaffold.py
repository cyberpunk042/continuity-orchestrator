"""
Scaffold message templates — defaults regenerated after factory reset.

These are the message templates that ship with every new instance.
Each template is a plain-text or markdown file stored in templates/.
Unlike articles (Editor.js JSON), these are raw text with ${{variable}}
substitution markers.

Encryption support follows the same pattern as articles:
- If CONTENT_ENCRYPTION_KEY is set and encrypt=True, templates are
  written as .enc files (Fernet-encrypted at rest).
- The admin panel and adapters decrypt on read.
- No compression — templates are tiny text files.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


# ── Default template content ───────────────────────────────────────
#
# Each entry: relative path (from templates/) → raw text content.
# These are the factory defaults that get written on scaffold.

SCAFFOLD_TEMPLATES: Dict[str, str] = {}
"""rel_path → raw text content"""


def _register(rel_path: str, content: str) -> None:
    """Register a default template."""
    SCAFFOLD_TEMPLATES[rel_path] = content


# ── operator/reminder_basic.md (REMIND_1 — email) ─────────────────

_register("operator/reminder_basic.md", """\
# ⏰ Scheduled Reminder — Renewal Due

Your continuity system deadline is approaching.

**Project**: ${{project}}
**Time remaining**: ~${{time_to_deadline_hours}} hours (${{time_to_deadline_minutes}} min)
**Stage**: ${{stage}}

Please complete your renewal using your offline procedure when convenient.

No action is required if you have already renewed.

---
*Automated message from ${{project}} • Tick ${{tick_id}}*
""")


# ── operator/reminder_strong.md (REMIND_2 — email) ────────────────

_register("operator/reminder_strong.md", """\
# ⚠️ URGENT — Renewal Required Immediately

**Your deadline expires in approximately ${{time_to_deadline_minutes}} minutes.**

If renewal is not completed before the deadline, the system will escalate automatically. Once escalation begins, it cannot be stopped except by manual intervention.

**Project**: ${{project}}
**Current stage**: ${{stage}}
**Time remaining**: ${{time_to_deadline_minutes}} minutes

**You must renew now using your offline procedure.**

---
*This is an automated escalation alert from ${{project}} • Tick ${{tick_id}}*
*Do not reply to this email.*
""")


# ── operator/reminder_sms.txt (REMIND_2 — SMS) ────────────────────

_register("operator/reminder_sms.txt", """\
⚠️ URGENT: ${{project}} renewal expires in ~${{time_to_deadline_minutes}}min. Escalation is imminent. Renew now using offline procedure.
""")


# ── custodians/pre_release_notice.md (PRE_RELEASE — email) ────────

_register("custodians/pre_release_notice.md", """\
# Pre-Release Notice

You are receiving this notice because you are registered as a custodian.

A continuity process has entered the pre-release stage. This means:

- The operator has not renewed within the expected window
- Automated escalation will proceed if renewal does not occur
- Public actions may follow

**Current stage**: ${{stage}}  
**Overdue**: ${{overdue_minutes}} minutes

This is an informational notice. No action is required from you at this time.

---
*Automated notice from ${{project}}*
""")


# ── public/partial_notice.md (PARTIAL — X/Reddit/etc) ─────────────

_register("public/partial_notice.md", """\
A previously configured continuity process has entered an automated phase.

Stage: ${{stage}}

Additional information may become available if escalation continues.
""")


# ── public/full_release.md (FULL — X/Reddit/etc) ──────────────────

_register("public/full_release.md", """\
# Continuity Process — Full Execution

This publication marks the final execution stage of a preconfigured continuity process.

The process operated according to predeclared rules and published timelines.

## Status

- **Stage**: ${{stage}}
- **Execution time**: ${{now_iso}}
- **Overdue by**: ${{overdue_hours}} hours

Associated documents and artifacts are now available through public channels.

---
*This is an automated publication.*
""")


# ── articles/full_article.md (FULL — article_publish) ─────────────

_register("articles/full_article.md", """\
# Continuity Execution Summary

## Overview

This article consolidates materials released as part of an automated continuity process.

The process operated according to predeclared rules and timelines. All artifacts referenced here were generated automatically upon confirmed non-renewal.

## Timeline

- **System mode**: ${{mode}}
- **Final stage**: ${{stage}}
- **Execution timestamp**: ${{now_iso}}

## What This Means

This publication exists because a preconfigured countdown was not renewed within the allowed window.

The system was designed to ensure visibility and continuity of information in the event of non-renewal.

## Associated Artifacts

The following materials have been made available:

- Public notices on configured platforms
- Webhook signals to registered observers
- GitHub surface documents

## Technical Details

- **Plan ID**: ${{plan_id}}
- **Tick ID**: ${{tick_id}}

---

*This article was generated automatically by ${{project}}.*
""")


# ── Public API ─────────────────────────────────────────────────────


def generate_template_scaffold(
    root: Path,
    *,
    encrypt: bool = True,
    overwrite: bool = False,
) -> Dict[str, List[str]]:
    """
    Regenerate default message templates in templates/.

    Args:
        root: Project root directory.
        encrypt: If True and CONTENT_ENCRYPTION_KEY is set, encrypt templates
                 at rest as .enc files. Plain-text originals are not kept.
        overwrite: If True, overwrite existing templates with same path.

    Returns:
        {"created": [...], "skipped": [...]}
    """
    templates_dir = root / "templates"

    # Load encryption key if available
    passphrase = None
    if encrypt:
        try:
            from .crypto import get_encryption_key
            passphrase = get_encryption_key()
        except Exception:
            pass

    created: List[str] = []
    skipped: List[str] = []

    for rel_path, content in SCAFFOLD_TEMPLATES.items():
        dest = templates_dir / rel_path

        # Check for both plain and encrypted versions
        dest_enc = dest.parent / (dest.name + ".enc")
        if (dest.exists() or dest_enc.exists()) and not overwrite:
            skipped.append(rel_path)
            continue

        # Ensure parent directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Encrypt if key available
        if passphrase:
            try:
                from .crypto import encrypt_file as _encrypt

                encrypted = _encrypt(
                    content.encode("utf-8"),
                    dest.name,
                    "text/plain",
                    passphrase,
                )
                dest_enc.write_bytes(encrypted)
                # Remove plain version if it exists (upgrade path)
                if dest.exists():
                    dest.unlink()
                created.append(rel_path)
                logger.info(f"Scaffold template created (encrypted): {rel_path}")
                continue
            except Exception as e:
                logger.warning(
                    f"Could not encrypt scaffold template {rel_path}: {e}"
                )
                # Fall through to plaintext write

        # Write plaintext
        dest.write_text(content)
        created.append(rel_path)
        logger.info(f"Scaffold template created: {rel_path}")

    return {"created": created, "skipped": skipped}
