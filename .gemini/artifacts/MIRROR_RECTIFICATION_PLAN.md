# Mirror Integration — Rectification Plan

## Current State Assessment

### Architecture: How the project works (correctly)

The project is **CLI-first**. The admin panel (`server.py`) is a thin HTTP wrapper over CLI commands:

| Feature | Server endpoint | How it works |
|---------|----------------|--------------|
| Test email | `POST /api/test/email` | `subprocess.run(["python", "-m", "src.main", "test", "email", ...], env=_fresh_env())` |
| Test SMS | `POST /api/test/sms` | `subprocess.run(["python", "-m", "src.main", "test", "sms", ...], env=_fresh_env())` |
| Git sync | `POST /api/git/sync` | `subprocess.run(["git", "add", ...])` + `subprocess.run(["git", "push", ...])` |
| Status | `GET /api/status` | `subprocess.run(["python", "-m", "src.main", "status", "--json"])` |

**Pattern:** Server calls CLI via subprocess → CLI does the work → CLI returns JSON output → Server returns it to UI.

The server NEVER imports domain modules. It NEVER holds state. It NEVER runs logic in threads.

### Architecture: How mirror currently works (broken)

| What | How it's done (WRONG) |
|------|----------------------|
| Startup | `from ..mirror.manager import MirrorManager` — imports domain code into server |
| Startup | `MirrorManager.from_env()` → stored in `app.config["MIRROR_MANAGER"]` — in-process singleton |
| Status | `mm.get_status()` — calls Python method on cached object |
| Sync | `mm.propagate_all()` — fires background thread inside Flask process |
| Env refresh | `_fresh_mirror_manager()` — hacks `os.environ` temporarily to re-read `.env` |
| Git sync hook | After git push, calls `mm.propagate_code_sync()` inline |
| Env save hook | After .env write, calls `mm.propagate_secrets()` inline |

**Violations:**
1. Domain module imported into server (only mirror does this)
2. In-process stateful object (`app.config["MIRROR_MANAGER"]`)
3. Env hack function (`_fresh_mirror_manager`) — exists nowhere else
4. Background threads for sync — zero observability
5. No CLI command exists at all (`main.py` has zero mirror commands)
6. `manage.sh` has zero mirror entries

---

## File Inventory — What exists today

### `src/mirror/` module (5 files)

| File | Lines | Role | Status |
|------|-------|------|--------|
| `__init__.py` | 7 | Package docstring | ✅ Fine |
| `config.py` | 130 | Parse `MIRROR_*` env vars into `MirrorSettings` / `MirrorConfig` | ✅ Fine (clean dataclass, no server coupling) |
| `git_sync.py` | 155 | `push_to_mirror()` — runs `git push` subprocess | ✅ Fine (pure git operations) |
| `github_sync.py` | 386 | GitHub API calls (secrets, vars, workflows) | ❌ BROKEN: uses `from nacl import ...` — a dependency (`PyNaCl`) that was **never installed** and **never added to `pyproject.toml`**. The project already pushes secrets via `gh secret set` (manage.sh line 289). This file reinvents the wheel with raw REST API. |
| `manager.py` | 332 | Orchestrator — coordinates all sync operations | ⚠️ Logic is fine, but designed as an in-process library called from server threads |
| `state.py` | 184 | `MirrorState` — read/write `state/mirror_status.json` | ✅ Fine (clean file-based state) |

### `src/admin/server.py` — Mirror-related code

| Lines | What | Status |
|-------|------|--------|
| 43-53 | Startup: import + instantiate `MirrorManager` | ❌ Remove |
| 78-108 | `_fresh_mirror_manager()` — env swap hack | ❌ Remove entirely |
| 572-576 | Env-save hook: `mm.propagate_secrets()` | ❌ Remove (should be CLI) |
| 1327-1332 | Git-sync hook: `mm.propagate_code_sync()` | ❌ Remove (should be CLI) |
| 1350-1400 | Mirror API endpoints (status, sync, sync/code, sync/secrets) | ❌ Rewrite to subprocess |

### `src/admin/static/index.html` — UI

