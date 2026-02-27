# Dependency & Container Optimization — Analysis

> Created: 2026-02-27  
> Scope: Production readiness — smaller footprint, lazy-install features

---

## What We Know

### Current dependency inventory (69 packages, 196MB)

**Core (always needed for any tick):**

| Package | Size | Has .so? | Notes |
|---------|------|----------|-------|
| pydantic + pydantic_core | 8.2MB | **YES** (Rust) | State/policy models |
| pyyaml | 3.0MB | **YES** (C) | Policy file loading |
| click | 700KB | No | CLI framework |
| python-dateutil | 732KB | No | Time calculations |
| python-dotenv | 108KB | No | .env loading |
| httpx | 616KB | No | Sentinel notify + adapters |
| jinja2 | 1.0MB | No | Template rendering |
| **TOTAL** | **~14MB** | | |

**Adapter-specific (only needed when a specific adapter fires):**

| Package | Size | Has .so? | Used by | Guard exists? |
|---------|------|----------|---------|---------------|
| twilio | **40MB** | No (pure Python!) | `sms_twilio.py` | ✅ `TWILIO_AVAILABLE` |
| resend | 688KB | No | `email_resend.py` | ✅ `RESEND_AVAILABLE` |
| praw | ~5MB | No | `reddit.py` | ✅ `PRAW_AVAILABLE` (not even installed locally) |

**Feature-specific (only needed for specific features):**

| Package | Size | Has .so? | Used by | Notes |
|---------|------|----------|---------|-------|
| cryptography | **14MB** | **YES** (Rust) | `content/crypto.py`, `admin/vault.py` | Only for encrypted templates |
| flask | 728KB | No | Admin panel | Not used in CI tick path |
| pillow | **6MB** | **YES** (C) | `content/media_optimize.py` | Not used in CI tick path |

**Dead weight (installed but never imported):**

