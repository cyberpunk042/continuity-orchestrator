"""
GitHub Sync — Sync secrets, variables, and workflow state to GitHub mirrors.

Uses the `gh` CLI to propagate secrets and variables to slave repos,
and to enable/disable workflows for failover.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .config import MirrorConfig

logger = logging.getLogger(__name__)

# ┌─────────────────────────────────────────────────────────────────────┐
# │ ⚠️  These lists MUST stay in sync with:                            │
# │   1. .github/workflows/cron.yml  → env: blocks (what the pipeline │
# │      injects). If a secret is here but not in cron.yml env:, the  │
# │      mirror-sync step won't have the value to push.               │
# │   2. src/admin/static/index.html → GITHUB_SECRETS / GITHUB_VARS   │
# │      arrays (~line 1765). If a value isn't in the right tier,     │
# │      it shows "Local only" and never reaches GitHub.              │
# └─────────────────────────────────────────────────────────────────────┘

# Secrets that should be synced to mirrors
# Must match what .github/workflows/cron.yml and deploy-site.yml inject
#
# WHAT IS NOT HERE (and why):
# - GITHUB_TOKEN: NEVER sync the master's token to the slave. The slave's
#   own GITHUB_TOKEN (auto-provided by GitHub Actions) is sufficient for
#   sentinel health checks on the master repo. Syncing the master's token
#   would give the slave write access to the master — a security hole.
# - MIRROR_1_TOKEN: Never synced to slave — slave doesn't manage its own mirrors.
# - RELEASE_SECRET: Master-specific. Syncing it would let the slave trigger
#   disclosure using the master's secret. If slave promotes, it uses its own.
# - RENEWAL_TRIGGER_TOKEN: Per-repo PAT, synced via RENAMED_SECRETS instead.
SYNCABLE_SECRETS = [
    "CONTINUITY_CONFIG",      # Core config (needed if slave promotes to master)
    "RESEND_API_KEY",         # Email adapter (needed for failover notifications)
    "TWILIO_ACCOUNT_SID",     # SMS adapter
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "X_API_KEY",              # X/Twitter adapter
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_SECRET",
    "REDDIT_CLIENT_ID",       # Reddit adapter
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USERNAME",
    "REDDIT_PASSWORD",
    "PERSISTENCE_API_URL",    # Persistence layer
    "PERSISTENCE_API_KEY",    # Persistence auth (cron.yml line 99)
    "ADMIN_TOKEN",            # Admin panel auth
]

# Per-mirror secrets that are stored on the MASTER with a mirror-specific name
# and pushed to the slave under a different (standard) name.
#
# Example: master stores MIRROR_1_RENEWAL_TRIGGER_TOKEN (a PAT scoped to the
# slave's repo). The sync pushes it as RENEWAL_TRIGGER_TOKEN on the slave.
# The "{N}" placeholder is replaced with the mirror number (1, 2, ...).
RENAMED_SECRETS = {
    "MIRROR_{N}_RENEWAL_TRIGGER_TOKEN": "RENEWAL_TRIGGER_TOKEN",
}

# Variables (non-secret) to sync to mirror repos
# Must match what .github/workflows/cron.yml reads via ${{ vars.X }}
SYNCABLE_VARS = [
    "MASTER_REPO",        # Primary repo for sentinel to check
    "MIRROR_ROLE",        # SLAVE / TEMPORARY_MASTER / MASTER
    "SENTINEL_THRESHOLD", # Number of failures before self-promotion
    "ADAPTER_MOCK_MODE",  # cron.yml line 51 — 'true' while slave
]


def compute_fingerprint(items: Dict[str, str]) -> str:
    """Hash a dict of name→value pairs into a short fingerprint.

    Used to detect staleness: if the fingerprint at status-check time
    differs from the one stored at sync time, values have changed.
    """
    canonical = "\n".join(f"{k}={v}" for k, v in sorted(items.items()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def secrets_fingerprint(mirror_num: str = "1") -> str:
    """Compute fingerprint for secrets that would be synced right now."""
    items = {}
    for name in SYNCABLE_SECRETS:
        val = os.environ.get(name)
        if val:
            items[name] = val
    # Include renamed secrets
    for master_tmpl, slave_name in RENAMED_SECRETS.items():
        master_key = master_tmpl.replace("{N}", mirror_num)
        val = os.environ.get(master_key)
        if val:
            items[slave_name] = val
    return compute_fingerprint(items)


def variables_fingerprint() -> str:
    """Compute fingerprint for variables that would be synced right now."""
    master_repo = os.environ.get("GITHUB_REPOSITORY", "")
    items = {
        "MIRROR_ROLE": "SLAVE",
        "SENTINEL_THRESHOLD": os.environ.get("SENTINEL_THRESHOLD", "3"),
        "ADAPTER_MOCK_MODE": "true",
    }
    if master_repo:
        items["MASTER_REPO"] = master_repo
    return compute_fingerprint(items)

def sync_secret(
    token: str,
    repo: str,
    secret_name: str,
    secret_value: str,
) -> Tuple[bool, Optional[str]]:
    """
    Set a secret on a GitHub repository using `gh secret set`.

    Uses the gh CLI which handles encryption internally.
    Returns (success, error_message).
    """
    import subprocess

    env = {**os.environ, "GH_TOKEN": token}

    try:
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "-R", repo],
            input=secret_value,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            logger.info(f"[mirror-github] Secret {secret_name} synced to {repo}")
            return True, None
        return False, f"gh secret set failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "gh CLI not installed. Install from https://cli.github.com"
    except subprocess.TimeoutExpired:
        return False, "gh secret set timed out"
    except Exception as e:
        return False, str(e)


def sync_variable(
    token: str,
    repo: str,
    var_name: str,
    var_value: str,
) -> Tuple[bool, Optional[str]]:
    """
    Set a variable on a GitHub repository using `gh variable set`.

    Uses the gh CLI which handles create-or-update internally.
    Returns (success, error_message).
    """
    import subprocess

    env = {**os.environ, "GH_TOKEN": token}

    try:
        result = subprocess.run(
            ["gh", "variable", "set", var_name, "-R", repo, "--body", var_value],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            logger.info(f"[mirror-github] Variable {var_name} synced to {repo}")
            return True, None
        return False, f"gh variable set failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "gh CLI not installed. Install from https://cli.github.com"
    except subprocess.TimeoutExpired:
        return False, "gh variable set timed out"
    except Exception as e:
        return False, str(e)


def sync_all_secrets(
    mirror: MirrorConfig,
) -> Tuple[bool, int, int, Optional[str]]:
    """
    Sync all known secrets from local env to a GitHub mirror.

    Returns (overall_success, synced_count, total_count, error_message).
    """
    if not mirror.is_github or not mirror.sync_secrets:
        return True, 0, 0, "Secrets sync not configured for this mirror"

    synced = 0
    total = 0
    errors = []

    for secret_name in SYNCABLE_SECRETS:
        value = os.environ.get(secret_name)
        if not value:
            continue

        total += 1

        ok, err = sync_secret(
            mirror.token, mirror.repo, secret_name, value
        )
        if ok:
            synced += 1
        else:
            errors.append(f"{secret_name}: {err}")

    overall_ok = synced == total
    error_msg = "; ".join(errors) if errors else None

    logger.info(
        f"[mirror-github] Secrets sync to {mirror.repo}: {synced}/{total}"
        + (f" — errors: {error_msg}" if error_msg else "")
    )

    return overall_ok, synced, total, error_msg


def sync_all_variables(
    mirror: MirrorConfig,
    master_repo: Optional[str] = None,
) -> Tuple[bool, int, int, Optional[str]]:
    """
    Sync variables to a GitHub mirror.

    Returns (overall_success, synced_count, total_count, error_message).
    """
    if not mirror.is_github or not mirror.sync_vars:
        return True, 0, 0, "Variables sync not configured for this mirror"

    # Build the variables to sync
    vars_to_sync = {
        "MIRROR_ROLE": "SLAVE",
        "SENTINEL_THRESHOLD": os.environ.get("SENTINEL_THRESHOLD", "3"),
        "ADAPTER_MOCK_MODE": "true",  # Slave doesn't send notifications
    }

    # Set MASTER_REPO so sentinel knows what to check
    if master_repo:
        vars_to_sync["MASTER_REPO"] = master_repo
    else:
        # Try to detect from current GITHUB_REPOSITORY
        detected = os.environ.get("GITHUB_REPOSITORY")
        if detected:
            vars_to_sync["MASTER_REPO"] = detected

    synced = 0
    total = len(vars_to_sync)
    errors = []

    for var_name, var_value in vars_to_sync.items():
        ok, err = sync_variable(mirror.token, mirror.repo, var_name, var_value)
        if ok:
            synced += 1
        else:
            errors.append(f"{var_name}: {err}")

    overall_ok = synced == total
    error_msg = "; ".join(errors) if errors else None

    return overall_ok, synced, total, error_msg


def set_workflow_enabled(
    token: str,
    repo: str,
    workflow_filename: str,
    enabled: bool,
) -> Tuple[bool, Optional[str]]:
    """
    Enable or disable a GitHub Actions workflow using `gh workflow`.

    Returns (success, error_message).
    """
    import subprocess

    action = "enable" if enabled else "disable"
    env = {**os.environ, "GH_TOKEN": token}

    try:
        result = subprocess.run(
            ["gh", "workflow", action, workflow_filename, "-R", repo],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            logger.info(
                f"[mirror-github] Workflow {workflow_filename} "
                f"{'enabled' if enabled else 'disabled'} on {repo}"
            )
            return True, None
        return False, f"gh workflow {action} failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "gh CLI not installed. Install from https://cli.github.com"
    except subprocess.TimeoutExpired:
        return False, f"gh workflow {action} timed out"
    except Exception as e:
        return False, str(e)


def setup_slave_workflows(
    mirror: MirrorConfig,
) -> Tuple[bool, Optional[str]]:
    """
    Configure workflows on a slave: disable operational ones, enable sentinel.

    Returns (success, error_message).
    """
    if not mirror.is_github:
        return True, "Not a GitHub mirror"

    errors = []

    # Disable operational workflows
    for workflow in ["cron.yml", "deploy-site.yml"]:
        ok, err = set_workflow_enabled(mirror.token, mirror.repo, workflow, False)
        if not ok:
            errors.append(f"disable {workflow}: {err}")

    # Enable sentinel
    ok, err = set_workflow_enabled(mirror.token, mirror.repo, "sentinel.yml", True)
    if not ok:
        errors.append(f"enable sentinel.yml: {err}")

    return len(errors) == 0, "; ".join(errors) if errors else None


def check_repo_health(
    token: str, repo: str
) -> Tuple[bool, Optional[str]]:
    """
    Check if a GitHub repository is reachable using `gh repo view`.

    Returns (healthy, error_message).
    """
    import subprocess

    env = {**os.environ, "GH_TOKEN": token}

    try:
        result = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "name"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        if result.returncode == 0:
            return True, None
        return False, f"gh repo view failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "gh CLI not installed. Install from https://cli.github.com"
    except subprocess.TimeoutExpired:
        return False, "gh repo view timed out"
    except Exception as e:
        return False, str(e)
