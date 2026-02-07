# Refactoring Plan — Module Decomposition

**Goal:** Break the 3 oversized files into logical, focused modules.  
**Target:** ~500 lines max per file (~700 for complex exceptions).  
**Principle:** Each file has a single responsibility. Shared utilities extracted.

---

## Current State

| File | Lines | Role |
|------|-------|------|
| `src/admin/static/index.html` | **5,258** | Entire SPA: HTML + CSS + JS |
| `src/main.py` | **2,164** | All CLI commands (37 functions) |
| `src/admin/server.py` | **1,641** | All API routes (43 endpoints) |

Everything else in the project is already well-structured (adapters, engine, mirror, config, etc. — all ≤520 lines).

---

## Phase 1: `src/main.py` → CLI Command Groups

The CLI has clear logical groups. Extract each into its own module.

### Target Structure

```
src/
├── main.py                          (~80 lines)  — CLI entry, group registration
├── cli/
│   ├── __init__.py                  — re-exports `cli` group
│   ├── core.py                      (~200 lines) — tick, status, set-deadline, reset, renew
│   ├── release.py                   (~120 lines) — trigger-release
│   ├── config.py                    (~180 lines) — check-config, config-status, generate-config
│   ├── health.py                    (~100 lines) — health, metrics, retry-queue, circuit-breakers
│   ├── mirror.py                    (~450 lines) — mirror-status, mirror-sync, mirror-clean
│   ├── init.py                      (~250 lines) — init (project scaffolding)
│   ├── test.py                      (~270 lines) — test email/sms/webhook/github/all
│   ├── deploy.py                    (~200 lines) — export-secrets, explain-stages, simulate-timeline
│   └── site.py                      (~120 lines) — build-site
```

### Migration Pattern
```python
# src/main.py (after refactoring)
from .cli import cli

if __name__ == "__main__":
    cli()
```

```python
# src/cli/__init__.py
import click
from .core import tick, status, set_deadline, reset, renew
from .mirror import mirror_status, mirror_sync, mirror_clean
# ... etc

@click.group()
@click.pass_context
def cli(ctx):
    """Continuity Orchestrator — Policy-first automation system."""
    ctx.ensure_object(dict)

# Register all commands
cli.add_command(tick)
cli.add_command(status)
# ... etc
```

### Order of Extraction
1. `cli/test.py` — Standalone, no dependencies on other commands
2. `cli/deploy.py` — Standalone (export-secrets, explain-stages, simulate-timeline)
3. `cli/site.py` — Standalone (build-site)
4. `cli/config.py` — Standalone (check-config, config-status, generate-config)
5. `cli/health.py` — Standalone (health, metrics, retry-queue, circuit-breakers)
6. `cli/release.py` — Standalone (trigger-release)
7. `cli/init.py` — Standalone (init)
8. `cli/mirror.py` — The largest group, has emit() helper to share
9. `cli/core.py` — tick, status, set-deadline, reset, renew (foundational)
10. Final: `main.py` becomes thin entry point + `cli/__init__.py` wires it up

---

## Phase 2: `src/admin/server.py` → Route Blueprints

Flask Blueprints are the native pattern for this. Group routes by domain.

### Target Structure

```
src/admin/
├── server.py                        (~180 lines) — create_app(), helpers, run_server
├── routes/
│   ├── __init__.py                  — registers all blueprints
│   ├── status.py                    (~80 lines)  — /api/status, /api/run
│   ├── env.py                       (~200 lines) — /api/env/read, /api/env/write
│   ├── secrets.py                   (~350 lines) — /api/secrets/push, /api/gh/*, /api/secret/*
│   ├── git.py                       (~250 lines) — /api/git/status, /api/git/sync
│   ├── mirror.py                    (~250 lines) — /api/mirror/status, /api/mirror/sync/*
│   ├── archive.py                   (~250 lines) — /api/archive, /api/archive/check
│   ├── testing.py                   (~100 lines) — /api/test/email, /api/test/sms
│   └── state.py                     (~100 lines) — /api/state/reset, /api/state/factory-reset,
│                                                    /api/renew, /api/set-deadline
├── helpers.py                       (~80 lines)  — _fresh_env, _gh_repo_flag,
│                                                    _trigger_mirror_sync_bg, kill_port
├── static/
│   ├── index.html                   (see Phase 3)
│   ├── css/
│   └── js/
└── __init__.py
```

### Blueprint Pattern
```python
# src/admin/routes/git.py
from flask import Blueprint, jsonify, request
from ..helpers import _fresh_env, _trigger_mirror_sync_bg

git_bp = Blueprint('git', __name__)

@git_bp.route("/api/git/status")
def api_git_status():
    ...

@git_bp.route("/api/git/sync", methods=["POST"])
def api_git_sync():
    ...
```

