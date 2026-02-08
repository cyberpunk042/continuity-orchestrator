---
description: Evolve Factory Reset with content cleanup, git history purge, and mirror cascade protection
status: PLANNING
created: 2026-02-08
---

# Evolved Factory Reset + Mirror Cascade Protection

## What This Is

Three features, all rooted in the **existing Factory Reset** flow in the Debugging tab:

1. **Content cleanup** — option in the factory reset modal to also wipe articles + media
2. **Git history purge** — option to remove media blobs from git history after content cleanup
3. **Mirror cascade protection** — feature toggle (`MIRROR_PROPAGATE_RESET`) in Secrets/Vars
   tier + Wizard mirror config, preventing factory reset from cascading to the slave

---

## Current State — What Already Exists

### Debugging tab (`partials/_tab_debugging.html`, lines 91-101)
```
State Controls card:
  🔄 Reset Timer → resetState() → POST /api/state/reset
  🗑️ Factory Reset → factoryReset() → POST /api/state/factory-reset
```

### Factory Reset flow
```
UI button (Debugging tab)
  → confirm() dialog (plain JS alert)
  → POST /api/state/factory-reset { backup: true, hours: 48 }
  → routes_core.py: subprocess → `python -m src.main reset --full -y --hours 48 --backup`
  → cli/core.py reset():
      1. Backs up state/current.json + audit/ledger.ndjson
      2. Creates fresh state (OK, new deadline)
      3. Clears audit log (single factory_reset entry)
  → UI shows alert(✅), calls loadStatus()
```

### What factory reset does NOT touch (today)
- `content/articles/*.json` (7 files)
- `content/media/*.enc` (4 files, ~950KB)
- `content/manifest.yaml`
- `content/media/manifest.json`
- Git history
- Mirror (no sync triggered)

### Mirror cascade path (today — implicit)
```
Factory reset (local) → changes state/current.json + audit/
  → User clicks "Git Sync" (or auto-sync on next cron tick)
  → git push to origin
  → cron.yml mirror-sync step: git push --force mirror-1 main
  → Slave gets the reset state
No protection. No toggle. No warning.
```

---

## Feature 1: Evolved Factory Reset Modal

### What changes

**Today:** A simple `confirm()` dialog with hardcoded text, then API call.

**After:** A proper HTML modal in the Debugging tab (like the vault lock modal pattern) with:

```
┌─────────────────────────────────────────────┐
│  ⚠️  Factory Reset                          │
│                                              │
│  This will:                                  │
│  • Create fresh state file                   │
│  • Clear audit log                           │
│  • Reset to OK stage                         │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ ⏱ Deadline hours         [ 48    ▾]   │  │
│  │ 💾 Backup existing state  [✓]         │  │
│  │ 📝 Also wipe content     [ ]          │  │
│  │   └ Delete all articles               │  │
│  │   └ Delete all media (N files, X MB)  │  │
│  │   └ Reset manifests                   │  │
│  │ 🧹 Purge media from git history [ ]   │  │
│  │   └ Requires git-filter-repo          │  │
│  │   └ Rewrites commit hashes            │  │
│  │   └ Requires force-push after         │  │
│  └────────────────────────────────────────┘  │
│                                              │
│           [ Cancel ]  [ 🗑️ Reset ]           │
└─────────────────────────────────────────────┘
```

**The modal shows NOTHING about the mirror.** No mention, no status, no variable name.
The cascade protection works silently in the backend. If an attacker gains access to
the admin panel, they should have zero indication that a mirror exists or that their
factory reset won't propagate. They trigger the reset, see success, and walk away —
not knowing the mirror is untouched.

### Files touched

| File | What changes |
|------|-------------|
| `partials/_tab_debugging.html` | Add modal HTML (hidden by default) |
| `scripts/_wizard.html` | Evolve `factoryReset()` to open modal instead of `confirm()` |
| `src/cli/core.py` | Add `--include-content` and `--purge-history` flags to `reset` command |
| `src/admin/routes_core.py` | Pass new flags to subprocess |

### CLI evolution

```
python -m src.main reset --full -y --hours 48 --backup [--include-content] [--purge-history]
```

New flags:
- `--include-content`: After state reset, also delete all articles + media + reset manifests
- `--purge-history`: After content cleanup, run `git filter-repo` to purge media blobs from history
  (requires `--include-content`, errors if git-filter-repo not installed)

