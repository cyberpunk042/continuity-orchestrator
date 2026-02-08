"""
Tests for src.content.media — Media manifest management.

Covers:
- MediaEntry creation and serialization
- Stage-based visibility checks
- Manifest load/save round-trip
- Query methods (by ID, by stage, by article, orphans)
- Mutation methods (add, remove, update, references)
- ID generation (sequential, prefix-based)
- Edge cases (missing manifest, malformed entries, duplicate IDs)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.content.media import MediaEntry, MediaManifest, STAGE_ORDER


# -- Fixtures -----------------------------------------------------------------

PASSPHRASE = "test-passphrase"


def _make_entry(
    id: str = "img_001",
    original_name: str = "photo.jpg",
    mime_type: str = "image/jpeg",
    size_bytes: int = 1024,
    sha256: str = "abc123",
    min_stage: str = "FULL",
    referenced_by: list = None,
    caption: str = "",
) -> MediaEntry:
    """Helper to create a MediaEntry with sensible defaults."""
    return MediaEntry(
        id=id,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256,
        min_stage=min_stage,
        referenced_by=referenced_by or [],
        caption=caption,
    )


# -- MediaEntry ---------------------------------------------------------------


class TestMediaEntry:
    """Verify MediaEntry dataclass behavior."""

    def test_create_entry(self):
        """Basic entry creation should set all fields."""
        entry = _make_entry()
        assert entry.id == "img_001"
        assert entry.original_name == "photo.jpg"
        assert entry.mime_type == "image/jpeg"
        assert entry.size_bytes == 1024
        assert entry.encrypted is True

    def test_uploaded_at_auto_set(self):
        """uploaded_at should be auto-populated if not provided."""
        entry = _make_entry()
        assert entry.uploaded_at != ""
        assert "T" in entry.uploaded_at  # ISO format

    def test_enc_filename(self):
        """enc_filename should be id + .enc."""
        entry = _make_entry(id="doc_003")
        assert entry.enc_filename == "doc_003.enc"

    def test_to_dict(self):
        """Serialization should produce a JSON-compatible dict."""
        entry = _make_entry()
        d = entry.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "img_001"
        assert d["original_name"] == "photo.jpg"
        # Should be JSON-serializable
        json.dumps(d)

    def test_from_dict(self):
        """Deserialization should restore all fields."""
        data = {
            "id": "vid_001",
            "original_name": "deposition.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 50000,
            "sha256": "deadbeef",
            "min_stage": "PARTIAL",
            "referenced_by": ["evidence"],
            "uploaded_at": "2026-02-08T00:00:00Z",
            "caption": "Full deposition video",
        }
        entry = MediaEntry.from_dict(data)
        assert entry.id == "vid_001"
        assert entry.mime_type == "video/mp4"
        assert entry.min_stage == "PARTIAL"
        assert entry.referenced_by == ["evidence"]
        assert entry.caption == "Full deposition video"

    def test_from_dict_ignores_unknown_keys(self):
        """Unknown keys in the dict should be silently ignored."""
        data = {
            "id": "img_001",
            "original_name": "photo.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 1024,
            "sha256": "abc",
            "future_field": "ignored",
        }
        entry = MediaEntry.from_dict(data)
        assert entry.id == "img_001"
        assert not hasattr(entry, "future_field")

    def test_roundtrip_dict(self):
        """to_dict → from_dict should preserve all data."""
        original = _make_entry(
            id="doc_001",
            original_name="contract.pdf",
            mime_type="application/pdf",
            size_bytes=5000,
            sha256="xyz789",
            min_stage="PARTIAL",
            referenced_by=["article-1", "article-2"],
            caption="Contract v2",
        )
        restored = MediaEntry.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.original_name == original.original_name
        assert restored.mime_type == original.mime_type
        assert restored.size_bytes == original.size_bytes
        assert restored.sha256 == original.sha256
        assert restored.min_stage == original.min_stage
        assert restored.referenced_by == original.referenced_by
        assert restored.caption == original.caption


# -- Stage visibility ----------------------------------------------------------


class TestStageVisibility:
    """Verify stage-based visibility checks."""

    def test_ok_stage_sees_ok_media(self):
        """Media with min_stage=OK should be visible at OK."""
        entry = _make_entry(min_stage="OK")
        assert entry.is_visible_at("OK") is True

    def test_ok_stage_blocks_full_media(self):
        """Media with min_stage=FULL should NOT be visible at OK."""
        entry = _make_entry(min_stage="FULL")
        assert entry.is_visible_at("OK") is False

    def test_full_stage_sees_all(self):
        """At FULL stage, all media should be visible."""
        for stage in STAGE_ORDER:
            entry = _make_entry(min_stage=stage)
            assert entry.is_visible_at("FULL") is True

    def test_partial_stage_visibility(self):
        """PARTIAL stage should see OK, REMIND_*, PRE_RELEASE, and PARTIAL media."""
        for visible_stage in ["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL"]:
            entry = _make_entry(min_stage=visible_stage)
            assert entry.is_visible_at("PARTIAL") is True, f"{visible_stage} should be visible"

        entry = _make_entry(min_stage="FULL")
        assert entry.is_visible_at("PARTIAL") is False

    def test_unknown_stage_conservative(self):
        """Unknown current stage should be treated conservatively (order 0)."""
        entry = _make_entry(min_stage="PARTIAL")
        assert entry.is_visible_at("UNKNOWN") is False


# -- Manifest load/save -------------------------------------------------------


class TestManifestLoadSave:
    """Verify manifest persistence."""

    def test_load_empty_manifest(self, tmp_path: Path):
        """Loading an empty manifest should return zero entries."""
        path = tmp_path / "manifest.json"
        path.write_text('{"version": 1, "media": []}')

        manifest = MediaManifest.load(path)
        assert len(manifest.entries) == 0
        assert manifest.version == 1

    def test_load_with_entries(self, tmp_path: Path):
        """Loading a manifest with entries should parse them all."""
        path = tmp_path / "manifest.json"
        data = {
            "version": 1,
            "media": [
                {"id": "img_001", "original_name": "photo.jpg", "mime_type": "image/jpeg",
                 "size_bytes": 1024, "sha256": "abc"},
                {"id": "doc_001", "original_name": "file.pdf", "mime_type": "application/pdf",
                 "size_bytes": 2048, "sha256": "def"},
            ],
        }
        path.write_text(json.dumps(data))

        manifest = MediaManifest.load(path)
        assert len(manifest.entries) == 2
        assert manifest.get("img_001").original_name == "photo.jpg"
        assert manifest.get("doc_001").original_name == "file.pdf"

    def test_load_missing_file(self, tmp_path: Path):
        """Missing manifest file should return empty manifest."""
        path = tmp_path / "nonexistent.json"
        manifest = MediaManifest.load(path)
        assert len(manifest.entries) == 0

    def test_load_malformed_json(self, tmp_path: Path):
        """Malformed JSON should return empty manifest."""
        path = tmp_path / "manifest.json"
        path.write_text("not valid json {{{")
        manifest = MediaManifest.load(path)
        assert len(manifest.entries) == 0

    def test_save_creates_file(self, tmp_path: Path):
        """Saving should create the JSON file."""
        path = tmp_path / "subdir" / "manifest.json"
        manifest = MediaManifest(entries=[], path=path)
        manifest.add_entry(_make_entry(id="img_001"))
        manifest.save()

        assert path.exists()
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert len(data["media"]) == 1
        assert data["media"][0]["id"] == "img_001"

    def test_roundtrip_save_load(self, tmp_path: Path):
        """Save then load should preserve all data."""
        path = tmp_path / "manifest.json"

        original = MediaManifest(entries=[], path=path)
        original.add_entry(_make_entry(id="img_001", min_stage="PARTIAL"))
        original.add_entry(_make_entry(id="doc_002", original_name="report.pdf",
                                        mime_type="application/pdf", min_stage="FULL"))
        original.save()

        loaded = MediaManifest.load(path)
        assert len(loaded.entries) == 2
        assert loaded.get("img_001").min_stage == "PARTIAL"
        assert loaded.get("doc_002").original_name == "report.pdf"

    def test_load_skips_malformed_entries(self, tmp_path: Path):
        """Malformed individual entries should be skipped, not crash."""
        path = tmp_path / "manifest.json"
        data = {
            "version": 1,
            "media": [
                {"id": "img_001", "original_name": "photo.jpg", "mime_type": "image/jpeg",
                 "size_bytes": 1024, "sha256": "abc"},
                {"bad": "entry"},  # Missing required fields
            ],
        }
        path.write_text(json.dumps(data))

        manifest = MediaManifest.load(path)
        # Should load the good entry, skip the bad one
        assert len(manifest.entries) == 1
        assert manifest.get("img_001") is not None


# -- Query methods -------------------------------------------------------------


class TestManifestQueries:
    """Verify manifest query methods."""

    def _manifest_with_entries(self, tmp_path: Path) -> MediaManifest:
        """Helper to create a manifest with several test entries."""
        manifest = MediaManifest(entries=[], path=tmp_path / "manifest.json")
        manifest.add_entry(_make_entry(id="img_001", min_stage="OK",
                                        referenced_by=["about"]))
        manifest.add_entry(_make_entry(id="img_002", min_stage="PARTIAL",
                                        referenced_by=["evidence"]))
        manifest.add_entry(_make_entry(id="doc_001", min_stage="FULL",
                                        referenced_by=["evidence"]))
        manifest.add_entry(_make_entry(id="vid_001", min_stage="FULL",
                                        referenced_by=[]))
        return manifest

    def test_get_by_id(self, tmp_path: Path):
        """get() should find by ID."""
        manifest = self._manifest_with_entries(tmp_path)
        assert manifest.get("img_001").id == "img_001"
        assert manifest.get("nonexistent") is None

    def test_get_visible_at_ok(self, tmp_path: Path):
        """At OK stage, only OK-staged media should be visible."""
        manifest = self._manifest_with_entries(tmp_path)
        visible = manifest.get_visible_entries("OK")
        assert len(visible) == 1
        assert visible[0].id == "img_001"

    def test_get_visible_at_full(self, tmp_path: Path):
        """At FULL stage, all media should be visible."""
        manifest = self._manifest_with_entries(tmp_path)
        visible = manifest.get_visible_entries("FULL")
        assert len(visible) == 4

    def test_get_entries_for_article(self, tmp_path: Path):
        """Should find all media referenced by a specific article."""
        manifest = self._manifest_with_entries(tmp_path)
        evidence_media = manifest.get_entries_for_article("evidence")
        assert len(evidence_media) == 2
        ids = {e.id for e in evidence_media}
        assert ids == {"img_002", "doc_001"}

    def test_get_orphaned_entries(self, tmp_path: Path):
        """Should find entries with no article references."""
        manifest = self._manifest_with_entries(tmp_path)
        orphans = manifest.get_orphaned_entries()
        assert len(orphans) == 1
        assert orphans[0].id == "vid_001"

    def test_total_size_bytes(self, tmp_path: Path):
        """total_size_bytes should sum all entry sizes."""
        manifest = self._manifest_with_entries(tmp_path)
        # All entries have size_bytes=1024 from _make_entry default
        assert manifest.total_size_bytes == 4 * 1024


# -- Mutations -----------------------------------------------------------------


class TestManifestMutations:
    """Verify manifest mutation methods."""

    def test_add_entry(self, tmp_path: Path):
        """Adding an entry should make it queryable."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="new_001"))
        assert manifest.get("new_001") is not None
        assert len(manifest.entries) == 1

    def test_add_duplicate_id_raises(self, tmp_path: Path):
        """Adding a duplicate ID should raise ValueError."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001"))
        with pytest.raises(ValueError, match="already exists"):
            manifest.add_entry(_make_entry(id="img_001"))

    def test_remove_entry(self, tmp_path: Path):
        """Removing an entry should make it no longer queryable."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001"))
        removed = manifest.remove_entry("img_001")
        assert removed.id == "img_001"
        assert manifest.get("img_001") is None
        assert len(manifest.entries) == 0

    def test_remove_nonexistent(self, tmp_path: Path):
        """Removing a nonexistent entry should return None."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        assert manifest.remove_entry("nonexistent") is None

    def test_update_entry(self, tmp_path: Path):
        """Updating fields should modify the entry in place."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001", min_stage="FULL"))
        updated = manifest.update_entry("img_001", min_stage="PARTIAL", caption="New caption")
        assert updated.min_stage == "PARTIAL"
        assert updated.caption == "New caption"
        assert manifest.get("img_001").min_stage == "PARTIAL"

    def test_update_nonexistent(self, tmp_path: Path):
        """Updating a nonexistent entry should return None."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        assert manifest.update_entry("nope", min_stage="OK") is None

    def test_add_reference(self, tmp_path: Path):
        """Adding a reference should link article to media."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001"))
        assert manifest.add_reference("img_001", "evidence") is True
        assert "evidence" in manifest.get("img_001").referenced_by

    def test_add_reference_idempotent(self, tmp_path: Path):
        """Adding the same reference twice should not duplicate."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001"))
        manifest.add_reference("img_001", "evidence")
        manifest.add_reference("img_001", "evidence")
        assert manifest.get("img_001").referenced_by.count("evidence") == 1

    def test_remove_reference(self, tmp_path: Path):
        """Removing a reference should unlink article from media."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        manifest.add_entry(_make_entry(id="img_001", referenced_by=["evidence"]))
        assert manifest.remove_reference("img_001", "evidence") is True
        assert "evidence" not in manifest.get("img_001").referenced_by


