"""
Tests for the Editor.js image integration endpoints and renderer updates.

Tests cover:
- editor-upload endpoint (hybrid: inline <100KB, vault ≥100KB)
- editor-fetch-url endpoint (URL validation)
- EditorJS renderer handling of data.file.url format
- EditorJS renderer handling of data: URIs
"""

import base64
import io
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from src.admin.server import create_app
from src.site.editorjs import EditorJSRenderer


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def tmpdir():
    """Temporary directory for test artifacts."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def app(tmpdir):
    """Flask test app with isolated content directory."""
    content_dir = tmpdir / "content"
    (content_dir / "articles").mkdir(parents=True)
    (content_dir / "media").mkdir(parents=True)

    # Seed empty manifest
    manifest = content_dir / "media" / "manifest.json"
    manifest.write_text(json.dumps({"entries": []}))

    os.environ["CONTENT_ENCRYPTION_KEY"] = "test-editor-key-for-integration"
    os.environ["PROJECT_ROOT"] = str(tmpdir)

    app = create_app()
    app.config["TESTING"] = True
    app.config["PROJECT_ROOT"] = tmpdir

    yield app

    os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
    os.environ.pop("PROJECT_ROOT", None)


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


def _small_png(size_bytes=500):
    """Create a minimal valid-ish PNG of approximately the given size."""
    # 1x1 PNG header + padding to desired size
    header = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    if size_bytes > len(header):
        header += b"\x00" * (size_bytes - len(header))
    return header


def _large_png():
    """Create a PNG larger than 100KB (the inline threshold)."""
    return _small_png(150 * 1024)


# ═══════════════════════════════════════════════════════════════════
# Editor Upload Tests
# ═══════════════════════════════════════════════════════════════════


class TestEditorUploadInline:
    """Test that small images are returned as base64 data URIs."""

    def test_small_image_returns_data_uri(self, client):
        data = io.BytesIO(_small_png(500))
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "tiny.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["inline"] is True
        assert result["file"]["url"].startswith("data:image/png;base64,")
        assert result["size_bytes"] == 500

    def test_inline_data_uri_decodes_correctly(self, client):
        original = _small_png(800)
        data = io.BytesIO(original)
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "test.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        # Extract and decode the base64 part
        _, b64_part = result["file"]["url"].split(",", 1)
        decoded = base64.b64decode(b64_part)
        assert decoded == original

    def test_small_jpeg_uses_jpeg_mime(self, client):
        data = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 500)
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "photo.jpg")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["inline"] is True
        assert "image/jpeg" in result["file"]["url"]


class TestEditorUploadVault:
    """Test that large images are routed through the media vault."""

    def test_large_image_returns_media_uri(self, client):
        data = io.BytesIO(_large_png())
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "big_photo.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["inline"] is False
        assert result["file"]["url"].startswith("/api/content/media/img_")
        assert result["file"]["url"].endswith("/preview")
        assert result["media_id"].startswith("img_")
        assert result["media_uri"].startswith("media://img_")

    def test_vault_image_creates_enc_file(self, client, app):
        data = io.BytesIO(_large_png())
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "big.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        media_id = result["media_id"]
        enc_path = app.config["PROJECT_ROOT"] / "content" / "media" / f"{media_id}.enc"
        assert enc_path.exists()

    def test_vault_image_registered_in_manifest(self, client, app):
        data = io.BytesIO(_large_png())
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "big.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        manifest_path = app.config["PROJECT_ROOT"] / "content" / "media" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        ids = [e["id"] for e in manifest["media"]]
        assert result["media_id"] in ids

    def test_large_no_key_fails(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.admin.routes_media._get_encryption_key",
            lambda: None,
        )
        data = io.BytesIO(_large_png())
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "big.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        assert result["success"] == 0
        assert "CONTENT_ENCRYPTION_KEY" in result["error"]


class TestEditorUploadErrors:
    """Test error handling for the editor-upload endpoint."""

    def test_no_file(self, client):
        resp = client.post("/api/content/media/editor-upload")
        result = resp.get_json()
        assert result["success"] == 0

    def test_empty_file(self, client):
        data = io.BytesIO(b"")
        resp = client.post(
            "/api/content/media/editor-upload",
            data={"image": (data, "empty.png")},
            content_type="multipart/form-data",
        )
        result = resp.get_json()
        assert result["success"] == 0


# ═══════════════════════════════════════════════════════════════════
# Editor Fetch URL Tests
# ═══════════════════════════════════════════════════════════════════


class TestEditorFetchUrl:
    """Test the editor-fetch-url endpoint."""

    def test_https_url_passes_through(self, client):
        resp = client.post(
            "/api/content/media/editor-fetch-url",
            json={"url": "https://example.com/photo.jpg"},
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["file"]["url"] == "https://example.com/photo.jpg"

    def test_media_uri_passes_through(self, client):
        resp = client.post(
            "/api/content/media/editor-fetch-url",
            json={"url": "media://img_001"},
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["file"]["url"] == "media://img_001"

    def test_data_uri_passes_through(self, client):
        resp = client.post(
            "/api/content/media/editor-fetch-url",
            json={"url": "data:image/png;base64,AAAA"},
        )
        result = resp.get_json()
        assert result["success"] == 1
        assert result["file"]["url"] == "data:image/png;base64,AAAA"

    def test_invalid_scheme_rejected(self, client):
        resp = client.post(
            "/api/content/media/editor-fetch-url",
            json={"url": "ftp://example.com/file.jpg"},
        )
        result = resp.get_json()
        assert result["success"] == 0

    def test_empty_url_rejected(self, client):
        resp = client.post(
            "/api/content/media/editor-fetch-url",
            json={"url": ""},
        )
        result = resp.get_json()
        assert result["success"] == 0


# ═══════════════════════════════════════════════════════════════════
# Renderer Tests — file.url format + data: URIs
# ═══════════════════════════════════════════════════════════════════


class TestRendererFileUrlFormat:
    """Test that the renderer handles data.file.url (Editor.js image format)."""

    def test_file_url_format(self):
        renderer = EditorJSRenderer()
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": "https://example.com/photo.jpg"},
                        "caption": "A photo",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert "https://example.com/photo.jpg" in html
        assert "<figure>" in html
        assert "A photo" in html

    def test_legacy_url_format_still_works(self):
        renderer = EditorJSRenderer()
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "url": "https://example.com/old.jpg",
                        "caption": "Legacy",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert "https://example.com/old.jpg" in html

    def test_file_url_takes_precedence_over_url(self):
        renderer = EditorJSRenderer()
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": "https://new.com/img.jpg"},
                        "url": "https://old.com/img.jpg",
                        "caption": "",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert "https://new.com/img.jpg" in html
        assert "https://old.com/img.jpg" not in html


class TestRendererDataUri:
    """Test that the renderer handles base64 data: URIs."""

    def test_data_uri_rendered_as_src(self):
        renderer = EditorJSRenderer()
        data_uri = "data:image/png;base64,iVBORw0KGgo="
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": data_uri},
                        "caption": "",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert data_uri in html
        assert '<img src="data:image/png;base64,' in html

    def test_data_uri_not_escaped(self):
        """Data URIs contain characters that html.escape would break."""
        renderer = EditorJSRenderer()
        # A data URI with special chars that would get mangled by escaping
        data_uri = "data:image/png;base64,AA+BB/CC=="
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": data_uri},
                        "caption": "",
                    },
                }
            ]
        }
        html = renderer.render(data)
        # The + and / and = should NOT be escaped
        assert data_uri in html


class TestRendererMediaUriWithFileFormat:
    """Test media:// URIs in the file.url format."""

    def test_media_uri_in_file_url(self):
        def resolver(media_id):
            if media_id == "img_001":
                return "/media/photo.jpg"
            return None

        renderer = EditorJSRenderer(media_resolver=resolver)
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": "media://img_001"},
                        "caption": "Vault image",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert "/media/photo.jpg" in html
        assert "Vault image" in html

    def test_restricted_media_in_file_url(self):
        def resolver(media_id):
            return None  # All restricted

        renderer = EditorJSRenderer(media_resolver=resolver)
        data = {
            "blocks": [
                {
                    "type": "image",
                    "data": {
                        "file": {"url": "media://img_002"},
                        "caption": "",
                    },
                }
            ]
        }
        html = renderer.render(data)
        assert "restricted" in html.lower() or "placeholder" in html.lower()
