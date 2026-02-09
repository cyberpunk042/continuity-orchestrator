"""
Admin server shared helpers.

Functions used across multiple route blueprints. Each takes
`project_root` explicitly so they can be called from any context
without depending on closure variables.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def fresh_env(project_root: Path) -> dict:
    """Build subprocess env with fresh .env values.

    The server process's os.environ is stale — it was loaded at startup.
    This reads the current .env file on each call so test commands
    (email, SMS, etc.) use the latest values.
    """
    env = {**os.environ, "TERM": "dumb"}
    env_file = project_root / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Strip surrounding quotes
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    env[key] = value
    return env


def trigger_mirror_sync_bg(project_root: Path, mode: str = "all") -> bool:
    """Fire mirror-sync in the background if mirroring is enabled.

    Called after git sync or secrets push so the mirror stays up to date.
    After the sync, auto-commits the state file so it doesn't leave a
    dirty working tree (which would cause an infinite sync loop).
    Uses a lock file so the UI can detect syncing in progress.

    Args:
        project_root: Path to the project root directory.
        mode: 'all', 'code-only', or 'secrets-only'
    Returns:
        True if mirror sync was triggered, False if skipped.
    """
    env = fresh_env(project_root)
    if env.get("MIRROR_ENABLED", "").lower() != "true":
        return False
    lock = project_root / "state" / ".mirror_sync_lock"
    if lock.exists():
        logger.info("[mirror-bg] Sync already in progress, skipping")
        return False
    flag = f"--{mode}" if mode != "all" else ""
    lock_path = str(lock)
    # Shell script: lock → mirror-sync → auto-commit state → unlock
    script = (
        f'touch "{lock_path}"; '
        f'python -m src.main mirror-sync {flag} 2>/dev/null; '
        'if ! git diff --quiet state/mirror_status.json 2>/dev/null; then '
        'git add state/mirror_status.json && '
        'git commit -m "mirror: update sync state" --no-verify && '
        'git push 2>/dev/null || true; '
        'fi; '
        f'rm -f "{lock_path}"'
    )
    logger.info("[mirror-bg] Triggering background mirror-sync (%s)", mode)
    try:
        subprocess.Popen(
            ["bash", "-c", script],
            cwd=str(project_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        logger.warning("[mirror-bg] Failed to start mirror-sync: %s", e)
        lock.unlink(missing_ok=True)
        return False


def gh_repo_flag(project_root: Path) -> list:
    """Get -R repo flag for gh CLI commands.

    Required because mirror remotes cause gh to fail with
    'multiple remotes detected' when no -R is specified.
    """
    repo = fresh_env(project_root).get("GITHUB_REPOSITORY", "")
    return ["-R", repo] if repo else []