| Section | Lines (approx) | Status |
|---------|---------------|--------|
| Mirror card HTML | 1351-1360 | ⚠️ OK structure, needs content fix |
| Mirror CSS | 484+ | ✅ Fine |
| `loadMirrorStatus()` | 3161-3264 | ❌ Shows empty when `slaves: []`, no configured mirrors view |
| `mirrorSyncAll/Code/Secrets()` | 3266-3310 | ❌ No proper feedback, button IDs missing |
| Wizard step | 4014-4130 | ✅ Recently rewritten, OK |
| Secrets category | 1988 | ✅ Recently simplified, OK |

### `src/main.py` — CLI commands

**Zero mirror commands exist.** There is no `mirror-status`, `mirror-sync`, or `mirror-setup`.

### `manage.sh` — Management script

**Zero mirror entries.** No menu option, no function.

### `state/mirror_status.json`

Contains data from an **untraceable sync** that ran silently in a background thread when the user clicked "Sync All Now". This execution:
- Had **zero UI feedback** (no toast, no progress, no log)
- Had **zero audit trail** (no ledger entry, no CLI output)
- Ran in a Flask background thread with no observability
- Cannot be trusted or relied upon

Current contents:
- 1 slave: `Eloverflow/continuity-orchestrator-mirror-1`
- Code: pushed `093f7683e987` — but was this the right commit? No way to verify.
- Secrets: ❌ Failed (`No module named 'nacl'`) — see nacl analysis below
- Variables: synced 3/3 — but with what values? No log.
- Workflows: Never attempted

**Action:** Wipe this file. Any future sync must go through the CLI with full output.

### The `nacl` problem — `github_sync.py` reinvents the wheel

The project already pushes secrets to GitHub using `gh secret set` (manage.sh line 289). The `gh` CLI handles encryption internally — no extra libraries needed.

`github_sync.py` was written to sync secrets via the **raw GitHub REST API**, which requires:
1. Fetch the repo's public key via API
2. Encrypt each secret with `libsodium` (`PyNaCl` library)
3. Upload the encrypted blob via API

But `PyNaCl` was **never added to `pyproject.toml`** — so `github_sync.py` was broken from the day it was committed. The `nacl` error wasn't a regression; it was always dead code.

**Fix:** Rewrite secret sync to use `gh secret set` subprocess calls, consistent with the rest of the project. Delete the `nacl` import entirely.

---

## Rectification Plan

### Phase 1: Add CLI commands to `main.py`

Add two new Click commands that do the actual work:

**`mirror-status`** — Read config + state, output JSON or human-readable

```
python -m src.main mirror-status [--json]
```

Output:
```json
{
  "enabled": true,
  "self_role": "MASTER",
  "mirrors": [
    {
      "id": "mirror-1",
      "repo": "Eloverflow/continuity-orchestrator-mirror-1",
      "type": "github",
      "code": {"status": "ok", "last_sync": "2026-02-07T18:01:05Z", "detail": "093f7683e987"},
      "secrets": {"status": "failed", "last_sync": "2026-02-07T18:01:05Z", "error": "..."},
      "variables": {"status": "ok", "last_sync": "2026-02-07T18:01:07Z", "detail": "3/3"},
      "health": "unknown"
    }
  ]
}
```

This merges CONFIG (which mirrors are configured) with STATE (what synced last).

**`mirror-sync`** — Run the sync operations, print progress to stdout

```
python -m src.main mirror-sync [--code-only] [--secrets-only] [--vars-only]
```

Output (human-readable, line by line):
```
[mirror] Syncing 1 mirror(s)...
[mirror-1] Eloverflow/continuity-orchestrator-mirror-1
  📦 Code push... ✅ pushed 093f7683e987
  🔐 Secrets sync... ❌ nacl not available
  📋 Variables sync... ✅ 3/3 synced
[mirror] Done. 1 mirror(s) synced.
```

