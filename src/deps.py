"""
Dependency management — lazy-install packages on first use.

Production images ship with core deps only (Tier 0).
Adapter and feature deps are installed on demand when first needed.
Uses uv (preferred) or pip as fallback.

## Design

- `ensure_package()` checks if a module is importable.
- If not, it attempts to install via `uv pip install` (fast) or `pip install`.
- Returns True/False — caller decides how to degrade gracefully.
- A module-level `_PIP_NAMES` registry maps module names to pip package names
  where they differ (e.g., `PIL` → `Pillow`).
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

# Registry: module_name → pip package name (only where they differ)
_PIP_NAMES: dict[str, str] = {
    "PIL": "Pillow",
}

# Cache: avoid re-attempting failed installs within the same process
_install_attempted: set[str] = set()


def ensure_package(module_name: str, pip_name: str | None = None) -> bool:
    """
    Ensure a Python package is importable. Install via uv/pip if missing.

    Returns True if the package is available (either already installed or
    successfully installed on the fly). Returns False if install failed.

    Does NOT raise — the caller decides how to degrade.
    """
    # Fast path: already importable
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        pass

    # Don't retry failed installs within the same process
    if module_name in _install_attempted:
        return False
    _install_attempted.add(module_name)

    pip_name = pip_name or _PIP_NAMES.get(module_name, module_name)
    logger.info(f"📦 Auto-installing {pip_name} (first use)...")

    # Try uv first (standalone binary, faster), then pip as fallback
    # uv is installed via `curl | sh` in Docker, available on PATH
    # pip fallback needs --break-system-packages on Debian/Ubuntu 3.12+
    import shutil
    installers = []
    uv_path = shutil.which("uv")
    if uv_path:
        installers.append([uv_path, "pip", "install", "--system", pip_name, "-q"])
    installers.append(
        [sys.executable, "-m", "pip", "install",
         "--break-system-packages", pip_name, "-q"],
    )

    for cmd in installers:
        try:
            subprocess.check_call(cmd, timeout=120)
            # Verify import works after install
            importlib.import_module(module_name)
            logger.info(f"✅ {pip_name} installed successfully")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        except ImportError:
            logger.error(f"❌ {pip_name} installed but import still fails")
            return False

    logger.error(f"❌ Failed to install {pip_name}")
    return False
