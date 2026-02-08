"""
Admin API — Media management endpoints.

Blueprint: media_bp
Prefix: /api/content/media
Routes:
    GET    /api/content/media                  # List all media entries
    GET    /api/content/media/<media_id>       # Get single entry metadata
    POST   /api/content/media/upload           # Upload + encrypt a media file
    GET    /api/content/media/<media_id>/preview  # Decrypt + serve binary
    DELETE /api/content/media/<media_id>       # Delete media file + manifest entry
    PATCH  /api/content/media/<media_id>       # Update metadata (min_stage, caption)
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
MIME_PREFIX_MAP = {
    "image/": "img",
    "video/": "vid",
    "audio/": "aud",
    "application/pdf": "doc",
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
    for prefix_pattern, id_prefix in MIME_PREFIX_MAP.items():
        if mime_type.startswith(prefix_pattern) or mime_type == prefix_pattern:
            return id_prefix
    return "media"


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


@media_bp.route("/upload", methods=["POST"])
def api_upload_media():
    """
    Upload and encrypt a media file.

    Accepts multipart/form-data:
        file: The file to upload (required)
        min_stage: Minimum disclosure stage (default: "FULL")
        caption: Optional caption text
        article_slug: Optional article to reference
    """
    from ..content.crypto import encrypt_file

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

    # ── Check encryption key ──

    key = _get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    # ── Determine metadata ──

    original_name = file.filename
    mime_type = (
        file.content_type
        or mimetypes.guess_type(original_name)[0]
        or "application/octet-stream"
    )
    sha256 = hashlib.sha256(file_data).hexdigest()

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

    # ── Generate ID and encrypt ──

    manifest = _load_manifest()
    id_prefix = _id_prefix_for_mime(mime_type)
    media_id = manifest.next_id(id_prefix)

    try:
        encrypted_data = encrypt_file(file_data, original_name, mime_type, key)
    except Exception as e:
        logger.error(f"Failed to encrypt media file: {e}")
        return jsonify({"error": f"Encryption failed: {e}"}), 500

    # ── Write encrypted file ──

    enc_path = manifest.enc_path(media_id)
    enc_path.parent.mkdir(parents=True, exist_ok=True)
    enc_path.write_bytes(encrypted_data)

    # ── Update manifest ──

    from ..content.media import MediaEntry
    entry = MediaEntry(
        id=media_id,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=len(file_data),
        sha256=sha256,
        min_stage=min_stage,
        referenced_by=[article_slug] if article_slug else [],
        caption=caption,
    )
    manifest.add_entry(entry)
    manifest.save()

    logger.info(
        f"Media uploaded: {media_id} ({original_name}, "
        f"{len(file_data)} bytes, stage={min_stage})"
    )

    return jsonify({
        "success": True,
        "id": media_id,
        "media_uri": f"media://{media_id}",
        "original_name": original_name,
        "mime_type": mime_type,
        "size_bytes": len(file_data),
        "encrypted_size_bytes": len(encrypted_data),
        "min_stage": min_stage,
    }), 201


@media_bp.route("/<media_id>/preview", methods=["GET"])
def api_preview_media(media_id: str):
    """
    Decrypt and serve a media file for admin preview.

    Returns the decrypted binary data with the correct Content-Type header.
    This endpoint is for admin preview only and should not be publicly exposed.
    """
    from ..content.crypto import decrypt_file

    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    enc_path = manifest.enc_path(media_id)
    if not enc_path.exists():
        return jsonify({"error": f"Encrypted file missing for '{media_id}'"}), 404

    key = _get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    try:
        envelope = enc_path.read_bytes()
        result = decrypt_file(envelope, key)
    except Exception as e:
        logger.error(f"Failed to decrypt media '{media_id}': {e}")
        return jsonify({"error": f"Decryption failed: {e}"}), 500

    return Response(
        result["plaintext"],
        mimetype=result["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{result["filename"]}"',
            "Cache-Control": "no-store",  # Never cache decrypted media
        },
    )


@media_bp.route("/<media_id>", methods=["DELETE"])
def api_delete_media(media_id: str):
    """Delete a media file and its manifest entry."""
    manifest = _load_manifest()
    entry = manifest.get(media_id)

    if not entry:
        return jsonify({"error": f"Media '{media_id}' not found"}), 404

    # Delete the encrypted file
    enc_path = manifest.enc_path(media_id)
    if enc_path.exists():
        enc_path.unlink()
        logger.debug(f"Deleted encrypted file: {enc_path}")

    # Remove from manifest
    manifest.remove_entry(media_id)
    manifest.save()

    logger.info(f"Media deleted: {media_id} ({entry.original_name})")

    return jsonify({
        "success": True,
        "id": media_id,
        "original_name": entry.original_name,
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

    # ── Larger file → optimize if needed, encrypt, store ──
    from ..content.crypto import encrypt_file
    from ..content.media_optimize import (
        should_optimize, optimize_image, classify_storage,
        LARGE_THRESHOLD_BYTES,
    )

    key = _get_encryption_key()
    if not key:
        return jsonify({
            "success": 0,
            "error": "CONTENT_ENCRYPTION_KEY not set — cannot encrypt images",
        }), 400

    # Auto-optimize large images (resize + convert to WebP)
    store_data = file_data
    store_mime = mime_type
    optimized = False
    if should_optimize(len(file_data), mime_type):
        store_data, store_mime, _ext = optimize_image(file_data, mime_type)
        optimized = len(store_data) < len(file_data)
        if optimized:
            logger.info(
                f"Editor upload: optimized {original_name} "
                f"{len(file_data):,} → {len(store_data):,} bytes "
                f"({store_mime})"
            )

    # Determine storage tier based on (possibly optimized) size
    storage_tier = classify_storage(len(store_data))
    # Files that came through optimization are at least 100KB,
    # so tier will be "git" or "large" (never "inline")

    sha256 = hashlib.sha256(store_data).hexdigest()
    manifest = _load_manifest()
    id_prefix = _id_prefix_for_mime(store_mime)
    media_id = manifest.next_id(id_prefix)

    try:
        encrypted_data = encrypt_file(store_data, original_name, store_mime, key)
    except Exception as e:
        logger.error(f"Editor upload encryption failed: {e}")
        return jsonify({"success": 0, "error": f"Encryption failed: {e}"}), 500

    # Register in manifest FIRST (so enc_path resolves correctly)
    from ..content.media import MediaEntry
    entry = MediaEntry(
        id=media_id,
        original_name=original_name,
        mime_type=store_mime,
        size_bytes=len(store_data),
        sha256=sha256,
        min_stage=request.form.get("min_stage", "FULL").upper(),
        caption="",
        storage=storage_tier,
    )
    manifest.add_entry(entry)

    # Write encrypted file to the correct location
    enc_path = manifest.enc_path(media_id)
    enc_path.parent.mkdir(parents=True, exist_ok=True)
    enc_path.write_bytes(encrypted_data)
    manifest.save()

    logger.info(
        f"Editor upload ({storage_tier}): {media_id} ({original_name}, "
        f"{len(store_data):,} bytes → {len(encrypted_data):,} enc, "
        f"optimized={optimized})"
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
        "original_size_bytes": len(file_data),
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

