"""
Tests for binary file encryption in src.content.crypto.

Covers:
- Round-trip encrypt → decrypt for binary files
- Encrypted file envelope detection (is_encrypted_file)
- Metadata reading without decryption (read_file_metadata)
- Wrong passphrase rejection
- Tampered envelope rejection
- SHA-256 integrity verification
- Edge cases (empty file, missing filename, huge metadata)
- Various file types (images, PDFs, text files)
"""

from __future__ import annotations

import hashlib
import os
import struct

import pytest

from src.content.crypto import (
    FILE_MAGIC,
    SHA256_BYTES,
    SALT_BYTES,
    IV_BYTES,
    TAG_BYTES,
    decrypt_file,
    encrypt_file,
    is_encrypted_file,
    read_file_metadata,
)


# -- Fixtures -----------------------------------------------------------------

PASSPHRASE = "test-passphrase-for-unit-tests-only"
OTHER_PASSPHRASE = "completely-different-passphrase-value"

# Small synthetic "image" (just random bytes, not a real JPEG)
SAMPLE_IMAGE_BYTES = os.urandom(1024)
SAMPLE_IMAGE_NAME = "evidence-photo.jpg"
SAMPLE_IMAGE_MIME = "image/jpeg"

# Simulated PDF header + random content
SAMPLE_PDF_BYTES = b"%PDF-1.4 " + os.urandom(2048)
SAMPLE_PDF_NAME = "contract.pdf"
SAMPLE_PDF_MIME = "application/pdf"

# Small text file
SAMPLE_TEXT_BYTES = "This is a plain text document.\nWith multiple lines.\n".encode("utf-8")
SAMPLE_TEXT_NAME = "notes.txt"
SAMPLE_TEXT_MIME = "text/plain"


# -- Round-trip tests ---------------------------------------------------------


