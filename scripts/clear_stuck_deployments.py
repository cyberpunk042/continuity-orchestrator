#!/usr/bin/env python3
"""
Clear stuck GitHub Pages deployments before a new deployment.

Finds recent deployments in the 'github-pages' environment that are stuck
in non-terminal states (in_progress, queued, waiting, pending) and marks
them as inactive. This prevents the "in progress deployment" lock that
blocks deploy-pages@v4 from creating new deployments.

Usage (from GitHub Actions):
    python scripts/clear_stuck_deployments.py

Requires:
    - `gh` CLI authenticated with access to the repository
    - GITHUB_REPOSITORY env var (set automatically by Actions)

Exit codes:
    0 — success (even if no stuck deployments found)
    1 — fatal error (gh CLI missing, etc.)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def run_gh(*args: str) -> subprocess.CompletedProcess:
    """Run a `gh` CLI command and return the result."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


def get_repo() -> str:
    """Get the repository slug (owner/repo)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        # Try to detect from git remote
        result = run_gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
        if result.returncode == 0 and result.stdout.strip():
            repo = result.stdout.strip()
    return repo


def main() -> int:
    repo = get_repo()
    if not repo:
        print("ERROR: Cannot determine repository. Set GITHUB_REPOSITORY.", file=sys.stderr)
        return 1

    print(f"Checking for stuck deployments in {repo}...")

    # Fetch recent deployments for the github-pages environment
    result = run_gh(
        "api", f"repos/{repo}/deployments",
        "--jq", ".",
        "-f", "environment=github-pages",
        "-f", "per_page=5",
    )
    if result.returncode != 0:
        print(f"WARNING: Could not fetch deployments: {result.stderr.strip()}")
        return 0  # Non-fatal — let the deploy attempt proceed

    try:
        deployments = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("WARNING: Could not parse deployments response")
        return 0

    if not isinstance(deployments, list):
        print("WARNING: Unexpected deployments format")
        return 0

    stuck_states = {"in_progress", "queued", "waiting", "pending"}
    cleared = 0

    for dep in deployments:
        dep_id = dep.get("id")
        sha = dep.get("sha", "?")[:12]

        if not dep_id:
            continue

        # Get the latest status for this deployment
        status_result = run_gh(
            "api", f"repos/{repo}/deployments/{dep_id}/statuses",
        )
        if status_result.returncode != 0:
            continue

        try:
            statuses = json.loads(status_result.stdout)
        except json.JSONDecodeError:
            continue

        if not statuses:
            continue

        latest_state = statuses[0].get("state", "")
        if latest_state not in stuck_states:
            continue

        # Mark as inactive
        print(f"  Clearing stuck deployment {dep_id} (sha:{sha}, state:{latest_state})")
        clear_result = run_gh(
            "api", "-X", "POST",
            f"repos/{repo}/deployments/{dep_id}/statuses",
            "-f", "state=inactive",
            "-f", "description=Auto-cleared before new deployment",
        )
        if clear_result.returncode == 0:
            cleared += 1
        else:
            print(f"    WARNING: Failed to clear: {clear_result.stderr.strip()}")

    if cleared:
        print(f"Cleared {cleared} stuck deployment(s)")
    else:
        print("No stuck deployments found")

    return 0


if __name__ == "__main__":
    sys.exit(main())
