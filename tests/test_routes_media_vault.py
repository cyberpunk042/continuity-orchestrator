"""
Tests for admin media vault API routes.

Tests the /api/content/media/* vault endpoints (release-status, release-cancel,
restore-large) and the helper functions (upload_to_release_bg, delete_release_asset).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")

# Direct access to the in-memory status dict for test setup
from src.admin.routes_media_vault import (
    _release_active_procs,
    _release_upload_status,
)


# ── Release Status ───────────────────────────────────────────────────


class TestReleaseStatus:

    def setup_method(self):
        _release_upload_status.clear()
        _release_active_procs.clear()

    def test_unknown_media_id(self, client):
        resp = client.get("/api/content/media/unknown-id/release-status")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "unknown"

    def test_pending_status(self, client):
        _release_upload_status["test-001"] = {
            "status": "pending",
            "message": "Queued (5 MB)",
        }
        resp = client.get("/api/content/media/test-001/release-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "pending"

    def test_done_status(self, client):
        _release_upload_status["test-002"] = {
            "status": "done",
            "message": "Uploaded in 30s",
        }
        resp = client.get("/api/content/media/test-002/release-status")
        data = resp.get_json()
        assert data["status"] == "done"


# ── Release Cancel ───────────────────────────────────────────────────


class TestReleaseCancel:

    def setup_method(self):
        _release_upload_status.clear()
        _release_active_procs.clear()

    def test_cancel_unknown_id(self, client):
        resp = client.post("/api/content/media/unknown-id/release-cancel")
        assert resp.status_code == 404

    def test_cancel_pending_upload(self, client):
        _release_upload_status["test-003"] = {
            "status": "uploading",
            "message": "Uploading 10 MB...",
        }
        resp = client.post("/api/content/media/test-003/release-cancel")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert _release_upload_status["test-003"]["status"] == "cancelled"

    def test_cancel_kills_subprocess(self, client):
        _release_upload_status["test-004"] = {
            "status": "uploading",
            "message": "In progress",
        }
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        _release_active_procs["test-004"] = mock_proc

        resp = client.post("/api/content/media/test-004/release-cancel")
        assert resp.status_code == 200
        mock_proc.kill.assert_called_once()
        assert "test-004" not in _release_active_procs

    def test_cancel_already_done(self, client):
        _release_upload_status["test-005"] = {
            "status": "done",
            "message": "Uploaded",
        }
        resp = client.post("/api/content/media/test-005/release-cancel")
        data = resp.get_json()
        assert data["success"] is True
        assert "Already done" in data["message"]

    def test_cancel_already_failed(self, client):
        _release_upload_status["test-006"] = {
            "status": "failed",
            "message": "Error",
        }
        resp = client.post("/api/content/media/test-006/release-cancel")
        data = resp.get_json()
        assert data["success"] is True
        assert "Already failed" in data["message"]


# ── Restore Large ────────────────────────────────────────────────────


class TestRestoreLarge:

    def test_restore_no_gh(self, client, app):
        mock_manifest = MagicMock()
        mock_manifest.entries = []

        with patch("src.content.media.MediaManifest.load", return_value=mock_manifest), \
             patch("shutil.which", return_value=None):
            resp = client.post("/api/content/media/restore-large")
        data = resp.get_json()
        assert data["success"] is True
        assert data["gh_available"] is False

    def test_restore_nothing_missing(self, client, app):
        entry = MagicMock(storage="large", id="img-001")
        mock_manifest = MagicMock()
        mock_manifest.entries = [entry]

        # Create the .enc file so it's "already present"
        large_dir = app.config["PROJECT_ROOT"] / "content" / "media" / "large"
        large_dir.mkdir(parents=True, exist_ok=True)
        enc_file = large_dir / "img-001.enc"
        enc_file.write_bytes(b"encrypted data")
        mock_manifest.enc_path.return_value = enc_file

        with patch("src.content.media.MediaManifest.load", return_value=mock_manifest), \
             patch("shutil.which", return_value="/usr/bin/gh"):
            resp = client.post("/api/content/media/restore-large")
        data = resp.get_json()
        assert data["success"] is True
        assert "img-001" in data["already_present"]

    def test_restore_downloads_missing(self, client, app):
        entry = MagicMock(storage="large", id="img-002")
        mock_manifest = MagicMock()
        mock_manifest.entries = [entry]

        large_dir = app.config["PROJECT_ROOT"] / "content" / "media" / "large"
        large_dir.mkdir(parents=True, exist_ok=True)
        enc_path = large_dir / "img-002.enc"
        mock_manifest.enc_path.return_value = enc_path

        def fake_run(cmd, **kwargs):
            # Simulate gh download creating the file
            enc_path.write_bytes(b"downloaded")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("src.content.media.MediaManifest.load", return_value=mock_manifest), \
             patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("subprocess.run", side_effect=fake_run):
            resp = client.post("/api/content/media/restore-large")
        data = resp.get_json()
        assert data["success"] is True
        assert "img-002" in data["restored"]

    def test_restore_skips_non_large(self, client, app):
        entry = MagicMock(storage="inline", id="small-001")
        mock_manifest = MagicMock()
        mock_manifest.entries = [entry]

        with patch("src.content.media.MediaManifest.load", return_value=mock_manifest), \
             patch("shutil.which", return_value="/usr/bin/gh"):
            resp = client.post("/api/content/media/restore-large")
        data = resp.get_json()
        assert data["success"] is True
        assert data["restored"] == []
        assert data["already_present"] == []


# ── Upload Helper ────────────────────────────────────────────────────


class TestUploadToReleaseBg:

    def setup_method(self):
        _release_upload_status.clear()
        _release_active_procs.clear()

    def test_no_gh_cli(self, client, app):
        from src.admin.routes_media_vault import upload_to_release_bg

        with app.app_context(), \
             patch("shutil.which", return_value=None):
            upload_to_release_bg("test-media", Path("/tmp/fake.enc"))
        assert _release_upload_status["test-media"]["status"] == "failed"
        assert "not installed" in _release_upload_status["test-media"]["message"]


# ── Delete Release Asset ─────────────────────────────────────────────


class TestDeleteReleaseAsset:

    def test_no_gh(self, client, app):
        from src.admin.routes_media_vault import delete_release_asset

        with app.app_context(), \
             patch("shutil.which", return_value=None):
            # Should not raise, just silently skip
            delete_release_asset("test-media")

    def test_delete_fires_popen(self, client, app):
        from src.admin.routes_media_vault import delete_release_asset

        with app.app_context(), \
             patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            delete_release_asset("img-999")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "delete-asset" in args
        assert "img-999.enc" in args
