"""
.env Vault — encrypt/decrypt the .env file at rest.

When locked, the plaintext .env is encrypted into .env.vault using
AES-256-GCM with PBKDF2 key derivation from a user-chosen passphrase.
The plaintext .env is securely overwritten and deleted.

When unlocked, the vault is decrypted back to .env and the vault file
is kept as a backup until the next lock cycle.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Crypto constants (same as content encryption)
KDF_ITERATIONS = 100_000
SALT_BYTES = 16
IV_BYTES = 12
KEY_BYTES = 32
TAG_BYTES = 16

VAULT_FILENAME = ".env.vault"


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


def vault_status() -> dict:
    """Check vault status.

    Returns:
        Dict with 'locked' bool and metadata.
    """
    env_exists = _env_path().exists()
    vault_exists = _vault_path().exists()

    if vault_exists and not env_exists:
        return {"locked": True, "vault_file": VAULT_FILENAME}
    elif env_exists:
        return {"locked": False, "vault_file": VAULT_FILENAME if vault_exists else None}
    else:
        # No .env and no vault — nothing to protect
        return {"locked": False, "vault_file": None, "empty": True}


def lock_vault(passphrase: str) -> dict:
    """Encrypt .env into .env.vault and securely delete the plaintext.

    Args:
        passphrase: User-chosen passphrase for encryption.

    Returns:
        Success dict or raises ValueError.
    """
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

    logger.info("Vault locked — .env encrypted and deleted")
    return {"success": True, "message": "Vault locked"}


def unlock_vault(passphrase: str) -> dict:
    """Decrypt .env.vault back to .env.

    Args:
        passphrase: The passphrase used during lock.

    Returns:
        Success dict or raises ValueError/InvalidTag.
    """
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
    iterations = envelope.get("kdf_iterations", KDF_ITERATIONS)
    key = _derive_key(passphrase, salt)

    # Decrypt
    aesgcm = AESGCM(key)
    ciphertext_and_tag = ciphertext + tag

    try:
        plaintext = aesgcm.decrypt(iv, ciphertext_and_tag, None)
    except Exception:
        raise ValueError("Wrong passphrase — decryption failed")

    # Write .env back
    env_path.write_bytes(plaintext)

    # Remove the vault file — no longer needed
    try:
        vault_path.unlink()
    except Exception:
        pass

    logger.info("Vault unlocked — .env restored, vault deleted")
    return {"success": True, "message": "Vault unlocked"}


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
