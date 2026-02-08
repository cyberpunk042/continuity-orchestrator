"""
Tests for scripts/docker_git_sync.py

Tests the DockerGitSync class: divergence detection, sync behaviour,
tick-and-push flow, and alpha/non-alpha mode handling.

All git operations are mocked — no real repos needed.
"""

import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

# The script lives outside src/, so we load it into sys.modules
# so that @mock.patch("docker_git_sync.xxx") works correctly.
import importlib.util

_script_path = Path(__file__).parent.parent / "scripts" / "docker_git_sync.py"
_spec = importlib.util.spec_from_file_location("docker_git_sync", _script_path)
docker_git_sync = importlib.util.module_from_spec(_spec)
sys.modules["docker_git_sync"] = docker_git_sync
_spec.loader.exec_module(docker_git_sync)

DockerGitSync = docker_git_sync.DockerGitSync
STATE_UP_TO_DATE = docker_git_sync.STATE_UP_TO_DATE
STATE_BEHIND = docker_git_sync.STATE_BEHIND
STATE_AHEAD = docker_git_sync.STATE_AHEAD
STATE_DIVERGED = docker_git_sync.STATE_DIVERGED
STATE_ERROR = docker_git_sync.STATE_ERROR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sync(tmp_path: Path, alpha: bool = False) -> DockerGitSync:
    """Create a DockerGitSync instance pointing at tmp_path."""
    return DockerGitSync(
        repo=tmp_path,
        branch="main",
        alpha=alpha,
        tick_interval=900,
        sync_interval=30,
        public_dir=tmp_path / "public",
    )


def _mock_git_result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Create a mock subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ---------------------------------------------------------------------------
# detect_state()
# ---------------------------------------------------------------------------

class TestDetectState:
    """Test the 4 sync states: up-to-date, behind, ahead, diverged."""

    @mock.patch("docker_git_sync._git_output")
    @mock.patch("docker_git_sync._git")
    def test_up_to_date(self, mock_git, mock_output, tmp_path):
        """Same commit on local and remote → up-to-date."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = ["abc123", "abc123"]

        assert sync.detect_state() == STATE_UP_TO_DATE

    @mock.patch("docker_git_sync._git_output")
    @mock.patch("docker_git_sync._git")
    def test_behind(self, mock_git, mock_output, tmp_path):
        """Local is ancestor of remote → behind."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = ["local1", "remote2"]
        # merge-base --is-ancestor local remote → 0 (yes, local is ancestor)
        mock_git.return_value = _mock_git_result(returncode=0)

        assert sync.detect_state() == STATE_BEHIND

    @mock.patch("docker_git_sync._git_output")
    @mock.patch("docker_git_sync._git")
    def test_ahead(self, mock_git, mock_output, tmp_path):
        """Remote is ancestor of local → ahead."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = ["local1", "remote2"]
        mock_git.side_effect = [
            _mock_git_result(returncode=1),  # local NOT ancestor of remote
            _mock_git_result(returncode=0),  # remote IS ancestor of local
        ]

        assert sync.detect_state() == STATE_AHEAD

    @mock.patch("docker_git_sync._git_output")
    @mock.patch("docker_git_sync._git")
    def test_diverged(self, mock_git, mock_output, tmp_path):
        """Neither is ancestor → diverged."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = ["local1", "remote2"]
        mock_git.side_effect = [
            _mock_git_result(returncode=1),  # local NOT ancestor of remote
            _mock_git_result(returncode=1),  # remote NOT ancestor of local
        ]

        assert sync.detect_state() == STATE_DIVERGED

    @mock.patch("docker_git_sync._git_output")
    def test_error_no_local_ref(self, mock_output, tmp_path):
        """Can't resolve local HEAD → error."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = [None, "remote2"]

        assert sync.detect_state() == STATE_ERROR

    @mock.patch("docker_git_sync._git_output")
    def test_error_no_remote_ref(self, mock_output, tmp_path):
        """Can't resolve remote ref → error."""
        sync = _make_sync(tmp_path)
        mock_output.side_effect = ["local1", None]

        assert sync.detect_state() == STATE_ERROR


# ---------------------------------------------------------------------------
# sync_from_remote()
# ---------------------------------------------------------------------------