These commands use `MirrorManager` directly (that's where domain code belongs — in the CLI, not the server).

### Phase 2: Fix `manager.py` — Merge config into status

Fix `get_status()` to include configured mirrors even if they've never been synced:

```python
def get_status(self) -> Dict:
    # Merge configured mirrors + state
    slaves = []
    for mirror in self.settings.mirrors:
        state_slave = self.state.get_slave(mirror.id)
        slave_dict = {
            "id": mirror.id,
            "repo": mirror.repo,
            "type": mirror.type,
            "code": asdict(state_slave.code) if state_slave else {"status": "unknown"},
            "secrets": asdict(state_slave.secrets) if state_slave else {"status": "unknown"},
            "variables": asdict(state_slave.variables) if state_slave else {"status": "unknown"},
            "health": state_slave.health if state_slave else "unknown",
        }
        slaves.append(slave_dict)
    
    return {
        "enabled": self.enabled,
        "self_role": self.state.self_role,
        "mirrors": slaves,
        "last_full_sync_iso": self.state.last_full_sync_iso,
    }
```

This way the status always shows configured mirrors — even before any sync runs.

### Phase 3: Rewrite server.py — CLI subprocess pattern

**Remove:**
- Lines 43-53: Startup MirrorManager init
- Lines 78-108: `_fresh_mirror_manager()` hack
- Lines 572-576: Env-save mirror hook
- Lines 1327-1332: Git-sync mirror hook

**Rewrite mirror endpoints to use subprocess:**

```python
@app.route("/api/mirror/status", methods=["GET"])
def api_mirror_status():
    """Get mirror status via CLI."""
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "mirror-status", "--json"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
            env=_fresh_env(),
        )
        if result.returncode == 0:
            return jsonify(json.loads(result.stdout))
        return jsonify({"enabled": False, "error": result.stderr})
    except Exception as e:
        return jsonify({"enabled": False, "error": str(e)})

@app.route("/api/mirror/sync", methods=["POST"])
def api_mirror_sync():
    """Run mirror sync via CLI."""
    data = request.json or {}
    cmd = ["python", "-m", "src.main", "mirror-sync"]
    if data.get("code_only"):
        cmd.append("--code-only")
    if data.get("secrets_only"):
        cmd.append("--secrets-only")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
            env=_fresh_env(),
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Sync timed out"}), 504
```

**About the hooks (git-sync, env-save):**
These auto-sync behaviors are actually nice but belong in the WORKFLOW, not the server. For now, remove them. The user can manually sync from the UI. Later, the cron workflow can auto-sync.

### Phase 4: Fix the integration card UI

1. **Remove the empty `slaves.length === 0` branch** — with Phase 2 fix, `mirrors[]` always has entries for configured mirrors
2. **Always show the configured mirror repos** with their sync status (✅/❌/⏳)
3. **Fix button IDs** so loading states work
4. **Show sync output** in the card after clicking sync (like other test buttons do)
5. **Show the repo name** prominently
6. **Show the error** for secrets failure (missing nacl)

### Phase 5: Fix `github_sync.py` — Replace `nacl` with `gh` CLI

Rewrite secret sync functions to use `gh secret set` (subprocess) instead of raw API + nacl encryption.

**Remove:**
- `_encrypt_secret()` function (nacl import)
- `get_repo_public_key()` function (only needed for nacl)
- `sync_secret()` function (raw API call)

**Replace with:**
- `sync_secret_gh()` — calls `gh secret set NAME -R owner/repo` via subprocess
- `sync_all_secrets_gh()` — loops over secrets, calls `gh secret set` for each

This matches the existing pattern in manage.sh (line 289) and requires no extra dependencies.

Similarly for variables — check if `gh variable set` can be used instead of raw API.

---

## Execution Order

0. **Phase 0** — Wipe `state/mirror_status.json` (untraceable data, cannot be trusted)
1. **Phase 1** — CLI commands (`main.py`) — this is the foundation
2. **Phase 2** — Fix `get_status()` in `manager.py` — makes status useful
3. **Phase 3** — Rewrite `server.py` mirror code — clean architecture
4. **Phase 4** — Fix integration card UI — visible results
5. **Phase 5** — Fix `github_sync.py` — replace nacl with `gh` CLI

## Files Modified

| File | Action |
|------|--------|
| `src/main.py` | ADD: `mirror-status` and `mirror-sync` commands |
| `src/mirror/manager.py` | FIX: `get_status()` to merge config + state |
| `src/admin/server.py` | REMOVE: all direct mirror imports/logic; REWRITE: endpoints to subprocess |
| `src/admin/static/index.html` | FIX: integration card to show real data and feedback |
| `manage.sh` | ADD: mirror menu entry (optional, low priority) |
