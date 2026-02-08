# Task C+D: Deploy Mode Awareness — Full System Analysis

## The Demand

"Total awareness of GitHub Pages when in GitHub Pages,
and Docker when in Docker."

Not just a label — the admin panel must **operate** differently depending
on mode. Real buttons. Real actions. No "copy this command."

---

## Current State: Complete Audit

### 1. The Two Worlds

| Aspect | GitHub Pages Mode | Docker Mode |
|--------|------------------|-------------|
| **Who runs ticks** | `cron.yml` (Actions, every 30min) | Docker container loop (configurable) |
| **Who builds the site** | Actions → `upload-pages-artifact` | Container → writes to `/data/public` volume |
| **Who serves the site** | GitHub Pages CDN | nginx container (port 8080) + optional Cloudflare tunnel |
| **Where state lives** | In the Git repo (committed by Actions) | In Docker volume (synced to Git by git-sync) |
| **Where secrets live** | GitHub Secrets/Variables + `.env` locally | `.env` only (read by container) |
| **Secret push** | `gh` CLI → GitHub API | Just `.env` (gh push optional) |
| **Git sync** | Actions commits after tick | `docker_git_sync.py` background loop |
| **Mirror sync** | Actions step in `cron.yml` | Would need to be in the tick loop (not there yet) |
| **Archive** | Archives `{owner}.github.io/{repo}` URL | Archives tunnel URL or custom domain |
| **Restart** | N/A — Actions runs fresh each time | **Needed** — container must restart for env changes |
| **Deploy trigger** | `gh workflow run deploy-site.yml` (already exists as `apiRun('deploy-site')`) | Nginx serves volume automatically; `docker compose restart` or `docker compose up -d` |

---

### 2. What the Admin Panel Can Control (Tools Available)

The admin panel runs **locally** (Flask via `manage.sh web`), not inside
Docker. So it has access to:

- ✅ `docker` CLI — already checked in `system_status.py` (line 415)
- ✅ `docker compose ps` — can query container status
- ✅ `docker compose restart` — can restart services
- ✅ `docker compose logs` — can fetch container logs
- ✅ `docker compose up -d --profile X` — can start services
- ✅ `gh` CLI — can trigger workflows, check Pages status
- ✅ `.env` — can read/write directly
- ✅ `envData` — already loaded on every tab switch

**Key insight**: The admin panel is NOT inside the container. It's the
local operator's tool. So it CAN manage Docker containers the same way
it manages Git (via subprocess calls).

---

### 3. Every UI Surface — What Needs to Change

#### 📊 Dashboard (`_dashboard.html`)

**Current**: Shows System State, Adapters, Tools, Secrets, Health, Quick Actions.
No mode awareness at all.

**Changes needed**:

| Element | Change |
|---------|--------|
| Subtitle | "Local Admin Console" → show mode badge: 🌐 GitHub Pages / 🐳 Docker |
| Mode row (L110) | Currently shows Mock/Live. Add deploy mode below it |
| Quick Actions | **GitHub Pages**: Add "🚀 Deploy to Pages" button (already exists as `deploy-site` command but hidden in Command Center) |
| Quick Actions | **Docker**: Add "🔄 Restart Containers" button |

#### 🧙 Wizard (`_wizard.html`)

**Critical bug**: Line 2198 `delete secrets.DEPLOY_MODE` throws away the
user's choice. Must fix.

**Mode-conditional step content** (4 steps):

| Step | GitHub Pages | Docker |
|------|-------------|--------|
| `archive` (10) | Hint: "Leave empty for GitHub Pages auto-detect" | Hint: "Enter your site URL (tunnel or custom domain)" |
| `mirror` (11) | "Mirror sync runs automatically via Actions" | "Mirror sync runs during each Docker tick" |
| `push` (12) | Full `gh` CLI push flow | Downplay `gh` — "Secrets saved to .env. Docker reads them directly. gh push is optional for backup." |
| `complete` (13) | "Check the Dashboard, run a Dry Run" | "Start your containers: [▶️ Start Docker] button. Optionally enable tunnel." |

