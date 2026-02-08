# Exploration Plan — Feb 8, 2026 (Revised)

Updated after completing Tasks 1-3 from the original plan.
Remaining work organized by interplay and dependency order.

---

## Completed ✅

| What | Status | Notes |
|------|--------|-------|
| Fix failing tests (47 failed → 0) | ✅ Done | Jinja2 Path, env bleed, manifest ID, Flask importskip |
| Renewal token obfuscation (Level 1) | ✅ Done | Base64 in generator.py + atob() in countdown.html |
| Vault passphrase registration | ✅ Done | register_passphrase(), route, banner, register modal mode |
| Pipeline secrets sync verification | ✅ Verified | SYNCABLE_SECRETS ↔ cron.yml in sync, no action needed |

Test suite: **474 passed, 3 skipped** (all green)

---

## Remaining Work — Ordered by Dependency

Topics are grouped by interplay. Within each group, later items build on
earlier ones. We tackle them one at a time, analyse → plan → implement.

---

### Task A: Git Sync Concurrency (Docker)

**Risk: 🔴 HIGH — potential data loss**

**Problem**: The git-sync docker-compose mode has race conditions and no
protection against remote history rewrites.

**Current behaviour** (docker-compose.yml lines 291-324):
1. Background loop every 30s: `git fetch → git reset --hard origin/main`
2. Tick loop every 15min: `tick → build-site → git add → commit → push`
3. These two loops run concurrently with zero coordination.

**Issues:**
- Background sync does `git reset --hard` while tick may be writing to state/
  → mid-write data corruption
- Factory reset on remote accepted silently — user loses local state
- No concept of "alpha mode" (accept rewrites) vs "production mode" (protect state)
- Push failures silently swallowed: "Push failed, will retry next tick"

**Desired behaviour:**
- Mutex/lockfile between the sync loop and the tick loop
- Detect diverged history (force push / factory reset on remote) and either:
  - **Alpha mode** (Docker is dominant): ignore the remote rewrite, force-push
    local state back onto the remote. "I am the source of truth."
  - **Non-alpha mode** (remote is dominant): accept the remote rewrite, reset
    local state to match. "The remote is the source of truth."
- Configurable via env var (e.g. `GIT_SYNC_ALPHA=true|false`)

**Scope**: `docker-compose.yml` (shell scripts), possibly a new
`scripts/docker_sync.py` to replace the bash loops with proper Python logic.

**Also relevant**: `src/mirror/git_sync.py` — the `push_to_mirror()` function
defaults to `force=True` for mirrors. This is correct for mirrors (slave repos)
but the main repo sync in docker-compose should NOT force-push by default.

---

### Task B: Cloudflared Sidecar

**Risk: 🟢 LOW — additive, no existing code touched**

**Problem**: No way to expose the Docker-hosted site via Cloudflare Tunnel.
Currently nginx exposes port 8080 locally.

**Design** (from original exploration plan, still valid):
```yaml
cloudflared:
  image: cloudflare/cloudflared:latest
  container_name: continuity-tunnel
  restart: unless-stopped
  profiles:
    - tunnel
  depends_on:
    nginx:
      condition: service_started
  environment:
    - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
  command: tunnel run
  networks:
    - continuity-net
```

**Also needed:**
- `CLOUDFLARE_TUNNEL_TOKEN` → LOCAL_ONLY tier (never syncs to GitHub)
- Optional wizard field for tunnel token
- Documentation in docker-compose.yml header comments

**Why after Task A**: Same file (docker-compose.yml), same infrastructure layer.
Cleaner to do both docker-compose changes in sequence.

---

### Task C: Docker Deploy Mode (Admin UI)

**Risk: 🟡 MEDIUM — UX gap, wizard choice has no effect**

**Problem**: The setup wizard has a "🐳 Docker (Self-Hosted)" radio button,
but selecting it does absolutely nothing. The `DEPLOY_MODE` value is captured
then deleted before pushing secrets. No conditional logic exists.

