"""
CLI backup commands — export, import, and restore snapshots.

Usage:
    python -m src.main backup-export [--include-articles] [--include-media]
    python -m src.main backup-import <archive>
    python -m src.main backup-restore <archive> [--state] [--audit] [--content]
    python -m src.main backup-list
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

# ── Archive creation ────────────────────────────────────────────────


def _count_article_encryption(articles_dir: Path) -> Tuple[int, int]:
    """Count encrypted vs plaintext articles."""
    encrypted = 0
    plaintext = 0
    if articles_dir.exists():
        for f in articles_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("encrypted"):
                    encrypted += 1
                else:
                    plaintext += 1
            except Exception:
                plaintext += 1
    return encrypted, plaintext


def create_backup_archive(
    root: Path,
    *,
    include_state: bool = True,
    include_audit: bool = True,
    include_articles: bool = False,
    include_media: bool = False,
    include_policy: bool = False,
    decrypt_content: bool = False,
    trigger: str = "manual_export",
) -> Tuple[Path, dict]:
    """
    Create a backup archive (.tar.gz) in the backups/ directory.

    Args:
        decrypt_content: If True, decrypt encrypted articles and media before
            adding them to the archive. Requires CONTENT_ENCRYPTION_KEY to be
            available. If decryption fails for any file, it falls back to
            exporting as-is.

    Returns (archive_path, manifest_dict).
    """
    import logging
    logger = logging.getLogger(__name__)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%S")
    backup_dir = root / "backups"
    backup_dir.mkdir(exist_ok=True)

    archive_name = f"backup_{timestamp}.tar.gz"
    archive_path = backup_dir / archive_name

    # Gather stats
    articles_dir = root / "content" / "articles"
    media_dir = root / "content" / "media"

    articles_enc, articles_plain = _count_article_encryption(articles_dir)
    article_files = list(articles_dir.glob("*.json")) if articles_dir.exists() else []
    media_files = list(media_dir.glob("*.enc")) if media_dir.exists() else []
    media_bytes = sum(f.stat().st_size for f in media_files)

    project_name = os.environ.get("PROJECT_NAME", "unknown")

    # If decrypting, resolve the encryption key
    passphrase = None
    if decrypt_content and (include_articles or include_media):
        try:
            from ..content.crypto import get_encryption_key
            passphrase = get_encryption_key()
            if not passphrase:
                logger.warning("decrypt_content=True but no CONTENT_ENCRYPTION_KEY — exporting encrypted")
                decrypt_content = False
        except Exception:
            logger.warning("Could not load encryption key — exporting encrypted")
            decrypt_content = False

    # Adjust stats if we're decrypting
    if decrypt_content:
        final_enc_count = 0
        final_plain_count = articles_enc + articles_plain
    else:
        final_enc_count = articles_enc
        final_plain_count = articles_plain

    manifest = {
        "format_version": 1,
        "created_at": now.isoformat(),
        "project": project_name,
        "trigger": trigger,
        "content_decrypted": decrypt_content,
        "includes": {
            "state": include_state,
            "audit": include_audit,
            "content_articles": include_articles,
            "content_media": include_media,
            "policy": include_policy,
        },
        "stats": {
            "article_count": len(article_files) if include_articles else 0,
            "articles_encrypted": final_enc_count if include_articles else 0,
            "articles_plaintext": final_plain_count if include_articles else 0,
            "media_count": len(media_files) if include_media else 0,
            "media_bytes": media_bytes if include_media else 0,
        },
        "encryption_notice": (
            "This archive contains decrypted (plaintext) content. "
            "Handle with extreme care — sensitive data is readable."
        ) if decrypt_content else (
            "This archive may contain encrypted content. "
            "Articles with encrypted=true and all media .enc files require "
            "the original CONTENT_ENCRYPTION_KEY to be usable. "
            "This key is NOT included — back it up separately using a "
            "secure method (vault, encrypted zip, etc.)."
        ),
    }

    with tarfile.open(archive_path, "w:gz") as tar:
        # Write manifest
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="backup_manifest.json")
        info.size = len(manifest_bytes)
        info.mtime = int(now.timestamp())
        tar.addfile(info, io.BytesIO(manifest_bytes))

        # State
        if include_state:
            state_path = root / "state" / "current.json"
            if state_path.exists():
                tar.add(str(state_path), arcname="state/current.json")

        # Audit
        if include_audit:
            audit_path = root / "audit" / "ledger.ndjson"
            if audit_path.exists():
                tar.add(str(audit_path), arcname="audit/ledger.ndjson")

        # Articles
        if include_articles:
            content_manifest = root / "content" / "manifest.yaml"
            if content_manifest.exists():
                tar.add(str(content_manifest), arcname="content/manifest.yaml")

            if decrypt_content and passphrase:
                from ..content.crypto import decrypt_content as _decrypt_article
                from ..content.crypto import is_encrypted
                for f in sorted(article_files):
                    try:
                        data = json.loads(f.read_text())
                        if is_encrypted(data):
                            decrypted = _decrypt_article(data, passphrase)
                            article_bytes = json.dumps(decrypted, indent=2, ensure_ascii=False).encode("utf-8")
                            info = tarfile.TarInfo(name=f"content/articles/{f.name}")
                            info.size = len(article_bytes)
                            info.mtime = int(now.timestamp())
                            tar.addfile(info, io.BytesIO(article_bytes))
                        else:
                            tar.add(str(f), arcname=f"content/articles/{f.name}")
                    except Exception as e:
                        logger.warning(f"Failed to decrypt article {f.name}, exporting encrypted: {e}")
                        tar.add(str(f), arcname=f"content/articles/{f.name}")
            else:
                for f in sorted(article_files):
                    tar.add(str(f), arcname=f"content/articles/{f.name}")

        # Media
        if include_media:
            media_manifest = media_dir / "manifest.json"
            if media_manifest.exists():
                tar.add(str(media_manifest), arcname="content/media/manifest.json")

            if decrypt_content and passphrase:
                from ..content.crypto import decrypt_file as _decrypt_media
                for f in sorted(media_files):
                    try:
                        envelope = f.read_bytes()
                        result = _decrypt_media(envelope, passphrase)
                        plaintext = result["plaintext"]
                        original_filename = result["filename"]
                        # Use media_id + original extension to preserve ID for import
                        media_id = f.stem  # e.g. "img_001" from "img_001.enc"
                        ext = Path(original_filename).suffix or ".bin"
                        archive_name = f"content/media/{media_id}{ext}"
                        info = tarfile.TarInfo(name=archive_name)
                        info.size = len(plaintext)
                        info.mtime = int(now.timestamp())
                        tar.addfile(info, io.BytesIO(plaintext))
                    except Exception as e:
                        logger.warning(f"Failed to decrypt media {f.name}, exporting encrypted: {e}")
                        tar.add(str(f), arcname=f"content/media/{f.name}")
            else:
                for f in sorted(media_files):
                    tar.add(str(f), arcname=f"content/media/{f.name}")

        # Policy
        if include_policy:
            policy_dir = root / "policy"
            if policy_dir.exists():
                for f in sorted(policy_dir.rglob("*")):
                    if f.is_file():
                        arcname = f"policy/{f.relative_to(policy_dir)}"
                        tar.add(str(f), arcname=arcname)

    return archive_path, manifest


# ── Archive reading ─────────────────────────────────────────────────


def read_archive_manifest(archive_path: Path) -> Optional[dict]:
    """Read the backup_manifest.json from an archive without extracting."""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember("backup_manifest.json")
            f = tar.extractfile(member)
            if f:
                return json.loads(f.read())
    except Exception:
        return None


def list_archive_contents(archive_path: Path) -> List[str]:
    """List all files in an archive."""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            return tar.getnames()
    except Exception:
        return []


# ── Restore logic (override) ───────────────────────────────────────


def restore_from_archive(
    root: Path,
    archive_path: Path,
    *,
    restore_state: bool = True,
    restore_audit: bool = True,
    restore_content: bool = True,
    restore_policy: bool = True,
) -> Dict[str, List[str]]:
    """
    Restore (OVERRIDE) files from an archive.

    State and audit are replaced entirely.
    Content articles and media are replaced entirely.

    Returns {"restored": [...], "skipped": [...]}.
    """
    restored: List[str] = []
    skipped: List[str] = []

    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            # Security: prevent path traversal
            if member.name.startswith("/") or ".." in member.name:
                skipped.append(f"{member.name} (blocked: path traversal)")
                continue

            # Skip manifest — it's metadata, not a restorable file
            if member.name == "backup_manifest.json":
                continue

            # Determine if this file should be restored
            should_restore = False
            if member.name.startswith("state/") and restore_state:
                should_restore = True
            elif member.name.startswith("audit/") and restore_audit:
                should_restore = True
            elif member.name.startswith("content/") and restore_content:
                should_restore = True
            elif member.name.startswith("policy/") and restore_policy:
                should_restore = True

            if should_restore:
                dest = root / member.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if member.isfile():
                    src = tar.extractfile(member)
                    if src:
                        dest.write_bytes(src.read())
                        restored.append(member.name)
                else:
                    skipped.append(f"{member.name} (not a file)")
            else:
                skipped.append(member.name)

    return {"restored": restored, "skipped": skipped}


# ── Import logic (additive) ────────────────────────────────────────


def import_from_archive(
    root: Path,
    archive_path: Path,
) -> Dict[str, List[str]]:
    """
    Import (ADDITIVE) content from an archive.

    Only content articles and media are imported.
    Existing articles (by slug) are skipped.
    Existing media (by id) are skipped.
    State and audit are never imported (use restore for that).

    Handles both encrypted and decrypted archives:
    - Encrypted archives: .enc media files imported as-is
    - Decrypted archives: plaintext media re-encrypted with local key,
      articles re-encrypted if local instance has encryption configured

    Returns {"imported": [...], "skipped": [...]}.
    """
    import logging
    logger = logging.getLogger(__name__)

    imported: List[str] = []
    skipped: List[str] = []

    articles_dir = root / "content" / "articles"
    media_dir = root / "content" / "media"
    articles_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    # Read manifest first to check if archive is decrypted
    manifest = read_archive_manifest(archive_path)
    is_decrypted = manifest.get("content_decrypted", False) if manifest else False

    # If importing decrypted content, we need the encryption key to re-encrypt
    passphrase = None
    if is_decrypted:
        try:
            from ..content.crypto import get_encryption_key
            passphrase = get_encryption_key()
            if not passphrase:
                logger.warning("Importing decrypted archive but no CONTENT_ENCRYPTION_KEY — "
                               "media will be stored unencrypted")
        except Exception:
            logger.warning("Could not load encryption key for re-encryption")

    with tarfile.open(archive_path, "r:gz") as tar:
        archive_articles = {}
        archive_media = {}
        archive_content_manifest = None
        archive_media_manifest = None

        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name:
                skipped.append(f"{member.name} (blocked: path traversal)")
                continue

            if member.name.startswith("content/articles/") and member.name.endswith(".json"):
                slug = Path(member.name).stem
                archive_articles[slug] = member
            elif member.name.startswith("content/media/") and member.name != "content/media/manifest.json":
                # Accept both .enc (encrypted) and other extensions (decrypted)
                media_id = Path(member.name).stem
                if member.isfile():
                    archive_media[media_id] = member
            elif member.name == "content/manifest.yaml":
                archive_content_manifest = member
            elif member.name == "content/media/manifest.json":
                archive_media_manifest = member

        # Import articles that don't exist locally
        for slug, member in sorted(archive_articles.items()):
            dest = articles_dir / f"{slug}.json"
            if dest.exists():
                skipped.append(f"article:{slug} (already exists)")
            else:
                src = tar.extractfile(member)
                if src:
                    content = src.read()
                    # If archive is decrypted and we have a key, re-encrypt articles
                    if is_decrypted and passphrase:
                        try:
                            from ..content.crypto import encrypt_content as _encrypt_article
                            data = json.loads(content)
                            encrypted = _encrypt_article(data, passphrase)
                            content = json.dumps(encrypted, indent=2).encode("utf-8")
                        except Exception as e:
                            logger.warning(f"Could not re-encrypt article {slug}: {e}")
                    dest.write_bytes(content)
                    imported.append(f"article:{slug}")

        # Import media that don't exist locally
        for media_id, member in sorted(archive_media.items()):
            dest = media_dir / f"{media_id}.enc"
            if dest.exists():
                skipped.append(f"media:{media_id} (already exists)")
            else:
                src = tar.extractfile(member)
                if src:
                    content = src.read()
                    # If archive is decrypted and we have a key, re-encrypt media
                    if is_decrypted and passphrase and not member.name.endswith(".enc"):
                        try:
                            from ..content.crypto import encrypt_file as _encrypt_media
                            original_filename = Path(member.name).name
                            # Guess MIME type from extension
                            import mimetypes
                            mime_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
                            encrypted = _encrypt_media(content, original_filename, mime_type, passphrase)
                            content = encrypted
                        except Exception as e:
                            logger.warning(f"Could not re-encrypt media {media_id}: {e}")
                            # Store as-is — operator will need to handle manually
                    dest.write_bytes(content)
                    imported.append(f"media:{media_id}")

        # Merge content manifest (add article entries that don't exist)
        if archive_content_manifest and imported:
            _merge_content_manifest(root, tar, archive_content_manifest, archive_articles)

        # Merge media manifest (add media entries that don't exist)
        if archive_media_manifest and any(i.startswith("media:") for i in imported):
            _merge_media_manifest(root, tar, archive_media_manifest, archive_media)

    return {"imported": imported, "skipped": skipped}


def _merge_content_manifest(root, tar, manifest_member, imported_articles):
    """Merge article entries from archive manifest into local manifest."""
    try:
        import yaml

        # Read archive manifest
        src = tar.extractfile(manifest_member)
        if not src:
            return
        archive_manifest = yaml.safe_load(src.read()) or {}
        archive_articles_list = archive_manifest.get("articles", [])

        # Read local manifest
        local_path = root / "content" / "manifest.yaml"
        if local_path.exists():
            local_manifest = yaml.safe_load(local_path.read_text()) or {}
        else:
            local_manifest = {"version": 1, "articles": []}

        local_slugs = {a["slug"] for a in local_manifest.get("articles", [])}

        # Add new entries
        for entry in archive_articles_list:
            if entry.get("slug") not in local_slugs:
                # Only add if the article file was actually imported
                article_dest = root / "content" / "articles" / f"{entry['slug']}.json"
                if article_dest.exists():
                    local_manifest.setdefault("articles", []).append(entry)

        local_path.write_text(yaml.dump(local_manifest, default_flow_style=False, sort_keys=False))
    except Exception:
        pass  # Best-effort manifest merge


def _merge_media_manifest(root, tar, manifest_member, imported_media):
    """Merge media entries from archive manifest into local manifest."""
    try:
        # Read archive manifest
        src = tar.extractfile(manifest_member)
        if not src:
            return
        archive_manifest = json.loads(src.read())
        archive_media_list = archive_manifest.get("media", [])

        # Read local manifest
        local_path = root / "content" / "media" / "manifest.json"
        if local_path.exists():
            local_manifest = json.loads(local_path.read_text())
        else:
            local_manifest = {"version": 1, "media": []}

        local_ids = {m["id"] for m in local_manifest.get("media", [])}

        # Add new entries
        for entry in archive_media_list:
            if entry.get("id") not in local_ids:
                # Only add if the media file was actually imported
                media_dest = root / "content" / "media" / f"{entry['id']}.enc"
                if media_dest.exists():
                    local_manifest.setdefault("media", []).append(entry)

        local_path.write_text(json.dumps(local_manifest, indent=2) + "\n")
    except Exception:
        pass  # Best-effort manifest merge


# ── CLI Commands ────────────────────────────────────────────────────


@click.command("backup-export")
@click.option("--include-state/--no-state", default=True, help="Include state file")
@click.option("--include-audit/--no-audit", default=True, help="Include audit log")
@click.option("--include-articles", is_flag=True, help="Include content articles")
@click.option("--include-media", is_flag=True, help="Include encrypted media files")
@click.pass_context
def backup_export(
    ctx: click.Context,
    include_state: bool,
    include_audit: bool,
    include_articles: bool,
    include_media: bool,
) -> None:
    """Export a backup archive (.tar.gz) to backups/."""
    root = ctx.obj["root"]

    if not any([include_state, include_audit, include_articles, include_media]):
        raise click.ClickException("Nothing to export. Specify at least one --include flag.")

    if include_media and not include_articles:
        click.echo("  ℹ️  --include-media implies --include-articles")
        include_articles = True

    archive_path, manifest = create_backup_archive(
        root,
        include_state=include_state,
        include_audit=include_audit,
        include_articles=include_articles,
        include_media=include_media,
        trigger="cli_export",
    )

    size_kb = archive_path.stat().st_size / 1024

    click.secho(f"\n✅ Export complete: {archive_path.name}", fg="green", bold=True)
    click.echo(f"  Path:     {archive_path}")
    click.echo(f"  Size:     {size_kb:.1f} KB")
    click.echo("  Contains:")
    if include_state:
        click.echo("    • State (current.json)")
    if include_audit:
        click.echo("    • Audit log (ledger.ndjson)")
    if include_articles:
        s = manifest["stats"]
        click.echo(f"    • Articles ({s['article_count']}: "
                   f"{s['articles_plaintext']} plaintext, "
                   f"{s['articles_encrypted']} encrypted)")
    if include_media:
        s = manifest["stats"]
        click.echo(f"    • Media ({s['media_count']} files, "
                   f"{s['media_bytes'] / 1024:.0f} KB)")

    if include_articles or include_media:
        click.secho(
            "\n  ⚠️  Encrypted content requires your CONTENT_ENCRYPTION_KEY.",
            fg="yellow",
        )
        click.echo("     Back it up separately using a secure method.")
        click.echo("     Never include .env or keys in the same archive.\n")


@click.command("backup-restore")
@click.argument("archive", type=click.Path(exists=True))
@click.option("--state/--no-state", "restore_state", default=True, help="Restore state file")
@click.option("--audit/--no-audit", "restore_audit", default=True, help="Restore audit log")
@click.option("--content/--no-content", "restore_content", default=True, help="Restore content")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def backup_restore(
    ctx: click.Context,
    archive: str,
    restore_state: bool,
    restore_audit: bool,
    restore_content: bool,
    yes: bool,
) -> None:
    """Restore (OVERRIDE) from a backup archive. Replaces current files."""
    root = ctx.obj["root"]
    archive_path = Path(archive)

    manifest = read_archive_manifest(archive_path)
    if not manifest:
        raise click.ClickException("Invalid archive: no backup_manifest.json found.")

    click.echo(f"\n📦 Archive: {archive_path.name}")
    click.echo(f"   Created: {manifest.get('created_at', '?')}")
    click.echo(f"   Project: {manifest.get('project', '?')}")
    click.echo(f"   Trigger: {manifest.get('trigger', '?')}")

    if not yes:
        click.secho("\n⚠️  RESTORE will OVERWRITE current files:", fg="yellow", bold=True)
        if restore_state:
            click.echo("  • state/current.json")
        if restore_audit:
            click.echo("  • audit/ledger.ndjson")
        if restore_content:
            click.echo("  • All content articles and media")
        if not click.confirm("\nProceed?"):
            click.echo("Cancelled.")
            return

    result = restore_from_archive(
        root, archive_path,
        restore_state=restore_state,
        restore_audit=restore_audit,
        restore_content=restore_content,
    )

    click.secho("\n✅ Restore complete", fg="green", bold=True)
    click.echo(f"  Restored: {len(result['restored'])} file(s)")
    for f in result["restored"]:
        click.echo(f"    ✓ {f}")
    if result["skipped"]:
        click.echo(f"  Skipped:  {len(result['skipped'])} file(s)")
        for f in result["skipped"]:
            click.echo(f"    · {f}")


@click.command("backup-import")
@click.argument("archive", type=click.Path(exists=True))
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def backup_import(
    ctx: click.Context,
    archive: str,
    yes: bool,
) -> None:
    """Import (ADDITIVE) content from a backup archive. Existing items are skipped."""
    root = ctx.obj["root"]
    archive_path = Path(archive)

    manifest = read_archive_manifest(archive_path)
    if not manifest:
        raise click.ClickException("Invalid archive: no backup_manifest.json found.")

    includes = manifest.get("includes", {})
    if not includes.get("content_articles") and not includes.get("content_media"):
        raise click.ClickException(
            "This archive has no content to import. "
            "Import only works with content (articles/media). "
            "Use 'backup-restore' for state/audit."
        )

    click.echo(f"\n📦 Archive: {archive_path.name}")
    click.echo(f"   Created: {manifest.get('created_at', '?')}")
    stats = manifest.get("stats", {})
    if stats.get("article_count"):
        click.echo(f"   Articles: {stats['article_count']} "
                   f"({stats.get('articles_plaintext', '?')} plaintext, "
                   f"{stats.get('articles_encrypted', '?')} encrypted)")
    if stats.get("media_count"):
        click.echo(f"   Media: {stats['media_count']} files "
                   f"({stats.get('media_bytes', 0) / 1024:.0f} KB)")

    if not yes:
        click.echo("\n  Import adds new items without removing existing ones.")
        click.echo("  If an article slug or media ID already exists, it is skipped.")
        if not click.confirm("\nProceed?"):
            click.echo("Cancelled.")
            return

    result = import_from_archive(root, archive_path)

    click.secho("\n✅ Import complete", fg="green", bold=True)
    click.echo(f"  Imported: {len(result['imported'])} item(s)")
    for item in result["imported"]:
        click.echo(f"    + {item}")
    if result["skipped"]:
        click.echo(f"  Skipped:  {len(result['skipped'])} item(s)")
        for item in result["skipped"]:
            click.echo(f"    · {item}")


@click.command("backup-list")
@click.pass_context
def backup_list(ctx: click.Context) -> None:
    """List available backup archives in backups/."""
    root = ctx.obj["root"]
    backup_dir = root / "backups"

    if not backup_dir.exists():
        click.echo("No backups directory found.")
        return

    archives = sorted(backup_dir.glob("backup_*.tar.gz"), reverse=True)

    if not archives:
        click.echo("No backups found.")
        return

    click.echo(f"\n📦 Backup archives ({len(archives)}):\n")
    for a in archives:
        size_kb = a.stat().st_size / 1024
        manifest = read_archive_manifest(a)
        if manifest:
            includes = manifest.get("includes", {})
            parts = []
            if includes.get("state"):
                parts.append("state")
            if includes.get("audit"):
                parts.append("audit")
            if includes.get("content_articles"):
                parts.append(f"{manifest['stats']['article_count']} articles")
            if includes.get("content_media"):
                parts.append(f"{manifest['stats']['media_count']} media")
            scope = " + ".join(parts) or "unknown"
            click.echo(f"  {a.name}  ({size_kb:.1f} KB)  [{scope}]")
            click.echo(f"    Created: {manifest['created_at']}  Trigger: {manifest['trigger']}")
        else:
            click.echo(f"  {a.name}  ({size_kb:.1f} KB)  [no manifest]")
        click.echo()