class TestFileEncryptDecryptRoundtrip:
    """Verify that encrypt_file → decrypt_file returns identical content."""

    def test_basic_roundtrip(self):
        """Encrypt then decrypt should return the original bytes exactly."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["plaintext"] == SAMPLE_IMAGE_BYTES
        assert result["filename"] == SAMPLE_IMAGE_NAME
        assert result["mime_type"] == SAMPLE_IMAGE_MIME

    def test_pdf_roundtrip(self):
        """PDF-like content should encrypt/decrypt correctly."""
        encrypted = encrypt_file(SAMPLE_PDF_BYTES, SAMPLE_PDF_NAME, SAMPLE_PDF_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["plaintext"] == SAMPLE_PDF_BYTES
        assert result["filename"] == SAMPLE_PDF_NAME
        assert result["mime_type"] == SAMPLE_PDF_MIME

    def test_text_roundtrip(self):
        """Text files should encrypt/decrypt correctly."""
        encrypted = encrypt_file(SAMPLE_TEXT_BYTES, SAMPLE_TEXT_NAME, SAMPLE_TEXT_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["plaintext"] == SAMPLE_TEXT_BYTES
        assert result["filename"] == SAMPLE_TEXT_NAME
        assert result["mime_type"] == SAMPLE_TEXT_MIME

    def test_unicode_filename(self):
        """Unicode characters in filename should survive encryption."""
        filename = "résumé_证据_📸.jpg"
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, filename, SAMPLE_IMAGE_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["filename"] == filename

    def test_large_file(self):
        """A 1 MB file should encrypt/decrypt correctly."""
        large_data = os.urandom(1024 * 1024)
        encrypted = encrypt_file(large_data, "big.bin", "application/octet-stream", PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["plaintext"] == large_data
        assert len(result["plaintext"]) == 1024 * 1024

    def test_single_byte_file(self):
        """The smallest possible file (1 byte) should work."""
        data = b"\x42"
        encrypted = encrypt_file(data, "tiny.bin", "application/octet-stream", PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert result["plaintext"] == data


# -- SHA-256 integrity ---------------------------------------------------------


class TestSha256Integrity:
    """Verify the SHA-256 integrity hash is correct."""

    def test_sha256_matches(self):
        """Decrypted result should include correct SHA-256 hex digest."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        expected_hash = hashlib.sha256(SAMPLE_IMAGE_BYTES).hexdigest()
        assert result["sha256"] == expected_hash

    def test_tampered_hash_detected(self):
        """If the stored SHA-256 is tampered with, decryption should fail."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

        # Locate the SHA-256 hash in the envelope and tamper with it
        envelope = bytearray(encrypted)

        # Parse past the header to find the hash offset
        offset = len(FILE_MAGIC)
        filename_len = struct.unpack_from(">H", envelope, offset)[0]
        offset += 2 + filename_len
        mime_len = struct.unpack_from(">H", envelope, offset)[0]
        offset += 2 + mime_len

        # Flip a byte in the SHA-256 hash
        envelope[offset] ^= 0xFF

        with pytest.raises(ValueError, match="Integrity check failed"):
            decrypt_file(bytes(envelope), PASSPHRASE)


# -- Encrypted file detection --------------------------------------------------


class TestIsEncryptedFile:
    """Verify encrypted file envelope detection."""

    def test_encrypted_file_detected(self):
        """Encrypted file envelope should be detected."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        assert is_encrypted_file(encrypted) is True

    def test_random_bytes_not_detected(self):
        """Random bytes should NOT be detected as encrypted."""
        assert is_encrypted_file(os.urandom(256)) is False

    def test_empty_bytes(self):
        """Empty bytes should NOT be detected."""
        assert is_encrypted_file(b"") is False

    def test_too_short(self):
        """Bytes shorter than the minimum envelope should NOT be detected."""
        assert is_encrypted_file(b"COVAULT\x01") is False

    def test_wrong_magic(self):
        """Bytes with wrong magic should NOT be detected."""
        fake = b"NOTCOVT\x01" + b"\x00" * 100
        assert is_encrypted_file(fake) is False

    def test_non_bytes(self):
        """Non-bytes input should return False, not crash."""
        assert is_encrypted_file("not bytes") is False  # type: ignore[arg-type]
        assert is_encrypted_file(None) is False  # type: ignore[arg-type]
        assert is_encrypted_file(42) is False  # type: ignore[arg-type]

    def test_json_article_not_detected(self):
        """JSON article envelope bytes should NOT be detected as binary envelope."""
        import json
        from src.content.crypto import encrypt_content
        article = {"blocks": [{"type": "paragraph", "data": {"text": "Hello"}}]}
        envelope = encrypt_content(article, PASSPHRASE)
        json_bytes = json.dumps(envelope).encode("utf-8")
        assert is_encrypted_file(json_bytes) is False


# -- Metadata reading ----------------------------------------------------------


class TestReadFileMetadata:
    """Verify reading metadata without decryption."""

    def test_read_metadata(self):
        """Should extract filename, MIME type, and SHA-256 without passphrase."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        meta = read_file_metadata(encrypted)

        assert meta is not None
        assert meta["filename"] == SAMPLE_IMAGE_NAME
        assert meta["mime_type"] == SAMPLE_IMAGE_MIME
        assert meta["sha256"] == hashlib.sha256(SAMPLE_IMAGE_BYTES).hexdigest()
        assert meta["encrypted_size"] == len(encrypted)
        assert meta["approx_size"] > 0

    def test_approx_size_close_to_original(self):
        """Approximate size should be very close to original file size."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        meta = read_file_metadata(encrypted)

        # GCM adds no padding, so approx_size should equal original size
        assert meta["approx_size"] == len(SAMPLE_IMAGE_BYTES)

    def test_invalid_data_returns_none(self):
        """Invalid data should return None, not crash."""
        assert read_file_metadata(b"not an envelope") is None
        assert read_file_metadata(b"") is None


# -- Security tests -------------------------------------------------------------


