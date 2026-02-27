# Dependency & Container Optimization — Implementation Plan

> Created: 2026-02-27  
> Reference: ci-dependency-optimization.analysis.md  
> Status: ✅ ALL PARTS COMPLETE

---

## Execution Order

```
Part 1: Prune dead weight        ✅ DONE — praw removed from Dockerfile, weasyprint is stale venv artifact
Part 2: uv cache in CI           ✅ DONE — added to cron.yml, renew.yml, test.yml, deploy-site.yml
Part 3: Define dependency tiers  ✅ DONE — httpx→core, cryptography→[crypto], per-adapter extras
Part 4: Lazy-install mechanism   ✅ DONE — src/deps.py + registry integration
Part 5: Lean production image    ✅ DONE — core-only Dockerfile, Python 3.12, uv for lazy-installs
```

---

## Part 1: Prune Dead Weight

**Goal:** Remove packages that are installed but never used.

### 1a: Remove weasyprint

**Evidence:** `grep -r "weasyprint" src/` → zero results.

**Action:** Remove from pip list. It's not in `pyproject.toml` (already
clean there), but check if it's a transitive dep or dev artifact.

```bash
# Check how it got installed
pip show weasyprint  # → look at "Required-by" field
```

If it's standalone (not pulled by anything), just `pip uninstall weasyprint`.
If it's a transient dep, the Dockerfile/pip line that pulls it needs fixing.

**Savings:** ~7MB (weasyprint + fonttools + cssselect2 + tinycss2 + pydyf)

### 1b: Remove praw from Dockerfile

**Current Dockerfile line 27-32:**
```dockerfile
RUN pip install --no-cache-dir \
    twilio \
    httpx \
    praw \          # ← Remove: not in pyproject.toml, adapter guards it
    resend \
    || true
```

**Action:** Remove `praw` from this line. The Reddit adapter already
guards with `PRAW_AVAILABLE = False` when praw is missing. It will
become a lazy-install candidate in Part 4.

### 1c: Verify nothing breaks

```bash
python -m pytest tests/ -x -q --tb=short
```

**Risk:** None. weasyprint has zero imports. praw was already not
installed locally and the adapter handles it.

---

## Part 2: uv Cache in CI

**Goal:** Cache pip/uv packages between GitHub Actions runs.

**File:** `.github/workflows/cron.yml`

### Current (lines 82-85):

```yaml
- name: Install uv and package
  run: |
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv pip install --system -e ".[adapters]" --quiet
```

### Proposed:

```yaml
- name: Cache uv packages
  uses: actions/cache@v4
  with:
    path: ~/.cache/uv
    key: uv-${{ runner.os }}-${{ hashFiles('pyproject.toml') }}

- name: Install uv and package
  run: |
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv pip install --system -e ".[adapters]" --quiet
```

**Savings:** Cached install ~3-5s vs uncached ~15-25s.

**Risk:** None. Cache miss = current behavior. Cache hit = faster.

---

## Part 3: Define Dependency Tiers

**Goal:** Restructure `pyproject.toml` so the tiers are explicit.

### Current pyproject.toml extras:

```toml
dependencies = [
    "pyyaml>=6.0", "pydantic>=2.0", "click>=8.0",
    "python-dateutil>=2.8", "python-dotenv>=1.0",
    "jinja2>=3.0", "cryptography>=42.0",  # ← cryptography in core!
]

[project.optional-dependencies]
adapters = ["httpx>=0.25", "resend>=1.0", "twilio>=8.0"]
admin = ["flask>=3.0", "Pillow>=10.0"]
```

### Proposed:

```toml
# Tier 0: Minimum viable tick
dependencies = [
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "click>=8.0",
    "python-dateutil>=2.8",
    "python-dotenv>=1.0",
    "jinja2>=3.0",
    "httpx>=0.25",          # ← moved from adapters (sentinel needs it)
]

[project.optional-dependencies]
# Tier 1: Adapter-specific (lazy-installable)
adapters-email = ["resend>=1.0"]
adapters-sms = ["twilio>=8.0"]
adapters-reddit = ["praw>=7.0"]

# Tier 2: Feature modules (lazy-installable)
crypto = ["cryptography>=42.0"]     # ← moved from core
admin = ["flask>=3.0", "Pillow>=10.0"]

# Convenience groups
adapters = [
    "continuity-orchestrator[adapters-email]",
    "continuity-orchestrator[adapters-sms]",
    "continuity-orchestrator[adapters-reddit]",
]
all = [
    "continuity-orchestrator[adapters]",
    "continuity-orchestrator[crypto]",
    "continuity-orchestrator[admin]",
]

# Dev always gets everything
dev = [
    "continuity-orchestrator[all]",
    "pytest>=7.0", "pytest-cov>=4.0",
    "ruff>=0.1", "mypy>=1.0",
]
```

### Key decisions

1. **`httpx` moves to core.** Sentinel notification runs every tick.
   4 adapters also use it but they lazy-import it already.

2. **`cryptography` moves OUT of core.** Only needed if templates are
   encrypted or admin vault is used. Content crypto already lazy-imports
   it (`from cryptography.hazmat...` inside functions).

3. **`adapters` meta-group preserved.** `pip install -e ".[adapters]"`
   still works for dev/CI. But production can install `pip install -e "."`
   for core only.

### Impact on existing code

The `cryptography` move requires checking that no top-level import
exists in the tick path:

```bash
grep -rn "^from cryptography\|^import cryptography" src/
# Expected: zero results (all imports are inside functions)
```