**The `complete` step must have real buttons**:
- Docker mode: [▶️ Start Containers] → calls new API endpoint
- Docker mode + tunnel token provided: [▶️ Start with Tunnel] → starts with `--profile tunnel`

#### 🔐 Secrets (`_secrets.html`)

**Current**: Docker/Tunnel category defaults to collapsed.

**Change**: When `DEPLOY_MODE === 'docker'`, default it to expanded.
When `github-pages`, keep collapsed. Read from `envData['DEPLOY_MODE']`.

#### ⚡ Command Center (`_tab_commands.html`)

**Current**: Engine, Status, Preview, Build, Test, Recovery cards.

**Changes needed**:

| Card | GitHub Pages | Docker |
|------|-------------|--------|
| Build card | "Build Static Site" (local preview) | Same button, but also: "This updates the live site served by nginx" |
| **New: Deploy card** | [🚀 Deploy to Pages] — triggers `gh workflow run` | [🔄 Restart Containers] [📋 View Logs] [⏹ Stop] |

The Deploy card in Command Center is mode-aware:
- **GitHub Pages**: "Deploy to Pages" (calls existing `deploy-site` command) + "Trigger Tick" (calls `gh workflow run cron.yml`)
- **Docker**: Container management buttons with real API calls

#### 🔌 Integrations (`_tab_integrations.html` + `_integrations.html`)

**Currently**: Cards for Repo Mirror, Email, SMS, X, Reddit.

**Add: 🚀 Deployment card** — positioned first, mode-aware.

**GitHub Pages mode card:**
```
🚀 Deployment                               🌐 GitHub Pages
┌──────────────────────────────────────────────────────────┐
│ Pages URL: https://{owner}.github.io/{repo}    [🔗 Open] │
│ Status: ✅ Active / ❓ Unknown                            │
│ Cron: Every 30 min via Actions                           │
│ Last deploy: 2h ago (via gh CLI query)                   │
│                                                          │
│ [🚀 Deploy Now]  [🔄 Trigger Tick]  [⚡ View Actions →]  │
│                                                          │
│ 💡 To disable auto-deploys: disable cron.yml in Actions  │
└──────────────────────────────────────────────────────────┘
```

**Action flow — Git sync FIRST, then deploy:**

Every deploy/restart action must push local changes to Git **before**
triggering the actual deploy. Otherwise Actions builds stale code, or
Docker git-sync pulls old data on restart.

The pattern follows what the Command Center already does with
`runCmdWithSync()` — but in reverse order: **sync → then act**.

```
User clicks [🚀 Deploy Now]:
  1. 🔄 Git sync (commit + push local changes)    ← /api/git/sync
  2. ⏳ Wait for sync to complete
  3. 🚀 Trigger deploy-site workflow               ← apiRun('deploy-site')
  4. ✅ Show result

User clicks [🔄 Trigger Tick]:
  1. 🔄 Git sync first
  2. ⚡ gh workflow run cron.yml                    ← apiRun('trigger-cron')
  3. ✅ Show result
```

Buttons:
- **Deploy Now** → git sync → `apiRun('deploy-site')` (already exists)
- **Trigger Tick** → git sync → new: `gh workflow run cron.yml`
- **View Actions** → link to `github.com/{repo}/actions` (no sync needed)
- ☐ **Auto git-sync** checkbox (checked by default, same pattern as Command Center)

**Docker mode card:**
```
🚀 Deployment                               🐳 Docker
┌──────────────────────────────────────────────────────────┐
│ Containers:                                              │
│   ✅ continuity-git-sync    Running (2h 15m)             │
│   ✅ continuity-nginx       Running (2h 15m)             │
│   ❌ continuity-tunnel      Not running                  │
│                                                          │
│ Git Sync: Non-alpha · Tick 15m · Sync 30s                │
│ Serving:  nginx :8080                                    │
│ Tunnel:   Not configured                                 │
│                                                          │
│ ☑ Auto git-sync before restart                           │
│ [🔄 Restart]  [📋 Logs]  [⏹ Stop]                       │
│                                                          │
│ ⚡ Tunnel:                                               │
│   [▶️ Start Tunnel]  (requires CLOUDFLARE_TUNNEL_TOKEN)  │
│                                                          │
│ ⚠️ Restart needed — 2 secrets changed since last start   │
│   Changed: RESEND_API_KEY, OPERATOR_EMAIL                │
│   [🔄 Apply Changes (Restart)]                           │
└──────────────────────────────────────────────────────────┘
```