| Package | Size | Notes |
|---------|------|-------|
| weasyprint | 2MB + fonttools (5MB) + deps | **Zero imports in entire src/** |
| aiohttp chain | 5.3MB | Transitive dep, likely from twilio |

### What adapters actually import (and how)

Every adapter already uses **graceful degradation**:

```python
# email_resend.py, sms_twilio.py, reddit.py — all do this:
try:
    import resend          # or twilio, praw
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

# Then in is_enabled():
def is_enabled(self, context):
    if not RESEND_AVAILABLE:
        logger.warning("resend package not installed, email adapter disabled")
        return False
```

The adapters using `httpx` (webhook, x_twitter, persistence_api, 
github_surface) do local imports inside `execute()` but do NOT have
ImportError guards.

### Binary extension reality check

These packages ship prebuilt `manylinux` wheels on PyPI:
- `pydantic_core` → prebuilt for linux/amd64, arm64
- `cryptography` → prebuilt for linux/amd64, arm64
- `PyYAML` → prebuilt, plus has pure-Python fallback

**This means `uv pip install cryptography` works on a slim Docker image
without gcc/headers.** No build tools needed — it downloads the wheel.

---

## Part 1: Dependency Tiers

Split the monolithic `pip install -e ".[adapters]"` into tiers:

```
┌──────────────────────────────────────────────────┐
│  TIER 0 — Always installed (~14MB)               │
│  pydantic, pyyaml, click, dateutil, dotenv,      │
│  httpx, jinja2                                   │
│  → Tick can evaluate rules, compute state,       │
│    detect quiescence, notify sentinel            │
├──────────────────────────────────────────────────┤
│  TIER 1 — Lazy-installed per adapter (~46MB)     │
│  twilio (40MB), resend (688KB), praw (~5MB)      │
│  → Only installed when the adapter actually      │
│    needs to fire for the first time              │
├──────────────────────────────────────────────────┤
│  TIER 2 — Feature modules (~21MB)                │
│  cryptography (14MB) → content encryption        │
│  flask + pillow (7MB) → admin panel              │
│  → Only installed when the feature is activated  │
└──────────────────────────────────────────────────┘
```

### What this means in practice

**Quiescent tick (90%+ of runs):**
- Needs: Tier 0 only (14MB)
- No adapters fire, no crypto needed
- Sentinel notification uses httpx (already in Tier 0)

**Active tick (state transition, adapters fire):**
- Needs: Tier 0 + whichever adapters are configured
- First time an adapter fires → lazy-install its dep
- Second time → already cached, instant

**Admin panel:**
- Needs: Tier 0 + Tier 2 (flask, pillow, cryptography)
- Separate deployment path anyway (not CI)

---

## Part 2: Lazy-Install Mechanism

### The utility function

```python
# src/deps.py
import importlib
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

def ensure_package(module_name: str, pip_name: str = None) -> bool:
    """
    Ensure a Python package is available. Install via uv/pip if missing.
    Returns True if available, False if install failed.
    """
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        pass

    pip_name = pip_name or module_name
    logger.info(f"📦 Installing {pip_name} (first use)...")

    # Prefer uv (faster), fall back to pip
    for installer in [
        [sys.executable, "-m", "uv", "pip", "install", pip_name, "-q"],
        [sys.executable, "-m", "pip", "install", pip_name, "-q"],
    ]:
        try:
            subprocess.check_call(installer, timeout=120)
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

### How adapters would use it

The existing guard pattern barely changes:

```python
# Before (current):
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

# After (with lazy-install):
from ..deps import ensure_package

RESEND_AVAILABLE = ensure_package("resend")
```

Or even lazier — install only when the adapter is about to fire:

```python
def is_enabled(self, context):
    if not RESEND_AVAILABLE:
        # Try to install on demand
        if ensure_package("resend"):
            import resend
            resend.api_key = self.api_key
            return True
        return False
```

### Decision: Module-load-time vs execution-time install?

| Approach | When install happens | Pro | Con |
|----------|---------------------|-----|-----|
| Module load | When adapter file is imported | Simpler | Installs even if adapter won't fire |
| Execution time | When `is_enabled()` or `execute()` is called | Truly lazy | Slightly more complex |

**Recommendation:** Execution-time. The adapters already check 
`is_enabled()` before `execute()`. The install should happen in
`is_enabled()` — if the package isn't there AND the env vars are
configured, install it. If env vars aren't set, don't bother installing.

---

## Part 3: CI (GitHub Actions) Optimization

Two independent wins:

### 3a: uv cache (zero-risk, 3 lines)

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

Cached install: ~3-5s instead of ~15-25s. Works for all ticks.

### 3b: Install only core in CI, lazy-install adapters (medium effort)

```yaml
- name: Install core package
  run: |
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv pip install --system -e "." --quiet     # Core only, ~14MB
```

The tick's adapter execution path would lazy-install `twilio`/`resend`
if an adapter needs to fire. On quiescent ticks → nothing extra installed.

**Prerequisite:** Part 2 (lazy-install mechanism) must be implemented first.

### 3a vs 3b — not mutually exclusive

Do 3a immediately (free win). Do 3b after Part 2 is implemented. They
stack — the uv cache makes lazy-installs faster on subsequent runs too.

---

## Part 4: Docker Image Optimization

### Current Dockerfile

```dockerfile
FROM python:3.11-slim                  # ~125MB base
RUN pip install --no-cache-dir -e .    # Core deps
RUN pip install --no-cache-dir twilio httpx resend praw || true  # Everything
```

Total image: ~350MB+ (estimated)

### Proposed: Lean production image

```dockerfile
FROM python:3.12-slim AS production

# System deps: only git (for git-sync mode) and curl (for uv)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# Install ONLY core deps (Tier 0)
COPY pyproject.toml .
COPY src ./src
RUN uv pip install --system -e "." --quiet

# Copy application
COPY policy ./policy
COPY templates ./templates
COPY content ./content
COPY scripts ./scripts

# pip cache volume — lazy-installed packages persist across restarts
VOLUME /root/.cache/uv

# ... rest of Dockerfile (user, healthcheck, CMD)
```

Image size: ~150-170MB (vs ~350MB+)

### How lazy-install works in Docker

1. Container starts with Tier 0 only
2. First active tick needs email → `ensure_package("resend")` → 
   `uv pip install resend` → writes to `/root/.cache/uv` volume
3. Container restarts → cache volume persists → `resend` is already 
   available (uv checks cache first)
4. First SMS tick → `uv pip install twilio` → cached for future

### The tradeoff

| Scenario | Fat image (current) | Lean + lazy |
|----------|--------------------|-|
| Cold start (no cache) | 0s (everything baked) | +5-15s first adapter use |
| Warm start (cached) | 0s | 0s |
| Image pull time | ~350MB | ~170MB (~50% smaller) |
| Quiescent tick | Pays for 196MB of unused deps | Only 14MB loaded |

---

## Part 5: Prune Dead Weight (Free Wins)

### weasyprint — zero imports

```bash
$ grep -r "weasyprint" src/
# (nothing)
```

Installed but never used. Remove from pip list / Dockerfile.
Saves: ~7MB (weasyprint + fonttools + deps)

### praw — not in pyproject.toml

Only in the Dockerfile's `pip install praw || true` line. The adapter
already guards with `PRAW_AVAILABLE`. Should be lazy-installed, not baked.

### aiohttp chain — transitive

Likely pulled in by twilio. If twilio becomes lazy-installed, this
disappears from the base image automatically.

---

## Summary: Implementation Parts

| Part | What | Effort | Risk | Prerequisite |
|------|------|--------|------|--------------|
| **1** | Define dependency tiers in pyproject.toml | Low | None | — |
| **2** | `ensure_package()` utility + adapter integration | Medium | Low | — |
| **3a** | uv cache in CI | 3 lines | None | — |
| **3b** | CI installs core only | Low | Low | Part 2 |
| **4** | Lean Docker image | Medium | Low | Part 2 |
| **5** | Prune weasyprint, praw | 5 minutes | None | — |

### Recommended order

```
Part 5 (prune dead weight)  → free, do now
Part 3a (uv cache)          → free, do now
Part 1 (define tiers)       → foundation for everything else
Part 2 (lazy-install)       → the core mechanism
Part 3b (CI core-only)      → uses Part 2
Part 4 (lean Docker)        → uses Part 2
```

Parts 5 + 3a can ship immediately with zero risk.
Parts 1 + 2 are the real work — the lazy-install mechanism.
Parts 3b + 4 follow naturally once the mechanism exists.

---

## Open Questions

1. **Should `httpx` stay in Tier 0?** It's used by sentinel (every tick)
   AND by 4 adapters. If we remove it from Tier 0, sentinel notification
   fails on quiescent ticks until it's lazy-installed. Keeping it in
   Tier 0 is the safe call.

2. **Should `cryptography` be Tier 1 or Tier 2?** It's needed for
   encrypted template resolution during active ticks. If templates are
   encrypted, the tick needs it DURING execution. If not encrypted, 
   never needed. Current answer: Tier 2 (lazy when content crypto is
   activated).

3. **Should `jinja2` stay in Tier 0?** Only needed for template rendering
   during active ticks. But it's small (1MB) and the tick code imports
   template resolver conditionally already. Safe to keep in Tier 0.

4. **uv availability in Docker?** The lean image needs `uv` installed for
   fast lazy-installs. `curl` is needed to bootstrap `uv`. Both are
   small. Alternatively, `pip` works but is slower.