### Content cleanup logic (inside `reset` command, when `--include-content`)

```python
# Wipe articles
articles_dir = root / "content" / "articles"
deleted_articles = 0
for f in articles_dir.glob("*.json"):
    f.unlink()
    deleted_articles += 1

# Wipe media
media_dir = root / "content" / "media"
deleted_media = 0
freed_bytes = 0
for f in media_dir.glob("*.enc"):
    freed_bytes += f.stat().st_size
    f.unlink()
    deleted_media += 1

# Reset media manifest
media_manifest = media_dir / "manifest.json"
media_manifest.write_text(json.dumps({"version": 1, "media": []}, indent=2))

# Reset content manifest (keep stage definitions, remove article entries)
manifest_path = root / "content" / "manifest.yaml"
import yaml
manifest = yaml.safe_load(manifest_path.read_text())
manifest["articles"] = []
manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))

click.echo(f"  Deleted {deleted_articles} article(s)")
click.echo(f"  Deleted {deleted_media} media file(s) ({freed_bytes / 1024:.0f} KB)")
click.echo(f"  Reset manifests")
```

### Git history purge logic (when `--purge-history`)

```python
# Check prerequisites
import shutil
if not shutil.which("git-filter-repo"):
    raise click.ClickException(
        "git-filter-repo is not installed.\n"
        "Install with: pip install git-filter-repo"
    )

# Check for clean working tree
result = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=str(root), capture_output=True, text=True
)
if result.stdout.strip():
    raise click.ClickException(
        "Working tree is dirty. Commit or stash changes first."
    )

# Run filter-repo to purge content/media/ from all history
click.echo("  Purging media from git history...")
result = subprocess.run(
    ["git", "filter-repo", "--invert-paths", "--path", "content/media/", "--force"],
    cwd=str(root), capture_output=True, text=True, timeout=120
)
if result.returncode != 0:
    raise click.ClickException(f"git filter-repo failed: {result.stderr}")

click.secho("  ✅ History rewritten", fg="green")
click.secho("  ⚠️  You must now force-push: git push --force origin main", fg="yellow")
```

### API evolution (`routes_core.py`)