**Action flow — Docker restart also syncs first:**

```
User clicks [🔄 Restart] (with auto-sync checked):
  1. 🔄 Git sync (push .env changes, state, etc.)  ← /api/git/sync
  2. ⏳ Wait for sync to complete
  3. 🐳 docker compose --profile git-sync restart   ← /api/docker/restart
  4. ✅ The git-sync container pulls latest on restart
  5. 📊 Refresh container status

User clicks [🔄 Apply Changes (Restart)]:
  Same flow — sync → restart → clear the "changed secrets" warning
```

Buttons (all real API calls, all git-sync-first):
- **Restart** → git sync → `docker compose --profile git-sync restart`
- **Logs** → `docker compose logs --tail 100` (no sync needed)
- **Stop** → `docker compose --profile git-sync down` (no sync needed)
- **Start Tunnel** → `docker compose --profile tunnel up -d`
- **Apply Changes (Restart)** → git sync → restart → clear env diff

**Restart awareness** (Task D): 
- On page load, snapshot `envData` into `window._envSnapshot`
- On every secret save (`pushSecrets`), compare new values to snapshot
- If keys differ → compute diff → show warning in Deployment card
- **No new API endpoint needed for tracking** — pure frontend diff
- The "Apply Changes" button syncs + restarts + clears the warning

#### 🐛 Debugging (`_tab_debugging.html`)

**Current**: Archive card says "Custom URL (or leave empty for GitHub Pages)"

**Changes**:
- Archive card placeholder: mode-aware text
  - GitHub Pages: "Custom URL (or leave empty for auto-detect)"
  - Docker: "Enter your site URL (e.g. your-tunnel.example.com)"
- Pre-fill archive URL field if `envData['ARCHIVE_URL']` is set

#### 🔗 Nav bar (`_nav.html`)

**Current**: 🔗 dropdown has Pages link and Actions link. Both
go to GitHub URLs.

**Changes**:
- **GitHub Pages**: Pages link → `https://{owner}.github.io/{repo}`
- **Docker**: Pages link → `http://localhost:8080` (or tunnel URL from env)
- **Docker + tunnel**: Pages link → tunnel URL
- Actions link: relevant in both modes (repo still has Actions)

---

### 4. Docker Compose Profile Map (Critical Detail)

Every `docker compose` command must include the **right profiles** or
profiled services will be silently ignored.

```
docker-compose.yml services:

SERVICE                     CONTAINER NAME           PROFILE       PURPOSE
─────────────────────────── ──────────────────────── ───────────── ──────────────────────
volume-init                 continuity-volume-init   (none)        Init: creates dirs
orchestrator                continuity-orchestrator  (none)        Standalone tick (no git)
orchestrator-git-sync       continuity-git-sync      git-sync      Tick + git sync (production)
nginx                       continuity-nginx         (none)        Static site server (:8080)
site-builder                continuity-site-builder  tools         One-shot build
health-check                continuity-health        tools         One-shot health
cloudflared                 continuity-tunnel        tunnel        Cloudflare tunnel
```

**Typical launch commands:**
- Standalone (test):     `docker compose up -d`
- Production (git-sync): `docker compose --profile git-sync up -d`
- With tunnel:           `docker compose --profile git-sync --profile tunnel up -d`

**The gotcha**: `docker compose restart` without `--profile git-sync`
will NOT restart `orchestrator-git-sync`. Same for stop, down, logs.
The API must **detect active profiles from running containers** and
include them in every command.

---

### 5. New Backend: API Endpoints (`routes_docker.py`)

All endpoints are profile-aware. The core helper:

