"""
Mirror Manager — Orchestrates all mirror sync operations.

This is the main entry point for mirror operations. It coordinates
git push, secret sync, variable sync, and health checks across
all configured mirrors.

## Usage from other modules:

    from src.mirror.manager import MirrorManager

    manager = MirrorManager.from_env()
    if manager.enabled:
        manager.propagate_code_sync(project_root)
        manager.propagate_secrets()
        manager.propagate_variables()
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import MirrorSettings, MirrorConfig
from .state import MirrorState, ROLE_SLAVE
from . import git_sync
from . import github_sync

logger = logging.getLogger(__name__)


class MirrorManager:
    """
    Orchestrates mirror sync operations.

    All propagation methods are fire-and-forget (async via threads)
    so they never block the primary operation.
    """

    def __init__(self, settings: MirrorSettings, state: Optional[MirrorState] = None):
        self.settings = settings
        self.state = state or MirrorState.load()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "MirrorManager":
        """Create manager from environment variables."""
        settings = MirrorSettings.from_env()
        state = MirrorState.load()
        return cls(settings, state)

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and len(self.settings.mirrors) > 0

    # ─── Code Sync ──────────────────────────────────────────

    def propagate_code_sync(
        self,
        project_root: Path,
        branch: str = "main",
        blocking: bool = False,
    ):
        """
        Push code to all mirrors after a git sync.

        By default runs in a background thread (non-blocking).
        Set blocking=True for synchronous operation (e.g. tests).
        """
        if not self.enabled:
            return

        mirrors = self.settings.get_all_enabled()
        if not mirrors:
            return

        def _do_push():
            logger.info(f"[mirror] Propagating code to {len(mirrors)} mirror(s)")
            results = git_sync.push_all_mirrors(mirrors, project_root, branch)

            with self._lock:
                for mirror_id, result in results.items():
                    mirror = next(
                        (m for m in mirrors if m.id == mirror_id), None
                    )
                    if not mirror:
                        continue
                    slave = self.state.ensure_slave(
                        mirror_id, mirror.type, mirror.repo, mirror.url
                    )
                    if result["ok"]:
                        slave.code.mark_ok(detail=result.get("commit"))
                    else:
                        slave.code.mark_failed(result.get("error", "Unknown error"))

                self.state.save()

            ok_count = sum(1 for r in results.values() if r["ok"])
            logger.info(
                f"[mirror] Code sync: {ok_count}/{len(results)} mirrors synced"
            )

        if blocking:
            _do_push()
        else:
            thread = threading.Thread(target=_do_push, name="mirror-code-sync", daemon=True)
            thread.start()

    # ─── Secrets Sync ───────────────────────────────────────

    def propagate_secrets(self, blocking: bool = False):
        """
        Sync secrets to all GitHub mirrors.

        By default runs in a background thread (non-blocking).
        """
        if not self.enabled:
            return

        github_mirrors = self.settings.get_github_mirrors()
        mirrors_with_secrets = [m for m in github_mirrors if m.sync_secrets]
        if not mirrors_with_secrets:
            return

        def _do_sync():
            logger.info(
                f"[mirror] Syncing secrets to {len(mirrors_with_secrets)} mirror(s)"
            )

            for mirror in mirrors_with_secrets:
                ok, synced, total, error = github_sync.sync_all_secrets(mirror)

                with self._lock:
                    slave = self.state.ensure_slave(
                        mirror.id, mirror.type, mirror.repo
                    )
                    if ok:
                        slave.secrets.mark_ok(detail=f"{synced}/{total}")
                    else:
                        slave.secrets.mark_failed(error or "Unknown error")

                    self.state.save()

        if blocking:
            _do_sync()
        else:
            thread = threading.Thread(
                target=_do_sync, name="mirror-secrets-sync", daemon=True
            )
            thread.start()

    # ─── Variables Sync ─────────────────────────────────────

    def propagate_variables(
        self,
        master_repo: Optional[str] = None,
        blocking: bool = False,
    ):
        """
        Sync variables to all GitHub mirrors.

        By default runs in a background thread (non-blocking).
        """
        if not self.enabled:
            return

        github_mirrors = self.settings.get_github_mirrors()
        mirrors_with_vars = [m for m in github_mirrors if m.sync_vars]
        if not mirrors_with_vars:
            return

        def _do_sync():
            logger.info(
                f"[mirror] Syncing variables to {len(mirrors_with_vars)} mirror(s)"
            )

            for mirror in mirrors_with_vars:
                ok, synced, total, error = github_sync.sync_all_variables(
                    mirror, master_repo
                )

                with self._lock:
                    slave = self.state.ensure_slave(
                        mirror.id, mirror.type, mirror.repo
                    )
                    if ok:
                        slave.variables.mark_ok(detail=f"{synced}/{total}")
                    else:
                        slave.variables.mark_failed(error or "Unknown error")

                    self.state.save()

        if blocking:
            _do_sync()
        else:
            thread = threading.Thread(
                target=_do_sync, name="mirror-vars-sync", daemon=True
            )
            thread.start()

    # ─── Full Sync ──────────────────────────────────────────

    def propagate_all(
        self,
        project_root: Path,
        branch: str = "main",
        master_repo: Optional[str] = None,
        blocking: bool = False,
    ):
        """
        Full sync: code + secrets + variables.

        For use on initial setup or force sync from admin panel.
        """
        if not self.enabled:
            return

        def _do_full():
            # Code sync (blocking within thread)
            self.propagate_code_sync(project_root, branch, blocking=True)
            # Secrets sync
            self.propagate_secrets(blocking=True)
            # Variables sync
            self.propagate_variables(master_repo, blocking=True)

            with self._lock:
                self.state.last_full_sync_iso = datetime.now(
                    timezone.utc
                ).isoformat()
                self.state.save()

            logger.info("[mirror] Full sync complete")

        if blocking:
            _do_full()
        else:
            thread = threading.Thread(
                target=_do_full, name="mirror-full-sync", daemon=True
            )
            thread.start()

    # ─── Setup Slave ────────────────────────────────────────

    def setup_slave(
        self,
        mirror: MirrorConfig,
        project_root: Path,
        master_repo: Optional[str] = None,
    ) -> Dict:
        """
        Full initial setup for a slave mirror.

        1. Push code
        2. Sync secrets
        3. Sync variables (including MASTER_REPO)
        4. Configure workflows (disable operational, enable sentinel)

        Returns results dict.
        """
        results = {"steps": []}

        # 1. Code push
        ok, commit, error = git_sync.push_to_mirror(mirror, project_root)
        results["steps"].append({
            "step": "code_push",
            "ok": ok,
            "detail": commit,
            "error": error,
        })

        if not ok:
            results["success"] = False
            results["error"] = f"Code push failed: {error}"
            return results

        # 2. Secrets
        if mirror.sync_secrets and mirror.is_github:
            ok, synced, total, error = github_sync.sync_all_secrets(mirror)
            results["steps"].append({
                "step": "secrets_sync",
                "ok": ok,
                "detail": f"{synced}/{total}",
                "error": error,
            })

        # 3. Variables
        if mirror.sync_vars and mirror.is_github:
            ok, synced, total, error = github_sync.sync_all_variables(
                mirror, master_repo
            )
            results["steps"].append({
                "step": "variables_sync",
                "ok": ok,
                "detail": f"{synced}/{total}",
                "error": error,
            })

        # 4. Workflow configuration
        if mirror.is_github:
            ok, error = github_sync.setup_slave_workflows(mirror)
            results["steps"].append({
                "step": "workflow_setup",
                "ok": ok,
                "error": error,
            })

        # Update state
        slave = self.state.ensure_slave(
            mirror.id, mirror.type, mirror.repo, mirror.url
        )
        slave.role = ROLE_SLAVE

        all_ok = all(s["ok"] for s in results["steps"])
        results["success"] = all_ok
        self.state.save()

        return results

    # ─── Status ─────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get mirror status for API/admin panel."""
        return {
            "enabled": self.enabled,
            "self_role": self.state.self_role,
            "mirrors_configured": len(self.settings.mirrors),
            "mirrors": self.state.to_api_dict(),
        }
