"""
Tests for admin Docker API routes.

Tests the /api/docker/* endpoints (status, restart, start, stop, build, logs).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Helper Functions ─────────────────────────────────────────────────


class TestParseComposePs:

    def test_parse_ndjson(self):
        from src.admin.routes_docker import _parse_compose_ps
        stdout = (
            '{"Name":"continuity-orchestrator","State":"running","Service":"orchestrator"}\n'
            '{"Name":"continuity-nginx","State":"running","Service":"nginx"}\n'
        )
        result = _parse_compose_ps(stdout)
        assert len(result) == 2
        assert result[0]["Name"] == "continuity-orchestrator"

    def test_parse_empty(self):
        from src.admin.routes_docker import _parse_compose_ps
        assert _parse_compose_ps("") == []
        assert _parse_compose_ps("   ") == []

    def test_parse_invalid_json(self):
        from src.admin.routes_docker import _parse_compose_ps
        result = _parse_compose_ps("not json\n{\"valid\": true}\n")
        assert len(result) == 1
        assert result[0]["valid"] is True


# ── Docker Status ────────────────────────────────────────────────────


class TestDockerStatus:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.get("/api/docker/status")
        data = resp.get_json()
        assert data["available"] is False

    def test_no_compose_file(self, client):
        with patch("shutil.which", return_value="/usr/bin/docker"):
            resp = client.get("/api/docker/status")
        data = resp.get_json()
        assert data["available"] is True
        assert data["compose_file"] is False

    def test_compose_status(self, client, app):
        # Create docker-compose.yml
        compose_path = app.config["PROJECT_ROOT"] / "docker-compose.yml"
        compose_path.write_text("version: '3'\n")

        ndjson = (
            '{"Name":"continuity-orchestrator","State":"running","Service":"orchestrator","Status":"Up 2 hours"}\n'
            '{"Name":"continuity-nginx","State":"running","Service":"nginx","Status":"Up 2 hours"}\n'
        )
        mock_result = MagicMock(returncode=0, stdout=ndjson, stderr="")

        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/docker/status")
        data = resp.get_json()
        assert data["available"] is True
        assert data["compose_file"] is True
        assert len(data["containers"]) >= 2

    def test_compose_error(self, client, app):
        compose_path = app.config["PROJECT_ROOT"] / "docker-compose.yml"
        compose_path.write_text("version: '3'\n")

        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", side_effect=RuntimeError("docker broke")):
            resp = client.get("/api/docker/status")
        assert resp.status_code == 500


# ── Docker Restart ───────────────────────────────────────────────────


class TestDockerRestart:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/docker/restart")
        assert resp.status_code == 400

    def test_restart_success(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        # First call: _detect_active_profiles, then down, then up
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/docker/restart")
        data = resp.get_json()
        assert data["success"] is True


# ── Docker Start ─────────────────────────────────────────────────────


class TestDockerStart:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/docker/start")
        assert resp.status_code == 400

    def test_invalid_profile(self, client):
        with patch("shutil.which", return_value="/usr/bin/docker"):
            resp = client.post("/api/docker/start", json={"profiles": ["evil-profile"]})
        assert resp.status_code == 400
        assert "Unknown profile" in resp.get_json()["error"]

    def test_start_with_profiles(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/docker/start", json={"profiles": ["git-sync"]})
        data = resp.get_json()
        assert data["success"] is True
        # Verify --profile git-sync was in the command
        args = mock_run.call_args[0][0]
        assert "--profile" in args
        assert "git-sync" in args

    def test_start_standalone(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/docker/start", json={})
        assert resp.get_json()["success"] is True


# ── Docker Build ─────────────────────────────────────────────────────


class TestDockerBuild:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/docker/build")
        assert resp.status_code == 400

    def test_build_with_cache(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/docker/build", json={"profiles": ["git-sync"]})
        data = resp.get_json()
        assert data["success"] is True
        args = mock_run.call_args[0][0]
        assert "--no-cache" not in args

    def test_build_no_cache(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/docker/build", json={
                "profiles": [],
                "no_cache": True,
            })
        args = mock_run.call_args[0][0]
        assert "--no-cache" in args

    def test_invalid_profile(self, client):
        with patch("shutil.which", return_value="/usr/bin/docker"):
            resp = client.post("/api/docker/build", json={"profiles": ["hacker"]})
        assert resp.status_code == 400


# ── Docker Stop ──────────────────────────────────────────────────────


class TestDockerStop:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/docker/stop")
        assert resp.status_code == 400

    def test_stop_default(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/docker/stop", json={})
        data = resp.get_json()
        assert data["success"] is True
        assert data["cleaned"]["volumes"] is False
        assert data["cleaned"]["images"] is False

    def test_stop_with_volume_cleanup(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/docker/stop", json={
                "remove_volumes": True,
                "remove_images": True,
            })
        data = resp.get_json()
        assert data["success"] is True
        assert data["cleaned"]["volumes"] is True
        assert data["cleaned"]["images"] is True
        args = mock_run.call_args[0][0]
        assert "-v" in args
        assert "--rmi" in args


# ── Docker Logs ──────────────────────────────────────────────────────


class TestDockerLogs:

    def test_docker_not_available(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.get("/api/docker/logs")
        assert resp.status_code == 400

    def test_logs_default(self, client):
        mock_result = MagicMock(returncode=0, stdout="log line 1\nlog line 2\n", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/docker/logs")
        data = resp.get_json()
        assert data["success"] is True
        assert "log line" in data["output"]
        assert data["service"] == "all"

    def test_logs_specific_service(self, client):
        mock_result = MagicMock(returncode=0, stdout="service logs", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.get("/api/docker/logs?service=nginx&lines=50")
        data = resp.get_json()
        assert data["service"] == "nginx"
        assert data["lines"] == 50
        args = mock_run.call_args[0][0]
        assert "nginx" in args

    def test_logs_max_lines_clamped(self, client):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/docker/logs?lines=9999")
        data = resp.get_json()
        assert data["lines"] == 500  # Clamped at max


# ── Run Compose Helper ───────────────────────────────────────────────


class TestRunCompose:

    def test_timeout_handled(self, client):
        import subprocess as sp
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", side_effect=sp.TimeoutExpired("docker", 30)):
            # Use a simple endpoint that calls _run_compose
            resp = client.post("/api/docker/stop", json={})
        data = resp.get_json()
        # _run_compose catches TimeoutExpired and returns error dict
        assert data["success"] is False
        assert "timed out" in data["error"].lower()
