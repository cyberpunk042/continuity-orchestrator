# Task A: Git Sync Concurrency — Implementation Plan

## Decisions

- Default mode: **non-alpha** (remote is the source of truth)
- On divergence: **fully automatic** — alpha force-pushes, non-alpha resets. No user prompt.
- On startup: **always pull latest from remote** regardless of mode
- Logging: structured, clear logs for every sync event

---

## File 1: `scripts/docker_git_sync.py` (NEW)

Replaces the inline bash loops in docker-compose.yml with a testable Python script.

### Class: `DockerGitSync`

```python
__init__(self, repo_path, branch="main", alpha=False,
         tick_interval=900, sync_interval=30)
```

Fields:
- `_lock: threading.Lock` — mutex between sync and tick
- `repo: Path` — git repo root
- `branch: str` — branch name
- `alpha: bool` — True = Docker dominant, False = remote dominant
- `tick_interval: int` — seconds between ticks (default 900 = 15min)
- `sync_interval: int` — seconds between syncs (default 30)

### Method: `initial_sync()`
Called once on startup. Always pulls latest from remote.
```
git fetch origin {branch}
git reset --hard origin/{branch}
```

### Method: `detect_state() → str`
Pure git inspection, no side effects. Returns one of:
- `"up-to-date"` — local HEAD == remote HEAD
- `"behind"` — local is ancestor of remote (remote has new commits)
- `"ahead"` — remote is ancestor of local (local has unpushed commits)
- `"diverged"` — neither is ancestor (history rewrite / force push)

Implementation:
```
local = git rev-parse HEAD
remote = git rev-parse origin/{branch}

if local == remote → "up-to-date"
if git merge-base --is-ancestor local remote → "behind"
if git merge-base --is-ancestor remote local → "ahead"
else → "diverged"
```

### Method: `sync_from_remote() → str`
Called every sync_interval. Acquires lock.
```
1. Lock
2. git fetch origin {branch}
3. state = detect_state()
4. Switch:
   - "up-to-date" → log debug, return
   - "behind" → git reset --hard origin/{branch}, rebuild site, log info
   - "ahead" → log debug "local ahead, will push on next tick", return
   - "diverged":
     - alpha=True → log WARNING "diverged, keeping local (alpha mode)"
                     set flag to force-push on next tick
     - alpha=False → log WARNING "diverged, accepting remote (non-alpha mode)"
                     git reset --hard origin/{branch}, rebuild site
5. Unlock
```

### Method: `run_tick_and_push() → str`
Called every tick_interval. Acquires lock.
```
1. Lock
2. python -m src.main tick
3. python -m src.main build-site --output /public
4. Check: git diff --quiet state/ audit/
   - No changes → log "no state changes", return
   - Changed:
     git add state/ audit/
     git commit -m "chore(state): tick at {iso_timestamp}"
     if alpha or force_push_pending:
       git push --force origin {branch}
       clear force_push_pending flag
     else:
       git push origin {branch}
       if push fails → log error "push failed, will retry"
5. Unlock
```

### Method: `_run_sync_loop()`
Background thread. Runs `sync_from_remote()` every sync_interval.
Catches all exceptions to prevent thread death.

### Method: `_run_tick_loop()`
Main thread. Runs `run_tick_and_push()` every tick_interval.

### Method: `start()`
Entry point:
```
initial_sync()
start sync thread
run tick loop (blocking, in main thread)
```

### CLI interface:
```
if __name__ == "__main__":
    argparse:
      --repo PATH (required)
      --branch STR (default "main")
      --alpha (flag, default False)
      --tick-interval INT (default 900)
      --sync-interval INT (default 30)
```

### Env var override:
`GIT_SYNC_ALPHA=true` overrides --alpha flag.

---

## File 2: `docker-compose.yml` (MODIFY)

### orchestrator-git-sync service changes:

**Environment** — add:
```yaml
- GIT_SYNC_ALPHA=${GIT_SYNC_ALPHA:-false}
- GIT_SYNC_TICK_INTERVAL=${GIT_SYNC_TICK_INTERVAL:-900}
- GIT_SYNC_SYNC_INTERVAL=${GIT_SYNC_SYNC_INTERVAL:-30}
```

**Command** — replace the 40-line inline bash with:
```yaml
command:
  - |
    # Clone repo if not already present
    if [ ! -d /repo/.git ]; then
      echo "Cloning repository..."
      if [ -z "$$GITHUB_TOKEN" ] || [ -z "$$GITHUB_REPOSITORY" ]; then
        echo "ERROR: GITHUB_TOKEN and GITHUB_REPOSITORY must be set"
        exit 1
      fi
      git clone "https://x-access-token:$$GITHUB_TOKEN@github.com/$$GITHUB_REPOSITORY.git" /repo
    fi

    cd /repo
    git config --global --add safe.directory /repo
    git config user.name "$$GIT_AUTHOR_NAME"
    git config user.email "$$GIT_AUTHOR_EMAIL"
    git remote set-url origin "https://x-access-token:$$GITHUB_TOKEN@github.com/$$GITHUB_REPOSITORY.git"

    # Clear shared volume for nginx
    rm -rf /public/* 2>/dev/null || true

    # Hand off to Python sync manager
    python /app/scripts/docker_git_sync.py \
      --repo /repo \
      --branch main \
      --public-dir /public \
      --tick-interval $${GIT_SYNC_TICK_INTERVAL:-900} \
      --sync-interval $${GIT_SYNC_SYNC_INTERVAL:-30}
```

Note: The `--alpha` flag is read from `GIT_SYNC_ALPHA` env var inside
the script, not passed as CLI arg (avoids YAML quoting issues).

---

## File 3: (NO new admin UI yet — that's Task C/D)

The env var `GIT_SYNC_ALPHA` is a LOCAL_ONLY var — it lives in `.env` on the
Docker host. It's not a secret, not synced to GitHub. The wizard can optionally
surface it when Docker mode is selected (Task C).

For now, documentation in the docker-compose.yml header comment is sufficient.

---

## What is NOT changing

- `src/mirror/git_sync.py` — slave mirror push logic, separate concern
- Standalone orchestrator mode — no git, no sync
- Observer mode — read-only
- Admin panel — no UI changes in this task

---

## Tooltip / description (for future wizard integration, Task C)

```
🔑 Git Sync Mode

☐ Alpha (Docker is dominant)
  This Docker instance is the authoritative source.
  If the remote repository history changes (e.g. factory reset
  from another device), this instance will OVERRIDE the remote
  with its own state. Use this when this Docker is your primary
  running system and nothing else should overwrite it.

☑ Non-Alpha (Remote is dominant) — DEFAULT
  The remote repository is the authoritative source.
  If the remote history changes, this instance will adapt and
  follow. Use this for secondary instances, testing, or when
  the GitHub Actions pipeline is the primary system.
```

---

## Testing strategy (deferred to Task F, but design for it)

The `DockerGitSync` class should be testable:
- `detect_state()` → mock git subprocess calls, test all 4 outcomes
- `sync_from_remote()` → mock detect_state + git commands, verify correct
  action for each state × alpha mode combination (8 cases)
- `run_tick_and_push()` → mock tick/build subprocess, verify commit/push logic
- Lock contention → verify sync waits for tick to finish and vice versa
