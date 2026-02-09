"""
Tests for admin backup API routes.

Tests the /api/backup/* endpoints (export, list, download, preview,
upload, restore, import) using Flask test client.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("flask")


def _make_backup_archive(backups_dir: Path, name: str = "backup_20260209T120000.tar.gz",
                         manifest: dict | None = None,
                         files: dict | None = None) -> Path:
    """Create a fake backup archive with a manifest.

    Args:
        backups_dir: Directory to create the archive in.
        name: Filename for the archive.
        manifest: Custom manifest dict; defaults to minimal valid manifest.
        files: Additional files to include as {name: content}.

    Returns:
        Path to the created archive.
    """
    if manifest is None:
        manifest = {
            "timestamp": "2026-02-09T12:00:00Z",
            "trigger": "test",
            "includes": {
                "state": True,
                "audit": True,
                "content_articles": False,
                "content_media": False,
                "policy": False,
            },
        }

    archive_path = backups_dir / name
    with tarfile.open(archive_path, "w:gz") as tar:
        # Add manifest
        manifest_bytes = json.dumps(manifest).encode()
        info = tarfile.TarInfo(name="backup_manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        # Add additional files
        if files:
            for fname, content in files.items():
                data = content.encode() if isinstance(content, str) else content
                info = tarfile.TarInfo(name=fname)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    return archive_path


# ── List ─────────────────────────────────────────────────────────────


class TestBackupList:

    def test_empty_list(self, client):
        resp = client.get("/api/backup/list")
        assert resp.status_code == 200
        assert resp.get_json()["backups"] == []

    def test_lists_existing_backups(self, client, backups_dir):
        _make_backup_archive(backups_dir, "backup_20260101T000000.tar.gz")
        _make_backup_archive(backups_dir, "backup_20260201T000000.tar.gz")

        resp = client.get("/api/backup/list")
        data = resp.get_json()
        assert len(data["backups"]) == 2
        # Should be sorted newest first
        assert data["backups"][0]["filename"] == "backup_20260201T000000.tar.gz"


# ── Download ─────────────────────────────────────────────────────────


class TestBackupDownload:

    def test_download_valid(self, client, backups_dir):
        _make_backup_archive(backups_dir)
        resp = client.get("/api/backup/download/backup_20260209T120000.tar.gz")
        assert resp.status_code == 200
        assert "gzip" in resp.content_type or resp.content_type == "application/gzip"

    def test_download_invalid_filename(self, client):
        # A filename that passes Flask routing but fails our safety check
        resp = client.get("/api/backup/download/evil_file.tar.gz")
        assert resp.status_code == 400

    def test_download_not_found(self, client):
        resp = client.get("/api/backup/download/backup_99990101T000000.tar.gz")
        assert resp.status_code == 404


# ── Preview ──────────────────────────────────────────────────────────


class TestBackupPreview:

    def test_preview_valid(self, client, backups_dir):
        manifest = {
            "timestamp": "2026-02-09T12:00:00Z",
            "trigger": "test",
            "includes": {"state": True},
        }
        _make_backup_archive(backups_dir, manifest=manifest,
                             files={"state/current.json": '{"test": true}'})

        resp = client.get("/api/backup/preview/backup_20260209T120000.tar.gz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["manifest"]["trigger"] == "test"
        assert len(data["files"]) >= 1

    def test_preview_invalid_filename(self, client):
        resp = client.get("/api/backup/preview/evil_file.tar.gz")
        assert resp.status_code == 400

    def test_preview_not_found(self, client):
        resp = client.get("/api/backup/preview/backup_99990101T000000.tar.gz")
        assert resp.status_code == 404


# ── Upload ───────────────────────────────────────────────────────────


class TestBackupUpload:

    def test_upload_no_file(self, client):
        resp = client.post("/api/backup/upload")
        assert resp.status_code == 400
        assert "No file" in resp.get_json()["error"]

    def test_upload_wrong_extension(self, client):
        data = {"file": (io.BytesIO(b"fake"), "backup.zip")}
        resp = client.post("/api/backup/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "tar.gz" in resp.get_json()["error"]

    def test_upload_invalid_archive(self, client, backups_dir):
        """Upload a .tar.gz that has no manifest -> should be rejected."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"hello"
            info = tarfile.TarInfo(name="random.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        data = {"file": (buf, "backup_20260209T999999.tar.gz")}
        resp = client.post("/api/backup/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "manifest" in resp.get_json()["error"].lower()

    def test_upload_valid(self, client, backups_dir):
        """Upload a valid archive."""
        # Create archive in memory
        buf = io.BytesIO()
        manifest = json.dumps({"timestamp": "now", "trigger": "upload_test", "includes": {}})
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            m_bytes = manifest.encode()
            info = tarfile.TarInfo(name="backup_manifest.json")
            info.size = len(m_bytes)
            tar.addfile(info, io.BytesIO(m_bytes))
        buf.seek(0)

        data = {"file": (buf, "backup_20260209T120000.tar.gz")}
        resp = client.post("/api/backup/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        rdata = resp.get_json()
        assert rdata["success"] is True
        assert rdata["manifest"]["trigger"] == "upload_test"

    def test_upload_unsafe_filename_sanitized(self, client, backups_dir):
        """Non-matching filenames should be sanitized."""
        buf = io.BytesIO()
        manifest = json.dumps({"timestamp": "now", "trigger": "t", "includes": {}})
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            m_bytes = manifest.encode()
            info = tarfile.TarInfo(name="backup_manifest.json")
            info.size = len(m_bytes)
            tar.addfile(info, io.BytesIO(m_bytes))
        buf.seek(0)

        data = {"file": (buf, "my_custom_name.tar.gz")}
        resp = client.post("/api/backup/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        # Should be renamed to backup_YYYYMMDDTHHMMSS.tar.gz pattern
        rdata = resp.get_json()
        assert rdata["filename"].startswith("backup_")


# ── Export ───────────────────────────────────────────────────────────


class TestBackupExport:

    def test_export_default(self, client, app):
        with patch("src.cli.backup.create_backup_archive") as mock:
            archive_path = app.config["PROJECT_ROOT"] / "backups" / "backup_20260209T120000.tar.gz"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            # Create a real file so stat() works
            archive_path.write_bytes(b"\x1f\x8b" + b"\x00" * 100)
            mock.return_value = (archive_path, {"trigger": "admin_export"})

            resp = client.post("/api/backup/export", json={})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "download_url" in data

    def test_export_with_options(self, client, app):
        with patch("src.cli.backup.create_backup_archive") as mock:
            archive_path = app.config["PROJECT_ROOT"] / "backups" / "backup_20260209T120001.tar.gz"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_bytes(b"\x1f\x8b" + b"\x00" * 50)
            mock.return_value = (archive_path, {"trigger": "admin_export"})

            resp = client.post("/api/backup/export", json={
                "include_articles": True,
                "include_media": True,
                "include_policy": True,
            })

        assert resp.status_code == 200
        _, kwargs = mock.call_args
        assert kwargs["include_articles"] is True
        assert kwargs["include_media"] is True
        assert kwargs["include_policy"] is True


# ── Restore ──────────────────────────────────────────────────────────


class TestBackupRestore:

    def test_restore_missing_filename(self, client):
        resp = client.post("/api/backup/restore", json={})
        assert resp.status_code == 400

    def test_restore_invalid_filename(self, client):
        resp = client.post("/api/backup/restore", json={"filename": "../evil.tar.gz"})
        assert resp.status_code == 400

    def test_restore_not_found(self, client):
        resp = client.post("/api/backup/restore", json={
            "filename": "backup_99990101T000000.tar.gz",
        })
        assert resp.status_code == 404

    def test_restore_valid(self, client, backups_dir):
        _make_backup_archive(backups_dir)

        with patch("src.cli.backup.restore_from_archive") as mock:
            mock.return_value = {"restored": ["state/current.json"], "skipped": []}
            resp = client.post("/api/backup/restore", json={
                "filename": "backup_20260209T120000.tar.gz",
            })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["restored"]) == 1


# ── Import ───────────────────────────────────────────────────────────


class TestBackupImport:

    def test_import_no_content(self, client, backups_dir):
        """Archive without content_articles or content_media should be rejected."""
        _make_backup_archive(backups_dir)  # default manifest has no content
        resp = client.post("/api/backup/import", json={
            "filename": "backup_20260209T120000.tar.gz",
        })
        assert resp.status_code == 400
        assert "no content" in resp.get_json()["error"].lower()

    def test_import_with_content(self, client, backups_dir):
        manifest = {
            "timestamp": "2026-02-09T12:00:00Z",
            "trigger": "test",
            "includes": {
                "content_articles": True,
                "content_media": False,
            },
        }
        _make_backup_archive(backups_dir, manifest=manifest)

        with patch("src.cli.backup.import_from_archive") as mock:
            mock.return_value = {"imported": ["articles/test.json"], "skipped": []}
            resp = client.post("/api/backup/import", json={
                "filename": "backup_20260209T120000.tar.gz",
            })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ── Filename Safety ──────────────────────────────────────────────────


class TestSafeFilename:

    def test_valid_filenames(self):
        from src.admin.routes_backup import _safe_filename
        assert _safe_filename("backup_20260209T120000.tar.gz") is True
        assert _safe_filename("backup_20251231T235959.tar.gz") is True

    def test_invalid_filenames(self):
        from src.admin.routes_backup import _safe_filename
        assert _safe_filename("../etc/passwd") is False
        assert _safe_filename("backup.tar.gz") is False
        assert _safe_filename("backup_abcdefghTijklmn.tar.gz") is False
        assert _safe_filename("") is False
        assert _safe_filename("backup_20260209T120000.zip") is False
