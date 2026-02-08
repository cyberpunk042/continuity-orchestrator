"""
Content Encryption — AES-256-GCM encryption for Editor.js article files.

Provides symmetric encryption for article content so that sensitive disclosure
documents can be stored safely in a public repository. The decryption key is
kept in .env (locally) or GitHub Secrets (CI), never committed.

## Cryptographic Design

- **Algorithm**: AES-256-GCM (authenticated encryption with associated data)
- **Key derivation**: PBKDF2-HMAC-SHA256 with 100 000 iterations
- **IV**: 12 random bytes (GCM standard nonce size)
- **Salt**: 16 random bytes (unique per encryption)
- **Passphrase**: Human-readable string stored as CONTENT_ENCRYPTION_KEY

## File Format

Encrypted articles are standard JSON with an envelope:

    {
        "encrypted": true,
        "version": 1,
        "algorithm": "aes-256-gcm",
        "kdf": "pbkdf2-sha256",
        "kdf_iterations": 100000,
        "salt": "<base64>",
        "iv": "<base64>",
        "tag": "<base64>",
        "ciphertext": "<base64>"
    }

## Usage

    from src.content.crypto import encrypt_content, decrypt_content, is_encrypted

    # Encrypt
    envelope = encrypt_content(editor_js_dict, passphrase="my-secret")

    # Check
    assert is_encrypted(envelope)

    # Decrypt
    original = decrypt_content(envelope, passphrase="my-secret")
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------

ENVELOPE_VERSION = 1
ALGORITHM = "aes-256-gcm"
KDF = "pbkdf2-sha256"
KDF_ITERATIONS = 100_000
SALT_BYTES = 16
IV_BYTES = 12  # GCM standard nonce length
KEY_BYTES = 32  # AES-256
TAG_BYTES = 16  # GCM tag length (128 bits)

ENV_VAR = "CONTENT_ENCRYPTION_KEY"

# Passphrase generation: 32 URL-safe characters ≈ 192 bits of entropy
GENERATED_KEY_LENGTH = 32


# -- Key Management -----------------------------------------------------------


def generate_key() -> str:
    """
    Generate a new content encryption passphrase.

    Returns a URL-safe string with sufficient entropy for use as
    CONTENT_ENCRYPTION_KEY. The passphrase is human-copyable and
    suitable for storing in .env or GitHub Secrets.

    Returns:
        A 32-character URL-safe random string.
    """
    return secrets.token_urlsafe(GENERATED_KEY_LENGTH)


def get_encryption_key() -> Optional[str]:
    """
    Read CONTENT_ENCRYPTION_KEY from environment or .env file.

    The server's os.environ is stale (loaded at startup). If the key
    was set via the admin Secrets page after startup, we fall back to
    reading the .env file directly.

    Returns:
        The passphrase string, or None if not configured.
    """
    # 1. Check live os.environ first
    key = os.environ.get(ENV_VAR)
    if key and key.strip():
        return key.strip()

    # 2. Fall back to reading .env directly (may have been updated at runtime)
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == ENV_VAR:
                        v = v.strip()
                        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                            v = v[1:-1]
                        if v:
                            return v
        except Exception:
            pass

    return None


# -- Encryption / Decryption -------------------------------------------------


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit AES key from a passphrase using PBKDF2-HMAC-SHA256.

    Args:
        passphrase: Human-readable passphrase string.
        salt: Random salt bytes (must be stored with ciphertext).

    Returns:
        32-byte derived key.
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_content(data: Dict[str, Any], passphrase: str) -> Dict[str, Any]:
    """
    Encrypt an Editor.js content dict into an encrypted envelope.

    The content is serialized to compact JSON, then encrypted with AES-256-GCM.
    A fresh random salt and IV are generated for each call, so encrypting the
    same content twice produces different ciphertext.

    Args:
        data: Editor.js JSON content (dict with "blocks", "time", etc.)
        passphrase: The CONTENT_ENCRYPTION_KEY passphrase.

    Returns:
        Envelope dict with encrypted content, ready to write as JSON.

    Raises:
        ValueError: If passphrase is empty.
    """
    if not passphrase or not passphrase.strip():
        raise ValueError("Encryption passphrase must not be empty")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # Serialize content to bytes
    plaintext = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # Generate random salt and IV
    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)

    # Derive key from passphrase + salt
    key = _derive_key(passphrase, salt)

    # Encrypt with AES-256-GCM
    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext + tag appended (tag is last 16 bytes)
    ciphertext_and_tag = aesgcm.encrypt(iv, plaintext, None)

    # Split ciphertext and authentication tag
    ciphertext = ciphertext_and_tag[:-TAG_BYTES]
    tag = ciphertext_and_tag[-TAG_BYTES:]

    return {
        "encrypted": True,
        "version": ENVELOPE_VERSION,
        "algorithm": ALGORITHM,
        "kdf": KDF,
        "kdf_iterations": KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_content(envelope: Dict[str, Any], passphrase: str) -> Dict[str, Any]:
    """
    Decrypt an encrypted envelope back to an Editor.js content dict.

    Verifies the authentication tag to ensure the ciphertext has not
    been tampered with.

    Args:
        envelope: Encrypted envelope dict (as produced by encrypt_content).
        passphrase: The CONTENT_ENCRYPTION_KEY passphrase.

    Returns:
        Original Editor.js content dict.

    Raises:
        ValueError: If the envelope is malformed or passphrase is empty.
        cryptography.exceptions.InvalidTag: If the passphrase is wrong
            or the ciphertext has been tampered with.
    """
    if not passphrase or not passphrase.strip():
        raise ValueError("Decryption passphrase must not be empty")

    if not is_encrypted(envelope):
        raise ValueError("Data is not an encrypted envelope (missing 'encrypted: true')")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # Validate envelope fields
    required = ("salt", "iv", "tag", "ciphertext")
    missing = [f for f in required if f not in envelope]
    if missing:
        raise ValueError(f"Encrypted envelope missing fields: {', '.join(missing)}")

    # Decode base64 fields
    try:
        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        tag = base64.b64decode(envelope["tag"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
    except Exception as e:
        raise ValueError(f"Failed to decode envelope fields: {e}") from e

    # Derive key from passphrase + salt
    iterations = envelope.get("kdf_iterations", KDF_ITERATIONS)
    key = _derive_key(passphrase, salt)

    # Reconstruct ciphertext + tag (AESGCM expects them concatenated)
    ciphertext_and_tag = ciphertext + tag

    # Decrypt and authenticate
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext_and_tag, None)

    # Parse JSON
    return json.loads(plaintext.decode("utf-8"))


# -- Detection ----------------------------------------------------------------


def is_encrypted(data: Dict[str, Any]) -> bool:
    """
    Check if a JSON dict is an encrypted content envelope.

    This is the canonical way to detect encrypted articles. It checks for
    the ``"encrypted": true`` flag combined with required envelope fields.

    Args:
        data: Parsed JSON dict (from an article file).

    Returns:
        True if this is an encrypted envelope, False otherwise.
    """
    if not isinstance(data, dict):
        return False
    if data.get("encrypted") is not True:
        return False
    # Require at least the core envelope fields to avoid false positives
    return "ciphertext" in data and "iv" in data


# -- File Helpers --------------------------------------------------------------


def load_article(path: Path, passphrase: Optional[str] = None) -> Dict[str, Any]:
    """
    Load an article from disk, decrypting if needed.

    This is the primary helper for pipeline integration. It reads a JSON file,
    checks if it's encrypted, and decrypts transparently if a passphrase is
    available.

    Args:
        path: Path to the article JSON file.
        passphrase: Encryption passphrase. If None, reads from environment.
            Required if the article is encrypted.

    Returns:
        Editor.js content dict (always plaintext).

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is encrypted but no passphrase is available.
        cryptography.exceptions.InvalidTag: If the passphrase is wrong.
    """
    if not path.exists():
        raise FileNotFoundError(f"Article not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not is_encrypted(data):
        return data

    # Encrypted — need a key
    key = passphrase or get_encryption_key()
    if not key:
        raise ValueError(
            f"Article '{path.name}' is encrypted but no {ENV_VAR} is configured. "
            f"Set {ENV_VAR} in your .env file or environment."
        )

    return decrypt_content(data, key)


def save_article(
    path: Path,
    content: Dict[str, Any],
    *,
    encrypt: bool = False,
    passphrase: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save an article to disk, optionally encrypting it.

    Args:
        path: Path to write the article JSON file.
        content: Editor.js content dict.
        encrypt: If True, encrypt before writing.
        passphrase: Encryption passphrase. If None, reads from environment.
            Required if encrypt=True.

    Returns:
        The data that was written (envelope if encrypted, content if not).

    Raises:
        ValueError: If encrypt=True but no passphrase is available.
    """
    if encrypt:
        key = passphrase or get_encryption_key()
        if not key:
            raise ValueError(
                f"Cannot encrypt: no {ENV_VAR} is configured. "
                f"Set {ENV_VAR} in your .env file or environment."
            )
        data = encrypt_content(content, key)
    else:
        data = content

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return data
