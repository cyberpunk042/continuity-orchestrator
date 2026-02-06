# Logging & Pipeline Deep Analysis

## 📊 Actual Performance Measurements (Local)

| Operation | Time | Notes |
|-----------|------|-------|
| `tick --dry-run` | **0.39s** | Very fast, pure logic |
| `build-site` | **0.42s** | Fast, 18 files |
| `pytest` (255 tests) | **2.35s** | Lightweight tests |
| `pip install -e .` | **4.8s** | Already cached |

**Local is fast.** The real question: where does time go in CI?

---

## 🔍 GitHub Actions: Where Time Actually Goes

### `cron.yml` Breakdown (per run)

| Step | Estimated Time | Why |
|------|----------------|-----|
| Checkout | 2-5s | `fetch-depth: 1` ✅ |
| `git pull --rebase` | 1-3s | Network to GitHub |
| Python setup + cache | **30-60s** | Cache restore overhead |
| `pip install -e .` | **15-30s** | Even with cache, wheel building |
| Run tick | 1-5s | Fast |
| `git commit + push` | 5-15s | Network to GitHub |
| Build site | 2-5s | Fast |
| Upload artifact | 5-10s | Compression + upload |
| Deploy Pages | **30-60s** | GitHub Pages infra |

**Real run time: ~2-3 minutes** (not 4 like I said before)

**Observation:** Most time is in:
1. Python setup (cache restore) ~45s
2. Pages deployment ~45s
3. Git operations ~15s

The tick logic itself is <1% of total time.

### Why cron MUST run every 30 min

You're right - this is the core function. The tick:
1. Evaluates countdown
2. Checks rules
3. Transitions states if needed
4. Executes actions when appropriate

If tick doesn't run, the system doesn't work. This is **non-negotiable**.

### `deploy-site.yml` Analysis

Triggers on:
- `push` to `public/**` - This would trigger AFTER cron commits (redundant)
- `push` to `state/**` - Also after cron commits (redundant)
- `push` to `templates/**` - Manual template changes (valid)
- `push` to `src/site/**` - Generator code changes (valid)

**Real issue:** When cron commits to `state/` → triggers deploy-site → double deploy

**But also needed:** When you manually push template/site changes without cron

**Questions to consider:**
1. Does cron already deploy to Pages? → YES (line 136-139 in cron.yml)
2. Does deploy-site duplicate this? → YES, when path triggers match

---

## 🔬 Logging: Actual Current State

### What's Being Logged (Well)

```
src/engine/tick.py:
  - Tick start (full context: project, state, plan, mode)
  - Time evaluation details
  - Rule matches
  - State transitions
  - Action selection
  - Tick completion (duration, counts)

src/adapters/registry.py:
  - Every adapter registration
  - Fallbacks used

src/adapters/*.py (each real adapter):
  - Action execution
  - API responses
  - Errors with context
```

### What's NOT Being Logged (Gaps)

1. **Admin server requests** - No request logging beyond Flask's minimal output
   - `/api/run` executions - what command, who called, result?
   - `/api/secret/set` - what was set? (not the value, but the key)
   - `/api/archive` - we added print() for debugging, not proper logging

2. **Startup/shutdown** - No log of:
   - When admin server starts
   - Which adapters loaded in admin context
   - Configuration loaded

3. **Site generation** - Silent except final summary
   - Which templates rendered?
   - Which articles generated?
   - Any render errors?

4. **Policy loading** - No log of:
   - Rules loaded
   - Actions defined
   - Stages configured

5. **State file operations** - No log of:
   - When state is read
   - When state is written
   - What changed

6. **File operations** - No log of:
   - Config files read
   - Templates loaded
   - Static assets copied

### Mixed `print()` and `logger` Usage (Inconsistency)

Files using `print()` instead of proper logging:
- `src/admin/server.py` - Archive endpoint (debug prints we just added)
- `src/adapters/internet_archive.py` - Archive operations (debug prints)
- `src/main.py` - CLI output (uses click.echo - appropriate for CLI)
- `src/engine/tick.py` - Some debug output
- `src/validation.py` - Validation messages

---

## 🏗️ Architecture: What Should Be Logged

### Tier 1: Critical (Always log)
- Tick start/end with timing
- State transitions
- Action executions
- Adapter successes/failures
- Authentication events
- Errors/exceptions

### Tier 2: Important (Log at INFO)
- Configuration loads
- Server startup/shutdown
- Site builds
- API requests (sanitized)
- Policy evaluations

### Tier 3: Debug (Log at DEBUG)
- Template rendering
- File I/O operations
- Cache hits/misses
- Rule evaluation details
- Request/response details

---

## � Actual Efficiency Concerns

### 1. Double Deploys (Real Issue)

The `deploy-site.yml` workflow can trigger when cron pushes to `state/`. This causes:
- deploy-site runs
- cron already deployed in same commit
- Result: 2 Pages deploys for same content

**Fix:** Either:
- A) Remove `state/**` and `public/**` from deploy-site triggers
- B) Add conditional skip if triggered by bot commit

### 2. Test Matrix (Cost Concern)

Running 3 Python versions (3.8, 3.11, 3.12) on every push:
- 3x parallel runs
- Most code doesn't need 3.8 compatibility testing every time

**Consideration:** Your `requires-python = ">=3.8"` suggests backward compat is important. But daily pushes rarely need full matrix.

### 3. No Caching of Site Output

Each tick regenerates the site even if state hasn't changed significantly. The output is:
- 18 files
- Always regenerated from scratch
- Uploaded as artifact every time

**But:** Site generation is only 0.4s, so this is minor.

---

## 📋 Recommended Actions (Prioritized)

### High Value, Low Effort

1. **Remove double-deploy triggers**
   ```yaml
   # deploy-site.yml
   paths:
     # - 'public/**'   # cron handles this
     # - 'state/**'    # cron handles this
     - 'templates/**'
     - 'src/site/**'
   ```

2. **Add proper logging to admin server**
   - Request logging (endpoint, duration)
   - Replace print() with logger.debug()
   - Add startup log with loaded adapters

### Medium Value, Medium Effort

3. **Add structured logging context**
   ```python
   logger.info("Action executed", extra={
       "tick_id": tick_id,
       "action_id": action.id,
       "duration_ms": duration,
   })
   ```

4. **Reduce test matrix on non-PR pushes**
   ```yaml
   strategy:
     matrix:
       python-version: ${{ github.event_name == 'pull_request' && fromJson('["3.8", "3.11", "3.12"]') || fromJson('["3.11"]') }}
   ```

### Low Urgency

5. **Add local file logging** for dev debugging
6. **Add policy load logging** to understand rule evaluation
7. **Add state change diffing** to show what changed

---

## 💡 Key Insight

The system is already quite efficient. The core operations are fast (<1s each).
The "cost" is dominated by CI infrastructure overhead that we can't control:
- Python setup/cache restore
- GitHub Pages deployment
- Artifact uploads

The real wins are:
1. **Avoiding duplicate work** (double deploys)
2. **Better observability** (logging gaps)
3. **Smarter test matrix** (run full only when needed)

Not "make tick faster" - tick is already 0.39s.

