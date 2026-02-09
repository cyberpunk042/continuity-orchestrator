"""
Admin API — Media management endpoints.

Blueprint: media_bp
Prefix: /api/content/media
Routes:
    GET    /api/content/media                  # List all media entries
    GET    /api/content/media/<media_id>       # Get single entry metadata
    POST   /api/content/media/upload           # Upload a media file (raw)
    GET    /api/content/media/<media_id>/preview  # Serve binary (decrypt if needed)
    DELETE /api/content/media/<media_id>       # Delete media file + manifest entry
    PATCH  /api/content/media/<media_id>       # Update metadata (min_stage, caption)
    POST   /api/content/media/<media_id>/toggle-encryption  # Encrypt ↔ decrypt
    GET    /api/content/media/health            # Check for missing files
    POST   /api/content/media/restore-large     # Restore large files from GitHub Release
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import Optional

from flask import Blueprint, Response, current_app, jsonify, request

media_bp = Blueprint("media", __name__)

logger = logging.getLogger(__name__)

# Maximum upload size: 50 MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# MIME type prefix → media ID prefix mapping
# Checked in order: exact matches first, then prefix (startswith) matches.
MIME_PREFIX_MAP = {
    # Exact matches
    "application/pdf":            "doc",
    "application/json":           "dat",
    "application/xml":            "dat",
    "application/zip":            "arc",
    "application/gzip":           "arc",
    "application/x-tar":          "arc",
    "application/x-7z-compressed": "arc",
    "message/rfc822":             "eml",
    # Prefix matches (type family)
    "image/":                     "img",
    "video/":                     "vid",
    "audio/":                     "aud",
    "text/":                      "txt",
}


# ── Helpers ──────────────────────────────────────────────────────


def _media_dir() -> Path:
    """Get the media directory path."""
    return current_app.config["PROJECT_ROOT"] / "content" / "media"


def _manifest_path() -> Path:
    """Get the media manifest file path."""
    return _media_dir() / "manifest.json"


def _load_manifest():
    """Load the media manifest."""
    from ..content.media import MediaManifest
    return MediaManifest.load(_manifest_path())


def _get_encryption_key() -> Optional[str]:
    """Get the content encryption key."""
    from ..content.crypto import get_encryption_key
    return get_encryption_key()


def _id_prefix_for_mime(mime_type: str) -> str:
    """Derive the media ID prefix from MIME type."""
    # Try exact match first, then prefix (startswith) match
    if mime_type in MIME_PREFIX_MAP:
        return MIME_PREFIX_MAP[mime_type]
    for pattern, id_prefix in MIME_PREFIX_MAP.items():
        if pattern.endswith("/") and mime_type.startswith(pattern):
            return id_prefix
    return "file"


# Release tag used for large media file backup
MEDIA_RELEASE_TAG = "media-vault"


def _upload_to_release_bg(media_id: str, enc_path: Path) -> None:
    """Upload a large .enc file to a GitHub Release in the background.

    Uses the `gh` CLI to attach the file as a release asset to the
    'media-vault' release. Creates the release if it doesn't exist.
    Runs as a background subprocess so it doesn't block the API response.
    """
    import subprocess
    import shutil

    if not shutil.which("gh"):
        logger.warning("[media-release] gh CLI not found — skipping release upload")
        return

    project_root = current_app.config["PROJECT_ROOT"]

    # Shell script: create release if missing, then upload asset
    # --clobber overwrites if the asset already exists (re-upload)
    script = (
        f'gh release view {MEDIA_RELEASE_TAG} > /dev/null 2>&1 || '
        f'gh release create {MEDIA_RELEASE_TAG} '
        f'--title "Media Vault" '
        f'--notes "Encrypted media files (large). Auto-managed by admin panel." '
        f'--latest=false; '
        f'gh release upload {MEDIA_RELEASE_TAG} '
        f'"{enc_path}" --clobber '
        f'&& echo "[media-release] Uploaded {media_id}" '
        f'|| echo "[media-release] Failed to upload {media_id}"'
    )

    logger.info(f"[media-release] Queueing background upload: {media_id}")
    try:
        subprocess.Popen(
            ["bash", "-c", script],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(f"[media-release] Failed to start upload: {e}")


def _restore_large_media(manifest) -> dict:
    """Download missing large .enc files from the 'media-vault' GitHub Release.

    Scans the manifest for entries with `storage == "large"` that don't have
    a local file on disk, then uses `gh release download` to restore them.

    Returns:
        Dict with 'restored', 'failed', 'skipped' lists and 'gh_available' bool.
    """
    import subprocess
    import shutil

    result = {
        "gh_available": bool(shutil.which("gh")),
        "restored": [],
        "failed": [],
        "skipped": [],
        "already_present": [],
    }

    if not result["gh_available"]:
        logger.warning("[media-restore] gh CLI not found — cannot restore")
        return result

    project_root = current_app.config["PROJECT_ROOT"]
    large_dir = project_root / "content" / "media" / "large"
    large_dir.mkdir(parents=True, exist_ok=True)

    for entry in manifest.entries:
        if entry.storage != "large":
            continue

        local_path = manifest.enc_path(entry.id)
        if local_path.exists():
            result["already_present"].append(entry.id)
            continue

        # Try to download from release
        asset_name = f"{entry.id}.enc"
        try:
            proc = subprocess.run(
                [
                    "gh", "release", "download", MEDIA_RELEASE_TAG,
                    "--pattern", asset_name,
                    "--dir", str(large_dir),
                    "--clobber",
                ],
                cwd=str(project_root),
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0 and local_path.exists():
                result["restored"].append(entry.id)
                logger.info(f"[media-restore] Restored {entry.id} from release")
            else:
                stderr = proc.stderr.strip()
                result["failed"].append({"id": entry.id, "error": stderr or "Download failed"})
                logger.warning(f"[media-restore] Failed to restore {entry.id}: {stderr}")
        except subprocess.TimeoutExpired:
            result["failed"].append({"id": entry.id, "error": "Download timed out (120s)"})
        except Exception as e:
            result["failed"].append({"id": entry.id, "error": str(e)})

    return result


# ── Routes ───────────────────────────────────────────────────────


@media_bp.route("", methods=["GET"])
def api_list_media():
    """List all media entries with metadata."""
    manifest = _load_manifest()
    key_available = _get_encryption_key() is not None

    entries = []
    for entry in manifest.entries:
        entry_dict = entry.to_dict()
        # Add computed fields
        entry_dict["enc_file_exists"] = manifest.enc_path(entry.id).exists()
        entries.append(entry_dict)

    return jsonify({
        "media": entries,
        "count": len(entries),
        "total_size_bytes": manifest.total_size_bytes,
        "encryption_available": key_available,
    })


@media_bp.route("/<media_id>", methods=["GET"])
def api_get_media(media_id: str):
    """Get a single media entry's metadata."""
    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    entry_dict = entry.to_dict()
    entry_dict["enc_file_exists"] = manifest.enc_path(entry.id).exists()
    entry_dict["media_uri"] = f"media://{entry.id}"

    return jsonify(entry_dict)


