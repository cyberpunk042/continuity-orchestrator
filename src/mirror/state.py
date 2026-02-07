"""
Mirror State — Track sync status for each mirror.

State is stored in state/mirror_status.json (separate from main state
to avoid coupling with the core state schema).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Mirror roles
ROLE_MASTER = "MASTER"
ROLE_SLAVE = "SLAVE"
ROLE_TEMPORARY_MASTER = "TEMPORARY_MASTER"


@dataclass
class SyncStatus:
    """Status of a specific sync layer."""

    last_sync_iso: Optional[str] = None
    status: str = "unknown"  # ok, failed, unknown, stale
    last_error: Optional[str] = None
    detail: Optional[str] = None  # e.g. commit hash, count
    fingerprint: Optional[str] = None  # hash of synced values (for staleness detection)

    def mark_ok(self, detail: Optional[str] = None, fingerprint: Optional[str] = None):
        self.last_sync_iso = datetime.now(timezone.utc).isoformat()
        self.status = "ok"
        self.last_error = None
        self.detail = detail
        if fingerprint is not None:
            self.fingerprint = fingerprint

    def mark_failed(self, error: str):
        self.last_sync_iso = datetime.now(timezone.utc).isoformat()
        self.status = "failed"
        self.last_error = error


@dataclass
class MirrorSlaveStatus:
    """Status of a single slave mirror."""

    id: str
    type: str
    repo: Optional[str] = None
    url: Optional[str] = None
    role: str = ROLE_SLAVE
    code: SyncStatus = field(default_factory=SyncStatus)
    secrets: SyncStatus = field(default_factory=SyncStatus)
    variables: SyncStatus = field(default_factory=SyncStatus)
    workflows: SyncStatus = field(default_factory=SyncStatus)
    health: str = "unknown"  # ok, unreachable, unknown
    last_health_check_iso: Optional[str] = None


@dataclass
class MirrorState:
    """Complete mirror state."""

    self_role: str = ROLE_MASTER
    slaves: List[MirrorSlaveStatus] = field(default_factory=list)
    last_full_sync_iso: Optional[str] = None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "MirrorState":
        """Load mirror state from file."""
        if path is None:
            path = cls._default_path()

        if not path.exists():
            return cls()

        try:
            with open(path) as f:
                data = json.load(f)
            return cls._from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load mirror state: {e}")
            return cls()

    def save(self, path: Optional[Path] = None):
        """Save mirror state to file."""
        if path is None:
            path = self._default_path()

        path.parent.mkdir(parents=True, exist_ok=True)

        data = self._to_dict()
        with open(path, "w") as f:
            json.dump(data, f, indent=4, default=str)

    def get_slave(self, mirror_id: str) -> Optional[MirrorSlaveStatus]:
        """Get slave status by ID."""
        for s in self.slaves:
            if s.id == mirror_id:
                return s
        return None

    def ensure_slave(self, mirror_id: str, mirror_type: str,
                     repo: Optional[str] = None,
                     url: Optional[str] = None) -> MirrorSlaveStatus:
        """Get or create slave status entry."""
        existing = self.get_slave(mirror_id)
        if existing:
            return existing

        slave = MirrorSlaveStatus(
            id=mirror_id,
            type=mirror_type,
            repo=repo,
            url=url,
        )
        self.slaves.append(slave)
        return slave

    @classmethod
    def _default_path(cls) -> Path:
        return Path("state") / "mirror_status.json"

    @classmethod
    def _from_dict(cls, data: dict) -> "MirrorState":
        slaves = []
        for s in data.get("slaves", []):
            slave = MirrorSlaveStatus(
                id=s["id"],
                type=s.get("type", "unknown"),
                repo=s.get("repo"),
                url=s.get("url"),
                role=s.get("role", ROLE_SLAVE),
                health=s.get("health", "unknown"),
                last_health_check_iso=s.get("last_health_check_iso"),
            )
            for layer in ("code", "secrets", "variables", "workflows"):
                layer_data = s.get(layer, {})
                if layer_data:
                    sync = SyncStatus(
                        last_sync_iso=layer_data.get("last_sync_iso"),
                        status=layer_data.get("status", "unknown"),
                        last_error=layer_data.get("last_error"),
                        detail=layer_data.get("detail"),
                        fingerprint=layer_data.get("fingerprint"),
                    )
                    setattr(slave, layer, sync)
            slaves.append(slave)

        return cls(
            self_role=data.get("self_role", ROLE_MASTER),
            slaves=slaves,
            last_full_sync_iso=data.get("last_full_sync_iso"),
        )

    def _to_dict(self) -> dict:
        result = {
            "self_role": self.self_role,
            "last_full_sync_iso": self.last_full_sync_iso,
            "slaves": [],
        }
        for s in self.slaves:
            slave_dict = {
                "id": s.id,
                "type": s.type,
                "repo": s.repo,
                "url": s.url,
                "role": s.role,
                "health": s.health,
                "last_health_check_iso": s.last_health_check_iso,
                "code": asdict(s.code),
                "secrets": asdict(s.secrets),
                "variables": asdict(s.variables),
                "workflows": asdict(s.workflows),
            }
            result["slaves"].append(slave_dict)
        return result

    def to_api_dict(self) -> dict:
        """Return a dict suitable for the admin API response."""
        return self._to_dict()
