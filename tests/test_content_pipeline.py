"""
Tests for content encryption pipeline integration.

Verifies that the site generator and ContentManager transparently
handle encrypted articles alongside plaintext ones.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from src.content.crypto import (
    ENV_VAR,
    encrypt_content,
    is_encrypted,
)
from src.site.editorjs import ContentManager, EditorJSRenderer


# -- Test Data ----------------------------------------------------------------

PASSPHRASE = "pipeline-test-passphrase"

PLAINTEXT_ARTICLE = {
    "time": 1738774200000,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "About Page", "level": 1}},
        {"type": "paragraph", "data": {"text": "This is the about page."}},
    ],
}

ENCRYPTED_ARTICLE_CONTENT = {
    "time": 1738774200000,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "Secret Disclosure", "level": 1}},
        {"type": "paragraph", "data": {"text": "Confidential content here."}},
    ],
}


# -- Helpers ------------------------------------------------------------------


def _setup_content_dir(tmp_path: Path) -> Path:
    """Create a content/articles directory with both plaintext and encrypted articles."""
    articles_dir = tmp_path / "articles"
    articles_dir.mkdir(parents=True)

    # Plaintext article
    plaintext_path = articles_dir / "about.json"
    plaintext_path.write_text(json.dumps(PLAINTEXT_ARTICLE, indent=2))

    # Encrypted article
    envelope = encrypt_content(ENCRYPTED_ARTICLE_CONTENT, PASSPHRASE)
    encrypted_path = articles_dir / "disclosure.json"
    encrypted_path.write_text(json.dumps(envelope, indent=2))

    return articles_dir


# -- ContentManager.list_articles tests ----------------------------------------


class TestListArticles:
    """Verify list_articles detects encrypted articles."""

    def test_lists_both_plaintext_and_encrypted(self, tmp_path: Path):
        """Should list both article types with correct encrypted flag."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            articles = manager.list_articles()

        slugs = {a["slug"] for a in articles}
        assert "about" in slugs
        assert "disclosure" in slugs

        about = next(a for a in articles if a["slug"] == "about")
        disclosure = next(a for a in articles if a["slug"] == "disclosure")

        assert about["encrypted"] is False
        assert disclosure["encrypted"] is True

    def test_plaintext_title_extracted(self, tmp_path: Path):
        """Plaintext article title should come from first header block."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {}, clear=True):
            articles = manager.list_articles()

        about = next(a for a in articles if a["slug"] == "about")
        assert about["title"] == "About Page"

    def test_encrypted_title_with_key(self, tmp_path: Path):
        """Encrypted article title should be extracted when key is available."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            articles = manager.list_articles()

        disclosure = next(a for a in articles if a["slug"] == "disclosure")
        assert disclosure["title"] == "Secret Disclosure"

    def test_encrypted_title_without_key(self, tmp_path: Path):
        """Encrypted article should fall back to slug-based title without key."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {}, clear=True):
            articles = manager.list_articles()

        disclosure = next(a for a in articles if a["slug"] == "disclosure")
        # Slug-based title: "disclosure" → "Disclosure"
        assert disclosure["title"] == "Disclosure"
        assert disclosure["encrypted"] is True

    def test_encrypted_metadata_without_key(self, tmp_path: Path):
        """Encrypted article time/version should be None without key."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {}, clear=True):
            articles = manager.list_articles()

        disclosure = next(a for a in articles if a["slug"] == "disclosure")
        assert disclosure["time"] is None
        assert disclosure["version"] is None

    def test_plaintext_metadata_always_available(self, tmp_path: Path):
        """Plaintext article time/version should always be available."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        articles = manager.list_articles()

        about = next(a for a in articles if a["slug"] == "about")
        assert about["time"] == 1738774200000
        assert about["version"] == "2.28.0"

    def test_empty_directory(self, tmp_path: Path):
        """Empty articles directory should return empty list."""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir(parents=True)
        manager = ContentManager(content_dir=articles_dir)

        assert manager.list_articles() == []

    def test_nonexistent_directory(self, tmp_path: Path):
        """Non-existent directory should return empty list."""
        manager = ContentManager(content_dir=tmp_path / "nonexistent")
        assert manager.list_articles() == []


# -- ContentManager.get_article tests -----------------------------------------


class TestGetArticle:
    """Verify get_article transparently decrypts."""

    def test_get_plaintext_article(self, tmp_path: Path):
        """Getting a plaintext article should work without a key."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        article = manager.get_article("about")

        assert article is not None
        assert article["slug"] == "about"
        assert article["title"] == "About Page"
        assert article["encrypted"] is False
        assert "<p>This is the about page.</p>" in article["html"]
        assert article["raw"] == PLAINTEXT_ARTICLE

    def test_get_encrypted_article_with_key(self, tmp_path: Path):
        """Getting an encrypted article with key should return decrypted content."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            article = manager.get_article("disclosure")

        assert article is not None
        assert article["slug"] == "disclosure"
        assert article["title"] == "Secret Disclosure"
        assert article["encrypted"] is True
        assert "<p>Confidential content here.</p>" in article["html"]
        assert article["raw"] == ENCRYPTED_ARTICLE_CONTENT

    def test_get_encrypted_article_no_key_raises(self, tmp_path: Path):
        """Getting an encrypted article without a key should raise ValueError."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("src.content.crypto._env_file_path", return_value=tmp_path / ".env"):
            with pytest.raises(ValueError, match="CONTENT_ENCRYPTION_KEY"):
                manager.get_article("disclosure")

    def test_get_nonexistent_article(self, tmp_path: Path):
        """Getting a non-existent article should return None."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        assert manager.get_article("nonexistent") is None

    def test_render_article_plaintext(self, tmp_path: Path):
        """render_article should work for plaintext articles."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        html = manager.render_article("about")

        assert html is not None
        assert "<h1>About Page</h1>" in html
        assert "<p>This is the about page.</p>" in html

    def test_render_article_encrypted(self, tmp_path: Path):
        """render_article should decrypt and render encrypted articles."""
        articles_dir = _setup_content_dir(tmp_path)
        manager = ContentManager(content_dir=articles_dir)

        with mock.patch.dict(os.environ, {ENV_VAR: PASSPHRASE}):
            html = manager.render_article("disclosure")

        assert html is not None
        assert "<h1>Secret Disclosure</h1>" in html


# -- EditorJSRenderer (unchanged behavior) ------------------------------------


class TestRendererUnchanged:
    """Verify the renderer still works with direct content dicts."""

    def test_render_plaintext_dict(self):
        """Renderer should still accept a plain content dict."""
        renderer = EditorJSRenderer()
        html = renderer.render(PLAINTEXT_ARTICLE)

        assert "<h1>About Page</h1>" in html
        assert "<p>This is the about page.</p>" in html

    def test_render_file_still_works(self, tmp_path: Path):
        """render_file should still work for plaintext files."""
        path = tmp_path / "test.json"
        path.write_text(json.dumps(PLAINTEXT_ARTICLE))

        renderer = EditorJSRenderer()
        html = renderer.render_file(path)

        assert "<h1>About Page</h1>" in html