@media_bp.route("/health", methods=["GET"])
def api_media_health():
    """Check media file integrity — reports missing files and storage tiers."""
    import shutil

    manifest = _load_manifest()
    issues = []
    stats = {"total": 0, "present": 0, "missing": 0, "git": 0, "large": 0}

    for entry in manifest.entries:
        stats["total"] += 1
        tier = entry.storage or "git"
        stats[tier] = stats.get(tier, 0) + 1

        local_path = manifest.enc_path(entry.id)
        if local_path.exists():
            stats["present"] += 1
        else:
            stats["missing"] += 1
            issues.append({
                "id": entry.id,
                "original_name": entry.original_name,
                "storage": tier,
                "expected_path": str(local_path),
            })

    return jsonify({
        "healthy": stats["missing"] == 0,
        "stats": stats,
        "missing_files": issues,
        "gh_available": bool(shutil.which("gh")),
    })


@media_bp.route("/restore-large", methods=["POST"])
def api_restore_large():
    """Download missing large media files from the 'media-vault' GitHub Release."""
    manifest = _load_manifest()
    result = _restore_large_media(manifest)

    return jsonify({
        "success": True,
        **result,
    })


@media_bp.route("/reoptimize", methods=["POST"])
def api_reoptimize():
    """Re-optimize existing media files that were stored without optimization.

    Reads each file, runs through the optimizer, and if the result is
    smaller, replaces the file on disk and updates the manifest entry.
    Handles storage tier migration (e.g. git → git if file shrinks).
    """
    from ..content.media_optimize import optimize_media, classify_storage
    from ..content.crypto import is_encrypted_file, decrypt_file, encrypt_file, get_encryption_key

    manifest = _load_manifest()
    results = {"optimized": [], "skipped": [], "failed": [], "total": len(manifest.entries)}

    passphrase = get_encryption_key()

    for entry in list(manifest.entries):
        old_path = manifest.enc_path(entry.id)
        if not old_path.exists():
            results["failed"].append({"id": entry.id, "error": "File missing"})
            continue

        try:
            raw_data = old_path.read_bytes()

            # Decrypt if needed to get plaintext for optimization
            was_encrypted = is_encrypted_file(raw_data)
            if was_encrypted:
                if not passphrase:
                    results["skipped"].append({"id": entry.id, "reason": "Encrypted, no key"})
                    continue
                dec = decrypt_file(raw_data, passphrase)
                plaintext = dec["plaintext"]
            else:
                plaintext = raw_data

            # Run optimizer
            opt_data, opt_mime, opt_ext, was_optimized = optimize_media(
                plaintext, entry.mime_type
            )

            if not was_optimized:
                results["skipped"].append({"id": entry.id, "reason": "Already optimal"})
                continue

            # Re-encrypt if it was encrypted before
            if was_encrypted:
                store_data = encrypt_file(opt_data, passphrase)
            else:
                store_data = opt_data

            # Determine new storage tier
            new_tier = classify_storage(len(opt_data))
            old_tier = entry.storage or "git"

            # Update manifest entry
            new_name = f"{Path(entry.original_name).stem}{opt_ext}"
            sha256 = hashlib.sha256(store_data).hexdigest()

            manifest.update_entry(
                entry.id,
                mime_type=opt_mime,
                size_bytes=len(opt_data),
                sha256=sha256,
                original_name=new_name,
                storage=new_tier,
            )

            # Determine new path
            # Temporarily update storage to get correct enc_path
            entry.storage = new_tier
            new_path = manifest.enc_path(entry.id)
            new_path.parent.mkdir(parents=True, exist_ok=True)

            # Write optimized file
            new_path.write_bytes(store_data)

            # Remove old file if path changed (tier migration)
            if old_path != new_path and old_path.exists():
                old_path.unlink()

            pct = len(opt_data) / len(plaintext) * 100
            results["optimized"].append({
                "id": entry.id,
                "original_size": len(plaintext),
                "optimized_size": len(opt_data),
                "reduction_pct": round(100 - pct, 1),
                "old_mime": entry.mime_type,
                "new_mime": opt_mime,
                "old_tier": old_tier,
                "new_tier": new_tier,
            })

            logger.info(
                f"Re-optimized {entry.id}: {len(plaintext):,} → {len(opt_data):,} bytes "
                f"({pct:.0f}%), {old_tier} → {new_tier}"
            )

        except Exception as e:
            results["failed"].append({"id": entry.id, "error": str(e)})
            logger.error(f"Re-optimize failed for {entry.id}: {e}")

    manifest.save()

    # Backup any newly-large files to GitHub Releases
    for item in results["optimized"]:
        if item["new_tier"] == "large":
            _upload_to_release_bg(item["id"], manifest.enc_path(item["id"]))

    return jsonify({"success": True, **results})