class TestSyncFromRemote:
    """Test sync behaviour for each state × alpha mode combination."""

    @mock.patch("docker_git_sync._git")
    def test_fetch_failure(self, mock_git, tmp_path):
        """Fetch fails → returns error, doesn't touch repo."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result(returncode=1, stderr="network error")

        result = sync.sync_from_remote()
        assert result == STATE_ERROR

    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_UP_TO_DATE)
    @mock.patch("docker_git_sync._git")
    def test_up_to_date(self, mock_git, mock_detect, tmp_path):
        """Up to date → no action."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result()

        result = sync.sync_from_remote()
        assert result == STATE_UP_TO_DATE

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_BEHIND)
    @mock.patch("docker_git_sync._git")
    def test_behind_fast_forwards(self, mock_git, mock_detect, mock_rebuild, tmp_path):
        """Behind → reset --hard + rebuild."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result()

        result = sync.sync_from_remote()
        assert result == STATE_BEHIND
        mock_rebuild.assert_called_once()

    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_AHEAD)
    @mock.patch("docker_git_sync._git")
    def test_ahead_no_action(self, mock_git, mock_detect, tmp_path):
        """Ahead → no action, just wait for next tick to push."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result()

        result = sync.sync_from_remote()
        assert result == STATE_AHEAD
        assert not sync._force_push_pending

    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_DIVERGED)
    @mock.patch("docker_git_sync._git")
    def test_diverged_alpha_keeps_local(self, mock_git, mock_detect, tmp_path):
        """Diverged + alpha → keep local, set force-push flag."""
        sync = _make_sync(tmp_path, alpha=True)
        mock_git.return_value = _mock_git_result()

        result = sync.sync_from_remote()
        assert result == STATE_DIVERGED
        assert sync._force_push_pending is True

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_DIVERGED)
    @mock.patch("docker_git_sync._git")
    def test_diverged_non_alpha_accepts_remote(
        self, mock_git, mock_detect, mock_rebuild, tmp_path
    ):
        """Diverged + non-alpha → accept remote (reset --hard), rebuild."""
        sync = _make_sync(tmp_path, alpha=False)
        mock_git.return_value = _mock_git_result()

        result = sync.sync_from_remote()
        assert result == STATE_DIVERGED
        assert sync._force_push_pending is False
        mock_rebuild.assert_called_once()


# ---------------------------------------------------------------------------
# run_tick_and_push()
# ---------------------------------------------------------------------------

class TestRunTickAndPush:
    """Test tick + commit + push logic."""

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch("docker_git_sync._git_output", return_value="abc12")
    @mock.patch("docker_git_sync._git")
    @mock.patch("docker_git_sync.subprocess.run")
    def test_no_changes(self, mock_run, mock_git, mock_output, mock_rebuild, tmp_path):
        """No state changes → no commit, no push."""
        sync = _make_sync(tmp_path)
        mock_run.return_value = _mock_git_result()
        # git diff --quiet returns 0 (no changes)
        mock_git.return_value = _mock_git_result(returncode=0)

        result = sync.run_tick_and_push()
        assert result == "no-changes"

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch("docker_git_sync._git_output", return_value="abc12")
    @mock.patch("docker_git_sync._git")
    @mock.patch("docker_git_sync.subprocess.run")
    def test_push_success(self, mock_run, mock_git, mock_output, mock_rebuild, tmp_path):
        """State changed → commit + push."""
        sync = _make_sync(tmp_path)
        mock_run.return_value = _mock_git_result()

        mock_git.side_effect = [
            _mock_git_result(returncode=1),            # diff --quiet: has changes
            _mock_git_result(),                         # git add
            _mock_git_result(),                         # git commit
            _mock_git_result(stderr="To github.com"),   # git push
        ]

        result = sync.run_tick_and_push()
        assert result == "pushed"

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch("docker_git_sync._git_output", return_value="abc12")
    @mock.patch("docker_git_sync._git")
    @mock.patch("docker_git_sync.subprocess.run")
    def test_push_failure(self, mock_run, mock_git, mock_output, mock_rebuild, tmp_path):
        """Push fails → returns push-failed."""
        sync = _make_sync(tmp_path)
        mock_run.return_value = _mock_git_result()

        mock_git.side_effect = [
            _mock_git_result(returncode=1),                   # diff: has changes
            _mock_git_result(),                                # add
            _mock_git_result(),                                # commit
            _mock_git_result(returncode=1, stderr="rejected"), # push FAILS
        ]

        result = sync.run_tick_and_push()
        assert result == "push-failed"

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch("docker_git_sync._git_output", return_value="abc12")
    @mock.patch("docker_git_sync._git")
    @mock.patch("docker_git_sync.subprocess.run")
    def test_force_push_pending_clears_flag(
        self, mock_run, mock_git, mock_output, mock_rebuild, tmp_path
    ):
        """When force_push_pending is set, push uses --force and clears the flag."""
        sync = _make_sync(tmp_path, alpha=True)
        sync._force_push_pending = True
        mock_run.return_value = _mock_git_result()

        mock_git.side_effect = [
            _mock_git_result(returncode=1),              # diff: has changes
            _mock_git_result(),                           # add
            _mock_git_result(),                           # commit
            _mock_git_result(stderr="forced update"),     # force push
        ]

        result = sync.run_tick_and_push()
        assert result == "pushed"
        assert sync._force_push_pending is False


