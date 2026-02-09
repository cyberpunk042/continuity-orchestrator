"""
Tests for admin mirror API routes.

Tests the /api/mirror/* endpoints (status, sync, sync/code, sync/secrets,
sync/stream, clean/stream).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Mirror Status ────────────────────────────────────────────────────


class TestMirrorStatus:

    def test_status_enabled(self, client, app):
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"enabled": True, "mirror_repo": "user/mirror"}),
            stderr="",
        )
        # Ensure state dir exists for lock check
        state_dir = app.config["PROJECT_ROOT"] / "state"
        state_dir.mkdir(exist_ok=True)

        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/mirror/status")
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["syncing"] is False

    def test_status_with_sync_lock(self, client, app):
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"enabled": True}),
            stderr="",
        )
        state_dir = app.config["PROJECT_ROOT"] / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / ".mirror_sync_lock").write_text("locked")

        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/mirror/status")
        data = resp.get_json()
        assert data["syncing"] is True

    def test_status_disabled(self, client, app):
        mock_result = MagicMock(returncode=1, stdout="", stderr="not configured")
        state_dir = app.config["PROJECT_ROOT"] / "state"
        state_dir.mkdir(exist_ok=True)

        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/mirror/status")
        data = resp.get_json()
        assert data["enabled"] is False

    def test_status_error(self, client, app):
        state_dir = app.config["PROJECT_ROOT"] / "state"
        state_dir.mkdir(exist_ok=True)

        with patch("subprocess.run", side_effect=OSError("boom")):
            resp = client.get("/api/mirror/status")
        data = resp.get_json()
        assert data["enabled"] is False
        assert "boom" in data["error"]


# ── Mirror Sync (Legacy Non-Streaming) ───────────────────────────────


class TestMirrorSync:

    def test_sync_success(self, client):
        mock_result = MagicMock(returncode=0, stdout="Synced OK", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/mirror/sync")
        data = resp.get_json()
        assert data["success"] is True
        assert "Synced OK" in data["output"]
        args = mock_run.call_args[0][0]
        assert "mirror-sync" in args

    def test_sync_failure(self, client):
        mock_result = MagicMock(returncode=1, stdout="", stderr="permission denied")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/mirror/sync")
        data = resp.get_json()
        assert data["success"] is False

    def test_sync_error(self, client):
        with patch("subprocess.run", side_effect=OSError("spawn failed")):
            resp = client.post("/api/mirror/sync")
        assert resp.status_code == 500


class TestMirrorSyncCode:

    def test_sync_code(self, client):
        mock_result = MagicMock(returncode=0, stdout="Code synced", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/mirror/sync/code")
        data = resp.get_json()
        assert data["success"] is True
        args = mock_run.call_args[0][0]
        assert "--code-only" in args


class TestMirrorSyncSecrets:

    def test_sync_secrets(self, client):
        mock_result = MagicMock(returncode=0, stdout="Secrets synced", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/mirror/sync/secrets")
        data = resp.get_json()
        assert data["success"] is True
        args = mock_run.call_args[0][0]
        assert "--secrets-only" in args


# ── Mirror Stream Endpoints ──────────────────────────────────────────
# These return SSE (text/event-stream) responses, which are harder to test
# because they spawn subprocesses. We test that the routes return the
# correct content type and that the command is constructed correctly.


class TestMirrorSyncStream:

    def test_sync_stream_content_type(self, client):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])  # empty iterator
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            resp = client.get("/api/mirror/sync/stream")
        assert resp.content_type.startswith("text/event-stream")

    def test_sync_stream_with_mode(self, client):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            resp = client.get("/api/mirror/sync/stream?mode=code")
        # Verify --code-only was passed
        cmd = mock_popen.call_args[0][0]
        assert "--code-only" in cmd

    def test_sync_stream_data(self, client):
        """Verify that stdout lines are forwarded as SSE data."""
        status_line = json.dumps({"step": "push", "status": "ok"})

        mock_proc = MagicMock()
        mock_proc.stdout = iter([status_line + "\n"])
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            resp = client.get("/api/mirror/sync/stream")
        body = resp.get_data(as_text=True)
        assert "data: " in body
        assert status_line in body


class TestMirrorCleanStream:

    def test_clean_stream_all(self, client):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            resp = client.get("/api/mirror/clean/stream")
        assert resp.content_type.startswith("text/event-stream")
        cmd = mock_popen.call_args[0][0]
        assert "--all" in cmd

    def test_clean_stream_secrets_mode(self, client):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            resp = client.get("/api/mirror/clean/stream?mode=secrets")
        cmd = mock_popen.call_args[0][0]
        assert "--secrets" in cmd
