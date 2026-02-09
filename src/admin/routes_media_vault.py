"""
Admin API — Media vault endpoints (GitHub Release sync for large files).

Blueprint: media_vault_bp
Prefix: /api/content/media  (same prefix as media_bp — routes don't collide)
Routes:
    GET    /api/content/media/<media_id>/release-status   # Poll upload status
    POST   /api/content/media/<media_id>/release-cancel   # Cancel upload
    POST   /api/content/media/restore-large               # Restore missing large files
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify

media_vault_bp = Blueprint("media_vault", __name__)

logger = logging.getLogger(__name__)


# Release tag used for large media file backup
MEDIA_RELEASE_TAG = "media-vault"

# In-memory release upload status tracking
# { media_id: { "status": "pending"|"uploading"|"done"|"failed"|"cancelled", "message": str } }
_release_upload_status = {}
# Active subprocess references for cancellation
_release_active_procs = {}


# ── Helpers ──────────────────────────────────────────────────────


def _load_manifest():
    """Load the media manifest."""
    from ..content.media import MediaManifest
    manifest_path = current_app.config["PROJECT_ROOT"] / "content" / "media" / "manifest.json"
    return MediaManifest.load(manifest_path)


def upload_to_release_bg(media_id: str, enc_path: Path) -> None:
    """Upload a large .enc file to a GitHub Release in the background.

    Uses the `gh` CLI to attach the file as a release asset to the
    'media-vault' release. Creates the release if it doesn't exist.
    Runs as a background thread so progress can be tracked and cancelled.
    """
    import shutil
    import subprocess
    import threading
    import time

    if not shutil.which("gh"):
        logger.warning("[media-release] gh CLI not found — skipping release upload")
        _release_upload_status[media_id] = {
            "status": "failed", "message": "gh CLI not installed"
        }
        return

    project_root = current_app.config["PROJECT_ROOT"]
    size_mb = enc_path.stat().st_size / (1024 * 1024) if enc_path.exists() else 0

    _release_upload_status[media_id] = {
        "status": "pending",
        "message": f"Queued ({size_mb:.0f} MB)",
        "started_at": time.time(),
        "size_mb": size_mb,
    }

    def _do_upload():
        try:
            # Check if cancelled before starting
            if _release_upload_status.get(media_id, {}).get("status") == "cancelled":
                return

            _release_upload_status[media_id]["status"] = "uploading"
            _release_upload_status[media_id]["message"] = "Ensuring release exists..."

            # Step 1: Ensure release exists
            check = subprocess.run(
                ["gh", "release", "view", MEDIA_RELEASE_TAG],
                cwd=str(project_root),
                capture_output=True, text=True, timeout=30,
            )
            if _release_upload_status.get(media_id, {}).get("status") == "cancelled":
                return

            if check.returncode != 0:
                _release_upload_status[media_id]["message"] = "Creating release..."
                create = subprocess.run(
                    ["gh", "release", "create", MEDIA_RELEASE_TAG,
                     "--title", "Media Vault",
                     "--notes", "Encrypted media files (large). Auto-managed by admin panel.",
                     "--latest=false"],
                    cwd=str(project_root),
                    capture_output=True, text=True, timeout=60,
                )
                if create.returncode != 0:
                    raise RuntimeError(f"Failed to create release: {create.stderr[:200]}")

            if _release_upload_status.get(media_id, {}).get("status") == "cancelled":
                return

            # Step 2: Upload asset (use Popen so we can kill it on cancel)
            _release_upload_status[media_id]["message"] = f"Uploading {size_mb:.0f} MB..."
            logger.info(f"[media-release] Uploading {media_id} ({size_mb:.0f} MB)...")

            proc = subprocess.Popen(
                ["gh", "release", "upload", MEDIA_RELEASE_TAG,
                 str(enc_path), "--clobber"],
                cwd=str(project_root),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _release_active_procs[media_id] = proc

            # Wait for completion
            stdout, stderr = proc.communicate(timeout=3600)

            # Clean up proc reference
            _release_active_procs.pop(media_id, None)

            # Check if we were cancelled while waiting
            if _release_upload_status.get(media_id, {}).get("status") == "cancelled":
                return

            if proc.returncode == 0:
                elapsed = time.time() - _release_upload_status[media_id].get("started_at", time.time())
                _release_upload_status[media_id] = {
                    "status": "done",
                    "message": f"Uploaded in {elapsed:.0f}s",
                }
                logger.info(
                    f"[media-release] ✅ {media_id} uploaded ({size_mb:.0f} MB, {elapsed:.0f}s)"
                )
            else:
                err = stderr.decode(errors="replace")[:300] if stderr else "unknown error"
                _release_upload_status[media_id] = {
                    "status": "failed",
                    "message": f"gh upload failed: {err}",
                }
                logger.warning(f"[media-release] ❌ {media_id} failed: {err}")

        except subprocess.TimeoutExpired:
            _release_active_procs.pop(media_id, None)
            # Kill the process on timeout
            if proc and proc.poll() is None:
                proc.kill()
            _release_upload_status[media_id] = {
                "status": "failed",
                "message": "Upload timed out (>1 hour)",
            }
            logger.warning(f"[media-release] ❌ {media_id} timed out")

        except Exception as e:
            _release_active_procs.pop(media_id, None)
            _release_upload_status[media_id] = {
                "status": "failed",
                "message": str(e),
            }
            logger.error(f"[media-release] ❌ {media_id} error: {e}", exc_info=True)

    logger.info(f"[media-release] Queueing background upload: {media_id}")
    thread = threading.Thread(target=_do_upload, name=f"release-{media_id}", daemon=True)
    thread.start()


def _restore_large_media(manifest) -> dict:
    """Download missing large .enc files from the 'media-vault' GitHub Release.

    Scans the manifest for entries with `storage == "large"` that don't have
    a local file on disk, then uses `gh release download` to restore them.

    Returns:
        Dict with 'restored', 'failed', 'skipped' lists and 'gh_available' bool.
    """
    import shutil
    import subprocess

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


def delete_release_asset(media_id: str) -> None:
    """Delete a media asset from the GitHub Release (fire-and-forget)."""
    import shutil
    import subprocess

    if not shutil.which("gh"):
        return

    project_root = current_app.config["PROJECT_ROOT"]
    asset_name = f"{media_id}.enc"
    try:
        subprocess.Popen(
            ["gh", "release", "delete-asset", MEDIA_RELEASE_TAG,
             asset_name, "--yes"],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"[media-release] Queued asset deletion: {asset_name}")
    except Exception as e:
        logger.warning(f"[media-release] Could not delete asset: {e}")


# ── Routes ───────────────────────────────────────────────────────


@media_vault_bp.route("/<media_id>/release-status")
def api_release_status(media_id):
    """Poll the status of a background release upload."""
    status = _release_upload_status.get(media_id)
    if not status:
        return jsonify({"status": "unknown", "message": "No upload tracked"}), 404
    return jsonify(status)


@media_vault_bp.route("/<media_id>/release-cancel", methods=["POST"])
def api_release_cancel(media_id):
    """Cancel a running release upload."""
    status = _release_upload_status.get(media_id)
    if not status:
        return jsonify({"success": False, "message": "No upload tracked"}), 404

    if status.get("status") in ("done", "failed", "cancelled"):
        return jsonify({"success": True, "message": f"Already {status['status']}"})

    # Mark as cancelled
    _release_upload_status[media_id] = {
        "status": "cancelled",
        "message": "Cancelled by user",
    }

    # Kill active subprocess if running
    proc = _release_active_procs.pop(media_id, None)
    if proc and proc.poll() is None:
        proc.kill()
        logger.info(f"[media-release] Killed upload process for {media_id}")

    logger.info(f"[media-release] ⚠️ {media_id} cancelled by user")
    return jsonify({"success": True, "message": "Upload cancelled"})


@media_vault_bp.route("/restore-large", methods=["POST"])
def api_restore_large():
    """Download missing large media files from the 'media-vault' GitHub Release."""
    manifest = _load_manifest()
    result = _restore_large_media(manifest)

    return jsonify({
        "success": True,
        **result,
    })