```python
@core_bp.route("/api/state/factory-reset", methods=["POST"])
def api_factory_reset():
    """Full factory reset (calls CLI: reset --full)."""
    project_root = _project_root()
    data = request.json or {}
    backup = data.get("backup", True)
    hours = data.get("hours", 48)
    include_content = data.get("include_content", False)
    purge_history = data.get("purge_history", False)

    cmd = ["python", "-m", "src.main", "reset", "--full", "-y", "--hours", str(hours)]
    if backup:
        cmd.append("--backup")
    else:
        cmd.append("--no-backup")
    if include_content:
        cmd.append("--include-content")
    if purge_history:
        cmd.append("--purge-history")

    try:
        result = subprocess.run(
            cmd, cwd=str(project_root),
            capture_output=True, text=True,
            timeout=120 if purge_history else 30,  # History purge may take longer
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

---

## Feature 2: Mirror Cascade Protection Toggle

### The variable

| Name | Tier | Default | Purpose |
|------|------|---------|---------|
| `MIRROR_PROPAGATE_RESET` | `GITHUB_VARS` | `false` | Whether factory reset cascades to mirror on next sync |

**Why `GITHUB_VARS` and not `LOCAL_ONLY`?**
Because the pipeline (cron.yml) needs to know this value when it runs `mirror-sync`.
If it were LOCAL_ONLY, the pipeline would never see it and always cascade.

Wait — actually let me reconsider. The cascade happens via `git push`. The cron tick
does `git add state/ audit/ && git commit && git push` to origin, then separately
runs `mirror-sync` which does `git push --force mirror-1 main`.

The protection gate needs to be at the `mirror-sync` code push level:
- If `MIRROR_PROPAGATE_RESET=false` and a factory reset happened recently → skip code push
- The "recently" detection: check if the audit log's latest entry is `factory_reset`

**BUT**: this is fragile — any commit after the reset would clear the signal.
A simpler approach: the gate isn't about detecting resets automatically. Instead:

**The protection works by:**
1. Factory reset runs locally
2. Next `git push` to origin happens normally (state goes to GitHub)
3. `mirror-sync` runs (in cron.yml or locally)
4. Before code push, check `MIRROR_PROPAGATE_RESET`:
   - If `true`: push normally (cascade)
   - If `false`: skip the code push entirely — log a warning
   - Secrets + variables still sync (those don't carry state data)

**This means:** When `MIRROR_PROPAGATE_RESET=false`, the mirror NEVER gets code pushes
from `mirror-sync`. It only gets secrets and variables. This is a clean gate — no fragile
"detect if reset happened" logic. The operator chooses: either the mirror is a full
real-time clone (propagate=true), or it's an independent checkpoint that only gets
credential updates (propagate=false).

**Actually, that would break normal code sync too.** The point is to block ONLY destructive
state changes, not all code pushes. Bug fixes and new features should still sync.

**Revised approach — two modes for the mirror:**

The toggle should be named more precisely:

| Name | Value | Behavior |
|------|-------|----------|
| `MIRROR_RESET_MODE` | `cascade` | Factory reset cascades to mirror (full clone behavior) |
| `MIRROR_RESET_MODE` | `isolated` | Factory reset does NOT cascade. Mirror keeps own state. |

**How `isolated` works in practice:**
- Normal code sync: still pushes everything (code, content, etc.)
- BUT: the reset CLI, when `MIRROR_RESET_MODE=isolated`, skips the next mirror-sync
  by creating a signal file `state/.mirror_skip_next_sync`
- The mirror-sync code checks for this file:
  - If present: skip code push, delete the file, log warning
  - If not: push normally
- This means exactly ONE sync is skipped after a factory reset
- Subsequent syncs (code changes, features, etc.) push normally

**Even simpler:** Instead of the signal file, just add the guard directly in the
factory reset CLI:

```python
# After factory reset, if mirror protection is on, skip the auto-git-sync
if include_mirror_skip:
    click.echo("  🛡 Mirror protection: next sync will skip code push")
    (root / "state" / ".skip_mirror_code_push").touch()
```

And in `push_to_mirror()` in `git_sync.py`:
```python
skip_file = project_root / "state" / ".skip_mirror_code_push"
if skip_file.exists():
    logger.warning("[mirror-git] Skipping code push (factory reset protection)")
    skip_file.unlink()
    return True, None, "skipped (factory reset protection)"
```

This is:
- Simple
- One-shot (skip exactly one sync, then resume normal)
- No env var needed at runtime — the signal is a file
- The toggle in Secrets/Wizard controls whether the CLI writes this file

### Where the toggle lives

**Tier:** `GITHUB_VARS` — so cron.yml can read it.

**Secrets tab (`_secrets.html`):**
```javascript
const GITHUB_VARS = ['ADAPTER_MOCK_MODE', 'ARCHIVE_ENABLED', 'ARCHIVE_URL',
                     'MIRROR_ENABLED', 'MIRROR_1_REPO', 'MIRROR_RESET_MODE'];
```

**Wizard mirror step (`_wizard.html`):**
Add below the renewal token section, inside `mirror-config-group`:

```html
<div style="background: var(--bg-input); border: 1px solid var(--border); border-radius: 10px;
            padding: 1.25rem; margin-top: 1.25rem;">
    <div style="font-weight: 600; margin-bottom: 0.75rem; font-size: 0.9rem;">
        🛡 Reset Protection
    </div>
    <p style="color: var(--text-dim); font-size: 0.85rem; line-height: 1.6; margin-bottom: 0.75rem;">
        Controls what happens when a Factory Reset is triggered on the master.
    </p>
    <div class="form-group" style="margin-bottom: 0;">
        <select class="form-input" id="wiz-mirror-reset-mode" style="width: auto; min-width: 200px;">
            <option value="isolated" ${resetMode !== 'cascade' ? 'selected' : ''}>
                🛡 Isolated — reset does NOT cascade (recommended)
            </option>
            <option value="cascade" ${resetMode === 'cascade' ? 'selected' : ''}>
                🔄 Cascade — reset propagates to mirror
            </option>
        </select>
        <div class="form-hint">
            <strong>Isolated (default):</strong> Factory reset only affects the master. The mirror
            keeps its own state as a safety checkpoint. An attacker with admin access cannot
            destroy both copies.<br>
            <strong>Cascade:</strong> The mirror always stays in perfect sync with the master,
            including resets. Simpler, but both copies are equally vulnerable.
        </div>
    </div>
