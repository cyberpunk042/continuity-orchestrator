"""
Tests for src.content.crypto — AES-256-GCM content encryption.

Covers:
- Round-trip encrypt → decrypt
- Encrypted envelope detection
- Wrong passphrase rejection
- Tampered ciphertext rejection
- Key generation entropy
- File load/save helpers
- Edge cases (empty passphrase, missing fields, non-encrypted data)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from src.content.crypto import (
    ENV_VAR,
    decrypt_content,
    encrypt_content,
    generate_key,
    get_encryption_key,
    is_encrypted,
    load_article,
    save_article,
)


# -- Fixtures -----------------------------------------------------------------


SAMPLE_CONTENT = {
    "time": 1738774200000,
    "version": "2.28.0",
    "blocks": [
        {
            "id": "h1",
            "type": "header",
            "data": {"text": "Test Article", "level": 1},
        },
        {
            "id": "p1",
            "type": "paragraph",
            "data": {"text": "This is test content with <b>bold</b> and <i>italic</i>."},
        },
        {
            "id": "list1",
            "type": "list",
            "data": {
                "style": "unordered",
                "items": ["Item A", "Item B", "Item C"],
            },
        },
    ],
}

PASSPHRASE = "test-passphrase-for-unit-tests-only"
OTHER_PASSPHRASE = "completely-different-passphrase-value"


# -- Round-trip tests ---------------------------------------------------------


class TestEncryptDecryptRoundtrip:
    """Verify that encrypt → decrypt returns identical content."""

    def test_basic_roundtrip(self):
        """Encrypt then decrypt should return the original content exactly."""
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        result = decrypt_content(envelope, PASSPHRASE)
        assert result == SAMPLE_CONTENT

    def test_empty_blocks(self):
        """Content with no blocks should encrypt/decrypt successfully."""
        content = {"time": 0, "version": "2.28.0", "blocks": []}
        envelope = encrypt_content(content, PASSPHRASE)
        result = decrypt_content(envelope, PASSPHRASE)
        assert result == content

    def test_unicode_content(self):
        """Unicode characters in content should survive encryption."""
        content = {
            "blocks": [
                {
                    "type": "paragraph",
                    "data": {"text": "Café ☕ résumé 日本語 émojis 🔒🔑"},
                }
            ]
        }
        envelope = encrypt_content(content, PASSPHRASE)
        result = decrypt_content(envelope, PASSPHRASE)
        assert result == content

    def test_large_content(self):
        """Large content (many blocks) should encrypt/decrypt correctly."""
        content = {
            "blocks": [
                {"type": "paragraph", "data": {"text": f"Paragraph {i}" * 100}}
                for i in range(100)
            ]
        }
        envelope = encrypt_content(content, PASSPHRASE)
        result = decrypt_content(envelope, PASSPHRASE)
        assert result == content

    def test_nested_json(self):
        """Deeply nested JSON structures should survive encryption."""
        content = {
            "blocks": [
                {
                    "type": "table",
                    "data": {
                        "withHeadings": True,
                        "content": [
                            ["Date", "Event", "Details"],
                            ["2026-02-01", "Notice sent", {"nested": True}],
                        ],
                    },
                }
            ]
        }
        envelope = encrypt_content(content, PASSPHRASE)
        result = decrypt_content(envelope, PASSPHRASE)
        assert result == content


# -- Envelope detection -------------------------------------------------------


class TestIsEncrypted:
    """Verify encrypted envelope detection."""

    def test_encrypted_envelope(self):
        """Encrypted envelope should be detected."""
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        assert is_encrypted(envelope) is True

    def test_plaintext_article(self):
        """Normal Editor.js content should NOT be detected as encrypted."""
        assert is_encrypted(SAMPLE_CONTENT) is False

    def test_empty_dict(self):
        """Empty dict should NOT be detected as encrypted."""
        assert is_encrypted({}) is False

    def test_partial_envelope(self):
        """Dict with 'encrypted: true' but missing fields should NOT match."""
        assert is_encrypted({"encrypted": True}) is False

    def test_encrypted_false(self):
        """Dict with 'encrypted: false' should NOT match."""
        assert is_encrypted({"encrypted": False, "ciphertext": "x", "iv": "y"}) is False

    def test_non_dict(self):
        """Non-dict input should return False, not crash."""
        assert is_encrypted("not a dict") is False  # type: ignore[arg-type]
        assert is_encrypted(None) is False  # type: ignore[arg-type]
        assert is_encrypted([]) is False  # type: ignore[arg-type]

    def test_encrypted_string_value(self):
        """'encrypted' as a string 'true' should NOT match (must be boolean)."""
        assert is_encrypted({"encrypted": "true", "ciphertext": "x", "iv": "y"}) is False


# -- Security tests -----------------------------------------------------------


class TestSecurityProperties:
    """Verify cryptographic security properties."""

    def test_wrong_passphrase_fails(self):
        """Decryption with the wrong passphrase should raise InvalidTag."""
        from cryptography.exceptions import InvalidTag

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        with pytest.raises(InvalidTag):
            decrypt_content(envelope, OTHER_PASSPHRASE)

    def test_different_encryptions_produce_different_ciphertext(self):
        """Two encryptions of the same content should differ (random IV/salt)."""
        envelope1 = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        envelope2 = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        assert envelope1["ciphertext"] != envelope2["ciphertext"]
        assert envelope1["iv"] != envelope2["iv"]
        assert envelope1["salt"] != envelope2["salt"]

    def test_tampered_ciphertext_fails(self):
        """Modified ciphertext should fail authentication."""
        import base64

        from cryptography.exceptions import InvalidTag

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        # Tamper with ciphertext (flip a byte)
        ct_bytes = base64.b64decode(envelope["ciphertext"])
        tampered = bytes([ct_bytes[0] ^ 0xFF]) + ct_bytes[1:]
        envelope["ciphertext"] = base64.b64encode(tampered).decode("ascii")

        with pytest.raises(InvalidTag):
            decrypt_content(envelope, PASSPHRASE)

    def test_tampered_tag_fails(self):
        """Modified authentication tag should fail."""
        import base64

        from cryptography.exceptions import InvalidTag

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        # Tamper with tag
        tag_bytes = base64.b64decode(envelope["tag"])
        tampered = bytes([tag_bytes[0] ^ 0xFF]) + tag_bytes[1:]
        envelope["tag"] = base64.b64encode(tampered).decode("ascii")

        with pytest.raises(InvalidTag):
            decrypt_content(envelope, PASSPHRASE)

    def test_tampered_iv_fails(self):
        """Modified IV should fail decryption (wrong nonce = wrong plaintext + auth fail)."""
        import base64

        from cryptography.exceptions import InvalidTag

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        # Tamper with IV
        iv_bytes = base64.b64decode(envelope["iv"])
        tampered = bytes([iv_bytes[0] ^ 0xFF]) + iv_bytes[1:]
        envelope["iv"] = base64.b64encode(tampered).decode("ascii")

        with pytest.raises(InvalidTag):
            decrypt_content(envelope, PASSPHRASE)


# -- Key generation -----------------------------------------------------------


class TestKeyGeneration:
    """Verify key generation quality."""

    def test_generate_key_returns_string(self):
        """Generated key should be a non-empty string."""
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_generate_key_sufficient_length(self):
        """Generated key should be at least 32 characters (sufficient entropy)."""
        key = generate_key()
        assert len(key) >= 32

    def test_generate_key_unique(self):
        """Two generated keys should be different."""
        key1 = generate_key()
        key2 = generate_key()
        assert key1 != key2

    def test_generate_key_is_url_safe(self):
        """Generated key should contain only URL-safe characters."""
        key = generate_key()
        # URL-safe base64 uses: A-Z, a-z, 0-9, -, _
        import re

        assert re.match(r"^[A-Za-z0-9_-]+$", key), f"Key contains unsafe characters: {key}"


# -- Environment variable reading ---------------------------------------------


class TestGetEncryptionKey:
    """Verify reading the encryption key from environment."""

    def test_key_from_env(self):
        """Should read CONTENT_ENCRYPTION_KEY from environment."""
        with mock.patch.dict(os.environ, {ENV_VAR: "my-secret-key"}):
            assert get_encryption_key() == "my-secret-key"

    def test_key_not_set(self, tmp_path):
        """Should return None when env var is not set."""
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            assert get_encryption_key() is None

    def test_key_empty_string(self, tmp_path):
        """Empty string should return None (not an empty key)."""
        with mock.patch.dict(os.environ, {ENV_VAR: ""}), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            assert get_encryption_key() is None

    def test_key_whitespace_only(self, tmp_path):
        """Whitespace-only should return None."""
        with mock.patch.dict(os.environ, {ENV_VAR: "   "}), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            assert get_encryption_key() is None

    def test_key_is_trimmed(self):
        """Key should be stripped of leading/trailing whitespace."""
        with mock.patch.dict(os.environ, {ENV_VAR: "  my-key  "}):
            assert get_encryption_key() == "my-key"


# -- Input validation ---------------------------------------------------------


class TestInputValidation:
    """Verify proper validation of inputs."""

    def test_encrypt_empty_passphrase(self):
        """Encrypting with empty passphrase should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encrypt_content(SAMPLE_CONTENT, "")

    def test_encrypt_whitespace_passphrase(self):
        """Encrypting with whitespace-only passphrase should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encrypt_content(SAMPLE_CONTENT, "   ")

    def test_decrypt_empty_passphrase(self):
        """Decrypting with empty passphrase should raise ValueError."""
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        with pytest.raises(ValueError, match="empty"):
            decrypt_content(envelope, "")

    def test_decrypt_non_encrypted_data(self):
        """Decrypting non-encrypted data should raise ValueError."""
        with pytest.raises(ValueError, match="not an encrypted envelope"):
            decrypt_content(SAMPLE_CONTENT, PASSPHRASE)

    def test_decrypt_missing_fields(self):
        """Decrypting with missing envelope fields should raise ValueError."""
        incomplete = {"encrypted": True, "ciphertext": "abc", "iv": "def"}
        # Missing 'tag' and 'salt'
        with pytest.raises(ValueError, match="missing fields"):
            decrypt_content(incomplete, PASSPHRASE)

    def test_decrypt_invalid_base64(self):
        """Invalid base64 in envelope should raise ValueError."""
        bad_envelope = {
            "encrypted": True,
            "ciphertext": "!!!not-base64!!!",
            "iv": "also-bad",
            "tag": "very-bad",
            "salt": "super-bad",
        }
        with pytest.raises(ValueError, match="decode"):
            decrypt_content(bad_envelope, PASSPHRASE)


# -- Envelope structure -------------------------------------------------------


class TestEnvelopeStructure:
    """Verify the encrypted envelope has the correct format."""

    def test_envelope_has_required_fields(self):
        """Encrypted envelope should contain all required fields."""
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        assert envelope["encrypted"] is True
        assert envelope["version"] == 1
        assert envelope["algorithm"] == "aes-256-gcm"
        assert envelope["kdf"] == "pbkdf2-sha256"
        assert envelope["kdf_iterations"] == 100_000
        assert "salt" in envelope
        assert "iv" in envelope
        assert "tag" in envelope
        assert "ciphertext" in envelope

    def test_envelope_is_json_serializable(self):
        """Envelope should serialize to valid JSON."""
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        json_str = json.dumps(envelope)
        parsed = json.loads(json_str)
        assert parsed == envelope

    def test_envelope_fields_are_base64(self):
        """Binary fields should be valid base64 strings."""
        import base64

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)

        for field in ("salt", "iv", "tag", "ciphertext"):
            value = envelope[field]
            assert isinstance(value, str)
            # Should decode without error
            decoded = base64.b64decode(value)
            assert len(decoded) > 0

    def test_salt_length(self):
        """Salt should be 16 bytes."""
        import base64

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        salt = base64.b64decode(envelope["salt"])
        assert len(salt) == 16

    def test_iv_length(self):
        """IV should be 12 bytes (GCM standard)."""
        import base64

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        iv = base64.b64decode(envelope["iv"])
        assert len(iv) == 12

    def test_tag_length(self):
        """Tag should be 16 bytes (128-bit GCM tag)."""
        import base64

        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        tag = base64.b64decode(envelope["tag"])
        assert len(tag) == 16


# -- File helpers --------------------------------------------------------------


class TestLoadArticle:
    """Verify load_article transparently handles encryption."""

    def test_load_plaintext(self, tmp_path: Path):
        """Loading a plaintext article should work without a key."""
        path = tmp_path / "test.json"
        path.write_text(json.dumps(SAMPLE_CONTENT))

        result = load_article(path)
        assert result == SAMPLE_CONTENT

    def test_load_encrypted_with_passphrase(self, tmp_path: Path):
        """Loading an encrypted article with passphrase should decrypt."""
        path = tmp_path / "test.json"
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        path.write_text(json.dumps(envelope))

        result = load_article(path, passphrase=PASSPHRASE)
        assert result == SAMPLE_CONTENT

    def test_load_encrypted_from_env(self, tmp_path: Path):
        """Loading an encrypted article should read key from environment."""
        path = tmp_path / "test.json"
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        path.write_text(json.dumps(envelope))

        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            result = load_article(path)
        assert result == SAMPLE_CONTENT

    def test_load_encrypted_no_key_raises(self, tmp_path: Path):
        """Loading encrypted article without key should raise ValueError."""
        path = tmp_path / "test.json"
        envelope = encrypt_content(SAMPLE_CONTENT, PASSPHRASE)
        path.write_text(json.dumps(envelope))

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            with pytest.raises(ValueError, match="CONTENT_ENCRYPTION_KEY"):
                load_article(path)

    def test_load_missing_file(self, tmp_path: Path):
        """Loading a non-existent file should raise FileNotFoundError."""
        path = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            load_article(path)


class TestSaveArticle:
    """Verify save_article with optional encryption."""

    def test_save_plaintext(self, tmp_path: Path):
        """Saving without encryption should write plain JSON."""
        path = tmp_path / "test.json"
        save_article(path, SAMPLE_CONTENT)

        data = json.loads(path.read_text())
        assert data == SAMPLE_CONTENT
        assert not is_encrypted(data)

    def test_save_encrypted(self, tmp_path: Path):
        """Saving with encryption should write an encrypted envelope."""
        path = tmp_path / "test.json"
        save_article(path, SAMPLE_CONTENT, encrypt=True, passphrase=PASSPHRASE)

        data = json.loads(path.read_text())
        assert is_encrypted(data)

        # Should decrypt back to original
        result = decrypt_content(data, PASSPHRASE)
        assert result == SAMPLE_CONTENT

    def test_save_encrypted_from_env(self, tmp_path: Path):
        """Saving encrypted should read key from environment."""
        path = tmp_path / "test.json"
        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            save_article(path, SAMPLE_CONTENT, encrypt=True)

        data = json.loads(path.read_text())
        assert is_encrypted(data)

    def test_save_encrypted_no_key_raises(self, tmp_path: Path):
        """Saving encrypted without key should raise ValueError."""
        path = tmp_path / "test.json"
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            with pytest.raises(ValueError, match="CONTENT_ENCRYPTION_KEY"):
                save_article(path, SAMPLE_CONTENT, encrypt=True)

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        """Saving should create parent directories if needed."""
        path = tmp_path / "deep" / "nested" / "test.json"
        save_article(path, SAMPLE_CONTENT)
        assert path.exists()

    def test_save_produces_readable_json(self, tmp_path: Path):
        """Saved file should be nicely formatted JSON (indented)."""
        path = tmp_path / "test.json"
        save_article(path, SAMPLE_CONTENT)

        text = path.read_text()
        assert "\n" in text  # Indented, not single-line
        assert text.endswith("\n")  # Trailing newline