```python
def _detect_active_profiles() -> list[str]:
    """
    Detect which profiles are active by checking running containers.
    
    Logic:
    - If 'continuity-git-sync' is running → 'git-sync' profile active
    - If 'continuity-tunnel' is running → 'tunnel' profile active
    - If neither profiled service runs → no profiles (standalone mode)
    
    Returns list of profile flags: ['--profile', 'git-sync', '--profile', 'tunnel']
    """
    profiles = []
    # docker compose ps --format json includes all running containers
    # Check container names to infer active profiles
    running = _get_running_containers()  # calls docker compose ps
    names = {c['name'] for c in running}
    
    if 'continuity-git-sync' in names:
        profiles.extend(['--profile', 'git-sync'])
    if 'continuity-tunnel' in names:
        profiles.extend(['--profile', 'tunnel'])
    
    return profiles

def _compose_cmd(*args, profiles=None):
    """
    Build a docker compose command with correct profiles.
    
    If profiles is None, auto-detect from running containers.
    If profiles is explicit (e.g. for start), use those.
    """
    cmd = ['docker', 'compose']
    if profiles is None:
        profiles = _detect_active_profiles()
    cmd.extend(profiles)
    cmd.extend(args)
    return cmd
```

#### `GET /api/docker/status`

Returns container status for all known Continuity services.
The status endpoint DOES pass all profiles so `ps` shows everything:

```python
# Calls: docker compose --profile git-sync --profile tunnel --profile tools ps --format json
# (pass ALL profiles to see everything, even stopped services)
{
    "available": true,              # docker CLI found
    "compose_file": true,           # docker-compose.yml exists in project root
    "active_profiles": ["git-sync"],  # detected from running containers
    "containers": [
        {
            "name": "continuity-git-sync",
            "service": "orchestrator-git-sync",
            "status": "running",
            "state": "Up 2 hours",
            "profile": "git-sync"
        },
        {
            "name": "continuity-nginx",
            "service": "nginx",
            "status": "running",
            "state": "Up 2 hours",
            "profile": null
        },
        {
            "name": "continuity-tunnel",
            "service": "cloudflared",
            "status": "not_found",
            "state": null,
            "profile": "tunnel"
        }
    ],
    "git_sync_config": {
        "alpha": false,
        "tick_interval": 900,
        "sync_interval": 30
    }
}
```

#### `POST /api/docker/restart`

Restarts services using **auto-detected profiles**:
```python
# Auto-detects: git-sync is running → includes --profile git-sync
# Calls: docker compose --profile git-sync restart
# If tunnel also running: docker compose --profile git-sync --profile tunnel restart
```

#### `POST /api/docker/start`

Starts services with **explicitly specified profiles** (user chooses):
```python
# Body: { "profiles": ["git-sync"] }
#   or: { "profiles": ["git-sync", "tunnel"] }
#
# Calls: docker compose --profile git-sync up -d
#   or:  docker compose --profile git-sync --profile tunnel up -d
#
# If no profiles specified: docker compose up -d (standalone mode)
```

#### `POST /api/docker/stop`

Stops services using **auto-detected profiles** (same as restart):
```python
# Auto-detects active profiles, then:
# Calls: docker compose --profile git-sync down
# (includes tunnel profile too if active)
```

#### `GET /api/docker/logs`

Returns recent container logs for a specific service:
```python
# Query params: ?service=orchestrator-git-sync&lines=50
# Auto-detects profiles, then:
# Calls: docker compose --profile git-sync logs --tail 50 orchestrator-git-sync
{
    "output": "...",
    "service": "orchestrator-git-sync",
    "lines": 50
}
```

#### `POST /api/deploy/trigger` (GitHub Pages mode)

Triggers GitHub Actions workflows:
```python
# Body: { "workflow": "deploy-site" }  or { "workflow": "cron" }
# Calls: gh workflow run deploy-site.yml  or  gh workflow run cron.yml
```

Note: `deploy-site` already exists in `routes_core.py` allowed_commands (line 90).
Need to add `trigger-cron` → `gh workflow run cron.yml`.

#### `GET /api/deploy/pages-status` (GitHub Pages mode)

