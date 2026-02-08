"""
Tests for CLI content commands — keygen, status, encrypt, decrypt.

Uses Click's CliRunner to test commands without spawning subprocesses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from src.content.crypto import ENV_VAR, encrypt_content, is_encrypted
from src.main import cli


# -- Fixtures -----------------------------------------------------------------

PASSPHRASE = "cli-test-passphrase"

SAMPLE_ARTICLE = {
    "time": 1738774200000,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "Test Title", "level": 1}},
        {"type": "paragraph", "data": {"text": "Test paragraph."}},
    ],
}

PUBLIC_ARTICLE = {
    "blocks": [
        {"type": "header", "data": {"text": "About", "level": 1}},
        {"type": "paragraph", "data": {"text": "Public info."}},
    ],
}


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal project structure with test articles."""
    # Content
    articles_dir = tmp_path / "content" / "articles"
    articles_dir.mkdir(parents=True)

    (articles_dir / "about.json").write_text(json.dumps(PUBLIC_ARTICLE, indent=2))
    (articles_dir / "disclosure.json").write_text(json.dumps(SAMPLE_ARTICLE, indent=2))

    # Manifest
    manifest = {
        "version": 1,
        "articles": [
            {"slug": "about", "title": "About", "visibility": {"min_stage": "OK"}},
            {"slug": "disclosure", "title": "Disclosure", "visibility": {"min_stage": "FULL"}},
        ],
    }
    (tmp_path / "content" / "manifest.yaml").write_text(
        "version: 1\narticles:\n"
        "  - slug: about\n    title: About\n    visibility:\n      min_stage: OK\n"
        "  - slug: disclosure\n    title: Disclosure\n    visibility:\n      min_stage: FULL\n"
    )

    # State (minimal for CLI context)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current.json").write_text("{}")

    return tmp_path


def _run(args: list, project_root: Path, env: dict | None = None) -> object:
    """Run a CLI command against a temporary project root."""
    runner = CliRunner()
    env_vars = {ENV_VAR: ""} if env is None else env
    with mock.patch("src.main.get_project_root", return_value=project_root):
        result = runner.invoke(cli, args, env=env_vars, catch_exceptions=False)
    return result


# -- content-keygen tests -----------------------------------------------------


class TestContentKeygen:
    """Verify content-keygen command."""

    def test_generates_key(self, tmp_path: Path):
        """Should output a key with instructions."""
        root = _setup_project(tmp_path)
        result = _run(["content-keygen"], root)

        assert result.exit_code == 0
        assert "CONTENT_ENCRYPTION_KEY=" in result.output
        assert "gh secret set" in result.output

    def test_key_is_different_each_time(self, tmp_path: Path):
        """Two invocations should produce different keys."""
        root = _setup_project(tmp_path)
        r1 = _run(["content-keygen"], root)
        r2 = _run(["content-keygen"], root)

        # Extract keys (line containing CONTENT_ENCRYPTION_KEY=)
        key1 = [l for l in r1.output.split("\n") if "CONTENT_ENCRYPTION_KEY=" in l][0]
        key2 = [l for l in r2.output.split("\n") if "CONTENT_ENCRYPTION_KEY=" in l][0]
        assert key1 != key2


# -- content-status tests -----------------------------------------------------


class TestContentStatus:
    """Verify content-status command."""

    def test_shows_all_articles(self, tmp_path: Path):
        """Should list all articles with their encryption status."""
        root = _setup_project(tmp_path)
        result = _run(["content-status"], root)

        assert result.exit_code == 0
        assert "about" in result.output
        assert "disclosure" in result.output
        assert "plaintext" in result.output

    def test_shows_encrypted_articles(self, tmp_path: Path):
        """Should show encrypted status for encrypted articles."""
        root = _setup_project(tmp_path)
        articles_dir = root / "content" / "articles"

        # Encrypt one article
        data = json.loads((articles_dir / "disclosure.json").read_text())
        envelope = encrypt_content(data, PASSPHRASE)
        (articles_dir / "disclosure.json").write_text(json.dumps(envelope))

        result = _run(["content-status"], root)

        assert result.exit_code == 0
        assert "encrypted" in result.output
        assert "1 encrypted" in result.output
        assert "1 plaintext" in result.output

    def test_shows_key_not_set(self, tmp_path: Path):
        """Should indicate when the encryption key is not configured."""
        root = _setup_project(tmp_path)
        result = _run(["content-status"], root, env={})

        assert result.exit_code == 0
        assert "Not set" in result.output


# -- content-encrypt tests ----------------------------------------------------