@media_bp.route("/upload", methods=["POST"])
def api_upload_media():
    """
    Upload a media file with automatic optimization.

    Pipeline:
    1. Validate input
    2. Optimize if possible (images → WebP, video → H.264, audio → AAC)
    3. Classify storage tier based on optimized size
    4. Write to disk, update manifest
    5. Backup to GitHub Releases if large

    Encryption is handled later at article save time — the article's
    encrypt checkbox determines whether its referenced media gets encrypted.

    Accepts multipart/form-data:
        file: The file to upload (required)
        min_stage: Minimum disclosure stage (default: "FULL")
        caption: Optional caption text
        article_slug: Optional article to reference
    """
    # ── Validate request ──

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Read file data
    file_data = file.read()

    if not file_data:
        return jsonify({"error": "Empty file"}), 400

    if len(file_data) > MAX_UPLOAD_BYTES:
        size_mb = len(file_data) / (1024 * 1024)
        max_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        return jsonify({
            "error": f"File too large: {size_mb:.1f} MB (max {max_mb:.0f} MB)"
        }), 413

    # ── Determine metadata ──

    original_name = file.filename
    mime_type = (
        file.content_type
        or mimetypes.guess_type(original_name)[0]
        or "application/octet-stream"
    )

    # Form fields
    min_stage = request.form.get("min_stage", "FULL").upper()
    caption = request.form.get("caption", "")
    article_slug = request.form.get("article_slug", "")

    # Validate min_stage
    from ..content.media import STAGE_ORDER
    if min_stage not in STAGE_ORDER:
        valid = ", ".join(STAGE_ORDER.keys())
        return jsonify({
            "error": f"Invalid min_stage '{min_stage}'. Valid: {valid}"
        }), 400

    # ── Optimize media (images, video, audio) ──

    from ..content.media_optimize import optimize_media, classify_storage

    original_size = len(file_data)
    store_data, store_mime, store_ext, was_optimized = optimize_media(
        file_data, mime_type
    )

    # Update original_name extension if format changed
    if was_optimized and store_ext:
        stem = Path(original_name).stem
        original_name = f"{stem}{store_ext}"

    sha256 = hashlib.sha256(store_data).hexdigest()

    # ── Generate ID and classify storage ──

    storage_tier = classify_storage(len(store_data))

    manifest = _load_manifest()
    id_prefix = _id_prefix_for_mime(store_mime)
    media_id = manifest.next_id(id_prefix)

    # ── Update manifest (before write so enc_path resolves correctly) ──

    from ..content.media import MediaEntry
    entry = MediaEntry(
        id=media_id,
        original_name=original_name,
        mime_type=store_mime,
        size_bytes=len(store_data),
        sha256=sha256,
        encrypted=False,
        min_stage=min_stage,
        referenced_by=[article_slug] if article_slug else [],
        caption=caption,
        storage=storage_tier,
    )
    manifest.add_entry(entry)

    # Write (possibly optimized) file to disk
    enc_path = manifest.enc_path(media_id)
    enc_path.parent.mkdir(parents=True, exist_ok=True)
    enc_path.write_bytes(store_data)
    manifest.save()

    opt_info = ""
    if was_optimized:
        pct = len(store_data) / original_size * 100
        opt_info = f", optimized {original_size:,} → {len(store_data):,} ({pct:.0f}%)"
    logger.info(
        f"Media uploaded: {media_id} ({original_name}, "
        f"{len(store_data):,} bytes, stage={min_stage}, "
        f"storage={storage_tier}{opt_info})"
    )

    # Backup large files to GitHub Releases
    if storage_tier == "large":
        _upload_to_release_bg(media_id, enc_path)

    return jsonify({
        "success": True,
        "id": media_id,
        "media_uri": f"media://{media_id}",
        "original_name": original_name,
        "mime_type": store_mime,
        "size_bytes": len(store_data),
        "original_size_bytes": original_size,
        "optimized": was_optimized,
        "min_stage": min_stage,
        "storage": storage_tier,
    }), 201