</div>
```

**Wizard collect:**
```javascript
result.MIRROR_RESET_MODE = document.getElementById('wiz-mirror-reset-mode').value;
```

### SYNCABLE_VARS (`github_sync.py`)

Add to the existing list:
```python
SYNCABLE_VARS = [
    "MASTER_REPO",
    "MIRROR_ROLE",
    "SENTINEL_THRESHOLD",
    "ADAPTER_MOCK_MODE",
    "ARCHIVE_ENABLED",
    "ARCHIVE_URL",
    "MIRROR_RESET_MODE",
]
```

### Pipeline (`cron.yml`)

In the mirror-sync step's env block, add:
```yaml
MIRROR_RESET_MODE: ${{ vars.MIRROR_RESET_MODE }}
```

### CLI integration (`cli/core.py`)

In the `reset` command, after the factory reset logic:
```python
# Mirror protection: if isolated mode, create skip signal
mirror_reset_mode = os.environ.get("MIRROR_RESET_MODE", "isolated")
skip_file = root / "state" / ".skip_mirror_code_push"
if full and mirror_reset_mode == "isolated":
    skip_file.touch()
    click.echo("  🛡 Mirror protection: code push to mirror will be skipped once")
elif skip_file.exists():
    # Clean up stale signal if mode changed to cascade
    skip_file.unlink()
```

### git_sync.py guard

In `push_to_mirror()`:
```python
def push_to_mirror(mirror, project_root, branch="main", force=False):
    # Check for factory reset skip signal
    skip_file = project_root / "state" / ".skip_mirror_code_push"
    if skip_file.exists():
        logger.warning(
            "[mirror-git] Skipping code push to %s (factory reset protection)",
            mirror.display_name,
        )
        try:
            skip_file.unlink()
        except Exception:
            pass
        return True, None, None  # Report success but skip

    # ... rest of existing push logic ...
```

---

## Feature 3: Content Info in the Modal (dynamic)

The modal needs to show actual counts before the user confirms. This requires
fetching content stats first.

### New API endpoint — `GET /api/content/stats`

**File:** `src/admin/routes_content.py`

```python
@content_bp.route("/api/content/stats", methods=["GET"])
def api_content_stats():
    """Return article and media counts for the reset modal."""
    articles_dir = _articles_dir()
    media_dir = _project_root() / "content" / "media"

    articles = list(articles_dir.glob("*.json")) if articles_dir.exists() else []
    media_files = list(media_dir.glob("*.enc")) if media_dir.exists() else []
    media_bytes = sum(f.stat().st_size for f in media_files)

    # Check git history for media objects
    import subprocess
    git_objects = 0
    try:
        result = subprocess.run(
            ["git", "rev-list", "--objects", "--all", "--", "content/media/"],
            cwd=str(_project_root()), capture_output=True, text=True, timeout=10
        )
        git_objects = len([l for l in result.stdout.strip().split("\n") if l.strip()])
    except Exception:
        pass

    # Check if git-filter-repo is available
    import shutil
    filter_repo_available = shutil.which("git-filter-repo") is not None

    return jsonify({
        "article_count": len(articles),
        "article_slugs": [f.stem for f in articles],
        "media_count": len(media_files),
        "media_bytes": media_bytes,
        "git_media_objects": git_objects,
        "filter_repo_available": filter_repo_available,
    })