# -- ID generation -------------------------------------------------------------


class TestIdGeneration:
    """Verify date-based ID generation."""

    def test_first_id(self, tmp_path: Path):
        """First ID should follow format prefix_YYYYMMDD_hex4."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        new_id = manifest.next_id("img")
        assert new_id.startswith("img_")
        # Format: img_YYYYMMDD_XXXX
        parts = new_id.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 4  # hex4 suffix
        assert parts[1].isdigit()

    def test_sequential_ids_are_unique(self, tmp_path: Path):
        """Two generated IDs should be different (random suffix)."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        id1 = manifest.next_id("img")
        manifest.add_entry(_make_entry(id=id1))
        id2 = manifest.next_id("img")
        assert id1 != id2

    def test_collision_avoidance(self, tmp_path: Path):
        """Should not generate an ID that already exists in the manifest."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        id1 = manifest.next_id("img")
        manifest.add_entry(_make_entry(id=id1))
        # The next ID should be different (collision avoided)
        id2 = manifest.next_id("img")
        assert id2 != id1
        assert id2.startswith("img_")

    def test_different_prefixes(self, tmp_path: Path):
        """Different prefixes should produce IDs with those prefixes."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        img_id = manifest.next_id("img")
        doc_id = manifest.next_id("doc")
        vid_id = manifest.next_id("vid")
        assert img_id.startswith("img_")
        assert doc_id.startswith("doc_")
        assert vid_id.startswith("vid_")

    def test_default_prefix(self, tmp_path: Path):
        """Default prefix should be 'media'."""
        manifest = MediaManifest(entries=[], path=tmp_path / "m.json")
        new_id = manifest.next_id()
        assert new_id.startswith("media_")


# -- File paths ----------------------------------------------------------------


class TestFilePaths:
    """Verify file path helpers."""

    def test_enc_path(self, tmp_path: Path):
        """enc_path should return full path to .enc file."""
        manifest = MediaManifest(entries=[], path=tmp_path / "manifest.json")
        path = manifest.enc_path("img_001")
        assert path == tmp_path / "img_001.enc"

    def test_list_orphaned_files(self, tmp_path: Path):
        """Should find .enc files not in manifest."""
        manifest = MediaManifest(entries=[], path=tmp_path / "manifest.json")
        manifest.add_entry(_make_entry(id="img_001"))

        # Create files: one known, one orphaned
        (tmp_path / "img_001.enc").write_bytes(b"known")
        (tmp_path / "orphan_002.enc").write_bytes(b"orphan")

        orphans = manifest.list_orphaned_files()
        assert len(orphans) == 1
        assert orphans[0].name == "orphan_002.enc"
