"""
Mirror Configuration — Parse MIRROR_* environment variables.

This configures GitHub-to-GitHub mirroring: a complete copy on a backup
account that can auto-activate if the primary goes down, and auto-deactivate
when the primary recovers.

Minimal required config:
    MIRROR_ENABLED=true
    MIRROR_1_REPO=backup-user/repo-name
    MIRROR_1_TOKEN=ghp_xxxxx

TYPE defaults to "github" — it's the only type that supports full failover
(code + secrets + variables + workflows + sentinel).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MirrorConfig:
    """Configuration for a single failover target."""

    id: str  # e.g. "mirror-1"
    type: str  # "github" (other types reserved for future)
    token: Optional[str] = None  # PAT for the backup account
    repo: Optional[str] = None  # owner/repo on the backup account
    url: Optional[str] = None  # Git remote URL (fallback)
    enabled: bool = True

    # For GitHub failover, these are ALWAYS true — the whole point is
    # a complete clone that can take over.
    sync_secrets: bool = True
    sync_vars: bool = True

    @property
    def is_github(self) -> bool:
        return self.type == "github"

    @property
    def remote_url(self) -> Optional[str]:
        """Get the git remote URL for this mirror."""
        if self.url:
            return self.url
        if self.is_github and self.repo and self.token:
            return f"https://x-access-token:{self.token}@github.com/{self.repo}.git"
        return None

    @property
    def display_name(self) -> str:
        """Human-readable name for this mirror."""
        if self.repo:
            return self.repo
        if self.url:
            return self.url
        return self.id


@dataclass
class MirrorSettings:
    """Global mirror/failover settings."""

    enabled: bool = False
    mirrors: List[MirrorConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "MirrorSettings":
        """Parse mirror configuration from environment variables."""
        enabled = os.environ.get("MIRROR_ENABLED", "").lower() in ("true", "1", "yes")

        mirrors: List[MirrorConfig] = []

        # Scan for MIRROR_N_* variables (N = 1..10)
        for i in range(1, 11):
            prefix = f"MIRROR_{i}_"

            # Repo is the minimum required field
            repo = os.environ.get(f"{prefix}REPO")
            token = os.environ.get(f"{prefix}TOKEN")

            if not repo and not token:
                continue  # No config for this slot

            mirror_type = os.environ.get(f"{prefix}TYPE", "github").lower()

            if not repo:
                logger.warning(f"MIRROR_{i}: Missing MIRROR_{i}_REPO, skipping")
                continue
            if not token:
                logger.warning(f"MIRROR_{i}: Missing MIRROR_{i}_TOKEN, skipping")
                continue

            mirror = MirrorConfig(
                id=f"mirror-{i}",
                type=mirror_type,
                token=token,
                repo=repo,
                url=os.environ.get(f"{prefix}URL"),
                enabled=os.environ.get(f"{prefix}ENABLED", "true").lower()
                in ("true", "1", "yes"),
                # Always sync everything for GitHub failover
                sync_secrets=True,
                sync_vars=True,
            )

            mirrors.append(mirror)
            logger.info(f"Loaded failover target: {mirror.display_name}")

        settings = cls(enabled=enabled, mirrors=mirrors)

        if enabled and not mirrors:
            logger.warning("MIRROR_ENABLED=true but no valid failover targets configured")

        return settings

    def get_github_mirrors(self) -> List[MirrorConfig]:
        """Get GitHub-type mirrors (for secrets/vars sync)."""
        return [m for m in self.mirrors if m.is_github and m.enabled]

    def get_all_enabled(self) -> List[MirrorConfig]:
        """Get all enabled mirrors."""
        return [m for m in self.mirrors if m.enabled]