# ---------------------------------------------------------------------------
# Lock contention
# ---------------------------------------------------------------------------

class TestLockContention:
    """Verify that sync and tick don't run simultaneously."""

    def test_lock_is_shared(self, tmp_path):
        """Both methods use the same lock."""
        sync = _make_sync(tmp_path)
        assert sync._lock is not None
        assert isinstance(sync._lock, type(threading.Lock()))

    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_UP_TO_DATE)
    @mock.patch("docker_git_sync._git")
    def test_sync_acquires_lock(self, mock_git, mock_detect, tmp_path):
        """sync_from_remote acquires the lock (blocks if tick is running)."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result()

        # Acquire the lock externally — sync should block
        sync._lock.acquire()
        result_holder = []

        def try_sync():
            result_holder.append(sync.sync_from_remote())

        t = threading.Thread(target=try_sync)
        t.start()

        # Give it a moment — it should be blocked
        t.join(timeout=0.1)
        assert t.is_alive(), "sync_from_remote should be blocked by the lock"

        # Release — it should complete
        sync._lock.release()
        t.join(timeout=2)
        assert not t.is_alive()
        assert result_holder[0] == STATE_UP_TO_DATE


# ---------------------------------------------------------------------------
# initial_sync()
# ---------------------------------------------------------------------------

class TestInitialSync:
    """Test startup sync (always accepts remote)."""

    @mock.patch("docker_git_sync._git")
    def test_initial_sync_fetches_and_resets(self, mock_git, tmp_path):
        """On startup, fetches and resets to remote HEAD."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result()

        sync.initial_sync()

        calls = mock_git.call_args_list
        assert len(calls) == 2
        # First call: fetch
        fetch_args = [a for a in calls[0][0] if isinstance(a, str)]
        assert "fetch" in fetch_args
        # Second call: reset --hard
        reset_args = [a for a in calls[1][0] if isinstance(a, str)]
        assert "reset" in reset_args
        assert "--hard" in reset_args

    @mock.patch("docker_git_sync._git")
    def test_initial_sync_fetch_failure_doesnt_crash(self, mock_git, tmp_path):
        """Fetch failure on startup doesn't crash (repo may have local state)."""
        sync = _make_sync(tmp_path)
        mock_git.return_value = _mock_git_result(returncode=1, stderr="network down")

        # Should not raise
        sync.initial_sync()


# ---------------------------------------------------------------------------
# Alpha mode configuration
# ---------------------------------------------------------------------------

class TestAlphaMode:
    """Test alpha mode flag and its effects."""

    def test_default_is_non_alpha(self, tmp_path):
        """Default mode is non-alpha."""
        sync = _make_sync(tmp_path)
        assert sync.alpha is False

    def test_alpha_flag(self, tmp_path):
        """Alpha mode can be explicitly set."""
        sync = _make_sync(tmp_path, alpha=True)
        assert sync.alpha is True

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_DIVERGED)
    @mock.patch("docker_git_sync._git")
    def test_alpha_diverged_sets_force_push(
        self, mock_git, mock_detect, mock_rebuild, tmp_path
    ):
        """Alpha mode + diverge → sets force push flag, doesn't reset."""
        sync = _make_sync(tmp_path, alpha=True)
        mock_git.return_value = _mock_git_result()

        sync.sync_from_remote()

        assert sync._force_push_pending is True
        # Should NOT have called rebuild (didn't accept remote)
        mock_rebuild.assert_not_called()

    @mock.patch.object(DockerGitSync, "_rebuild_site")
    @mock.patch.object(DockerGitSync, "detect_state", return_value=STATE_DIVERGED)
    @mock.patch("docker_git_sync._git")
    def test_non_alpha_diverged_resets(
        self, mock_git, mock_detect, mock_rebuild, tmp_path
    ):
        """Non-alpha mode + diverge → accepts remote, rebuilds."""
        sync = _make_sync(tmp_path, alpha=False)
        mock_git.return_value = _mock_git_result()

        sync.sync_from_remote()

        assert sync._force_push_pending is False
        mock_rebuild.assert_called_once()
