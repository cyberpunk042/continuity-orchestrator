"""
Tests for admin git API routes.

Tests the /api/git/* endpoints (status, fetch, sync) using Flask test client.
All git/subprocess calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


def _mock_git_run(outputs: dict):
    """Create a subprocess.run mock that returns different outputs per git command.

    Args:
        outputs: mapping of git-subcommand → (returncode, stdout, stderr).
                 The subcommand is the first arg after 'git' (e.g. 'rev-parse').
                 Use '__default__' for any unmatched command.
    """
    def fake_run(cmd, **kwargs):
        # Find the git subcommand
        subcmd = None
        for i, arg in enumerate(cmd):
            if arg == "git" and i + 1 < len(cmd):
                subcmd = cmd[i + 1]
                break
        key = subcmd if subcmd in outputs else "__default__"
        if key not in outputs:
            return MagicMock(returncode=0, stdout="", stderr="")
        rc, out, err = outputs[key]
        return MagicMock(returncode=rc, stdout=out, stderr=err)
    return fake_run


# ── Git Status ───────────────────────────────────────────────────────


class TestGitStatus:

    def test_git_not_installed(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.get("/api/git/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is False
        assert "not installed" in data["error"].lower()

    def test_not_a_git_repo(self, client):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="")
            resp = client.get("/api/git/status")
        data = resp.get_json()
        assert data["available"] is False

    def test_clean_repo(self, client):
        outputs = {
            "rev-parse": (0, "true", ""),
            "branch": (0, "main", ""),
            "log": (0, "abc1234 initial commit", ""),
            "status": (0, "", ""),
            "rev-list": (0, "0\t0", ""),
        }
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=_mock_git_run(outputs)):
            resp = client.get("/api/git/status")
        data = resp.get_json()
        assert data["available"] is True
        assert data["branch"] == "main"
        assert data["clean"] is True
        assert data["staged"] == 0
        assert data["ahead"] == 0

    def test_dirty_repo(self, client):
        outputs = {
            "rev-parse": (0, "true", ""),
            "branch": (0, "dev", ""),
            "log": (0, "abc1234 wip", ""),
            "status": (0, " M src/main.py\n?? new_file.txt\n", ""),
            "rev-list": (0, "1\t0", ""),
        }
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=_mock_git_run(outputs)):
            resp = client.get("/api/git/status")
        data = resp.get_json()
        assert data["available"] is True
        assert data["total_changes"] >= 2  # modified + untracked
        assert data["untracked"] == 1
        assert data["clean"] is False

    def test_exception_handled(self, client):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=OSError("boom")):
            resp = client.get("/api/git/status")
        data = resp.get_json()
        assert data["available"] is False
        assert "boom" in data["error"]


# ── Git Fetch ────────────────────────────────────────────────────────


class TestGitFetch:

    def test_git_not_installed(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is False

    def test_not_a_git_repo(self, client):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal")
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is False

    def test_no_remote(self, client):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # rev-parse
                return MagicMock(returncode=0, stdout="true", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")  # remote → empty
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is False
        assert "remote" in data["error"].lower()

    def test_clean_up_to_date(self, client):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # rev-parse
                return MagicMock(returncode=0, stdout="true", stderr="")
            if call_count[0] == 2:  # remote
                return MagicMock(returncode=0, stdout="origin", stderr="")
            if call_count[0] == 3:  # fetch
                return MagicMock(returncode=0, stdout="", stderr="")
            if call_count[0] == 4:  # status --porcelain
                return MagicMock(returncode=0, stdout="", stderr="")
            if call_count[0] == 5:  # rev-parse upstream
                return MagicMock(returncode=0, stdout="origin/main", stderr="")
            if call_count[0] == 6:  # rev-list
                return MagicMock(returncode=0, stdout="0\t0", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is True
        assert data["state"] == "clean"
        assert data["pulled"] is False

    def test_behind_auto_pulls(self, client):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # rev-parse
                return MagicMock(returncode=0, stdout="true", stderr="")
            if call_count[0] == 2:  # remote
                return MagicMock(returncode=0, stdout="origin", stderr="")
            if call_count[0] == 3:  # fetch
                return MagicMock(returncode=0, stdout="", stderr="")
            if call_count[0] == 4:  # status --porcelain (clean)
                return MagicMock(returncode=0, stdout="", stderr="")
            if call_count[0] == 5:  # rev-parse upstream
                return MagicMock(returncode=0, stdout="origin/main", stderr="")
            if call_count[0] == 6:  # rev-list (0 ahead, 2 behind)
                return MagicMock(returncode=0, stdout="0\t2", stderr="")
            if call_count[0] == 7:  # pull --ff-only
                return MagicMock(returncode=0, stdout="Updating abc..def", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is True
        assert data["pulled"] is True
        assert data["state"] == "pulled"

    def test_dirty_tree_skips_pull(self, client):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # rev-parse
                return MagicMock(returncode=0, stdout="true", stderr="")
            if call_count[0] == 2:  # remote
                return MagicMock(returncode=0, stdout="origin", stderr="")
            if call_count[0] == 3:  # fetch
                return MagicMock(returncode=0, stdout="", stderr="")
            if call_count[0] == 4:  # status --porcelain (dirty!)
                return MagicMock(returncode=0, stdout=" M README.md\n", stderr="")
            if call_count[0] == 5:  # rev-parse upstream
                return MagicMock(returncode=0, stdout="origin/main", stderr="")
            if call_count[0] == 6:  # rev-list
                return MagicMock(returncode=0, stdout="0\t0", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/fetch")
        data = resp.get_json()
        assert data["fetched"] is True
        assert data["has_local_changes"] is True
        assert data["pulled"] is False
        assert data["state"] == "dirty"

    def test_timeout_504(self, client):
        import subprocess as sp
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=sp.TimeoutExpired("git", 30)):
            resp = client.post("/api/git/fetch")
        assert resp.status_code == 504


# ── Git Sync ─────────────────────────────────────────────────────────


class TestGitSync:

    def test_git_not_installed(self, client):
        with patch("shutil.which", return_value=None):
            resp = client.post("/api/git/sync", json={"message": "test"})
        data = resp.get_json()
        assert data["success"] is False
        assert "not installed" in data["error"]

    def test_not_a_git_repo(self, client):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal")
            resp = client.post("/api/git/sync", json={})
        data = resp.get_json()
        assert data["success"] is False
        assert "steps" in data

    def test_no_remote(self, client):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # rev-parse
                return MagicMock(returncode=0, stdout="true", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")  # remote -v → empty
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/sync", json={})
        data = resp.get_json()
        assert data["success"] is False
        assert "remote" in data["error"].lower()

    def test_successful_sync(self, client):
        """Happy path: commit + push succeeds."""
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        # diff --cached returns non-zero (there ARE changes), then zero (nothing more)
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            # The diff --cached calls return different things at different steps
            if "diff" in cmd and "--cached" in cmd:
                # First diff check: has changes (rc=1), second: nothing left
                if call_count[0] < 10:
                    return MagicMock(returncode=1, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect), \
             patch("src.admin.helpers.trigger_mirror_sync_bg", return_value=False):
            resp = client.post("/api/git/sync", json={"message": "test commit"})
        data = resp.get_json()
        assert data["success"] is True
        assert "steps" in data
        assert len(data["steps"]) > 0

    def test_timeout_504(self, client):
        import subprocess as sp
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return MagicMock(returncode=0, stdout="ok", stderr="")
            raise sp.TimeoutExpired("git push", 120)
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=side_effect):
            resp = client.post("/api/git/sync", json={})
        assert resp.status_code == 504

    def test_generic_error_500(self, client):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=RuntimeError("boom")):
            resp = client.post("/api/git/sync", json={})
        assert resp.status_code == 500
