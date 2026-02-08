"""
Media Manifest — Registry of encrypted media files.

Manages the content/media/manifest.json file, which tracks all encrypted
media files, their metadata, and stage-based visibility rules.

## Usage

    from src.content.media import MediaManifest

    manifest = MediaManifest.load()

    # List all media
    for entry in manifest.entries:
        print(entry.id, entry.original_name, entry.min_stage)

    # Get visible media at a given stage
    visible = manifest.get_visible_entries("PARTIAL")

    # Add a new entry after upload
    manifest.add_entry(MediaEntry(
        id="img_001",
        original_name="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=845322,
        sha256="a1b2c3...",
        min_stage="PARTIAL",
    ))
    manifest.save()
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Stage order — must match src/site/manifest.py
STAGE_ORDER = {
    "OK": 0,
    "REMIND_1": 10,
    "REMIND_2": 20,
    "PRE_RELEASE": 30,
    "PARTIAL": 40,
    "FULL": 50,
}

MANIFEST_VERSION = 1


@dataclass
class MediaEntry:
    """A single media file entry in the manifest."""

    id: str
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    encrypted: bool = True
    min_stage: str = "FULL"
    referenced_by: List[str] = field(default_factory=list)
    uploaded_at: str = ""
    caption: str = ""

    def __post_init__(self):
        if not self.uploaded_at:
            self.uploaded_at = datetime.now(timezone.utc).isoformat()

    def is_visible_at(self, stage: str) -> bool:
        """Check if this media file is visible at the given stage."""
        current_order = STAGE_ORDER.get(stage, 0)
        min_order = STAGE_ORDER.get(self.min_stage, 50)
        return current_order >= min_order

    @property
    def enc_filename(self) -> str:
        """The encrypted filename on disk (e.g. 'img_001.enc')."""
        return f"{self.id}.enc"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaEntry":
        """Create from a JSON dict, ignoring unknown keys."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class MediaManifest:
    """
    Load, query, and update the media manifest.

    The manifest is a JSON file mapping media IDs to their metadata.
    """

    def __init__(
        self,
        entries: List[MediaEntry],
        version: int = MANIFEST_VERSION,
        path: Optional[Path] = None,
    ):
        self.entries = entries
        self.version = version
        self._path = path or self._default_path()

        # Index by ID for quick lookup
        self._by_id: Dict[str, MediaEntry] = {e.id: e for e in entries}

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "MediaManifest":
        """Load manifest from JSON file."""
        if path is None:
            path = cls._default_path()

        if not path.exists():
            logger.info(f"Media manifest not found at {path}, creating empty")
            return cls(entries=[], path=path)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls._from_dict(data, path)
        except Exception as e:
            logger.error(f"Failed to load media manifest: {e}")
            return cls(entries=[], path=path)

    @classmethod
    def _default_path(cls) -> Path:
        """Get default manifest path: content/media/manifest.json."""
        return Path(__file__).resolve().parents[2] / "content" / "media" / "manifest.json"

    @classmethod
    def _from_dict(cls, data: Dict[str, Any], path: Path) -> "MediaManifest":
        """Parse manifest from dictionary."""
        version = data.get("version", MANIFEST_VERSION)
        entries = []

        for entry_data in data.get("media", []):
            try:
                entries.append(MediaEntry.from_dict(entry_data))
            except Exception as e:
                entry_id = entry_data.get("id", "unknown")
                logger.warning(f"Skipping malformed media entry '{entry_id}': {e}")

        return cls(entries=entries, version=version, path=path)

    def save(self, path: Optional[Path] = None) -> None:
        """Write manifest back to disk."""
        target = path or self._path
        target.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self.version,
            "media": [e.to_dict() for e in self.entries],
        }

        target.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.debug(f"Saved media manifest: {len(self.entries)} entries → {target}")

    # ── Queries ──────────────────────────────────────────────────

    def get(self, media_id: str) -> Optional[MediaEntry]:
        """Get a media entry by ID."""
        return self._by_id.get(media_id)

    def get_visible_entries(self, stage: str) -> List[MediaEntry]:
        """Get all media entries visible at the given stage."""
        return [e for e in self.entries if e.is_visible_at(stage)]

    def get_entries_for_article(self, slug: str) -> List[MediaEntry]:
        """Get all media entries referenced by a specific article."""
        return [e for e in self.entries if slug in e.referenced_by]

    def get_orphaned_entries(self) -> List[MediaEntry]:
        """Get entries not referenced by any article."""
        return [e for e in self.entries if not e.referenced_by]

    @property
    def total_size_bytes(self) -> int:
        """Total size of all media files (original, not encrypted)."""
        return sum(e.size_bytes for e in self.entries)

    # ── Mutations ────────────────────────────────────────────────

    def add_entry(self, entry: MediaEntry) -> None:
        """Add a new media entry. Raises ValueError if ID already exists."""
        if entry.id in self._by_id:
            raise ValueError(f"Media ID '{entry.id}' already exists in manifest")
        self.entries.append(entry)
        self._by_id[entry.id] = entry

    def remove_entry(self, media_id: str) -> Optional[MediaEntry]:
        """Remove a media entry by ID. Returns the removed entry or None."""
        entry = self._by_id.pop(media_id, None)
        if entry:
            self.entries = [e for e in self.entries if e.id != media_id]
        return entry

    def update_entry(self, media_id: str, **kwargs) -> Optional[MediaEntry]:
        """
        Update fields on an existing entry.

        Only the provided keyword arguments are updated.
        Returns the updated entry or None if not found.
        """
        entry = self._by_id.get(media_id)
        if not entry:
            return None

        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
            else:
                logger.warning(f"Unknown media field: {key}")

        return entry

    def add_reference(self, media_id: str, article_slug: str) -> bool:
        """Add an article reference to a media entry. Returns success."""
        entry = self._by_id.get(media_id)
        if not entry:
            return False
        if article_slug not in entry.referenced_by:
            entry.referenced_by.append(article_slug)
        return True

    def remove_reference(self, media_id: str, article_slug: str) -> bool:
        """Remove an article reference from a media entry. Returns success."""
        entry = self._by_id.get(media_id)
        if not entry:
            return False
        if article_slug in entry.referenced_by:
            entry.referenced_by.remove(article_slug)
        return True

    def next_id(self, prefix: str = "media") -> str:
        """
        Generate the next sequential ID with the given prefix.

        Examples:
            next_id("img")  → "img_001" (if no img_* entries exist)
            next_id("img")  → "img_004" (if img_001, img_002, img_003 exist)
            next_id("doc")  → "doc_001"
        """
        existing_nums = []
        for entry in self.entries:
            if entry.id.startswith(f"{prefix}_"):
                try:
                    num = int(entry.id[len(prefix) + 1:])
                    existing_nums.append(num)
                except ValueError:
                    pass

        next_num = (max(existing_nums) + 1) if existing_nums else 1
        return f"{prefix}_{next_num:03d}"

    # ── Media directory ──────────────────────────────────────────

    @property
    def media_dir(self) -> Path:
        """Get the media directory path (parent of the manifest file)."""
        return self._path.parent

    def enc_path(self, media_id: str) -> Path:
        """Get the full path to an encrypted media file."""
        return self.media_dir / f"{media_id}.enc"

    def list_orphaned_files(self) -> List[Path]:
        """Find .enc files in the media dir that are NOT in the manifest."""
        known_ids = set(self._by_id.keys())
        orphaned = []

        for enc_file in self.media_dir.glob("*.enc"):
            file_id = enc_file.stem
            if file_id not in known_ids:
                orphaned.append(enc_file)

        return orphaned
