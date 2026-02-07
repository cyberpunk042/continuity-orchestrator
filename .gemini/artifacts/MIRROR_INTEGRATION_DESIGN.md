# Mirror Integration — Design Document

## Principle

A **new integration** — pure addition. No changes to core behavior.
The mirror system hooks into existing sync/update flows and propagates them to slave repos.

---

## Terminology

| Term | Meaning |
|------|---------|
| **MASTER** | The primary repo. Runs all pipelines. Pushes to slaves. |
| **SLAVE** | A dormant clone. Only runs `sentinel.yml`. Receives pushes. |
| **TEMPORARY_MASTER** | A promoted slave. Master went down, slave self-activated. |

---

## How It Integrates (Touch Points)

The mirror adapter hooks into **existing operations** without changing them.
Each operation queues a propagation to all configured slaves.

| Existing Operation | Mirror Hook | What Propagates |
|---|---|---|
| `git sync` (admin panel, post-trigger) | After push to primary | `git push --mirror` to all slaves |
| Secret update (`.env` save via admin) | After write | GitHub API: `PUT /repos/{slave}/actions/secrets/{name}` |
| Env var update (admin panel) | After write | GitHub API: `PUT /repos/{slave}/actions/variables/{name}` |
| Trigger / Reset / State change | Included in git sync | Propagated via code sync (state files are committed) |

**Key: These are async/queued. They never block the primary operation.**

---

## Pipeline Swapping (Slave ↔ Master)

### On the PRIMARY repo, all workflows are active:
- `cron.yml` — tick every 30 min
- `deploy-site.yml` — deploy GitHub Pages
- `test.yml` — run tests on push
- `sentinel.yml` — **DISABLED** (not needed on master)