**What's missing:**
- No persistence of the deploy mode choice (it's thrown away)
- No conditional wizard steps (Docker mode should skip GitHub Pages setup,
  show docker-compose instructions instead)
- No admin panel awareness of deploy mode (everything assumes GitHub Pages)
- No Docker management card in the UI

**Design direction (needs deeper analysis before implementation):**
- Persist `DEPLOY_MODE` in `.env` as a local-only variable
- Wizard: conditional steps based on mode (skip Pages setup for Docker,
  show docker-compose commands, offer git-sync profile)
- Admin panel: new card in debugging tab (or a new Operations tab):
  - Shows current deploy mode
  - Docker: shows container status, offers restart guidance
  - GitHub Pages: shows deployment URL, workflow status

**Interplay**: Depends on Task A (git sync must be solid before building
management UI on top) and Task B (tunnel is a Docker-mode feature).

---

### Task D: Docker Restart Awareness

**Risk: 🟡 MEDIUM — user confusion, silent misconfiguration**

**Problem**: When the user changes `.env` variables in the admin panel, the
running Docker container doesn't pick them up. There's no notification that
a restart is needed, and no way to trigger one from the UI.

**What's needed:**
- Track which env vars have changed since container start
- Show a notification: "Environment changed — restart required for X, Y, Z"
- Optionally: offer a restart command or show the exact `docker compose` command

**Interplay**: Builds on Task C (needs deploy mode awareness — this only
applies in Docker mode, not GitHub Pages mode). The notification could live
in the Docker management card from Task C.

---

### Task E: Media Editor UX + CSS

**Risk: 🟢 LOW — feature gap, images work fine**

**Current state (corrected from original plan):**

The **rendering pipeline** is complete:
- ✅ Image → `<img>` with caption, lazy loading, CSS classes
- ✅ Video → `<video controls>` with poster, caption
- ✅ Audio → `<audio controls>` with caption
- ✅ Attachment → download link with file size
- ✅ All types support `media://` URI resolution + stage restriction

What's **NOT** done:
- ❓ Admin editor UI — does it expose video/audio/attachment block tools?
  (needs investigation of the EditorJS setup in the admin panel)
- ❓ Article CSS — are `.video-block`, `.audio-block`, `.attachment` styled
  in the site templates? (needs investigation)
- ❓ Media upload API — does the file upload flow correctly detect MIME types
  and create the right block type in EditorJS?

**Priority**: Low. Images are the primary use case and work end-to-end.
Video/audio/PDF support is a feature enhancement.

---

### Task F: Test Coverage Sweep

**Risk: 🟡 MEDIUM — blindspots in critical paths**

**Current state**: 474 tests, all passing. But coverage has blindspots:

**Known gaps (needs investigation):**
- Vault: register_passphrase() has no tests yet
- Vault: routes_vault.py register-passphrase endpoint untested
- Git sync: push_to_mirror() error paths, force push behaviour
- Docker git-sync: no integration tests for the sync loops (shell scripts)
- EditorJS renderer: video, audio, attachment blocks have tests?
  (needs check — original tests focused on image/paragraph/list)
- Media manifest: MIME-based prefix assignment, large file storage path
- Content crypto: encrypted article round-trip with media references
- Admin routes: any vault/content/git API endpoint not covered
- Site generator: media resolution callback integration
- Wizard: deploy mode persistence (once Task C is implemented)

**Approach**: Run coverage report, identify files < 80% coverage,
prioritise tests for:
1. New code from this session (register_passphrase, routes)
2. Critical paths (vault lock/unlock, state persistence, git sync)
3. Integration tests (full tick → build-site → deploy cycle)
4. Edge cases (concurrent access, rate limiting, error paths)

**Why last**: Tests should cover the final state of the code, after all
the features above are implemented. Writing tests for code that's about
to change is wasted effort.

---

## Execution Order

| Step | Task | Scope | Dependencies | Est. Effort |
|------|------|-------|--------------|-------------|
| 1 | **A: Git sync concurrency** | docker-compose.yml, scripts/ | None | Large |
| 2 | **B: Cloudflared sidecar** | docker-compose.yml | After A (same file) | Small |
| 3 | **C: Docker deploy mode** | wizard, admin UI, .env | After A+B (needs infra) | Large |
| 4 | **D: Docker restart awareness** | admin UI notifications | After C (needs mode) | Medium |
| 5 | **E: Media editor UX + CSS** | editorjs setup, CSS | Independent | Medium |
| 6 | **F: Test coverage sweep** | tests/ | After all features | Large |

---

## Session Notes

- One task at a time: analyse → plan → confirm → implement
- Follow /think-before-acting and /before-any-change workflows
- No rushing — quality over speed
