#!/usr/bin/env python3
"""
Docker Git Sync — Coordinated tick + sync loops for the git-sync Docker profile.

Replaces the inline bash loops in docker-compose.yml with proper concurrency
control, divergence detection, and alpha/non-alpha mode support.

Usage:
    python scripts/docker_git_sync.py \
        --repo /repo \
        --branch main \
        --public-dir /public \
        --tick-interval 900 \
        --sync-interval 30

Environment:
    DOCKER_GIT_SYNC_ALPHA=true|false (default: false)
        true  = Docker is dominant. On divergence, force-pushes local state.
        false = Remote is dominant. On divergence, accepts remote state.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("docker-git-sync")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git_output(repo: Path, *args: str) -> str | None:
    """Run a git command and return stripped stdout, or None on failure."""
    result = _git(repo, *args)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Sync states
# ---------------------------------------------------------------------------

STATE_UP_TO_DATE = "up-to-date"
STATE_BEHIND = "behind"         # remote has new commits, local doesn't
STATE_AHEAD = "ahead"           # local has commits not on remote
STATE_DIVERGED = "diverged"     # history diverged (force push / factory reset)
STATE_ERROR = "error"


# ---------------------------------------------------------------------------
# DockerGitSync
# ---------------------------------------------------------------------------

class DockerGitSync:
    """Coordinated git sync + tick loop manager.

    Uses a threading.Lock to prevent the background sync loop and the
    tick loop from modifying the git repo at the same time.
    """

    def __init__(
        self,
        repo: Path,
        branch: str = "main",
        alpha: bool = False,
        tick_interval: int = 900,
        sync_interval: int = 30,
        public_dir: Path | None = None,
    ):
        self.repo = Path(repo)
        self.branch = branch
        self.alpha = alpha
        self.tick_interval = tick_interval
        self.sync_interval = sync_interval
        self.public_dir = Path(public_dir) if public_dir else None
        self._lock = threading.Lock()
        self._force_push_pending = False
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Initial sync (startup — always accept remote)
    # ------------------------------------------------------------------

    def initial_sync(self) -> None:
        """Pull latest from remote on startup. Always accepts remote state."""
        logger.info("Initial sync — pulling latest from remote...")

        result = _git(self.repo, "fetch", "origin", self.branch)
        if result.returncode != 0:
            logger.error(f"Initial fetch failed: {result.stderr.strip()}")
            # Don't exit — repo might already have usable state
            return

        result = _git(self.repo, "reset", "--hard", f"origin/{self.branch}")
        if result.returncode != 0:
            logger.error(f"Initial reset failed: {result.stderr.strip()}")
            return

        logger.info("Initial sync complete — on latest remote state")

    # ------------------------------------------------------------------
    # Divergence detection
    # ------------------------------------------------------------------

    def detect_state(self) -> str:
        """Inspect local vs remote HEAD and determine the sync state.

        Returns one of: 'up-to-date', 'behind', 'ahead', 'diverged', 'error'.
        """
        local = _git_output(self.repo, "rev-parse", "HEAD")
        remote = _git_output(self.repo, "rev-parse", f"origin/{self.branch}")

        if not local or not remote:
            logger.error("Could not resolve HEAD or remote ref")
            return STATE_ERROR

        if local == remote:
            return STATE_UP_TO_DATE

        # Is local an ancestor of remote? → local is behind
        is_local_ancestor = _git(
            self.repo, "merge-base", "--is-ancestor", local, remote
        )
        if is_local_ancestor.returncode == 0:
            return STATE_BEHIND

        # Is remote an ancestor of local? → local is ahead
        is_remote_ancestor = _git(
            self.repo, "merge-base", "--is-ancestor", remote, local
        )
        if is_remote_ancestor.returncode == 0:
            return STATE_AHEAD

        # Neither is ancestor → diverged
        return STATE_DIVERGED

    # ------------------------------------------------------------------
    # Sync from remote (background loop body)
    # ------------------------------------------------------------------

    def sync_from_remote(self) -> str:
        """Fetch remote and sync if needed. Acquires lock."""
        with self._lock:
            # Fetch
            result = _git(self.repo, "fetch", "origin", self.branch)
            if result.returncode != 0:
                logger.warning(f"Fetch failed: {result.stderr.strip()}")
                return STATE_ERROR

            state = self.detect_state()

            if state == STATE_UP_TO_DATE:
                logger.debug("Sync: up to date")
                return state

            if state == STATE_BEHIND:
                logger.info("Sync: remote has new commits, fast-forwarding...")
                result = _git(self.repo, "reset", "--hard", f"origin/{self.branch}")
                if result.returncode != 0:
                    logger.error(f"Fast-forward failed: {result.stderr.strip()}")
                    return STATE_ERROR
                self._rebuild_site()
                logger.info("Sync: pulled and rebuilt site")
                return state

            if state == STATE_AHEAD:
                logger.debug("Sync: local is ahead, will push on next tick")
                return state

            if state == STATE_DIVERGED:
                if self.alpha:
                    logger.warning(
                        "DIVERGED: Remote history changed, but this instance is "
                        "ALPHA (dominant). Keeping local state — will force-push "
                        "on next tick."
                    )
                    self._force_push_pending = True
                else:
                    logger.warning(
                        "DIVERGED: Remote history changed. This instance is "
                        "non-alpha — accepting remote state."
                    )
                    result = _git(
                        self.repo, "reset", "--hard", f"origin/{self.branch}"
                    )
                    if result.returncode != 0:
                        logger.error(
                            f"Reset to remote failed: {result.stderr.strip()}"
                        )
                        return STATE_ERROR
                    self._rebuild_site()
                    logger.info("Sync: accepted remote state and rebuilt site")
                return state

            # STATE_ERROR
            return state

    # ------------------------------------------------------------------
    # Tick + push (tick loop body)
    # ------------------------------------------------------------------

    def run_tick_and_push(self) -> str:
        """Run tick, build site, commit and push changes. Acquires lock."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")

            logger.info(f"{'═' * 50}")
            logger.info(f"Running tick at {now}")

            # Run tick
            tick_result = subprocess.run(
                ["python", "-m", "src.main", "tick"],
                cwd=str(self.repo),
                capture_output=False,  # let output flow to container logs
                timeout=120,
            )
            if tick_result.returncode != 0:
                logger.error("Tick failed")

            # Build site
            self._rebuild_site()

            # Check for state changes
            diff_result = _git(self.repo, "diff", "--quiet", "state/", "audit/")
            if diff_result.returncode == 0:
                logger.info("No state changes to commit")
                return "no-changes"

            # Commit
            _git(self.repo, "add", "state/", "audit/")
            commit_msg = f"chore(state): tick at {now}"
            commit_result = _git(self.repo, "commit", "-m", commit_msg)

            if commit_result.returncode != 0:
                logger.error(f"Commit failed: {commit_result.stderr.strip()}")
                return STATE_ERROR

            # Push
            push_cmd = ["push", "origin", self.branch]
            if self.alpha or self._force_push_pending:
                push_cmd.insert(1, "--force")
                if self._force_push_pending:
                    logger.info("Force-pushing to override diverged remote (alpha mode)")
                    self._force_push_pending = False

            push_result = _git(self.repo, *push_cmd, timeout=60)
            if push_result.returncode != 0:
                error = push_result.stderr.strip()
                logger.error(f"Push failed: {error}")
                return "push-failed"

            output = push_result.stderr.strip() or push_result.stdout.strip()
            if "Everything up-to-date" in (output or ""):
                logger.info("Push: already up to date")
            else:
                head = _git_output(self.repo, "rev-parse", "--short", "HEAD")
                logger.info(f"Push: committed and pushed {head}")

            return "pushed"

    # ------------------------------------------------------------------
    # Site rebuild helper
    # ------------------------------------------------------------------

    def _rebuild_site(self) -> None:
        """Build static site to the public directory."""
        cmd = ["python", "-m", "src.main", "build-site"]
        if self.public_dir:
            cmd.extend(["--output", str(self.public_dir)])

        try:
            subprocess.run(
                cmd,
                cwd=str(self.repo),
                capture_output=True,
                timeout=120,
            )
        except Exception as e:
            logger.warning(f"Site build failed: {e}")

    # ------------------------------------------------------------------
    # Loop runners
    # ------------------------------------------------------------------

    def _run_sync_loop(self) -> None:
        """Background thread: sync from remote every sync_interval seconds."""
        logger.info(
            f"Sync loop started (every {self.sync_interval}s, "
            f"mode={'ALPHA' if self.alpha else 'non-alpha'})"
        )
        while not self._stop.is_set():
            try:
                self.sync_from_remote()
            except Exception:
                logger.exception("Sync loop error (will retry)")

            self._stop.wait(timeout=self.sync_interval)

    def _run_tick_loop(self) -> None:
        """Main thread: run tick every tick_interval seconds."""
        logger.info(f"Tick loop started (every {self.tick_interval}s)")
        while not self._stop.is_set():
            try:
                self.run_tick_and_push()
            except Exception:
                logger.exception("Tick loop error (will retry)")

            self._stop.wait(timeout=self.tick_interval)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the sync manager. Blocks until interrupted."""
        mode = "ALPHA (Docker is dominant)" if self.alpha else "NON-ALPHA (remote is dominant)"
        logger.info(f"╔{'═' * 50}╗")
        logger.info(f"║  Continuity Orchestrator — GIT SYNC MODE")
        logger.info(f"║  Mode: {mode}")
        logger.info(f"║  Tick interval: {self.tick_interval}s")
        logger.info(f"║  Sync interval: {self.sync_interval}s")
        logger.info(f"╚{'═' * 50}╝")

        # Initial sync — always pull latest from remote
        self.initial_sync()

        # Start background sync thread
        sync_thread = threading.Thread(
            target=self._run_sync_loop,
            name="git-sync",
            daemon=True,
        )
        sync_thread.start()

        # Run tick loop in main thread (blocks until Ctrl+C)
        try:
            self._run_tick_loop()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self._stop.set()
            sync_thread.join(timeout=5)
            logger.info("Goodbye")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coordinated git sync + tick loop for Docker deployment."
    )
    parser.add_argument("--repo", required=True, help="Path to the git repository")
    parser.add_argument("--branch", default="main", help="Branch to sync (default: main)")
    parser.add_argument("--public-dir", default=None, help="Directory for built site output")
    parser.add_argument(
        "--tick-interval", type=int, default=900,
        help="Seconds between ticks (default: 900 = 15min)",
    )
    parser.add_argument(
        "--sync-interval", type=int, default=30,
        help="Seconds between remote syncs (default: 30)",
    )
    parser.add_argument(
        "--alpha", action="store_true", default=False,
        help="Alpha mode: this Docker instance is dominant (overrides remote on divergence)",
    )

    args = parser.parse_args()

    # Env var override for alpha mode
    env_alpha = os.environ.get("DOCKER_GIT_SYNC_ALPHA", "").lower()
    alpha = args.alpha or env_alpha in ("true", "1", "yes")

    sync = DockerGitSync(
        repo=Path(args.repo),
        branch=args.branch,
        alpha=alpha,
        tick_interval=args.tick_interval,
        sync_interval=args.sync_interval,
        public_dir=Path(args.public_dir) if args.public_dir else None,
    )
    sync.start()


if __name__ == "__main__":
    main()
