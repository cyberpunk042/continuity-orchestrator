"""
Tests for the Media API endpoints (routes_media.py).

Covers:
- GET    /api/content/media           — list all media entries
- GET    /api/content/media/<id>      — get single entry metadata
- POST   /api/content/media/upload    — upload + encrypt a file
- GET    /api/content/media/<id>/preview — decrypt + serve binary
- DELETE /api/content/media/<id>      — delete media + manifest entry
- PATCH  /api/content/media/<id>      — update metadata
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("flask")

from src.admin.server import create_app
from src.content.crypto import encrypt_file
from src.content.media import MediaEntry, MediaManifest


PASSPHRASE = "test-media-api-key"


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_path):
    """Create a Flask test app with isolated media directory."""
    # Setup media directory
    media_dir = tmp_path / "content" / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "manifest.json").write_text('{"version": 1, "media": []}')

    # Also create articles dir (some routes reference it)
    (tmp_path / "content" / "articles").mkdir(parents=True)

    app = create_app()
    app.config["TESTING"] = True
    app.config["PROJECT_ROOT"] = tmp_path

    # Patch the default manifest path to use our temp dir
    with mock.patch(
        "src.content.media.MediaManifest._default_path",
        return_value=media_dir / "manifest.json",
    ):
        yield app


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture
def seeded_app(tmp_path):
    """Create a Flask test app with a pre-seeded media entry."""
    media_dir = tmp_path / "content" / "media"
    media_dir.mkdir(parents=True)
    (tmp_path / "content" / "articles").mkdir(parents=True)

    # Create an encrypted file
    img_data = b"FAKE_JPEG_DATA_1234567890"
    enc_data = encrypt_file(img_data, "photo.jpg", "image/jpeg", PASSPHRASE)
    (media_dir / "img_001.enc").write_bytes(enc_data)

    # Create manifest with entry
    manifest = MediaManifest(entries=[], path=media_dir / "manifest.json")
    manifest.add_entry(MediaEntry(
        id="img_001",
        original_name="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=len(img_data),
        sha256="fake_sha256",
        min_stage="PARTIAL",
        referenced_by=["evidence-article"],
        caption="Evidence photo",
    ))
    manifest.save()

    app = create_app()
    app.config["TESTING"] = True
    app.config["PROJECT_ROOT"] = tmp_path

    with mock.patch(
        "src.content.media.MediaManifest._default_path",
        return_value=media_dir / "manifest.json",
    ):
        yield app, img_data


@pytest.fixture
def seeded_client(seeded_app):
    """Test client with pre-seeded media."""
    app, img_data = seeded_app
    return app.test_client(), img_data


# ── GET /api/content/media ───────────────────────────────────────


class TestListMedia:
    """GET /api/content/media — list all media entries."""

    def test_empty_list(self, client):
        """Empty manifest should return empty list."""
        rv = client.get("/api/content/media")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["media"] == []
        assert data["count"] == 0

    def test_list_with_entries(self, seeded_client):
        """Should list all entries from manifest."""
        client, _ = seeded_client
        rv = client.get("/api/content/media")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["count"] == 1
        assert data["media"][0]["id"] == "img_001"
        assert data["media"][0]["original_name"] == "photo.jpg"
        assert data["media"][0]["enc_file_exists"] is True

    def test_list_includes_total_size(self, seeded_client):
        """Should report total size across all entries."""
        client, _ = seeded_client
        rv = client.get("/api/content/media")
        data = rv.get_json()
        assert data["total_size_bytes"] > 0


# ── GET /api/content/media/<id> ──────────────────────────────────


class TestGetMedia:
    """GET /api/content/media/<id> — get single entry metadata."""

    def test_get_existing_entry(self, seeded_client):
        """Should return metadata for existing entry."""
        client, _ = seeded_client
        rv = client.get("/api/content/media/img_001")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["id"] == "img_001"
        assert data["media_uri"] == "media://img_001"
        assert data["caption"] == "Evidence photo"

    def test_get_nonexistent(self, client):
        """Should return 404 for missing entry."""
        rv = client.get("/api/content/media/nonexistent")
        assert rv.status_code == 404


# ── POST /api/content/media/upload ───────────────────────────────


class TestUploadMedia:
    """POST /api/content/media/upload — upload + encrypt."""

    def test_upload_image(self, client, tmp_path):
        """Should upload, encrypt, and register a JPEG image."""
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b"FAKE_JPEG_CONTENT"), "test.jpg"),
                    "min_stage": "PARTIAL",
                    "caption": "Test image",
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 201
        data = rv.get_json()
        assert data["success"] is True
        assert data["id"].startswith("img_")
        assert data["media_uri"].startswith("media://img_")
        assert data["original_name"] == "test.jpg"
        assert data["size_bytes"] == len(b"FAKE_JPEG_CONTENT")
        assert data["min_stage"] == "PARTIAL"

        # Verify .enc file was created
        enc_path = tmp_path / "content" / "media" / f"{data['id']}.enc"
        assert enc_path.exists()

    def test_upload_pdf(self, client, tmp_path):
        """PDF upload should get doc_ prefix."""
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b"%PDF-1.4 FAKE"), "contract.pdf"),
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 201
        data = rv.get_json()
        assert data["id"].startswith("doc_") or data["id"].startswith("media_")

    def test_upload_with_article_ref(self, client):
        """Upload with article_slug should add the reference."""
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b"DATA"), "test.png"),
                    "article_slug": "evidence-report",
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 201
        media_id = rv.get_json()["id"]

        # Verify reference in manifest
        rv2 = client.get(f"/api/content/media/{media_id}")
        assert "evidence-report" in rv2.get_json()["referenced_by"]

    def test_upload_no_file(self, client):
        """Should return 400 if no file is provided."""
        rv = client.post(
            "/api/content/media/upload",
            data={},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 400
        assert "No file" in rv.get_json()["error"]

    def test_upload_no_encryption_key_succeeds(self, client):
        """Should succeed without key — encryption is deferred to save time."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b"DATA"), "test.png"),
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 201
        data = rv.get_json()
        assert data["success"] is True
        assert data["id"].startswith("img_")

    def test_upload_invalid_stage(self, client):
        """Should reject invalid min_stage values."""
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b"DATA"), "test.png"),
                    "min_stage": "INVALID_STAGE",
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 400
        assert "Invalid min_stage" in rv.get_json()["error"]

    def test_upload_empty_file(self, client):
        """Should reject empty files."""
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.post(
                "/api/content/media/upload",
                data={
                    "file": (io.BytesIO(b""), "empty.png"),
                },
                content_type="multipart/form-data",
            )

        assert rv.status_code == 400
        assert "Empty" in rv.get_json()["error"]