@media_bp.route("/<media_id>/preview", methods=["GET"])
def api_preview_media(media_id: str):
    """
    Decrypt and serve a media file for admin preview.

    Returns the file binary data with the correct Content-Type header.
    For encrypted media, decrypts first. For unencrypted, serves directly.
    This endpoint is for admin preview only and should not be publicly exposed.
    """
    from ..content.crypto import decrypt_file, is_encrypted_file

    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    file_path = manifest.enc_path(media_id)
    if not file_path.exists():
        return jsonify({"error": f"Media file missing for '{media_id}'"}), 404

    raw_data = file_path.read_bytes()

    # If the file is unencrypted, serve directly
    if not entry.encrypted or not is_encrypted_file(raw_data):
        return Response(
            raw_data,
            mimetype=entry.mime_type,
            headers={
                "Content-Disposition": f'inline; filename="{entry.original_name}"',
                "Cache-Control": "no-store",
            },
        )

    # Encrypted — need key to decrypt
    key = _get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    try:
        result = decrypt_file(raw_data, key)
    except Exception as e:
        logger.error(f"Failed to decrypt media '{media_id}': {e}")
        return jsonify({"error": f"Decryption failed: {e}"}), 500

    return Response(
        result["plaintext"],
        mimetype=result["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{result["filename"]}"',
            "Cache-Control": "no-store",
        },
    )