Checks if Pages site is reachable:
```python
# Derives URL from GITHUB_REPOSITORY env var:
#   owner/repo → https://owner.github.io/repo
# Or uses ARCHIVE_URL if set
# Makes HTTP HEAD request, returns:
{
    "url": "https://owner.github.io/repo",
    "reachable": true,
    "status_code": 200
}
```

---

### 6. Backend: `deploy_mode` in SystemStatus

Add to the API response so frontend doesn't need to parse `.env` separately:

```python
# In SystemStatus dataclass:
deploy_mode: str = "github-pages"

# In get_system_status():
deploy_mode = env_values.get("DEPLOY_MODE", "github-pages")

# In to_dict() → config section:
"deploy_mode": self.deploy_mode,
```

---

### 7. Pipeline Impact

**No changes to GitHub Actions workflows.**

The workflows only run in Actions. In Docker mode they don't trigger.
The admin panel can trigger them manually via `gh workflow run` if the
user wants to (e.g., to deploy Pages alongside Docker for redundancy).

If someone runs Docker mode with Actions still enabled, both would run
ticks. The Deployment card could show an info notice:
"💡 Actions cron is still enabled. If you only want Docker ticks,
disable cron.yml in GitHub → Actions → Workflows."

But this is informational, not blocking.

---

## Implementation Plan

### Phase 1: Foundation

1. **Fix DEPLOY_MODE persistence** — remove `delete secrets.DEPLOY_MODE`
2. **Add deploy_mode to SystemStatus** — dataclass + to_dict + get_system_status
3. **Create `routes_docker.py`** — new API endpoints for container management

### Phase 2: Deployment Card (centerpiece)

4. **Add card HTML** to `_tab_integrations.html`
5. **Add `loadDeployStatus()`** to `_integrations.html`:
   - Reads `appData.config.deploy_mode`
   - GitHub Pages: calls `/api/deploy/pages-status`, shows deploy button
   - Docker: calls `/api/docker/status`, shows container grid + action buttons
6. **Restart awareness** — env snapshot on load, diff on save, warning display

### Phase 3: Wizard Mode Awareness

7. **archive step** — conditional hint text
8. **push step** — Docker mode: simplified messaging
9. **complete step** — Docker mode: real [▶️ Start Containers] button calling API

### Phase 4: Dashboard + Nav + Commands

10. **Dashboard** — deploy mode badge, mode-specific Quick Action buttons
11. **Command Center** — new Deploy card (mode-aware, same buttons as Integrations card)
12. **Nav** — Pages link target based on mode
13. **Debugging** — archive card placeholder text

### Phase 5: Polish

14. **Secrets** — conditional Docker/Tunnel collapse default
15. **Wizard mirror step** — note about Docker mirror gap
16. **Error handling** — Docker CLI not available, compose file not found, etc.

---

## Risk Assessment

- **Risk**: 🟡 MEDIUM — touches many files, but all changes are additive
- **Breaking changes**: Only the `delete secrets.DEPLOY_MODE` removal (bug fix)
- **New code**: `routes_docker.py` is the main new backend code
- **Dependencies**: Docker CLI must be installed (already checked by system_status)
- **Testing**: Need to verify both modes render correctly, Docker API endpoints
  handle missing docker gracefully

## Files Touched

| File | Change Type | Size |
|------|------------|------|
| `system_status.py` | Add deploy_mode field + read from env | Small |
| `routes_docker.py` | **NEW** — Docker management API endpoints | Medium |
| `routes_core.py` | Add `trigger-cron` to allowed commands | Tiny |
| `_wizard.html` | Stop deleting DEPLOY_MODE, conditional steps, start button | Medium |
| `_tab_integrations.html` | Add Deployment card HTML shell | Small |
| `_integrations.html` | Add loadDeployStatus() with mode-aware rendering | Large |
| `_dashboard.html` | Deploy mode badge + mode-specific Quick Action buttons | Small |
| `_tab_commands.html` | New Deploy card (mode-aware) | Medium |
| `_nav.html` | Pages link target based on mode | Small |
| `_tab_debugging.html` | Archive card placeholder | Tiny |
| `_secrets.html` | Conditional collapse default | Tiny |