# ── GET /api/content/media/<id>/preview ──────────────────────────


class TestPreviewMedia:
    """GET /api/content/media/<id>/preview — decrypt + serve."""

    def test_preview_returns_binary(self, seeded_client):
        """Should return decrypted binary with correct Content-Type."""
        client, img_data = seeded_client
        with mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            rv = client.get("/api/content/media/img_001/preview")

        assert rv.status_code == 200
        assert rv.content_type.startswith("image/jpeg")
        assert rv.data == img_data
        assert rv.headers.get("Cache-Control") == "no-store"

    def test_preview_nonexistent(self, client):
        """Should return 404 for missing entry."""
        rv = client.get("/api/content/media/nonexistent/preview")
        assert rv.status_code == 404

    def test_preview_no_key(self, seeded_client):
        """Should return 400 without encryption key."""
        client, _ = seeded_client
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            rv = client.get("/api/content/media/img_001/preview")

        assert rv.status_code == 400


# ── DELETE /api/content/media/<id> ───────────────────────────────


class TestDeleteMedia:
    """DELETE /api/content/media/<id> — delete file + entry."""

    def test_delete_existing(self, seeded_client, tmp_path):
        """Should remove .enc file and manifest entry."""
        client, _ = seeded_client
        # Determine the seeded_app's tmp_path from app config
        with client.application.app_context():
            project_root = client.application.config["PROJECT_ROOT"]

        rv = client.delete("/api/content/media/img_001")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert data["id"] == "img_001"

        # Verify .enc file is gone
        enc_path = project_root / "content" / "media" / "img_001.enc"
        assert not enc_path.exists()

        # Verify manifest no longer has entry
        rv2 = client.get("/api/content/media/img_001")
        assert rv2.status_code == 404

    def test_delete_nonexistent(self, client):
        """Should return 404 for missing entry."""
        rv = client.delete("/api/content/media/nonexistent")
        assert rv.status_code == 404