@media_bp.route("/<media_id>", methods=["DELETE"])
def api_delete_media(media_id: str):
    """Delete a media file and its manifest entry."""
    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    # Delete the file
    file_path = manifest.enc_path(media_id)
    if file_path.exists():
        file_path.unlink()
        logger.debug(f"Deleted media file: {file_path}")

    # Remove from manifest
    manifest.remove_entry(media_id)
    manifest.save()

    logger.info(f"Media deleted: {media_id} ({entry.original_name})")

    return jsonify({
        "success": True,
        "id": media_id,
        "original_name": entry.original_name,
    })


@media_bp.route("/<media_id>/toggle-encryption", methods=["POST"])
def api_toggle_encryption(media_id: str):
    """Toggle a media file between encrypted and plaintext.

    If currently plaintext → encrypts it (requires CONTENT_ENCRYPTION_KEY).
    If currently encrypted → decrypts it (requires CONTENT_ENCRYPTION_KEY).
    """
    from ..content.crypto import encrypt_file, decrypt_file, is_encrypted_file

    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    file_path = manifest.enc_path(media_id)
    if not file_path.exists():
        return jsonify({"error": f"Media file missing for '{media_id}'"}), 404

    key = _get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    raw_data = file_path.read_bytes()
    actually_encrypted = is_encrypted_file(raw_data)

    try:
        if actually_encrypted:
            # Decrypt
            result = decrypt_file(raw_data, key)
            file_path.write_bytes(result["plaintext"])
            entry.encrypted = False
            logger.info(
                f"Media '{media_id}' decrypted "
                f"({len(raw_data):,} → {len(result['plaintext']):,} bytes)"
            )
        else:
            # Encrypt
            encrypted_data = encrypt_file(raw_data, entry.original_name, entry.mime_type, key)
            file_path.write_bytes(encrypted_data)
            entry.encrypted = True
            logger.info(
                f"Media '{media_id}' encrypted "
                f"({len(raw_data):,} → {len(encrypted_data):,} bytes)"
            )
    except Exception as e:
        logger.error(f"Toggle encryption failed for '{media_id}': {e}")
        return jsonify({"error": f"Operation failed: {e}"}), 500

    manifest.save()

    return jsonify({
        "success": True,
        "id": media_id,
        "encrypted": entry.encrypted,
    })


@media_bp.route("/<media_id>", methods=["PATCH"])
def api_update_media(media_id: str):
    """
    Update metadata for a media entry.

    Accepts JSON body with optional fields:
        min_stage: New minimum disclosure stage
        caption: New caption text
        article_slug: Add an article reference
        remove_article_slug: Remove an article reference
    """
    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    body = request.get_json(silent=True) or {}

    # Validate min_stage if provided
    if "min_stage" in body:
        from ..content.media import STAGE_ORDER
        new_stage = body["min_stage"].upper()
        if new_stage not in STAGE_ORDER:
            valid = ", ".join(STAGE_ORDER.keys())
            return jsonify({
                "error": f"Invalid min_stage '{new_stage}'. Valid: {valid}"
            }), 400
        manifest.update_entry(media_id, min_stage=new_stage)

    # Update caption if provided
    if "caption" in body:
        manifest.update_entry(media_id, caption=body["caption"])

    # Add article reference
    if "article_slug" in body:
        manifest.add_reference(media_id, body["article_slug"])

    # Remove article reference
    if "remove_article_slug" in body:
        manifest.remove_reference(media_id, body["remove_article_slug"])

    manifest.save()

    # Return updated entry
    updated = manifest.get(media_id)
    return jsonify({
        "success": True,
        **updated.to_dict(),
        "media_uri": f"media://{media_id}",
    })


# ── Editor.js integration ────────────────────────────────────────

# Threshold: images under this size are inlined as base64 data URIs
INLINE_THRESHOLD_BYTES = 100 * 1024  # 100 KB