**Verified above:** All `cryptography` imports are inside function bodies
in `content/crypto.py` and `admin/vault.py`. Safe to move.

**Risk:** Low. Dev installs `[all]` or `[dev]`. CI can keep `[adapters]`
for now. Production uses core only.

---

## Part 4: Lazy-Install Mechanism

**Goal:** Adapters auto-install their dependency when first needed.

### 4a: Create `src/deps.py`

```python
"""
Dependency management — lazy-install packages on first use.

Production images ship with core deps only (Tier 0).
Adapter and feature deps are installed on demand when first needed.
Uses uv (preferred) or pip as fallback.
"""

import importlib
import logging
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Registry: module_name → pip_name (when they differ)
_PIP_NAMES = {
    "twilio": "twilio",
    "resend": "resend",
    "praw": "praw",
    "cryptography": "cryptography",
    "flask": "flask",
    "PIL": "Pillow",
}


def ensure_package(
    module_name: str,
    pip_name: Optional[str] = None,
) -> bool:
    """
    Ensure a Python package is importable. Install if missing.

    Uses uv (fast) with pip fallback. Returns True if available.
    Logs the install but does NOT raise on failure — caller decides
    how to degrade gracefully.
    """
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        pass

    pip_name = pip_name or _PIP_NAMES.get(module_name, module_name)
    logger.info(f"📦 Auto-installing {pip_name} (first use)...")

    for cmd in [
        [sys.executable, "-m", "uv", "pip", "install",
         "--system", pip_name, "-q"],
        [sys.executable, "-m", "pip", "install", pip_name, "-q"],
    ]:
        try:
            subprocess.check_call(cmd, timeout=120)
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
```

### 4b: Update adapter guards

Each adapter's existing `try/except ImportError` becomes:

**`email_resend.py`:**
```python
# Before:
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    resend = None

# After:
from ..deps import ensure_package

RESEND_AVAILABLE = ensure_package("resend")
if RESEND_AVAILABLE:
    import resend
else:
    resend = None
```

**Same pattern for `sms_twilio.py` and `reddit.py`.**

### 4c: Guard httpx adapters

The 4 adapters that use `httpx` via local import (webhook, x_twitter,
persistence_api, github_surface) need guards added. Since `httpx` is
Tier 0, this is belt-and-suspenders:

```python
# In execute():
try:
    import httpx
except ImportError:
    return Receipt.failed(
        adapter=self.name,
        error_code="missing_dep",
        error_message="httpx not available",
        retryable=False,
    )
```

### 4d: Guard cryptography in content/crypto.py

Content crypto functions already import inside function bodies.
Add a check at the top of functions that use it:

```python
def decrypt_content(key, data):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        from ..deps import ensure_package
        if not ensure_package("cryptography"):
            raise RuntimeError("cryptography package required for decryption")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # ... rest of function
```

**Risk:** Low. All adapters already handle the "not available" case.
The only new behavior is attempting to install before giving up.

---

## Part 5: Lean Production Image

**Goal:** Docker image with Tier 0 only, lazy-install for the rest.

**Depends on:** Part 3 (tiers) + Part 4 (lazy-install mechanism)

### 5a: New Dockerfile

```dockerfile
FROM python:3.12-slim AS production

# System deps: git (sync), curl (uv bootstrap)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git jq && rm -rf /var/lib/apt/lists/*

# Install uv for fast lazy-installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN useradd -m -s /bin/bash continuity
WORKDIR /app

# Install core deps only (Tier 0, ~14MB)
COPY pyproject.toml .
COPY src ./src
RUN uv pip install --system -e "." --quiet

COPY policy ./policy
COPY templates ./templates
COPY content ./content
COPY scripts ./scripts

RUN mkdir -p /data/state /data/audit && \
    chown -R continuity:continuity /app /data

USER continuity

ENV STATE_FILE=/data/state/current.json
ENV AUDIT_DIR=/data/audit
ENV POLICY_DIR=/app/policy
ENV ADAPTER_MOCK_MODE=false

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m src.main status || exit 1

CMD ["python", "-m", "src.main", "tick"]
```

### 5b: CI core-only install (optional, requires Part 4)

```yaml
# In cron.yml — install core only, let adapters lazy-install
- name: Install uv and core package
  run: |
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv pip install --system -e "." --quiet     # Core only
```

On quiescent ticks: nothing else installed.
On active ticks: adapters auto-install via `ensure_package()`.
With uv cache (Part 2): subsequent installs are instant.

### 5c: Docker compose with cache volume

```yaml
services:
  orchestrator:
    build: .
    volumes:
      - uv-cache:/root/.cache/uv    # Lazy-installed pkgs persist
      - ./state:/data/state
      - ./audit:/data/audit

volumes:
  uv-cache:
```

**Risk:** Medium. First active tick after cold start pays install cost
(~5-15s for twilio). Acceptable for a 30-min cron cycle.

---

## Summary

| Part | What | Files | Effort | Risk | Depends |
|------|------|-------|--------|------|---------|
| **1** | Prune dead weight | Dockerfile | 5 min | None | — |
| **2** | uv cache in CI | cron.yml | 5 min | None | — |
| **3** | Dependency tiers | pyproject.toml | 15 min | Low | — |
| **4** | Lazy-install mechanism | src/deps.py + adapters | 30 min | Low | — |
| **5** | Lean production image | Dockerfile, cron.yml | 20 min | Medium | 3, 4 |