class TestFileSecurityProperties:
    """Verify cryptographic security of binary file encryption."""

    def test_wrong_passphrase_fails(self):
        """Decryption with wrong passphrase should fail."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

        with pytest.raises(ValueError, match="Wrong passphrase"):
            decrypt_file(encrypted, OTHER_PASSPHRASE)

    def test_different_encryptions_differ(self):
        """Two encryptions of the same file should produce different envelopes."""
        enc1 = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        enc2 = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

        # Different random salt/IV means different ciphertext
        assert enc1 != enc2

    def test_tampered_ciphertext_fails(self):
        """Modified ciphertext should fail authentication."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        envelope = bytearray(encrypted)

        # Flip the last byte (in the ciphertext region)
        envelope[-1] ^= 0xFF

        with pytest.raises(ValueError):
            decrypt_file(bytes(envelope), PASSPHRASE)

    def test_truncated_envelope_fails(self):
        """Truncated envelope should fail."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

        # Cut off the last 100 bytes
        truncated = encrypted[:-100]

        with pytest.raises(ValueError):
            decrypt_file(truncated, PASSPHRASE)

    def test_no_size_overhead(self):
        """Binary format should have minimal size overhead (no base64 bloat)."""
        data = os.urandom(10000)
        encrypted = encrypt_file(data, "test.bin", "application/octet-stream", PASSPHRASE)

        # Overhead should be < 200 bytes (magic + metadata + crypto fields)
        # NOT 33% like base64 would add
        overhead = len(encrypted) - len(data)
        assert overhead < 200, f"Overhead too large: {overhead} bytes"


# -- Input validation -----------------------------------------------------------


class TestFileInputValidation:
    """Verify proper validation of inputs."""

    def test_encrypt_empty_passphrase(self):
        """Encrypting with empty passphrase should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, "")

    def test_encrypt_whitespace_passphrase(self):
        """Encrypting with whitespace-only passphrase should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, "   ")

    def test_encrypt_empty_file(self):
        """Encrypting empty bytes should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encrypt_file(b"", SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

    def test_encrypt_empty_filename(self):
        """Encrypting with empty filename should raise ValueError."""
        with pytest.raises(ValueError, match="Filename"):
            encrypt_file(SAMPLE_IMAGE_BYTES, "", SAMPLE_IMAGE_MIME, PASSPHRASE)

    def test_decrypt_empty_passphrase(self):
        """Decrypting with empty passphrase should raise ValueError."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        with pytest.raises(ValueError, match="empty"):
            decrypt_file(encrypted, "")

    def test_decrypt_non_envelope(self):
        """Decrypting non-envelope data should raise ValueError."""
        with pytest.raises(ValueError, match="not a valid"):
            decrypt_file(b"random data that is not an envelope at all and is long enough", PASSPHRASE)

    def test_default_mime_type(self):
        """Empty/None MIME type should default to application/octet-stream."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, "", PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)
        assert result["mime_type"] == "application/octet-stream"


# -- Envelope structure --------------------------------------------------------


class TestFileEnvelopeStructure:
    """Verify the binary envelope format."""

    def test_starts_with_magic(self):
        """Encrypted file should start with COVAULT magic bytes."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        assert encrypted[:8] == FILE_MAGIC

    def test_magic_is_correct_length(self):
        """FILE_MAGIC should be exactly 8 bytes."""
        assert len(FILE_MAGIC) == 8

    def test_contains_filename_in_header(self):
        """Original filename should be readable from the header."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)

        # The filename appears right after magic + 2-byte length
        offset = len(FILE_MAGIC)
        fn_len = struct.unpack_from(">H", encrypted, offset)[0]
        offset += 2
        filename = encrypted[offset:offset + fn_len].decode("utf-8")

        assert filename == SAMPLE_IMAGE_NAME

    def test_envelope_is_bytes(self):
        """encrypt_file should return bytes (not bytearray)."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        assert isinstance(encrypted, bytes)

    def test_result_is_dict(self):
        """decrypt_file should return a dict with the expected keys."""
        encrypted = encrypt_file(SAMPLE_IMAGE_BYTES, SAMPLE_IMAGE_NAME, SAMPLE_IMAGE_MIME, PASSPHRASE)
        result = decrypt_file(encrypted, PASSPHRASE)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"plaintext", "filename", "mime_type", "sha256"}
        assert isinstance(result["plaintext"], bytes)
        assert isinstance(result["filename"], str)
        assert isinstance(result["mime_type"], str)
        assert isinstance(result["sha256"], str)
        assert len(result["sha256"]) == 64  # hex digest length