@media_bp.route("/editor-upload", methods=["POST"])
def api_editor_upload():
    """
    Upload an image from Editor.js.

    Uses a hybrid strategy:
    - Files < 100 KB → returned as base64 data URI (inlined in article JSON)
    - Files ≥ 100 KB → encrypted via media vault → returns media:// URI

    Returns the Editor.js Image tool expected format:
        {success: 1, file: {url: "..."}}
    """
    import base64

    if "image" not in request.files:
        return jsonify({"success": 0, "error": "No image provided"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"success": 0, "error": "Empty filename"}), 400

    file_data = file.read()
    if not file_data:
        return jsonify({"success": 0, "error": "Empty file"}), 400

    if len(file_data) > MAX_UPLOAD_BYTES:
        return jsonify({"success": 0, "error": "File too large (max 10 MB)"}), 413

    original_name = file.filename
    mime_type = (
        file.content_type
        or mimetypes.guess_type(original_name)[0]
        or "application/octet-stream"
    )

    # ── Small file → inline as base64 data URI ──
    if len(file_data) < INLINE_THRESHOLD_BYTES:
        b64 = base64.b64encode(file_data).decode("ascii")
        data_uri = f"data:{mime_type};base64,{b64}"

        logger.info(
            f"Editor upload (inline): {original_name} "
            f"({len(file_data)} bytes, {mime_type})"
        )

        return jsonify({
            "success": 1,
            "file": {"url": data_uri},
            "inline": True,
            "size_bytes": len(file_data),
        })

    # ── Larger file → optimize if needed, store raw ──
    from ..content.media_optimize import optimize_media, classify_storage

    # Run universal optimization (images, video, audio)
    original_size = len(file_data)
    store_data, store_mime, store_ext, optimized = optimize_media(
        file_data, mime_type
    )

    # Update original_name extension if format changed
    if optimized and store_ext:
        stem = Path(original_name).stem
        original_name = f"{stem}{store_ext}"

    # Determine storage tier based on (possibly optimized) size
    storage_tier = classify_storage(len(store_data))

    sha256 = hashlib.sha256(store_data).hexdigest()
    manifest = _load_manifest()
    id_prefix = _id_prefix_for_mime(store_mime)
    media_id = manifest.next_id(id_prefix)

    # Register in manifest FIRST (so enc_path resolves correctly)
    from ..content.media import MediaEntry
    entry = MediaEntry(
        id=media_id,
        original_name=original_name,
        mime_type=store_mime,
        size_bytes=len(store_data),
        sha256=sha256,
        encrypted=False,
        min_stage=request.form.get("min_stage", "FULL").upper(),
        caption="",
        storage=storage_tier,
    )
    manifest.add_entry(entry)

    # Write (possibly optimized) file to disk
    enc_path = manifest.enc_path(media_id)
    enc_path.parent.mkdir(parents=True, exist_ok=True)
    enc_path.write_bytes(store_data)
    manifest.save()

    opt_info = ""
    if optimized:
        pct = len(store_data) / original_size * 100
        opt_info = f", optimized {original_size:,} → {len(store_data):,} ({pct:.0f}%)"
    logger.info(
        f"Editor upload ({storage_tier}): {media_id} ({original_name}, "
        f"{len(store_data):,} bytes{opt_info})"
    )

    # If stored in large/, trigger GitHub Release upload in background
    if storage_tier == "large":
        _upload_to_release_bg(media_id, enc_path)

    return jsonify({
        "success": 1,
        # Return preview URL for editor display; the JS save-hook
        # rewrites it back to media:// for storage.
        "file": {"url": f"/api/content/media/{media_id}/preview"},
        "inline": False,
        "media_id": media_id,
        "media_uri": f"media://{media_id}",
        "size_bytes": len(store_data),
        "original_size_bytes": original_size,
        "optimized": optimized,
        "storage": storage_tier,
    })


@media_bp.route("/editor-fetch-url", methods=["POST"])
def api_editor_fetch_url():
    """
    Validate a URL for the Editor.js Image tool "by URL" mode.

    Accepts: {url: "..."}
    Returns: {success: 1, file: {url: "..."}}

    Passes through media://, https://, and data: URIs as-is.
    """
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()

    if not url:
        return jsonify({"success": 0, "error": "No URL provided"}), 400

    # Accept media://, https://, http://, and data: URIs
    allowed_prefixes = ("media://", "https://", "http://", "data:")
    if not any(url.startswith(p) for p in allowed_prefixes):
        return jsonify({
            "success": 0,
            "error": "URL must start with https://, http://, media://, or data:",
        }), 400

    return jsonify({
        "success": 1,
        "file": {"url": url},
    })

