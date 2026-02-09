"""
Tests for admin secrets/GitHub CLI API routes.

Tests the /api/gh/* and /api/secret/* endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── GH Status ────────────────────────────────────────────────────────


class TestGhStatus:

    def test_gh_status(self, client):
        status = MagicMock()
        status.to_dict.return_value = {
            "installed": True,
            "authenticated": True,
            "version": "2.40.0",
        }
        with patch("src.config.system_status.check_tool", return_value=status):
            resp = client.get("/api/gh/status")
        assert resp.status_code == 200
        assert resp.get_json()["installed"] is True


# ── GH Auto ──────────────────────────────────────────────────────────


class TestGhAuto:

    def test_auto_detects_token_and_repo(self, client):
        def fake_run(cmd, **kwargs):
            if "auth" in cmd:
                return MagicMock(returncode=0, stdout="ghp_test_token_123\n", stderr="")
            if "remote" in cmd:
                return MagicMock(returncode=0, stdout="git@github.com:user/repo.git\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            resp = client.get("/api/gh/auto")
        data = resp.get_json()
        assert data["token"] == "ghp_test_token_123"
        assert data["repo"] == "user/repo"

    def test_auto_https_remote(self, client):
        def fake_run(cmd, **kwargs):
            if "auth" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "remote" in cmd:
                return MagicMock(returncode=0,
                                stdout="https://github.com/myorg/myproject.git\n",
                                stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            resp = client.get("/api/gh/auto")
        data = resp.get_json()
        assert data["token"] is None
        assert data["repo"] == "myorg/myproject"

    def test_auto_no_gh_no_remote(self, client):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            resp = client.get("/api/gh/auto")
        data = resp.get_json()
        assert data["token"] is None
        assert data["repo"] is None


# ── GH Secrets List ──────────────────────────────────────────────────


class TestGhSecrets:

    def test_gh_not_installed(self, client):
        status = MagicMock(installed=False, authenticated=False)
        with patch("src.config.system_status.check_tool", return_value=status):
            resp = client.get("/api/gh/secrets")
        data = resp.get_json()
        assert data["available"] is False
        assert data["secrets"] == []

    def test_gh_not_authenticated(self, client):
        status = MagicMock(installed=True, authenticated=False)
        with patch("src.config.system_status.check_tool", return_value=status):
            resp = client.get("/api/gh/secrets")
        data = resp.get_json()
        assert data["available"] is False
        assert "auth" in data["reason"].lower()

    def test_lists_secrets_and_variables(self, client):
        status = MagicMock(installed=True, authenticated=True)

        call_count = [0]
        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if "secret" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="API_KEY\tUpdated 2026-01-01\nDB_PASS\tUpdated 2026-01-02\n",
                    stderr="",
                )
            if "variable" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="DEPLOY_MODE\tgithub-pages\tUpdated 2026-01-01\n",
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("src.config.system_status.check_tool", return_value=status), \
             patch("subprocess.run", side_effect=fake_run):
            resp = client.get("/api/gh/secrets")
        data = resp.get_json()
        assert data["available"] is True
        assert "API_KEY" in data["secrets"]
        assert "DB_PASS" in data["secrets"]
        assert "DEPLOY_MODE" in data["variables"]


# ── Secret Set ───────────────────────────────────────────────────────


class TestSecretSet:

    def test_missing_name_400(self, client):
        resp = client.post("/api/secret/set", json={"value": "x"})
        assert resp.status_code == 400

    def test_set_local_only(self, client, env_file):
        resp = client.post("/api/secret/set", json={
            "name": "MY_KEY",
            "value": "my_value",
            "target": "local",
        })
        data = resp.get_json()
        assert data["local"]["success"] is True
        assert data["github"] is None
        content = env_file.read_text()
        assert "MY_KEY=my_value" in content

    def test_set_github_only(self, client):
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/secret/set", json={
                "name": "MY_SECRET",
                "value": "secret_val",
                "target": "github",
            })
        data = resp.get_json()
        assert data["local"] is None
        assert data["github"]["success"] is True

    def test_set_both(self, client, env_file):
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/secret/set", json={
                "name": "DUAL_KEY",
                "value": "dual_val",
                "target": "both",
            })
        data = resp.get_json()
        assert data["local"]["success"] is True
        assert data["github"]["success"] is True
        assert "DUAL_KEY=dual_val" in env_file.read_text()

    def test_set_github_failure(self, client):
        mock_result = MagicMock(returncode=1, stderr="auth required")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/secret/set", json={
                "name": "FAIL_KEY",
                "value": "val",
                "target": "github",
            })
        data = resp.get_json()
        assert data["github"]["success"] is False


# ── Secret Remove ────────────────────────────────────────────────────


class TestSecretRemove:

    def test_missing_name_400(self, client):
        resp = client.post("/api/secret/remove", json={})
        assert resp.status_code == 400

    def test_remove_local(self, client, env_file):
        env_file.write_text("KEEP=yes\nDELETE=old\n")
        resp = client.post("/api/secret/remove", json={
            "name": "DELETE",
            "target": "local",
        })
        data = resp.get_json()
        assert data["local"]["success"] is True
        assert data["github"] is None
        content = env_file.read_text()
        assert "DELETE" not in content
        assert "KEEP=yes" in content

    def test_remove_no_env_file(self, client):
        resp = client.post("/api/secret/remove", json={
            "name": "NONEXISTENT",
            "target": "local",
        })
        data = resp.get_json()
        assert data["local"]["success"] is True
        assert "not found" in data["local"].get("note", "").lower()

    def test_remove_github_secret(self, client):
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/secret/remove", json={
                "name": "OLD_SECRET",
                "target": "github",
                "kind": "secret",
            })
        data = resp.get_json()
        assert data["github"]["success"] is True
        args = mock_run.call_args[0][0]
        assert "secret" in args
        assert "delete" in args

    def test_remove_github_variable(self, client):
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/secret/remove", json={
                "name": "OLD_VAR",
                "target": "github",
                "kind": "variable",
            })
        args = mock_run.call_args[0][0]
        assert "variable" in args


# ── GH Install ───────────────────────────────────────────────────────


class TestGhInstall:

    def test_linux_terminal_opens(self, client, app):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            resp = client.post("/api/gh/install")
        data = resp.get_json()
        assert data["success"] is True

    def test_linux_no_terminal_fallback(self, client, app):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.Popen", side_effect=FileNotFoundError):
            resp = client.post("/api/gh/install")
        data = resp.get_json()
        # All terminal attempts fail → fallback to command
        assert data.get("fallback") is True or data.get("success") is False

    def test_unsupported_os(self, client):
        with patch("platform.system", return_value="FreeBSD"):
            resp = client.post("/api/gh/install")
        data = resp.get_json()
        assert data["success"] is False
        assert "Unsupported" in data["message"]
