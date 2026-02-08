---
description: MANDATORY checklist before making ANY code change to this project
---

# ⛔ STOP — Read This Before Writing ANY Code

This project has a strict, consistent architecture. Every feature follows the same pattern.
If you don't understand the pattern, you WILL break things.

## The Architecture (memorize this)

```
.env (local) → Admin Panel Tiers → GitHub Secrets/Variables → cron.yml → CLI commands
```

### Data Flow for ANY Configuration Value

1. **User sets value** in admin panel or .env
2. **Admin panel tier** determines if it goes to GitHub:
   - `GITHUB_SECRETS` array (index.html ~line 1759) → `gh secret set`
   - `GITHUB_VARS` array (index.html ~line 1770) → `gh variable set`
   - `AUTO_PROVIDED` → injected by GitHub Actions runtime (GITHUB_TOKEN, etc.)
   - Everything else → Local only (never reaches the pipeline)
3. **cron.yml** injects secrets/vars into env: `MY_VAR: ${{ secrets.MY_VAR }}`
4. **CLI command** reads from `os.environ` and does the work

### The Server Pattern (NO EXCEPTIONS)

`server.py` is a **thin HTTP wrapper over CLI commands**. It NEVER imports domain logic.

```python
# ✅ CORRECT — subprocess to CLI
result = subprocess.run(["python", "-m", "src.main", "some-command", "--json"],
                        cwd=str(project_root), capture_output=True, text=True,
                        timeout=15, env=_fresh_env())

# ❌ WRONG — importing domain code into server
from ..some_module import SomeManager
manager = SomeManager.from_env()
manager.do_something()
```

### The GitHub Integration Pattern

Everything uses the `gh` CLI. NEVER use raw REST API with httpx/requests.

```python
# ✅ CORRECT
subprocess.run(["gh", "secret", "set", name, "-R", repo], input=value, ...)
subprocess.run(["gh", "variable", "set", name, "-R", repo, "--body", value], ...)
subprocess.run(["gh", "workflow", "enable", filename, "-R", repo], ...)

# ❌ WRONG
httpx.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", ...)
from nacl import ...  # NEVER
```

### The UI Pattern

- **No invented functions.** NEVER call a function without verifying it exists in the file.
- **Follow existing patterns.** Look at how email test, SMS test, git sync show feedback.
- **Check ALL files** a change touches: HTML, server.py, main.py, the domain module.

## Pre-Flight Checklist

Before making ANY change, answer these questions:

### 1. Configuration Flow
- [ ] Is every new env var in the correct tier? (`GITHUB_SECRETS`, `GITHUB_VARS`, or `LOCAL_ONLY`)
- [ ] Is the env var injected in `cron.yml` if the pipeline needs it?
- [ ] Does the `SYNCABLE_SECRETS` list in `github_sync.py` match what `cron.yml` actually injects?

### 2. Server Pattern
- [ ] Does `server.py` ONLY use subprocess calls? No domain imports?
- [ ] Does the CLI command exist in `main.py`?

### 3. UI
- [ ] Does every function I call actually exist in index.html?
- [ ] Am I following the same pattern as other similar features?

### 4. Pipeline
- [ ] Does `cron.yml` have a step for this feature if it needs to run automatically?
- [ ] Are all required secrets/variables listed in that step's `env:` block?

### 5. Completeness
- [ ] Did I fix ALL related files in ONE pass? (Not half of them)
- [ ] Did I trace the full data flow from .env → admin panel → GitHub → pipeline → target?

## Key File Locations

| What | Where |
|------|-------|
| Secret tiers (CRITICAL) | `src/admin/static/index.html` ~line 1759 |
| Pipeline secrets injection | `.github/workflows/cron.yml` env blocks |
| Syncable secrets list | `src/mirror/github_sync.py` SYNCABLE_SECRETS |
| Server endpoints | `src/admin/server.py` |
| CLI commands | `src/main.py` |
| Mirror config parser | `src/mirror/config.py` MirrorSettings.from_env() |

## Common Mistakes (that have been made before — don't repeat them)

1. **Adding a secret but not putting it in the right tier** → shows "Local only", never reaches GitHub
2. **Using httpx/REST API instead of gh CLI** → reinventing the wheel, adding phantom dependencies
3. **Calling showToast() or other non-existent functions** → UI crashes silently
4. **Not adding a cron.yml step** → feature only works locally, not in the pipeline
5. **Fixing one file but not related files** → half-broken state requiring multiple rounds
6. **Not matching SYNCABLE_SECRETS to cron.yml** → mirror missing critical secrets
7. **Adding `<script>` tags inside `scripts/*.html`** → These files are raw JS inside a shared `<script>` block (opened by `_globals.html`, closed by `_boot.html`). Adding `<script>` tags causes a syntax error. Put HTML in `partials/`, JS in `scripts/`. See `src/admin/templates/README.md`.
8. **Modifying vault without understanding the session lifecycle** → The passphrase is held in RAM for auto-lock. See `src/admin/vault.py`.