class TestContentEncrypt:
    """Verify content-encrypt command."""

    def test_encrypt_single_article(self, tmp_path: Path):
        """Should encrypt a specific article."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-encrypt", "--slug", "disclosure"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "encrypted" in result.output

        # Verify file is encrypted
        data = json.loads((root / "content" / "articles" / "disclosure.json").read_text())
        assert is_encrypted(data)

    def test_encrypt_all_articles(self, tmp_path: Path):
        """Should encrypt all plaintext articles."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-encrypt", "--all"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0

        # Both files should be encrypted
        for name in ("about.json", "disclosure.json"):
            data = json.loads((root / "content" / "articles" / name).read_text())
            assert is_encrypted(data), f"{name} should be encrypted"

    def test_encrypt_skip_public(self, tmp_path: Path):
        """--skip-public should not encrypt articles with min_stage OK."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-encrypt", "--all", "--skip-public"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "skipped" in result.output.lower() or "OK" in result.output

        # about.json (min_stage=OK) should remain plaintext
        about = json.loads((root / "content" / "articles" / "about.json").read_text())
        assert not is_encrypted(about)

        # disclosure.json (min_stage=FULL) should be encrypted
        disclosure = json.loads((root / "content" / "articles" / "disclosure.json").read_text())
        assert is_encrypted(disclosure)

    def test_encrypt_already_encrypted_skipped(self, tmp_path: Path):
        """Already-encrypted articles should be skipped."""
        root = _setup_project(tmp_path)

        # Pre-encrypt
        articles_dir = root / "content" / "articles"
        data = json.loads((articles_dir / "disclosure.json").read_text())
        envelope = encrypt_content(data, PASSPHRASE)
        (articles_dir / "disclosure.json").write_text(json.dumps(envelope))

        result = _run(
            ["content-encrypt", "--slug", "disclosure"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "already encrypted" in result.output

    def test_encrypt_no_key_fails(self, tmp_path: Path):
        """Should fail if encryption key is not set."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-encrypt", "--slug", "disclosure"],
            root,
            env={},
        )

        assert result.exit_code != 0

    def test_encrypt_requires_slug_or_all(self, tmp_path: Path):
        """Should fail if neither --slug nor --all is specified."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-encrypt"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code != 0


# -- content-decrypt tests ----------------------------------------------------


class TestContentDecrypt:
    """Verify content-decrypt command."""

    def test_decrypt_single_article(self, tmp_path: Path):
        """Should decrypt a specific article back to plaintext."""
        root = _setup_project(tmp_path)
        articles_dir = root / "content" / "articles"

        # Encrypt first
        data = json.loads((articles_dir / "disclosure.json").read_text())
        envelope = encrypt_content(data, PASSPHRASE)
        (articles_dir / "disclosure.json").write_text(json.dumps(envelope))

        # Now decrypt
        result = _run(
            ["content-decrypt", "--slug", "disclosure"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "decrypted" in result.output

        # File should be plaintext
        restored = json.loads((articles_dir / "disclosure.json").read_text())
        assert not is_encrypted(restored)
        assert restored["blocks"] == SAMPLE_ARTICLE["blocks"]

    def test_decrypt_dry_run(self, tmp_path: Path):
        """--dry-run should show content without modifying the file."""
        root = _setup_project(tmp_path)
        articles_dir = root / "content" / "articles"

        # Encrypt first
        data = json.loads((articles_dir / "disclosure.json").read_text())
        envelope = encrypt_content(data, PASSPHRASE)
        (articles_dir / "disclosure.json").write_text(json.dumps(envelope))

        # Dry-run decrypt
        result = _run(
            ["content-decrypt", "--slug", "disclosure", "--dry-run"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "Test Title" in result.output  # Shows decrypted title

        # File should STILL be encrypted
        data_after = json.loads((articles_dir / "disclosure.json").read_text())
        assert is_encrypted(data_after)

    def test_decrypt_all(self, tmp_path: Path):
        """--all should decrypt all encrypted articles."""
        root = _setup_project(tmp_path)
        articles_dir = root / "content" / "articles"

        # Encrypt both
        for name in ("about.json", "disclosure.json"):
            data = json.loads((articles_dir / name).read_text())
            envelope = encrypt_content(data, PASSPHRASE)
            (articles_dir / name).write_text(json.dumps(envelope))

        # Decrypt all
        result = _run(
            ["content-decrypt", "--all"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0

        for name in ("about.json", "disclosure.json"):
            data = json.loads((articles_dir / name).read_text())
            assert not is_encrypted(data)

    def test_decrypt_plaintext_skipped(self, tmp_path: Path):
        """Already-plaintext articles should be skipped."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-decrypt", "--slug", "about"],
            root,
            env={ENV_VAR: PASSPHRASE},
        )

        assert result.exit_code == 0
        assert "already plaintext" in result.output

    def test_decrypt_no_key_fails(self, tmp_path: Path):
        """Should fail if encryption key is not set."""
        root = _setup_project(tmp_path)
        result = _run(
            ["content-decrypt", "--slug", "disclosure"],
            root,
            env={},
        )

        assert result.exit_code != 0
