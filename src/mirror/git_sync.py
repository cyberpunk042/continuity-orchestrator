"""
Git Sync — Push code to mirror remotes.

Uses git push to sync code, state, and audit to slave repos.
Manages git remotes dynamically based on mirror config.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .config import MirrorConfig

logger = logging.getLogger(__name__)


def ensure_remote(mirror: MirrorConfig, project_root: Path) -> bool:
    """
    Ensure a git remote exists for the mirror.

    Remote name = mirror.id (e.g. "mirror-1")
    Returns True if the remote is ready.
    """
    remote_name = mirror.id
    remote_url = mirror.remote_url

    if not remote_url:
        logger.error(f"[mirror-git] No remote URL for {mirror.id}")
        return False

    # Check if remote already exists
    result = subprocess.run(
        ["git", "remote", "get-url", remote_name],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode == 0:
        current_url = result.stdout.strip()
        # Update if URL changed (e.g. token rotation)
        if current_url != remote_url:
            logger.info(f"[mirror-git] Updating remote URL for {remote_name}")
            subprocess.run(
                ["git", "remote", "set-url", remote_name, remote_url],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
        return True

    # Remote doesn't exist — add it
    logger.info(f"[mirror-git] Adding remote: {remote_name} → {mirror.display_name}")
    result = subprocess.run(
        ["git", "remote", "add", remote_name, remote_url],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        logger.error(
            f"[mirror-git] Failed to add remote {remote_name}: {result.stderr}"
        )
        return False

    return True


def push_to_mirror(
    mirror: MirrorConfig,
    project_root: Path,
    branch: str = "main",
    force: bool = False,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Push current branch to a mirror remote.

    Returns (success, commit_hash, error_message).
    """

    remote_name = mirror.id

    # Ensure remote is configured
    if not ensure_remote(mirror, project_root):
        return False, None, f"Failed to configure remote for {mirror.id}"

    # Get current HEAD for reporting
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=5,
    )
    head_hash = head_result.stdout.strip()[:12] if head_result.returncode == 0 else None

    # Push
    cmd = ["git", "push", remote_name, branch]
    if force:
        cmd.insert(2, "--force")

    logger.info(
        f"[mirror-git] Pushing to {mirror.display_name} ({remote_name}/{branch})"
    )

    result = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode == 0:
        output = result.stderr.strip() or result.stdout.strip()
        up_to_date = "Everything up-to-date" in (output or "")
        if up_to_date:
            logger.info(f"[mirror-git] {mirror.display_name}: already up to date")
        else:
            logger.info(f"[mirror-git] {mirror.display_name}: pushed {head_hash}")
        return True, head_hash, None

    error = result.stderr.strip() or result.stdout.strip() or "Push failed"
    logger.error(f"[mirror-git] Push to {mirror.display_name} failed: {error}")
    return False, head_hash, error


def push_all_mirrors(
    mirrors: list,
    project_root: Path,
    branch: str = "main",
    force: bool = True,
) -> dict:
    """
    Push to all mirrors. Returns results per mirror.

    Returns: {mirror_id: {"ok": bool, "commit": str, "error": str}}
    """
    results = {}

    for mirror in mirrors:
        ok, commit, error = push_to_mirror(mirror, project_root, branch, force=force)
        results[mirror.id] = {
            "ok": ok,
            "commit": commit,
            "error": error,
        }

    return results
