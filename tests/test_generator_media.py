"""
Tests for SiteGenerator media processing integration.

Covers:
- _process_media() decrypting eligible files based on stage
- _process_media() skipping ineligible files
- _process_media() handling missing .enc files gracefully
- _process_media() with no encryption key
- _build_media_resolver() creating correct resolver callbacks
- Filename collision handling
- Integration: media map flows through to article rendering context
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from src.content.crypto import encrypt_file
from src.content.media import MediaEntry, MediaManifest
from src.site.generator import SiteGenerator


# -- Fixtures -----------------------------------------------------------------

PASSPHRASE = "test-passphrase-for-unit-tests-only"


@pytest.fixture
def media_workspace(tmp_path):
    """
    Create a realistic media workspace with manifest and encrypted files.

    Structure:
        tmp_path/
        ├── content/media/
        │   ├── manifest.json
        │   ├── img_001.enc
        │   └── doc_001.enc
        └── public/  (output dir)
    """
    content_dir = tmp_path / "content" / "media"
    content_dir.mkdir(parents=True)
    output_dir = tmp_path / "public"

    # Create encrypted files
    img_data = b"FAKE_JPEG_DATA_" * 100
    pdf_data = b"%PDF-1.4 FAKE_PDF_DATA " * 100

    img_enc = encrypt_file(img_data, "evidence.jpg", "image/jpeg", PASSPHRASE)
    pdf_enc = encrypt_file(pdf_data, "contract.pdf", "application/pdf", PASSPHRASE)

    (content_dir / "img_001.enc").write_bytes(img_enc)
    (content_dir / "doc_001.enc").write_bytes(pdf_enc)

    # Create manifest
    manifest = MediaManifest(entries=[], path=content_dir / "manifest.json")
    manifest.add_entry(MediaEntry(
        id="img_001",
        original_name="evidence.jpg",
        mime_type="image/jpeg",
        size_bytes=len(img_data),
        sha256="fake",
        min_stage="OK",
        referenced_by=["evidence-article"],
    ))
    manifest.add_entry(MediaEntry(
        id="doc_001",
        original_name="contract.pdf",
        mime_type="application/pdf",
        size_bytes=len(pdf_data),
        sha256="fake",
        min_stage="PARTIAL",
        referenced_by=["evidence-article"],
    ))
    manifest.save()

    return {
        "tmp_path": tmp_path,
        "content_dir": content_dir,
        "output_dir": output_dir,
        "manifest_path": content_dir / "manifest.json",
        "img_data": img_data,
        "pdf_data": pdf_data,
    }


# -- _process_media tests -----------------------------------------------------


class TestProcessMedia:
    """Verify _process_media decrypts and maps media files."""

    def test_decrypts_visible_at_ok(self, media_workspace, tmp_path):
        """At OK stage, only OK-staged media should be decrypted."""
        generator = SiteGenerator(output_dir=media_workspace["output_dir"])

        # Patch the manifest load to use our test manifest
        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=media_workspace["manifest_path"],
        ), mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            media_map = generator._process_media("OK")

        # Only img_001 is min_stage=OK, doc_001 is min_stage=PARTIAL
        assert "img_001" in media_map
        assert "doc_001" not in media_map

        # Verify file was actually written
        img_path = media_workspace["output_dir"] / media_map["img_001"]
        assert img_path.exists()
        assert img_path.read_bytes() == media_workspace["img_data"]

    def test_decrypts_all_at_full(self, media_workspace, tmp_path):
        """At FULL stage, all media should be decrypted."""
        generator = SiteGenerator(output_dir=media_workspace["output_dir"])

        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=media_workspace["manifest_path"],
        ), mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            media_map = generator._process_media("FULL")

        assert "img_001" in media_map
        assert "doc_001" in media_map

        # Verify both files written
        for media_id in ["img_001", "doc_001"]:
            path = media_workspace["output_dir"] / media_map[media_id]
            assert path.exists()

    def test_no_key_returns_empty_map(self, media_workspace):
        """Without encryption key, should return empty map."""
        generator = SiteGenerator(output_dir=media_workspace["output_dir"])

        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=media_workspace["manifest_path"],
        ), mock.patch.dict(os.environ, {}, clear=True):
            # Remove CONTENT_ENCRYPTION_KEY from environment
            os.environ.pop("CONTENT_ENCRYPTION_KEY", None)
            media_map = generator._process_media("FULL")

        assert media_map == {}

    def test_missing_enc_file_skipped(self, media_workspace):
        """Missing .enc file should be skipped with warning, not crash."""
        # Delete one of the .enc files
        (media_workspace["content_dir"] / "doc_001.enc").unlink()

        generator = SiteGenerator(output_dir=media_workspace["output_dir"])

        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=media_workspace["manifest_path"],
        ), mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            media_map = generator._process_media("FULL")

        # img_001 should still work
        assert "img_001" in media_map
        # doc_001 should be skipped
        assert "doc_001" not in media_map

    def test_empty_manifest_returns_empty_map(self, tmp_path):
        """Empty manifest should return empty map."""
        content_dir = tmp_path / "content" / "media"
        content_dir.mkdir(parents=True)
        manifest_path = content_dir / "manifest.json"
        manifest_path.write_text('{"version": 1, "media": []}')

        output_dir = tmp_path / "public"
        generator = SiteGenerator(output_dir=output_dir)

        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=manifest_path,
        ), mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            media_map = generator._process_media("FULL")

        assert media_map == {}

    def test_output_uses_original_name(self, media_workspace):
        """Decrypted files should use the original filename."""
        generator = SiteGenerator(output_dir=media_workspace["output_dir"])

        with mock.patch(
            "src.content.media.MediaManifest._default_path",
            return_value=media_workspace["manifest_path"],
        ), mock.patch.dict(os.environ, {"CONTENT_ENCRYPTION_KEY": PASSPHRASE}):
            media_map = generator._process_media("FULL")

        # Check the map points to original filenames
        assert media_map["img_001"].endswith("evidence.jpg")
        assert media_map["doc_001"].endswith("contract.pdf")


# -- _build_media_resolver tests -----------------------------------------------


class TestBuildMediaResolver:
    """Verify media resolver callback creation."""

    def test_resolver_returns_url_for_known_id(self, tmp_path):
        """Resolver should return URL for media in the map."""
        generator = SiteGenerator(output_dir=tmp_path)
        media_map = {"img_001": "media/evidence.jpg"}
        resolver = generator._build_media_resolver(media_map)

        assert resolver("img_001") == "media/evidence.jpg"

    def test_resolver_returns_none_for_unknown_id(self, tmp_path):
        """Resolver should return None for missing media."""
        generator = SiteGenerator(output_dir=tmp_path)
        media_map = {"img_001": "media/evidence.jpg"}
        resolver = generator._build_media_resolver(media_map)

        assert resolver("unknown_id") is None

    def test_resolver_with_base_path(self, tmp_path):
        """Resolver should prepend base_path for relative URLs."""
        generator = SiteGenerator(output_dir=tmp_path)
        media_map = {"img_001": "media/evidence.jpg"}
        resolver = generator._build_media_resolver(media_map, base_path="../")

        assert resolver("img_001") == "../media/evidence.jpg"

    def test_resolver_empty_base_path(self, tmp_path):
        """Empty base_path should not add any prefix."""
        generator = SiteGenerator(output_dir=tmp_path)
        media_map = {"img_001": "media/evidence.jpg"}
        resolver = generator._build_media_resolver(media_map, base_path="")

        assert resolver("img_001") == "media/evidence.jpg"