### On the SLAVE repo, only one workflow is active:
- `cron.yml` — **DISABLED**
- `deploy-site.yml` — **DISABLED**
- `test.yml` — **DISABLED** (or active for validation, doesn't hurt)
- `sentinel.yml` — **ACTIVE** — watches master health

### On SELF-PROMOTION (slave → TEMPORARY_MASTER):
```
sentinel detects master down
  → gh workflow enable cron.yml
  → gh workflow enable deploy-site.yml
  → gh workflow disable sentinel.yml (or keep for master recovery check)
  → update state marker: self_role = TEMPORARY_MASTER
  → commit + push
  → slave is now operating independently
```

### On DEMOTION (TEMPORARY_MASTER → SLAVE):
Manual action from admin panel:
```
  → gh workflow disable cron.yml
  → gh workflow disable deploy-site.yml
  → gh workflow enable sentinel.yml
  → update state marker: self_role = SLAVE
  → git pull from master to re-sync
```

---

## Sentinel Workflow

Lives in `.github/workflows/sentinel.yml`.
Runs on **schedule** — respecting GitHub's cron limits.

GitHub Actions minimum cron interval: **5 minutes** (but throttled for inactive repos).
**Recommended: every 15-30 minutes** to stay well within limits and avoid throttling.

```yaml
name: Sentinel — Watch Master
on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch: {}       # Manual trigger for testing

jobs:
  watch:
    runs-on: ubuntu-latest
    env:
      MASTER_REPO: ${{ vars.MASTER_REPO }}         # e.g. cyberpunk042/continuity-orchestrator
      CONSECUTIVE_FAILURES: ${{ vars.SENTINEL_FAILURES || '0' }}
      FAILURE_THRESHOLD: ${{ vars.SENTINEL_THRESHOLD || '3' }}  # 3 failures = 1.5h at 30min interval
    steps:
      - name: Check master health
        id: health
        run: |
          # Check 1: Is the master repo API reachable?
          HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: token ${{ secrets.MASTER_TOKEN }}" \
            "https://api.github.com/repos/${MASTER_REPO}/commits/main")
          
          # Check 2: Is state/current.json recent? (within 2h)
          if [ "$HTTP_CODE" = "200" ]; then
            STATE_JSON=$(curl -s \
              -H "Authorization: token ${{ secrets.MASTER_TOKEN }}" \
              "https://api.github.com/repos/${MASTER_REPO}/contents/state/current.json" \
              | jq -r '.content' | base64 -d)
            LAST_UPDATE=$(echo "$STATE_JSON" | jq -r '.meta.updated_at_iso')
            # Compare timestamps...
          fi
          
          echo "http_code=$HTTP_CODE" >> $GITHUB_OUTPUT
          echo "healthy=$([[ "$HTTP_CODE" = "200" ]] && echo true || echo false)" >> $GITHUB_OUTPUT

      - name: Track consecutive failures
        run: |
          if [ "${{ steps.health.outputs.healthy }}" = "true" ]; then
            # Reset counter
            gh variable set SENTINEL_FAILURES --body "0"
          else
            # Increment counter
            NEW_COUNT=$(( ${{ env.CONSECUTIVE_FAILURES }} + 1 ))
            gh variable set SENTINEL_FAILURES --body "$NEW_COUNT"
            echo "⚠️ Master unreachable. Failure count: $NEW_COUNT / ${{ env.FAILURE_THRESHOLD }}"
          fi
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Self-promote if threshold reached
        if: >
          steps.health.outputs.healthy == 'false' && 
          fromJSON(env.CONSECUTIVE_FAILURES) >= fromJSON(env.FAILURE_THRESHOLD)
        run: |
          echo "🚨 MASTER DOWN — SELF-PROMOTING TO TEMPORARY_MASTER"
          
          # Enable operational workflows
          gh workflow enable cron.yml
          gh workflow enable deploy-site.yml
          
          # Update role marker
          gh variable set MIRROR_ROLE --body "TEMPORARY_MASTER"
          
          # Optionally disable sentinel (or keep it to detect master recovery)
          # gh workflow disable sentinel.yml
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## State Extension

Additive field in `state/current.json`:

```json
{
  "mirrors": {
    "self_role": "MASTER",
    "slaves": [
      {
        "id": "github-backup",
        "type": "github",
        "repo": "backup-account/continuity-orchestrator",
        "role": "SLAVE",
        "sync": {
          "code": {
            "last_sync_iso": "2026-02-07T05:00:00Z",
            "status": "ok",
            "last_commit": "abc123"
          },
          "secrets": {
            "last_sync_iso": "2026-02-07T04:30:00Z",
            "status": "ok",
            "synced_count": 5
          },
          "variables": {
            "last_sync_iso": "2026-02-07T04:30:00Z",
            "status": "ok",
            "synced_count": 3
          }
        },
        "last_health_check_iso": "2026-02-07T05:00:00Z",
        "health": "ok"
      }
    ]
  }
}
```

---

## Admin Panel — Integrations Tab

New section in the **Integrations tab** (not dashboard):

```
┌─ 🔄 Repo Mirrors ──────────────────────────────────────┐
│                                                          │
│  Self Role: MASTER                                       │
│                                                          │
│  ┌─ github-backup ──────────────────────────────────┐   │
│  │  backup-account/continuity-orchestrator   SLAVE ✅ │   │
│  │                                                    │   │
│  │  Code:      synced 2m ago       commit abc123     │   │
│  │  Secrets:   synced 15m ago      5/5 synced        │   │
│  │  Variables: synced 15m ago      3/3 synced        │   │
│  │                                                    │   │
│  │  [Force Sync]  [Promote to Master]                │   │
│  └────────────────────────────────────────────────────┘   │
│                                                          │
│  [Add Mirror]  [Sync All Now]                           │
└──────────────────────────────────────────────────────────┘
```

---

## Configuration (`.env`)

```bash
# Mirror integration
MIRROR_ENABLED=true

# Slave 1: GitHub full failover
MIRROR_1_TYPE=github
MIRROR_1_TOKEN=ghp_xxxxx                              # PAT with repo+workflow scope
MIRROR_1_REPO=backup-account/continuity-orchestrator
MIRROR_1_SYNC_SECRETS=true
MIRROR_1_SYNC_VARS=true

# Slave 2: Archive only (bare git, no CI/CD)
# MIRROR_2_TYPE=git
# MIRROR_2_URL=ssh://backup.example.com/repo.git
# MIRROR_2_SSH_KEY_PATH=/path/to/key
```

---

## Files to Create

```
src/adapters/repo_mirror.py          ← Adapter: hooks into sync, propagates
src/mirror/__init__.py
src/mirror/config.py                 ← Parse MIRROR_* env vars
src/mirror/git_sync.py               ← git push --mirror logic
src/mirror/github_sync.py            ← Secrets/vars/workflow sync via API
src/mirror/health.py                 ← Check slave health
src/mirror/state.py                  ← Mirror state tracking
.github/workflows/sentinel.yml       ← Slave's self-promotion workflow
```

---

## What We DON'T Change

- `main.py` — no CLI changes
- `tick.py` / policy rules — untouched
- `generator.py` — untouched
- Core state schema — mirrors section is additive only
- Existing adapters — untouched

## What We Hook Into (additions only)

- `server.py` — add mirror sync calls after git sync/env update endpoints
- `server.py` — add mirror status endpoint for integrations tab
- `index.html` — add mirror section to integrations tab
- State model — add optional `mirrors` field (backwards compatible)

---

## Resolved Decisions

1. **Sentinel interval**: 30 minutes (3 failures = 1.5h before promotion)
2. **Auto-resync on master recovery**: Yes — sentinel detects master recovery, auto-demotes, pulls latest
3. **Health check method**: Heartbeat via `state/current.json` freshness (platform-agnostic — works for GitHub AND Docker)
4. **Secondary check**: GitHub API repo reachability (only if `MASTER_REPO` is set)
5. **Mirror status UI**: Integrations tab, not dashboard

---

## Implementation Status

| File | Status | Description |
|------|--------|-------------|
| `src/mirror/__init__.py` | ✅ Done | Module init |
| `src/mirror/config.py` | ✅ Done | Parse MIRROR_* env vars |
| `src/mirror/state.py` | ✅ Done | Track sync status per slave |
| `src/mirror/git_sync.py` | ✅ Done | Git push to mirrors |
| `src/mirror/github_sync.py` | ✅ Done | Secrets/vars/workflow sync via API |
| `src/mirror/manager.py` | ✅ Done | Main orchestrator |
| `.github/workflows/sentinel.yml` | ✅ Done | Slave self-promotion workflow |
| `src/admin/server.py` | ✅ Done | Mirror hooks + API endpoints |
| `src/admin/static/index.html` | ⬜ TODO | Mirror section in Integrations tab |
| Tests | ⬜ TODO | Unit tests for mirror modules |
