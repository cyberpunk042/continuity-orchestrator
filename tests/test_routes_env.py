"""
Tests for admin environment API routes.

Tests the /api/env/* and /api/secrets/push endpoints.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Read .env ────────────────────────────────────────────────────────


class TestEnvRead:

    def test_no_env_file(self, client):
        resp = client.get("/api/env/read")
        assert resp.status_code == 200
        assert resp.get_json()["values"] == {}

    def test_read_simple_env(self, client, env_file):
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        resp = client.get("/api/env/read")
        data = resp.get_json()
        assert data["values"]["FOO"] == "bar"
        assert data["values"]["BAZ"] == "qux"

    def test_read_quoted_values(self, client, env_file):
        env_file.write_text('NAME="hello world"\nSINGLE=\'quoted\'\n')
        resp = client.get("/api/env/read")
        data = resp.get_json()
        assert data["values"]["NAME"] == "hello world"
        assert data["values"]["SINGLE"] == "quoted"

    def test_read_ignores_comments(self, client, env_file):
        env_file.write_text("# A comment\nKEY=value\n# More comments\n")
        resp = client.get("/api/env/read")
        data = resp.get_json()
        assert len(data["values"]) == 1
        assert data["values"]["KEY"] == "value"

    def test_read_ignores_blank_lines(self, client, env_file):
        env_file.write_text("\n\nKEY=value\n\n")
        resp = client.get("/api/env/read")
        assert len(resp.get_json()["values"]) == 1


# ── Write .env ───────────────────────────────────────────────────────


class TestEnvWrite:

    def test_write_no_secrets_400(self, client):
        resp = client.post("/api/env/write", json={})
        assert resp.status_code == 400

    def test_write_creates_env(self, client, env_file):
        resp = client.post("/api/env/write", json={
            "secrets": {"NEW_KEY": "new_value"},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "NEW_KEY" in data["updated"]
        assert env_file.exists()
        content = env_file.read_text()
        assert "NEW_KEY=new_value" in content

    def test_write_preserves_existing(self, client, env_file):
        env_file.write_text("EXISTING=keep\n")
        resp = client.post("/api/env/write", json={
            "secrets": {"NEW": "added"},
        })
        assert resp.status_code == 200
        content = env_file.read_text()
        assert "EXISTING=keep" in content
        assert "NEW=added" in content

    def test_write_updates_existing(self, client, env_file):
        env_file.write_text("KEY=old\n")
        resp = client.post("/api/env/write", json={
            "secrets": {"KEY": "new"},
        })
        assert resp.status_code == 200
        content = env_file.read_text()
        assert "KEY=new" in content
        assert "old" not in content

    def test_write_quotes_spaces(self, client, env_file):
        resp = client.post("/api/env/write", json={
            "secrets": {"SPACED": "hello world"},
        })
        content = env_file.read_text()
        assert '"hello world"' in content

    def test_write_skips_empty_values(self, client, env_file):
        env_file.write_text("KEY=original\n")
        resp = client.post("/api/env/write", json={
            "secrets": {"KEY": ""},  # empty value -> keep original
        })
        content = env_file.read_text()
        assert "KEY=original" in content


# ── Push Secrets ─────────────────────────────────────────────────────


class TestPushSecrets:

    def test_save_to_env_only(self, client, env_file):
        """When push_to_github=False, should only save to .env."""
        resp = client.post("/api/secrets/push", json={
            "secrets": {"MY_SECRET": "value123"},
            "push_to_github": False,
            "save_to_env": True,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["env_saved"] is True
        assert data["all_success"] is True
        content = env_file.read_text()
        assert "MY_SECRET=value123" in content

    def test_push_to_github_without_gh(self, client, env_file):
        """When gh is not installed, should save to env but report GitHub error."""
        gh_status = MagicMock(installed=False, install_hint="brew install gh")
        with patch("src.config.system_status.check_tool", return_value=gh_status):
            resp = client.post("/api/secrets/push", json={
                "secrets": {"KEY": "val"},
                "push_to_github": True,
                "save_to_env": True,
            })
        data = resp.get_json()
        assert data["env_saved"] is True
        assert "github_error" in data
        assert data["all_success"] is False

    def test_push_to_github_not_authenticated(self, client, env_file):
        gh_status = MagicMock(installed=True, authenticated=False)
        with patch("src.config.system_status.check_tool", return_value=gh_status):
            resp = client.post("/api/secrets/push", json={
                "secrets": {"KEY": "val"},
                "push_to_github": True,
                "save_to_env": True,
            })
        data = resp.get_json()
        assert "github_error" in data
        assert "auth" in data["github_error"].lower()

    def test_push_secrets_and_variables(self, client, env_file):
        gh_status = MagicMock(installed=True, authenticated=True)
        mock_result = MagicMock(returncode=0, stderr="")

        with patch("src.config.system_status.check_tool", return_value=gh_status), \
             patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("src.admin.helpers.trigger_mirror_sync_bg", return_value=False):
            resp = client.post("/api/secrets/push", json={
                "secrets": {"SECRET_1": "val1"},
                "variables": {"VAR_1": "val2"},
                "push_to_github": True,
                "save_to_env": True,
            })
        data = resp.get_json()
        assert data["all_success"] is True
        assert len(data["results"]) == 2

    def test_push_skips_github_prefixed(self, client, env_file):
        """GITHUB_* keys should not be pushed to GitHub (they're reserved)."""
        gh_status = MagicMock(installed=True, authenticated=True)
        mock_result = MagicMock(returncode=0, stderr="")

        with patch("src.config.system_status.check_tool", return_value=gh_status), \
             patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("src.admin.helpers.trigger_mirror_sync_bg", return_value=False):
            resp = client.post("/api/secrets/push", json={
                "secrets": {"GITHUB_REPOSITORY": "user/repo", "REAL_SECRET": "val"},
                "push_to_github": True,
                "save_to_env": True,
            })
        data = resp.get_json()
        # Only REAL_SECRET should've been pushed
        pushed_names = [r["name"] for r in data["results"]]
        assert "GITHUB_REPOSITORY" not in pushed_names
        assert "REAL_SECRET" in pushed_names

    def test_push_applies_deletions(self, client, env_file):
        env_file.write_text("KEEP=yes\nDELETE_ME=old\n")
        resp = client.post("/api/secrets/push", json={
            "deletions": ["DELETE_ME"],
            "push_to_github": False,
            "save_to_env": True,
        })
        data = resp.get_json()
        assert "DELETE_ME" in data["deletions_applied"]
        content = env_file.read_text()
        assert "DELETE_ME" not in content
        assert "KEEP=yes" in content

    def test_push_exclude_from_github(self, client, env_file):
        """Excluded keys should be saved to .env but not pushed to GH."""
        gh_status = MagicMock(installed=True, authenticated=True)
        mock_result = MagicMock(returncode=0, stderr="")

        with patch("src.config.system_status.check_tool", return_value=gh_status), \
             patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("src.admin.helpers.trigger_mirror_sync_bg", return_value=False):
            resp = client.post("/api/secrets/push", json={
                "secrets": {"LOCAL_ONLY": "val", "PUSH_ME": "val2"},
                "push_to_github": True,
                "save_to_env": True,
                "exclude_from_github": ["LOCAL_ONLY"],
            })
        data = resp.get_json()
        pushed_names = [r["name"] for r in data["results"]]
        assert "LOCAL_ONLY" not in pushed_names
        assert "PUSH_ME" in pushed_names
        # But both should be in .env
        content = env_file.read_text()
        assert "LOCAL_ONLY=val" in content
        assert "PUSH_ME=val2" in content
