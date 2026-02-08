"""
.env Vault — encrypt/decrypt the .env file at rest.

When locked, the plaintext .env is encrypted into .env.vault using
AES-256-GCM with PBKDF2 key derivation from a user-chosen passphrase.
The plaintext .env is securely overwritten and deleted.

When unlocked, the vault is decrypted back to .env and the vault file
is deleted. The passphrase is held in server memory for auto-lock.

Features:
  - Auto-lock after configurable inactivity (default: 30 min)
  - Rate limiting with exponential backoff on failed unlock attempts
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from threading import Timer, Lock as ThreadLock
from typing import Optional

logger = logging.getLogger(__name__)

# Crypto constants (same as content encryption)
KDF_ITERATIONS = 100_000
SALT_BYTES = 16
IV_BYTES = 12
KEY_BYTES = 32
TAG_BYTES = 16

VAULT_FILENAME = ".env.vault"

# ── In-memory session state ──────────────────────────────────
_session_passphrase: Optional[str] = None     # Held in RAM for auto-lock
_auto_lock_timer: Optional[Timer] = None      # Timer for auto-lock
_auto_lock_minutes: int = 30                  # Default: 30 min inactivity
_lock = ThreadLock()                          # Thread safety

# ── Rate limiting state ──────────────────────────────────────
_failed_attempts: int = 0
_last_failed_time: float = 0
_RATE_LIMIT_TIERS = [
    # (max_attempts, lockout_seconds)
    (3, 30),      # After 3 fails: 30s lockout
    (6, 300),     # After 6 fails: 5min lockout
    (10, 900),    # After 10 fails: 15min lockout
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_path() -> Path:
    return _project_root() / ".env"


def _vault_path() -> Path:
    return _project_root() / VAULT_FILENAME


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive AES-256 key from passphrase using PBKDF2."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


# ── Rate limiting ────────────────────────────────────────────

def _check_rate_limit() -> Optional[dict]:
    """Check if unlock attempts are rate-limited.

    Returns:
        None if allowed, or dict with error info if blocked.
    """
    global _failed_attempts, _last_failed_time

    if _failed_attempts == 0:
        return None

    # Find applicable tier
    lockout_seconds = 0
    for max_attempts, seconds in _RATE_LIMIT_TIERS:
        if _failed_attempts >= max_attempts:
            lockout_seconds = seconds

    if lockout_seconds == 0:
        return None

    elapsed = time.time() - _last_failed_time
    remaining = lockout_seconds - elapsed

    if remaining > 0:
        return {
            "error": f"Too many failed attempts. Try again in {int(remaining)}s.",
            "retry_after": int(remaining),
            "attempts": _failed_attempts,
        }

    return None


def _record_failed_attempt():
    global _failed_attempts, _last_failed_time
    _failed_attempts += 1
    _last_failed_time = time.time()
    logger.warning(f"Vault unlock failed — attempt #{_failed_attempts}")


def _reset_rate_limit():
    global _failed_attempts, _last_failed_time
    _failed_attempts = 0
    _last_failed_time = 0


# ── Auto-lock timer ─────────────────────────────────────────

def _start_auto_lock_timer():
    """(Re)start the auto-lock inactivity timer."""
    global _auto_lock_timer

    _cancel_auto_lock_timer()

    if _auto_lock_minutes <= 0:
        return  # Disabled

    def _on_timeout():
        logger.info(f"Vault auto-lock triggered after {_auto_lock_minutes}min inactivity")
        try:
            auto_lock()
        except Exception as e:
            logger.error(f"Auto-lock failed: {e}")

    _auto_lock_timer = Timer(_auto_lock_minutes * 60, _on_timeout)
    _auto_lock_timer.daemon = True  # Don't prevent server shutdown
    _auto_lock_timer.start()
    logger.debug(f"Auto-lock timer set: {_auto_lock_minutes}min")


def _cancel_auto_lock_timer():
    """Cancel any pending auto-lock timer."""
    global _auto_lock_timer
    if _auto_lock_timer is not None:
        _auto_lock_timer.cancel()
        _auto_lock_timer = None


def touch_activity(request_path: str = "", request_method: str = "GET"):
    """Reset the auto-lock timer on user activity.

    Only resets for user-initiated requests, NOT background polling.
    Call this from the request middleware.
    """
    if _session_passphrase is None:
        return

    # Ignore background polling endpoints — these fire every 10-30s
    # and would prevent the timer from ever expiring
    _POLLING_ENDPOINTS = {
        "/api/status",
        "/api/git/status",
        "/api/env/read",
        "/api/vault/status",
        "/api/git/fetch",
    }

    if request_path in _POLLING_ENDPOINTS and request_method in ("GET", "POST"):
        return

    # Also ignore static files
    if request_path.startswith("/static/"):
        return

    _start_auto_lock_timer()


# ── Vault operations ────────────────────────────────────────

def vault_status() -> dict:
    """Check vault status.

    Returns:
        Dict with 'locked' bool and metadata.
    """
    env_exists = _env_path().exists()
    vault_exists = _vault_path().exists()

    result = {}

    if vault_exists and not env_exists:
        result = {"locked": True, "vault_file": VAULT_FILENAME}
    elif env_exists:
        result = {"locked": False, "vault_file": VAULT_FILENAME if vault_exists else None}
    else:
        # No .env and no vault — nothing to protect
        result = {"locked": False, "vault_file": None, "empty": True}

    # Include auto-lock config
    result["auto_lock_minutes"] = _auto_lock_minutes
    result["has_passphrase"] = _session_passphrase is not None

    # Include rate limit info if blocked
    rate_info = _check_rate_limit()
    if rate_info:
        result["rate_limited"] = True
        result["retry_after"] = rate_info["retry_after"]

    return result


def lock_vault(passphrase: str) -> dict:
    """Encrypt .env into .env.vault and securely delete the plaintext.

    Args:
        passphrase: User-chosen passphrase for encryption.

    Returns:
        Success dict or raises ValueError.
    """
    global _session_passphrase

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    env_path = _env_path()
    vault_path = _vault_path()

    if not env_path.exists():
        raise ValueError(".env file not found — nothing to lock")

    if not passphrase or len(passphrase) < 4:
        raise ValueError("Passphrase must be at least 4 characters")

    # Read plaintext
    plaintext = env_path.read_bytes()

    # Generate random salt and IV
    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)

    # Derive key
    key = _derive_key(passphrase, salt)

    # Encrypt
    aesgcm = AESGCM(key)
    ciphertext_and_tag = aesgcm.encrypt(iv, plaintext, None)
    ciphertext = ciphertext_and_tag[:-TAG_BYTES]
    tag = ciphertext_and_tag[-TAG_BYTES:]

    # Build vault envelope
    envelope = {
        "vault": True,
        "version": 1,
        "algorithm": "aes-256-gcm",
        "kdf": "pbkdf2-sha256",
        "kdf_iterations": KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }

    # Write vault
    vault_path.write_text(
        json.dumps(envelope, indent=2) + "\n",
        encoding="utf-8",
    )

    # Securely overwrite plaintext .env before deleting
    _secure_delete(env_path)

    # Store passphrase in memory for auto-lock re-use
    with _lock:
        _session_passphrase = passphrase

    # Cancel auto-lock timer (vault is already locked)
    _cancel_auto_lock_timer()

    logger.info("Vault locked — .env encrypted and deleted")
    return {"success": True, "message": "Vault locked"}


def unlock_vault(passphrase: str) -> dict:
    """Decrypt .env.vault back to .env.

    Args:
        passphrase: The passphrase used during lock.

    Returns:
        Success dict or raises ValueError/InvalidTag.
    """
    global _session_passphrase

    # Check rate limit first
    rate_info = _check_rate_limit()
    if rate_info:
        raise ValueError(rate_info["error"])

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    vault_path = _vault_path()
    env_path = _env_path()

    if not vault_path.exists():
        raise ValueError("No vault file found — nothing to unlock")

    if env_path.exists():
        raise ValueError(".env already exists — vault is already unlocked")

    # Read vault envelope
    envelope = json.loads(vault_path.read_text(encoding="utf-8"))

    if not envelope.get("vault"):
        raise ValueError("Invalid vault file format")

    # Decode fields
    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    tag = base64.b64decode(envelope["tag"])
    ciphertext = base64.b64decode(envelope["ciphertext"])

    # Derive key
    key = _derive_key(passphrase, salt)

    # Decrypt
    aesgcm = AESGCM(key)
    ciphertext_and_tag = ciphertext + tag

    try:
        plaintext = aesgcm.decrypt(iv, ciphertext_and_tag, None)
    except Exception:
        _record_failed_attempt()
        raise ValueError("Wrong passphrase — decryption failed")

    # Success — reset rate limit
    _reset_rate_limit()

    # Write .env back
    env_path.write_bytes(plaintext)

    # Remove the vault file — no longer needed
    try:
        vault_path.unlink()
    except Exception:
        pass

    # Store passphrase for auto-lock
    with _lock:
        _session_passphrase = passphrase

    # Start auto-lock inactivity timer
    _start_auto_lock_timer()

    logger.info("Vault unlocked — .env restored, vault deleted")
    return {"success": True, "message": "Vault unlocked"}


def auto_lock() -> dict:
    """Auto-lock using the stored passphrase from the last unlock.

    Called by the inactivity timer. If no passphrase is stored,
    this is a no-op.
    """
    with _lock:
        passphrase = _session_passphrase

    if not passphrase:
        logger.warning("Auto-lock skipped — no passphrase in memory")
        return {"success": False, "message": "No passphrase stored"}

    if not _env_path().exists():
        logger.debug("Auto-lock skipped — .env doesn't exist (already locked?)")
        return {"success": False, "message": "Already locked"}

    return lock_vault(passphrase)


def set_auto_lock_minutes(minutes: int):
    """Configure the auto-lock timeout.

    Args:
        minutes: Minutes of inactivity before auto-lock. 0 to disable.
    """
    global _auto_lock_minutes
    _auto_lock_minutes = max(0, minutes)

    # Restart timer with new duration if vault is unlocked
    if _session_passphrase is not None:
        _start_auto_lock_timer()

    logger.info(f"Auto-lock timeout set to {_auto_lock_minutes}min"
                + (" (disabled)" if _auto_lock_minutes == 0 else ""))


def _secure_delete(path: Path):
    """Overwrite file with random data before deleting."""
    try:
        size = path.stat().st_size
        # Overwrite with random bytes 3 times
        for _ in range(3):
            path.write_bytes(os.urandom(size))
            os.fsync(os.open(str(path), os.O_WRONLY))
        path.unlink()
    except Exception:
        # Fallback: just delete
        try:
            path.unlink()
        except Exception:
            pass