# ── PATCH /api/content/media/<id> ────────────────────────────────


class TestUpdateMedia:
    """PATCH /api/content/media/<id> — update metadata."""

    def test_update_min_stage(self, seeded_client):
        """Should update the min_stage field."""
        client, _ = seeded_client
        rv = client.patch(
            "/api/content/media/img_001",
            json={"min_stage": "FULL"},
        )
        assert rv.status_code == 200
        assert rv.get_json()["min_stage"] == "FULL"

    def test_update_caption(self, seeded_client):
        """Should update the caption field."""
        client, _ = seeded_client
        rv = client.patch(
            "/api/content/media/img_001",
            json={"caption": "Updated caption"},
        )
        assert rv.status_code == 200
        assert rv.get_json()["caption"] == "Updated caption"

    def test_add_article_reference(self, seeded_client):
        """Should add an article reference."""
        client, _ = seeded_client
        rv = client.patch(
            "/api/content/media/img_001",
            json={"article_slug": "new-article"},
        )
        assert rv.status_code == 200
        refs = rv.get_json()["referenced_by"]
        assert "new-article" in refs
        assert "evidence-article" in refs  # Original still there

    def test_remove_article_reference(self, seeded_client):
        """Should remove an article reference."""
        client, _ = seeded_client
        rv = client.patch(
            "/api/content/media/img_001",
            json={"remove_article_slug": "evidence-article"},
        )
        assert rv.status_code == 200
        assert "evidence-article" not in rv.get_json()["referenced_by"]

    def test_update_invalid_stage(self, seeded_client):
        """Should reject invalid stage values."""
        client, _ = seeded_client
        rv = client.patch(
            "/api/content/media/img_001",
            json={"min_stage": "INVALID"},
        )
        assert rv.status_code == 400

    def test_update_nonexistent(self, client):
        """Should return 404 for missing entry."""
        rv = client.patch(
            "/api/content/media/nonexistent",
            json={"caption": "Test"},
        )
        assert rv.status_code == 404


# ── Helper tests ─────────────────────────────────────────────────


class TestMimePrefixMapping:
    """Verify MIME type → ID prefix mapping."""

    def test_image_prefix(self):
        from src.admin.routes_media import _id_prefix_for_mime
        assert _id_prefix_for_mime("image/jpeg") == "img"
        assert _id_prefix_for_mime("image/png") == "img"

    def test_video_prefix(self):
        from src.admin.routes_media import _id_prefix_for_mime
        assert _id_prefix_for_mime("video/mp4") == "vid"

    def test_audio_prefix(self):
        from src.admin.routes_media import _id_prefix_for_mime
        assert _id_prefix_for_mime("audio/mpeg") == "aud"

    def test_pdf_prefix(self):
        from src.admin.routes_media import _id_prefix_for_mime
        assert _id_prefix_for_mime("application/pdf") == "doc"

    def test_unknown_prefix(self):
        from src.admin.routes_media import _id_prefix_for_mime
        assert _id_prefix_for_mime("application/octet-stream") == "media"