```python
# src/admin/server.py
from .routes import register_blueprints

def create_app():
    app = Flask(...)
    register_blueprints(app)
    return app
```

### Order of Extraction
1. `helpers.py` — Extract shared functions first (_fresh_env, _trigger_mirror_sync_bg, etc.)
2. `routes/testing.py` — Small, standalone (test email/sms)
3. `routes/state.py` — Small (reset, factory-reset, renew, set-deadline)
4. `routes/status.py` — Small (status, run)
5. `routes/archive.py` — Self-contained
6. `routes/env.py` — env read/write
7. `routes/secrets.py` — Largest: push, gh/secrets, secret/set, secret/remove
8. `routes/git.py` — git status + sync (uses mirror helper)
9. `routes/mirror.py` — mirror status + sync/clean streams
10. Final: `server.py` becomes thin app factory

---

## Phase 3: `src/admin/static/index.html` → SPA Components

This is the most impactful change. Extract CSS, then JS modules.

### Target Structure

```
src/admin/static/
├── index.html                       (~250 lines) — Shell: head, nav, tab containers, script tags
├── css/
│   ├── base.css                     (~200 lines) — Reset, variables, typography, dark/light theme
│   ├── components.css               (~200 lines) — Cards, buttons, forms, badges, terminals
│   ├── layout.css                   (~100 lines) — Grid, tabs, responsive
│   └── animations.css               (~30 lines)  — pulse, shimmer, pulse-glow
├── js/
│   ├── app.js                       (~100 lines) — Init, theme, language selector, tab switching
│   ├── api.js                       (~60 lines)  — Shared fetch helpers, error handling
│   ├── dashboard.js                 (~350 lines) — Status polling, git status, countdown, git sync
│   ├── secrets.js                   (~500 lines) — Secrets form, master secret, push, tier logic
│   ├── integrations.js              (~200 lines) — Integration cards, test buttons
│   ├── mirror.js                    (~350 lines) — Mirror panel, sync stream, clean stream
│   ├── wizard.js                    (~400 lines) — Setup wizard (multi-step)
│   └── utils.js                     (~60 lines)  — mirrorTimeAgo, formatBytes, etc.
```

### Key Decisions
- **No build step** — Plain `<script src="js/app.js">` tags, no webpack/vite
- **Shared state** — `window.appState = { envData, ghSecrets, ... }` for cross-module access
- **Event-driven** — Modules communicate via `CustomEvent` dispatch on `document`
- **CSS files** — Served as static files, linked via `<link rel="stylesheet">`

### Order of Extraction
1. `css/animations.css` — Trivial, ~30 lines of @keyframes
2. `css/base.css` — Variables, reset, typography
3. `css/components.css` — Buttons, cards, forms, badges
4. `css/layout.css` — Tab layout, grid
5. `js/utils.js` — Pure helper functions
6. `js/api.js` — Shared fetch/error helpers
7. `js/app.js` — Init, theme toggle, tabs
8. `js/dashboard.js` — Status + git (most independent)
9. `js/integrations.js` — Integration cards
10. `js/mirror.js` — Mirror panel
11. `js/secrets.js` — Secrets (largest JS module)
12. `js/wizard.js` — Wizard (last — depends on most other modules)
13. Final: `index.html` becomes thin shell

---

## Execution Rules

1. **One extraction at a time** — Extract → verify builds → verify UI works → commit → next
2. **No behavior changes** — Pure structural moves. Bugs are fixed separately.
3. **Tests pass after each step** — `python -m pytest` green before moving on
4. **Git commit after each extraction** — Clean history showing each module split
5. **500-line target** — Hard cap. If a module exceeds 700, split further.

---

## Priority Order

| # | Phase | File | Effort | Impact |
|---|-------|------|--------|--------|
| 1 | 3.1-3.4 | CSS extraction from index.html | Low | Instant cleanup |
| 2 | 2.1 | helpers.py from server.py | Low | Unblocks all route extractions |
| 3 | 1.1-1.4 | Easy CLI groups (test, deploy, site, config) | Low | Quick wins |
| 4 | 3.5-3.7 | JS utils, api, app from index.html | Medium | Foundation for JS modules |
| 5 | 2.2-2.5 | Small route blueprints (testing, state, status, archive) | Medium | server.py shrinks fast |
| 6 | 1.5-1.10 | Remaining CLI groups + thin main.py | Medium | main.py complete |
| 7 | 2.6-2.10 | Remaining blueprints + thin server.py | Medium | server.py complete |
| 8 | 3.8-3.13 | Remaining JS modules + thin index.html | High | Full SPA decomposition |
