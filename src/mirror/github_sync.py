"""
GitHub Sync — Sync secrets, variables, and workflow state to GitHub mirrors.

Uses the GitHub REST API to propagate secrets and variables to slave repos,
and to enable/disable workflows for failover.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .config import MirrorConfig

logger = logging.getLogger(__name__)

# Optional httpx import (same pattern as other adapters)
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

# Secrets that should be synced to mirrors
# These are the env var names that map to GitHub secret names
SYNCABLE_SECRETS = [
    "GITHUB_TOKEN",       # Will be stored as MASTER_TOKEN on slave
    "RESEND_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "PERSISTENCE_API_URL",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USERNAME",
    "REDDIT_PASSWORD",
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_SECRET",
    "RELEASE_SECRET",
    "ADMIN_TOKEN",
]

# Variables (non-secret) to sync
SYNCABLE_VARS = [
    "MASTER_REPO",  # Set to the primary repo for sentinel to check
    "MIRROR_ROLE",  # SLAVE / TEMPORARY_MASTER / MASTER
    "SENTINEL_THRESHOLD",  # Number of failures before self-promotion
]


def _get_headers(token: str) -> Dict[str, str]:
    """Get GitHub API headers."""
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_repo_public_key(
    token: str, repo: str
) -> Optional[Tuple[str, str]]:
    """
    Get the repository's public key for encrypting secrets.

    Returns (key_id, key) or None.
    """
    if not HTTPX_AVAILABLE:
        logger.error("[mirror-github] httpx not available")
        return None

    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    try:
        resp = httpx.get(url, headers=_get_headers(token), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data["key_id"], data["key"]
        logger.error(f"[mirror-github] Failed to get public key: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"[mirror-github] Error getting public key: {e}")
        return None


def _encrypt_secret(public_key: str, secret_value: str) -> str:
    """Encrypt a secret value with the repo's public key using libsodium."""
    try:
        from nacl import encoding, public as nacl_public

        public_key_bytes = nacl_public.PublicKey(
            public_key.encode("utf-8"), encoding.Base64Encoder
        )
        sealed_box = nacl_public.SealedBox(public_key_bytes)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")
    except ImportError:
        logger.error(
            "[mirror-github] PyNaCl not installed. "
            "Install with: pip install PyNaCl"
        )
        raise
    except Exception as e:
        logger.error(f"[mirror-github] Encryption failed: {e}")
        raise


def sync_secret(
    token: str,
    repo: str,
    secret_name: str,
    secret_value: str,
    key_id: str,
    public_key: str,
) -> Tuple[bool, Optional[str]]:
    """
    Set a secret on a GitHub repository.

    Returns (success, error_message).
    """
    if not HTTPX_AVAILABLE:
        return False, "httpx not available"

    try:
        encrypted_value = _encrypt_secret(public_key, secret_value)
    except Exception as e:
        return False, f"Encryption failed: {e}"

    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"

    try:
        resp = httpx.put(
            url,
            headers=_get_headers(token),
            json={
                "encrypted_value": encrypted_value,
                "key_id": key_id,
            },
            timeout=15,
        )
        if resp.status_code in (201, 204):
            logger.info(f"[mirror-github] Secret {secret_name} synced to {repo}")
            return True, None
        return False, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)


def sync_variable(
    token: str,
    repo: str,
    var_name: str,
    var_value: str,
) -> Tuple[bool, Optional[str]]:
    """
    Set a variable on a GitHub repository.

    Returns (success, error_message).
    """
    if not HTTPX_AVAILABLE:
        return False, "httpx not available"

    headers = _get_headers(token)

    # Try to update first (PATCH), then create (POST) if not found
    url = f"https://api.github.com/repos/{repo}/actions/variables/{var_name}"

    try:
        resp = httpx.patch(
            url,
            headers=headers,
            json={"value": var_value},
            timeout=15,
        )

        if resp.status_code == 204:
            logger.info(f"[mirror-github] Variable {var_name} updated on {repo}")
            return True, None

        if resp.status_code == 404:
            # Variable doesn't exist — create it
            create_url = f"https://api.github.com/repos/{repo}/actions/variables"
            resp = httpx.post(
                create_url,
                headers=headers,
                json={"name": var_name, "value": var_value},
                timeout=15,
            )
            if resp.status_code == 201:
                logger.info(f"[mirror-github] Variable {var_name} created on {repo}")
                return True, None
            return False, f"Create failed: HTTP {resp.status_code}"

        return False, f"HTTP {resp.status_code}: {resp.text}"
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

    # Get the repo's public key for encryption
    key_result = get_repo_public_key(mirror.token, mirror.repo)
    if not key_result:
        return False, 0, 0, "Could not get repo public key"

    key_id, public_key = key_result
    synced = 0
    total = 0
    errors = []

    for secret_name in SYNCABLE_SECRETS:
        value = os.environ.get(secret_name)
        if not value:
            continue

        total += 1
        # Special case: GITHUB_TOKEN → MASTER_TOKEN on slave
        target_name = "MASTER_TOKEN" if secret_name == "GITHUB_TOKEN" else secret_name

        ok, err = sync_secret(
            mirror.token, mirror.repo, target_name, value, key_id, public_key
        )
        if ok:
            synced += 1
        else:
            errors.append(f"{target_name}: {err}")

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
    Enable or disable a GitHub Actions workflow.

    Returns (success, error_message).
    """
    if not HTTPX_AVAILABLE:
        return False, "httpx not available"

    headers = _get_headers(token)

    # First, get the workflow ID from its filename
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_filename}"
    try:
        resp = httpx.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return False, f"Workflow {workflow_filename} not found: HTTP {resp.status_code}"

        workflow_id = resp.json()["id"]

        # Enable or disable
        action = "enable" if enabled else "disable"
        action_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/{action}"

        resp = httpx.put(action_url, headers=headers, timeout=15)
        if resp.status_code == 204:
            logger.info(
                f"[mirror-github] Workflow {workflow_filename} "
                f"{'enabled' if enabled else 'disabled'} on {repo}"
            )
            return True, None

        return False, f"HTTP {resp.status_code}: {resp.text}"
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
    Check if a GitHub repository is reachable.

    Returns (healthy, error_message).
    """
    if not HTTPX_AVAILABLE:
        return False, "httpx not available"

    url = f"https://api.github.com/repos/{repo}"
    try:
        resp = httpx.get(url, headers=_get_headers(token), timeout=15)
        if resp.status_code == 200:
            return True, None
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)