```

### Modal JS logic

When the user clicks "Factory Reset", the function:
1. Fetches `/api/content/stats` to get live numbers (article count, media count, sizes)
2. Populates the modal checkboxes and stats
3. Shows the modal

**NO mirror information is shown.** The modal is purely about the local reset options.
The mirror protection happens silently on the backend — the `reset` CLI writes the
skip signal file if `MIRROR_RESET_MODE=isolated`, and `push_to_mirror` checks it later.
The UI never reveals this mechanism.

On submit:
1. Gathers options from the modal (backup, hours, include_content, purge_history)
2. Calls `POST /api/state/factory-reset` with the full payload
3. On success: refresh UI, show results

---

## Implementation Order

### Step 1: Backend — CLI evolution
- **`src/cli/core.py`**: Add `--include-content` and `--purge-history` to `reset`
- **`src/admin/routes_core.py`**: Pass new flags to subprocess
- **`src/admin/routes_content.py`**: Add `GET /api/content/stats`
- **`src/main.py`**: No changes needed (reset command already registered)

### Step 2: Mirror protection plumbing
- **`src/mirror/git_sync.py`**: Add skip signal check in `push_to_mirror`
- **`src/cli/core.py`**: Write skip signal when `MIRROR_RESET_MODE=isolated`
- **`src/mirror/github_sync.py`**: Add `MIRROR_RESET_MODE` to `SYNCABLE_VARS`
- **`.github/workflows/cron.yml`**: Inject `MIRROR_RESET_MODE` in mirror-sync env

### Step 3: UI — Secrets/Wizard tier
- **`scripts/_secrets.html`**: Add `MIRROR_RESET_MODE` to `GITHUB_VARS`
- **`scripts/_wizard.html`**: Add reset protection toggle in mirror step

### Step 4: UI — Factory Reset modal
- **`partials/_tab_debugging.html`**: Add modal HTML
- **`scripts/_wizard.html`**: Replace `factoryReset()` confirm dialog with modal logic

### Step 5: Verify full flow
- Factory reset with content cleanup
- Factory reset with history purge
- Factory reset with mirror in isolated mode → verify mirror keeps old state
- Factory reset with mirror in cascade mode → verify mirror gets reset

---

## Complete File Inventory

### Modified files
| File | Change |
|------|--------|
| `src/cli/core.py` | `--include-content`, `--purge-history` flags + mirror skip signal |
| `src/admin/routes_core.py` | Pass new flags to subprocess, longer timeout for purge |
| `src/admin/routes_content.py` | `GET /api/content/stats` endpoint |
| `src/mirror/git_sync.py` | Skip signal check in `push_to_mirror` |
| `src/mirror/github_sync.py` | `MIRROR_RESET_MODE` in `SYNCABLE_VARS` |
| `src/admin/templates/partials/_tab_debugging.html` | Factory reset modal HTML |
| `src/admin/templates/scripts/_wizard.html` | `factoryReset()` modal logic, mirror wizard toggle |
| `src/admin/templates/scripts/_secrets.html` | `MIRROR_RESET_MODE` in `GITHUB_VARS` |
| `.github/workflows/cron.yml` | `MIRROR_RESET_MODE` injection |

### NOT touched
| File | Why |
|------|-----|
| `src/main.py` | `reset` command already registered |
| `src/admin/server.py` | `content_bp` already registered |
| `src/admin/templates/partials/_tab_content.html` | Content tab is for authoring, not resetting |
| `src/admin/templates/scripts/_content.html` | Not related to reset |
| `src/mirror/config.py` | `MIRROR_RESET_MODE` is read from env at CLI level, not config dataclass |
| `sentinel.yml` | Sentinel watches heartbeat, doesn't care about reset mode |

### .gitignore addition
```
state/.skip_mirror_code_push
```

---

## Security Notes

1. **Skip signal file (`state/.skip_mirror_code_push`)**
   - Created by factory reset CLI when `MIRROR_RESET_MODE=isolated`
   - Consumed (deleted) by `push_to_mirror` on next sync
   - One-shot: skips exactly one mirror code push, then resumes normal
   - If attacker deletes the file before sync: cascade happens. But they'd need FS access.
   - If attacker creates the file without a reset: one sync is skipped, mirror falls behind
     by one tick. Sentinel would detect staleness. Low impact.

2. **`MIRROR_RESET_MODE` in GITHUB_VARS**
   - Visible in GitHub repo settings (not encrypted like secrets)
   - An attacker with GitHub access could flip it to `cascade` AND trigger a reset
   - But they'd need BOTH admin panel access AND GitHub access. Defense in depth.

3. **Content cleanup is irreversible** (unless backup is taken)
   - The modal makes backup default ON
   - Articles are backed up alongside state

4. **Git history purge is destructive**
   - Rewrites commit hashes
   - Requires force-push
   - Modal clearly warns about this
   - The checkbox is disabled unless `--include-content` is also checked
   - Shows whether `git-filter-repo` is installed
