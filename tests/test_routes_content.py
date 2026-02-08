"""
Tests for admin content API routes.

Tests the /api/content/* endpoints using Flask test client.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def app(tmp_path):
    """Create a Flask test app with temp project root."""
    from src.admin.server import create_app

    app = create_app()
    app.config["PROJECT_ROOT"] = tmp_path
    app.config["TESTING"] = True

    # Create articles dir
    articles_dir = tmp_path / "content" / "articles"
    articles_dir.mkdir(parents=True)

    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_article():
    """A minimal Editor.js article."""
    return {
        "time": 1700000000000,
        "blocks": [
            {"type": "header", "data": {"text": "Test Article", "level": 1}},
            {"type": "paragraph", "data": {"text": "Hello world."}},
        ],
        "version": "2.28.0",
    }


@pytest.fixture
def articles_dir(app):
    return app.config["PROJECT_ROOT"] / "content" / "articles"


def _write_article(articles_dir, slug, data):
    """Helper to write a JSON article file."""
    path = articles_dir / f"{slug}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── List Articles ────────────────────────────────────────────────


class TestListArticles:

    def test_empty_dir(self, client):
        resp = client.get("/api/content/articles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["articles"] == []
        assert data["encryption_available"] is False

    def test_lists_plaintext_articles(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "about", sample_article)
        resp = client.get("/api/content/articles")
        data = resp.get_json()
        assert len(data["articles"]) == 1
        assert data["articles"][0]["slug"] == "about"
        assert data["articles"][0]["encrypted"] is False
        assert data["articles"][0]["title"] == "Test Article"

    def test_lists_encrypted_articles(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        env = {"CONTENT_ENCRYPTION_KEY": "test-key-for-listing"}
        with patch.dict(os.environ, env):
            envelope = encrypt_content(sample_article, "test-key-for-listing")
            _write_article(articles_dir, "secret", envelope)
            resp = client.get("/api/content/articles")
            data = resp.get_json()
            assert len(data["articles"]) == 1
            art = data["articles"][0]
            assert art["slug"] == "secret"
            assert art["encrypted"] is True
            assert art["title"] == "Test Article"  # key present → title extracted
            assert data["encryption_available"] is True

    def test_encryption_available_reflects_env(self, client, articles_dir):
        env = {"CONTENT_ENCRYPTION_KEY": "some-key"}
        with patch.dict(os.environ, env):
            resp = client.get("/api/content/articles")
            assert resp.get_json()["encryption_available"] is True


# ── Get Article ──────────────────────────────────────────────────


class TestGetArticle:

    def test_get_plaintext(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "about", sample_article)
        resp = client.get("/api/content/articles/about")
        data = resp.get_json()
        assert data["slug"] == "about"
        assert data["encrypted"] is False
        assert data["content"]["blocks"][0]["data"]["text"] == "Test Article"

    def test_get_nonexistent(self, client):
        resp = client.get("/api/content/articles/nope")
        assert resp.status_code == 404

    def test_get_encrypted_with_key(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        env = {"CONTENT_ENCRYPTION_KEY": "my-key"}
        with patch.dict(os.environ, env):
            envelope = encrypt_content(sample_article, "my-key")
            _write_article(articles_dir, "secret", envelope)
            resp = client.get("/api/content/articles/secret")
            data = resp.get_json()
            assert data["encrypted"] is True
            assert data["content"]["blocks"][0]["data"]["text"] == "Test Article"

    def test_get_encrypted_without_key(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        envelope = encrypt_content(sample_article, "my-key")
        _write_article(articles_dir, "secret", envelope)
        # No CONTENT_ENCRYPTION_KEY in env
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            resp = client.get("/api/content/articles/secret")
            data = resp.get_json()
            assert data["encrypted"] is True
            assert "error" in data
            assert "cannot decrypt" in data["error"].lower()


# ── Save Article ─────────────────────────────────────────────────


class TestSaveArticle:

    def test_save_plaintext(self, client, articles_dir, sample_article):
        resp = client.post(
            "/api/content/articles/new-post",
            json={"content": sample_article},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["encrypted"] is False

        # Verify file written
        path = articles_dir / "new-post.json"
        assert path.exists()
        written = json.loads(path.read_text())
        assert written["blocks"][0]["data"]["text"] == "Test Article"

    def test_save_encrypted(self, client, articles_dir, sample_article):
        env = {"CONTENT_ENCRYPTION_KEY": "save-test-key"}
        with patch.dict(os.environ, env):
            resp = client.post(
                "/api/content/articles/new-post",
                json={"content": sample_article, "encrypt": True},
            )
            data = resp.get_json()
            assert data["success"] is True
            assert data["encrypted"] is True

            # Verify file is encrypted
            path = articles_dir / "new-post.json"
            written = json.loads(path.read_text())
            assert written.get("encrypted") is True
            assert "ciphertext" in written

    def test_save_encrypted_no_key(self, client, sample_article):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            resp = client.post(
                "/api/content/articles/test",
                json={"content": sample_article, "encrypt": True},
            )
            assert resp.status_code == 400
            assert "not set" in resp.get_json()["error"].lower()

    def test_save_no_body(self, client):
        resp = client.post(
            "/api/content/articles/test",
            content_type="application/json",
            data="",
        )
        assert resp.status_code == 400

    def test_save_missing_content(self, client):
        resp = client.post(
            "/api/content/articles/test",
            json={"encrypt": False},
        )
        assert resp.status_code == 400


# ── Delete Article ───────────────────────────────────────────────


class TestDeleteArticle:

    def test_delete_existing(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "todelete", sample_article)
        resp = client.delete("/api/content/articles/todelete")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert not (articles_dir / "todelete.json").exists()

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/content/articles/nope")
        assert resp.status_code == 404


# ── Encrypt / Decrypt Article ────────────────────────────────────


class TestEncryptDecrypt:

    def test_encrypt_article(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "plain", sample_article)
        env = {"CONTENT_ENCRYPTION_KEY": "encrypt-test"}
        with patch.dict(os.environ, env):
            resp = client.post("/api/content/articles/plain/encrypt")
            data = resp.get_json()
            assert data["success"] is True
            assert data["encrypted"] is True

            # Verify file is now encrypted
            written = json.loads((articles_dir / "plain.json").read_text())
            assert written.get("encrypted") is True

    def test_encrypt_already_encrypted(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        env = {"CONTENT_ENCRYPTION_KEY": "test"}
        with patch.dict(os.environ, env):
            envelope = encrypt_content(sample_article, "test")
            _write_article(articles_dir, "enc", envelope)
            resp = client.post("/api/content/articles/enc/encrypt")
            assert resp.status_code == 400

    def test_encrypt_no_key(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "plain", sample_article)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            resp = client.post("/api/content/articles/plain/encrypt")
            assert resp.status_code == 400

    def test_decrypt_article(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        env = {"CONTENT_ENCRYPTION_KEY": "decrypt-test"}
        with patch.dict(os.environ, env):
            envelope = encrypt_content(sample_article, "decrypt-test")
            _write_article(articles_dir, "enc", envelope)
            resp = client.post("/api/content/articles/enc/decrypt")
            data = resp.get_json()
            assert data["success"] is True
            assert data["encrypted"] is False

            # Verify file is now plaintext
            written = json.loads((articles_dir / "enc.json").read_text())
            assert "blocks" in written
            assert written.get("encrypted") is not True

    def test_decrypt_already_plaintext(self, client, articles_dir, sample_article):
        _write_article(articles_dir, "plain", sample_article)
        env = {"CONTENT_ENCRYPTION_KEY": "test"}
        with patch.dict(os.environ, env):
            resp = client.post("/api/content/articles/plain/decrypt")
            assert resp.status_code == 400

    def test_decrypt_no_key(self, client, articles_dir, sample_article):
        from src.content.crypto import encrypt_content
        envelope = encrypt_content(sample_article, "key")
        _write_article(articles_dir, "enc", envelope)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            resp = client.post("/api/content/articles/enc/decrypt")
            assert resp.status_code == 400


# ── Encryption Status ────────────────────────────────────────────


class TestEncryptionStatus:

    def test_key_not_set(self, client):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            resp = client.get("/api/content/encryption-status")
            assert resp.get_json()["key_configured"] is False

    def test_key_set(self, client):
        env = {"CONTENT_ENCRYPTION_KEY": "test"}
        with patch.dict(os.environ, env):
            resp = client.get("/api/content/encryption-status")
            assert resp.get_json()["key_configured"] is True


# ── Key Generation ───────────────────────────────────────────────


class TestKeygen:

    def test_generates_key(self, client):
        resp = client.post("/api/content/keygen")
        data = resp.get_json()
        assert "key" in data
        assert len(data["key"]) > 20

    def test_keys_are_unique(self, client):
        key1 = client.post("/api/content/keygen").get_json()["key"]
        key2 = client.post("/api/content/keygen").get_json()["key"]
        assert key1 != key2
