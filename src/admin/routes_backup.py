"""
Admin API — Backup management endpoints.

Blueprint: backup_bp
Prefix: /api/backup
Routes:
    POST /api/backup/export                   # Create backup archive
    GET  /api/backup/list                     # List available backups
    GET  /api/backup/download/<filename>      # Download archive file
    POST /api/backup/upload                   # Upload archive for import/restore
    POST /api/backup/restore                  # Restore (override) from archive
    POST /api/backup/import                   # Import (additive) content from archive
    GET  /api/backup/preview/<filename>       # Preview archive contents
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

backup_bp = Blueprint("backup", __name__)

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return current_app.config["PROJECT_ROOT"]


def _backup_dir() -> Path:
    d = _project_root() / "backups"
    d.mkdir(exist_ok=True)
    return d


def _safe_filename(name: str) -> bool:
    """Validate that a filename is safe (no path traversal)."""
    return bool(re.match(r"^backup_\d{8}T\d{6}\.tar\.gz$", name))


# ── Export ──────────────────────────────────────────────────────────


@backup_bp.route("/export", methods=["POST"])
def api_export():
    """Create a backup archive."""
    from ..cli.backup import create_backup_archive

    data = request.json or {}

    archive_path, manifest = create_backup_archive(
        _project_root(),
        include_state=data.get("include_state", True),
        include_audit=data.get("include_audit", True),
        include_articles=data.get("include_articles", False),
        include_media=data.get("include_media", False),
        include_policy=data.get("include_policy", False),
        include_templates=data.get("include_templates", False),
        decrypt_content=data.get("decrypt_content", False),
        trigger="admin_export",
    )

    return jsonify({
        "success": True,
        "filename": archive_path.name,
        "size_bytes": archive_path.stat().st_size,
        "manifest": manifest,
        "download_url": f"/api/backup/download/{archive_path.name}",
    })


# ── List ────────────────────────────────────────────────────────────


@backup_bp.route("/list", methods=["GET"])
def api_list():
    """List available backup archives."""
    from ..cli.backup import read_archive_manifest

    backup_dir = _backup_dir()
    archives = sorted(backup_dir.glob("backup_*.tar.gz"), reverse=True)

    result = []
    for a in archives:
        entry = {
            "filename": a.name,
            "size_bytes": a.stat().st_size,
        }
        manifest = read_archive_manifest(a)
        if manifest:
            entry["manifest"] = manifest
        result.append(entry)

    return jsonify({
        "backups": result,
    })


# ── Download ────────────────────────────────────────────────────────


@backup_bp.route("/download/<filename>", methods=["GET"])
def api_download(filename: str):
    """Download a backup archive file."""
    if not _safe_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    file_path = _backup_dir() / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    return send_file(
        file_path,
        mimetype="application/gzip",
        as_attachment=True,
        download_name=filename,
    )


# ── Preview ─────────────────────────────────────────────────────────


@backup_bp.route("/preview/<filename>", methods=["GET"])
def api_preview(filename: str):
    """Preview the manifest of a backup archive."""
    from ..cli.backup import list_archive_contents, read_archive_manifest

    if not _safe_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    file_path = _backup_dir() / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    manifest = read_archive_manifest(file_path)
    contents = list_archive_contents(file_path)

    return jsonify({
        "filename": filename,
        "size_bytes": file_path.stat().st_size,
        "manifest": manifest,
        "files": contents,
    })


# ── Upload ──────────────────────────────────────────────────────────


@backup_bp.route("/upload", methods=["POST"])
def api_upload():
    """Upload a backup archive for import or restore."""
    from ..cli.backup import read_archive_manifest

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.endswith(".tar.gz"):
        return jsonify({"error": "File must be a .tar.gz archive"}), 400

    # Save to backups/
    backup_dir = _backup_dir()

    # Sanitize filename — keep the original name if it matches our pattern,
    # otherwise generate a safe name
    if _safe_filename(file.filename):
        dest_name = file.filename
    else:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest_name = f"backup_{ts}.tar.gz"

    dest = backup_dir / dest_name
    file.save(str(dest))

    # Validate it has a manifest
    manifest = read_archive_manifest(dest)
    if not manifest:
        dest.unlink()  # Remove invalid file
        return jsonify({"error": "Invalid archive: no backup_manifest.json found"}), 400

    return jsonify({
        "success": True,
        "filename": dest_name,
        "size_bytes": dest.stat().st_size,
        "manifest": manifest,
    })


# ── Restore (override) ─────────────────────────────────────────────


@backup_bp.route("/restore", methods=["POST"])
def api_restore():
    """Restore (OVERRIDE) current files from a backup archive."""
    from ..cli.backup import read_archive_manifest, restore_from_archive

    data = request.json or {}
    filename = data.get("filename")

    if not filename or not _safe_filename(filename):
        return jsonify({"error": "Invalid or missing filename"}), 400

    file_path = _backup_dir() / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    manifest = read_archive_manifest(file_path)
    if not manifest:
        return jsonify({"error": "Invalid archive"}), 400

    result = restore_from_archive(
        _project_root(),
        file_path,
        restore_state=data.get("restore_state", True),
        restore_audit=data.get("restore_audit", True),
        restore_content=data.get("restore_content", True),
        restore_policy=data.get("restore_policy", True),
    )

    return jsonify({
        "success": True,
        "restored": result["restored"],
        "skipped": result["skipped"],
    })


# ── Import (additive) ──────────────────────────────────────────────


@backup_bp.route("/import", methods=["POST"])
def api_import():
    """Import (ADDITIVE) content from a backup archive."""
    from ..cli.backup import import_from_archive, read_archive_manifest

    data = request.json or {}
    filename = data.get("filename")

    if not filename or not _safe_filename(filename):
        return jsonify({"error": "Invalid or missing filename"}), 400

    file_path = _backup_dir() / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    manifest = read_archive_manifest(file_path)
    if not manifest:
        return jsonify({"error": "Invalid archive"}), 400

    includes = manifest.get("includes", {})
    if (not includes.get("content_articles")
            and not includes.get("content_media")
            and not includes.get("content_templates")):
        return jsonify({
            "error": "This archive has no content to import. "
                     "Import only works with content (articles/media/templates). "
                     "Use restore for state/audit."
        }), 400

    result = import_from_archive(_project_root(), file_path)

    return jsonify({
        "success": True,
        "imported": result["imported"],
        "skipped": result["skipped"],
    })
