"""
Tests for admin archive API routes.

Tests the /api/archive endpoints (archive submit, archive check).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Archive (Submit) ─────────────────────────────────────────────────


class TestArchive:

    def test_archive_custom_url(self, client):
        with patch("src.adapters.internet_archive.archive_url_now") as mock:
            mock.return_value = {
                "success": True,
                "archive_url": "https://web.archive.org/web/20260209/https://example.com/",
                "original_url": "https://example.com/",
            }
            resp = client.post("/api/archive", json={
                "url": "https://example.com",
            })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "archive.org" in data["archive_url"]

    def test_archive_no_url_no_env(self, client, app):
        """No URL provided and no GITHUB_REPOSITORY → should try git remote."""
        mock_git = MagicMock(returncode=1, stdout="", stderr="")
        with patch.dict("os.environ", {}, clear=True), \
             patch("subprocess.run", return_value=mock_git):
            resp = client.post("/api/archive", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "No URL" in data["error"]

    def test_archive_from_env(self, client):
        with patch.dict("os.environ", {"ARCHIVE_URL": "https://my-site.com"}), \
             patch("src.adapters.internet_archive.archive_url_now") as mock:
            mock.return_value = {
                "success": True,
                "archive_url": "https://web.archive.org/...",
            }
            resp = client.post("/api/archive", json={})
        assert resp.status_code == 200

    def test_archive_from_github_repo(self, client):
        with patch.dict("os.environ", {
            "GITHUB_REPOSITORY": "user/myrepo",
            "ARCHIVE_URL": "",
        }, clear=False), \
             patch("src.adapters.internet_archive.archive_url_now") as mock:
            mock.return_value = {"success": True, "archive_url": "https://web.archive.org/..."}
            resp = client.post("/api/archive", json={})
        assert resp.status_code == 200
        # Verify it used the GitHub Pages URL pattern
        call_url = mock.call_args[0][0]
        assert "user.github.io/myrepo" in call_url

    def test_archive_all_pages(self, client, app):
        # Create public dir with some files
        public = app.config["PROJECT_ROOT"] / "public"
        public.mkdir()
        (public / "index.html").write_text("<html></html>")

        with patch.dict("os.environ", {"ARCHIVE_URL": "https://my-site.com"}), \
             patch("src.adapters.internet_archive.archive_url_now") as mock, \
             patch("src.site.generator.SiteGenerator.get_archivable_paths",
                   return_value=["", "about"]), \
             patch("time.sleep"):  # Skip rate-limit delay
            mock.return_value = {"success": True, "archive_url": "https://web.archive.org/..."}
            resp = client.post("/api/archive", json={"all_pages": True})
        data = resp.get_json()
        assert data["success"] is True
        assert data["total"] == 2
        assert data["archived"] == 2

    def test_archive_exception(self, client):
        with patch.dict("os.environ", {"ARCHIVE_URL": "https://my-site.com"}), \
             patch("src.adapters.internet_archive.archive_url_now",
                   side_effect=RuntimeError("Network error")):
            resp = client.post("/api/archive", json={})
        assert resp.status_code == 500
        assert "Network error" in resp.get_json()["error"]


# ── Archive Check ────────────────────────────────────────────────────


class TestArchiveCheck:

    def test_check_single_url(self, client):
        snapshot = {"timestamp": "20260101120000", "url": "https://example.com/"}
        with patch("src.adapters.internet_archive.InternetArchiveAdapter.check_availability",
                    return_value=snapshot):
            resp = client.post("/api/archive/check", json={
                "url": "https://example.com",
            })
        data = resp.get_json()
        assert data["archived"] is True
        assert data["snapshot"]["timestamp"] == "20260101120000"

    def test_check_single_not_archived(self, client):
        with patch("src.adapters.internet_archive.InternetArchiveAdapter.check_availability",
                    return_value=None):
            resp = client.post("/api/archive/check", json={
                "url": "https://brand-new-site.example.com",
            })
        data = resp.get_json()
        assert data["archived"] is False

    def test_check_no_url_400(self, client):
        resp = client.post("/api/archive/check", json={})
        assert resp.status_code == 400

    def test_check_all_pages(self, client, app):
        public = app.config["PROJECT_ROOT"] / "public"
        public.mkdir(exist_ok=True)

        with patch.dict("os.environ", {"ARCHIVE_URL": "https://my-site.com"}), \
             patch("src.site.generator.SiteGenerator.get_archivable_paths",
                   return_value=["", "about"]), \
             patch("src.adapters.internet_archive.InternetArchiveAdapter.check_availability") as mock:
            mock.side_effect = [
                {"timestamp": "20260101120000"},  # index
                None,  # about — not archived
            ]
            resp = client.post("/api/archive/check", json={"all_pages": True})
        data = resp.get_json()
        assert data["total"] == 2
        assert data["archived_count"] == 1

    def test_check_all_pages_no_url(self, client):
        with patch.dict("os.environ", {}, clear=True):
            resp = client.post("/api/archive/check", json={"all_pages": True})
        assert resp.status_code == 400

    def test_check_exception(self, client):
        with patch("src.adapters.internet_archive.InternetArchiveAdapter.check_availability",
                    side_effect=RuntimeError("API down")):
            resp = client.post("/api/archive/check", json={"url": "https://example.com"})
        data = resp.get_json()
        assert data["archived"] is False
        assert "API down" in data["error"]
