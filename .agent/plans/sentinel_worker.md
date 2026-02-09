# Sentinel Worker — Cloudflare Tick Scheduler

## Overview

Replace the unreliable GitHub Actions `*/30 * * * *` cron with a Cloudflare Worker
that runs **every minute**, makes a sub-millisecond decision ("should I trigger the
pipeline?"), and dispatches `workflow_dispatch` only when needed.

The Worker never reads the repo.  The engine **pushes** state to the Worker after
every tick.  The Worker is a passive state holder + active scheduler.

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│   Engine runs (anywhere)         CF Worker (KV)          │
│                                                          │
│   manage.sh tick ──┐                                     │
│   cron.yml tick  ──┼── POST /state ──► KV stored         │
│   admin UI tick  ──┘                                     │
│                                                          │
│   User renews ──────── POST /signal ──► KV stored        │
│                                                          │
│                         scheduled() ──► read KV          │
│                             │           decide           │
│                             │           dispatch?        │
│                             ▼                            │
│                      workflow_dispatch                   │
│                      (only when needed)                  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Part 1 — Worker (TypeScript)

### 1.1  Project Structure

```
worker/
├── sentinel/
│   ├── wrangler.toml            # Worker config + cron triggers + KV binding
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts             # Entry: fetch() + scheduled() handlers
│       ├── decide.ts            # Pure decision logic
│       ├── dispatch.ts          # GitHub workflow_dispatch call
│       ├── types.ts             # Shared types (SentinelState, Signal, Config)
│       └── auth.ts              # Bearer token validation
```

**No build toolchain required** beyond `wrangler` (which bundles TS natively).

### 1.2  KV Schema

Single KV namespace: `SENTINEL_KV`

| Key               | Type          | Written by     | Description                                    |
|-------------------|---------------|----------------|------------------------------------------------|
| `state`           | SentinelState | Engine (POST)  | Last tick result + timing fields               |
| `signal`          | Signal        | Renew (POST)   | Fresh renewal / urgent signals                 |
| `config`          | SentinelConfig| CLI deploy     | Thresholds, cadence, repo info                 |
| `last_decision`   | DecisionLog   | Worker (cron)  | Observability: why did/didn't we dispatch?     |
| `dispatch_lock`   | string (ISO)  | Worker (cron)  | Debounce: prevent double dispatch (TTL: 90s)   |

### 1.3  Types

```typescript
// What the engine pushes after every tick
interface SentinelState {
  lastTickAt: string;       // ISO timestamp of last tick
  deadline: string;         // timer.deadline_iso
  stage: string;            // escalation.state ("OK", "REMIND_1", ...)
  stageEnteredAt: string;   // escalation.state_entered_at_iso
  renewedThisTick: boolean; // renewal.renewed_this_tick
  lastRenewalAt: string;    // renewal.last_renewal_iso
  stateChanged: boolean;    // did the last tick change state?
  version: number;          // monotonic, for conflict detection
}

// What the renew endpoint pushes
interface Signal {
  type: "renewal" | "release" | "urgent";
  at: string;               // ISO timestamp
  nonce: string;            // random, to detect duplicates
}

// Static config (written once by CLI deploy)
interface SentinelConfig {
  repo: string;                 // "owner/repo"
  workflowFile: string;         // "cron.yml"
  defaultCadenceMinutes: number;// 15
  urgencyWindowMinutes: number; // 10 (dispatch early if stage × near)
  thresholds: Threshold[];      // from rules.yaml constants
  maxBackoffMinutes: number;    // 5
}

// Derived from policy/rules.yaml constants
interface Threshold {
  stage: string;          // "REMIND_1"
  minutesBefore: number;  // 360 (= constants.remind_1_at_minutes)
}

// Observability record
interface DecisionLog {
  at: string;
  shouldDispatch: boolean;
  reason: string;
  state: SentinelState | null;
  signal: Signal | null;
  nextDueAt: string | null;
}
```

### 1.4  Decision Algorithm (`decide.ts`)

```typescript
function shouldDispatch(
  state: SentinelState | null,
  signal: Signal | null,
  config: SentinelConfig,
  now: Date,
  lastDispatchAt: string | null,
): { dispatch: boolean; reason: string } {

  // 1. Bootstrap: no state yet → dispatch unconditionally
  if (!state) return { dispatch: true, reason: "bootstrap" };

  // 2. Fresh renewal signal
  if (signal && signal.at > state.lastTickAt) {
    return { dispatch: true, reason: `signal:${signal.type}` };
  }

  // 3. Stage threshold approaching
  const deadline = new Date(state.deadline);
  const minutesToDeadline = (deadline.getTime() - now.getTime()) / 60000;

  for (const t of config.thresholds) {
    if (minutesToDeadline <= t.minutesBefore + config.urgencyWindowMinutes
        && state.stage !== t.stage
        && minutesToDeadline > 0) {
      return { dispatch: true, reason: `stage_near:${t.stage}` };
    }
  }

  // 4. Overdue check (deadline passed)
  if (minutesToDeadline <= 0 && state.stage !== "FULL") {
    return { dispatch: true, reason: "overdue" };
  }

  // 5. Normal cadence
  const lastTick = new Date(state.lastTickAt);
  const minutesSinceLastTick = (now.getTime() - lastTick.getTime()) / 60000;
  if (minutesSinceLastTick >= config.defaultCadenceMinutes) {
    return { dispatch: true, reason: "cadence" };
  }

  // 6. Debounce: already dispatched recently
  if (lastDispatchAt) {
    const sinceLast = (now.getTime() - new Date(lastDispatchAt).getTime()) / 60000;
    if (sinceLast < config.maxBackoffMinutes) {
      return { dispatch: false, reason: `backoff:${Math.round(sinceLast)}m` };
    }
  }

  // 7. Terminal state: FULL = nothing to do
  if (state.stage === "FULL") {
    return { dispatch: false, reason: "terminal:FULL" };
  }

  return { dispatch: false, reason: "idle" };
}
```

### 1.5  HTTP Endpoints (`index.ts fetch()`)

| Method | Path        | Auth     | Description                                    |
|--------|-------------|----------|------------------------------------------------|
| POST   | `/state`    | Bearer   | Engine pushes state after tick                 |
| POST   | `/signal`   | Bearer   | Renewal/release signal                         |
| GET    | `/status`   | Public   | Current sentinel status (for dashboard/site)   |
| GET    | `/health`   | Public   | Simple health check                            |

**`/status` response** (consumed by admin UI + GitHub Pages site):
```json
{
  "healthy": true,
  "lastTickAt": "2026-02-09T16:00:00Z",
  "stage": "OK",
  "deadline": "2026-02-11T09:53:45Z",
  "lastDecision": {
    "at": "2026-02-09T16:01:00Z",
    "shouldDispatch": false,
    "reason": "idle"
  },
  "lastDispatchAt": "2026-02-09T15:58:00Z",
  "nextDueAt": "2026-02-09T16:13:00Z"
}
```

### 1.6  Cron Handler (`index.ts scheduled()`)

```typescript
export default {
  async scheduled(event, env, ctx) {
    const state  = await env.SENTINEL_KV.get("state", "json");
    const signal = await env.SENTINEL_KV.get("signal", "json");
    const config = await env.SENTINEL_KV.get("config", "json");
    const lock   = await env.SENTINEL_KV.get("dispatch_lock");

    const now = new Date();
    const decision = shouldDispatch(state, signal, config, now, lock);

    // Log decision
    await env.SENTINEL_KV.put("last_decision", JSON.stringify({
      at: now.toISOString(), ...decision,
      state, signal,
    }));

    if (decision.dispatch) {
      // Acquire lock (TTL 90s)
      await env.SENTINEL_KV.put("dispatch_lock", now.toISOString(), { expirationTtl: 90 });
      // Dispatch workflow
      await dispatchWorkflow(config, env.GITHUB_TOKEN, decision.reason);
      // Clear signal (consumed)
      if (signal) await env.SENTINEL_KV.delete("signal");
    }
  }
};
```

### 1.7  `wrangler.toml`

```toml
name = "continuity-sentinel"
main = "src/index.ts"
compatibility_date = "2024-12-01"

[triggers]
crons = ["* * * * *"]   # Every minute

[[kv_namespaces]]
binding = "SENTINEL_KV"
id = "xxx"               # Created by CLI wizard

[vars]
ENVIRONMENT = "production"

# Secrets (set via `wrangler secret put`):
# - SENTINEL_TOKEN   (Bearer token for /state and /signal)
# - GITHUB_TOKEN     (PAT with actions:write for workflow_dispatch)
```

---

## Part 2 — Engine Integration (Python)

### 2.1  Sentinel Notifier Module

New file: `src/sentinel/notify.py`

```python
"""
Sentinel Notifier — Push state to the Cloudflare Worker after every tick.

This is a fire-and-forget POST.  If it fails, the engine continues normally.
The sentinel will dispatch based on cadence anyway if it misses an update.
"""

def notify_sentinel(state, tick_result=None):
    """Push minimal state snapshot to the sentinel Worker."""
    url = os.environ.get("SENTINEL_URL")
    token = os.environ.get("SENTINEL_TOKEN")
    if not url or not token:
        return  # Sentinel not configured — no-op

    payload = {
        "lastTickAt":      state.meta.updated_at_iso,
        "deadline":        state.timer.deadline_iso,
        "stage":           state.escalation.state,
        "stageEnteredAt":  state.escalation.state_entered_at_iso,
        "renewedThisTick": state.renewal.renewed_this_tick,
        "lastRenewalAt":   state.renewal.last_renewal_iso or "",
        "stateChanged":    tick_result.state_changed if tick_result else False,
        "version":         int(time.time()),
    }

    try:
        requests.post(f"{url}/state", json=payload,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=3)
    except Exception:
        pass  # Fire and forget
```

### 2.2  Touch Points (Where to Call `notify_sentinel`)

| Location                              | When                              | Call                                          |
|---------------------------------------|-----------------------------------|-----------------------------------------------|
| `src/main.py` → `tick()`             | After `save_state()`             | `notify_sentinel(state, result)`             |
| `src/cli/core.py` → `renew()`       | After `save_state()`             | `signal_sentinel("renewal")`                 |
| `src/cli/core.py` → `reset()`       | After `save_state()`             | `notify_sentinel(state)`                     |
| `src/cli/core.py` → `trigger_release()` | After `save_state()`         | `signal_sentinel("release")`                 |
| `src/admin/routes_core.py` → API     | After state-changing operations  | Already calls CLI; gets it transitively      |

### 2.3  Signal Helper

```python
def signal_sentinel(signal_type: str):
    """Send a signal (renewal/release) to the sentinel."""
    url = os.environ.get("SENTINEL_URL")
    token = os.environ.get("SENTINEL_TOKEN")
    if not url or not token:
        return

    payload = {
        "type": signal_type,
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "nonce": secrets.token_hex(8),
    }

    try:
        requests.post(f"{url}/signal", json=payload,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=3)
    except Exception:
        pass
```

### 2.4  Pipeline Changes (`cron.yml`)

The cron schedule becomes a **safety net** only:

```yaml
on:
  schedule:
    # Safety fallback — Worker normally dispatches via workflow_dispatch
    - cron: "0 */6 * * *"   # Every 6 hours (safety net only)
  workflow_dispatch:
    inputs:
      reason:
        description: "Dispatch reason (from sentinel or manual)"
        required: false
        default: "manual_run"
      # ... existing inputs unchanged
```

Add sentinel notification step after tick:

```yaml
      - name: Notify sentinel
        if: steps.tick.outcome == 'success'
        continue-on-error: true
        env:
          SENTINEL_URL: ${{ secrets.SENTINEL_URL }}
          SENTINEL_TOKEN: ${{ secrets.SENTINEL_TOKEN }}
        run: |
          if [ -n "$SENTINEL_URL" ]; then
            python -c "
            from src.sentinel.notify import notify_sentinel
            from src.persistence.state_file import load_state
            from pathlib import Path
            state = load_state(Path('state/current.json'))
            notify_sentinel(state)
            print('✅ Sentinel notified')
            "
          fi
```

Similarly for `renew.yml`:

```yaml
      - name: Signal sentinel (renewal)
        continue-on-error: true
        env:
          SENTINEL_URL: ${{ secrets.SENTINEL_URL }}
          SENTINEL_TOKEN: ${{ secrets.SENTINEL_TOKEN }}
        run: |
          if [ -n "$SENTINEL_URL" ]; then
            python -c "
            from src.sentinel.notify import signal_sentinel
            signal_sentinel('renewal')
            print('✅ Sentinel signaled: renewal')
            "
          fi
```

---

## Part 3 — CLI Wizard

### 3.1  New CLI Command: `manage.sh setup sentinel`

Interactive setup flow:

```
🛡️ Sentinel Setup — Cloudflare Tick Scheduler

This replaces your GitHub Actions cron with a Cloudflare Worker
that checks every minute and dispatches only when needed.

Prerequisites:
  - Cloudflare account
  - Node.js / npx (for wrangler)

Step 1: Cloudflare Account ID
  → Enter your Cloudflare Account ID: ___

Step 2: Cloudflare API Token
  → Create at: https://dash.cloudflare.com/profile/api-tokens
  → Needs: Workers Scripts:Edit, Workers KV:Edit
  → Paste token: ___

Step 3: GitHub Token
  → Fine-grained PAT with Actions:Write for this repo
  → Paste token: ___

Step 4: Deploying...
  ✓ Creating KV namespace
  ✓ Uploading Worker
  ✓ Setting secrets (SENTINEL_TOKEN, GITHUB_TOKEN)
  ✓ Writing initial config to KV
  ✓ Adding cron trigger (* * * * *)

Step 5: Validating...
  ✓ Health check: https://continuity-sentinel.xxx.workers.dev/health
  ✓ Trigger test: dispatched (reason: bootstrap)

Step 6: Repository secrets
  Add these to your GitHub repo secrets:
    SENTINEL_URL = https://continuity-sentinel.xxx.workers.dev
    SENTINEL_TOKEN = <generated>

Done! Your sentinel is live.
  Dashboard: https://dash.cloudflare.com/.../workers/continuity-sentinel
  Status:    https://continuity-sentinel.xxx.workers.dev/status
```

### 3.2  Config Generation

The wizard reads `policy/rules.yaml` constants and generates the sentinel config:

```python
def generate_sentinel_config(policy_dir):
    """Generate SentinelConfig from policy constants."""
    rules = load_rules(policy_dir)
    constants = rules.constants

    thresholds = [
        {"stage": "REMIND_1",    "minutesBefore": constants.get("remind_1_at_minutes", 360)},
        {"stage": "REMIND_2",    "minutesBefore": constants.get("remind_2_at_minutes", 60)},
        {"stage": "PRE_RELEASE", "minutesBefore": constants.get("pre_release_at_minutes", 15)},
    ]

    return {
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflowFile": "cron.yml",
        "defaultCadenceMinutes": 15,
        "urgencyWindowMinutes": 10,
        "thresholds": thresholds,
        "maxBackoffMinutes": 5,
    }
```

---

## Part 4 — Admin Dashboard Integration

### 4.1  Status Card (Dashboard Tab)

Add a "Sentinel" card to the dashboard showing:

- **Status**: Connected / Not configured / Unreachable
- **Last check**: "32s ago" (from `/status` endpoint)
- **Last dispatch**: "15m ago — reason: cadence"
- **Next due**: "in 12m 30s"
- **Stage**: OK (with color)

### 4.2  API Endpoint

New endpoint in `routes_core.py`:

```python
@core_bp.route("/api/sentinel/status")
def api_sentinel_status():
    """Proxy the sentinel /status endpoint for the dashboard."""
    url = os.environ.get("SENTINEL_URL")
    if not url:
        return jsonify({"configured": False})
    try:
        resp = requests.get(f"{url}/status", timeout=3)
        data = resp.json()
        data["configured"] = True
        return jsonify(data)
    except Exception as e:
        return jsonify({"configured": True, "reachable": False, "error": str(e)})
```

---

## Part 5 — Cost & Reliability Analysis

### Cost (Cloudflare Workers Free Tier)

| Metric              | Usage                         | Free limit         | OK? |
|---------------------|-------------------------------|--------------------|-----|
| Requests/day        | 1440 (1/min cron) + ~50 POST  | 100,000/day        | ✅  |
| CPU time/invocation | < 1ms (pure KV reads + math)  | 10ms/invocation    | ✅  |
| KV reads/day        | ~4320 (3 reads × 1440 crons)  | 100,000/day        | ✅  |
| KV writes/day       | ~100 (few ticks + decisions)  | 1,000/day          | ✅  |

**Total cost: $0/month** on free tier for typical usage.

### Reliability Comparison

| Aspect                  | GitHub Cron          | Sentinel Worker         |
|-------------------------|----------------------|-------------------------|
| Schedule accuracy       | ±5–30 min delays     | ±1 min (cron trigger)   |
| Dropped ticks           | Common under load    | Never (purpose-built)   |
| Startup latency         | 30–60s (runner boot) | < 50ms (V8 isolate)     |
| Renewal responsiveness  | Next 30-min window   | < 60s (next cron cycle) |
| Stage-near precision    | ±30 min              | ±1 min                  |

---

## Implementation Order

### Phase 1: Foundation ✅
1. [x] Create `worker/sentinel/` project structure
2. [x] Implement Worker: types.ts, decide.ts, dispatch.ts, auth.ts, index.ts
3. [x] TypeScript compiles clean (`npx tsc --noEmit` → exit 0)
4. [ ] Manual deploy with wrangler for testing
5. [ ] Verify with `curl` that all endpoints work

### Phase 2: Engine Hook ✅
6. [x] Create `src/sentinel/__init__.py` (notify_sentinel + signal_sentinel)
7. [x] Add `notify_sentinel()` call in `src/main.py` tick command
8. [x] Add `signal_sentinel()` call in `src/cli/core.py` renew + trigger_release
9. [x] Add `notify_sentinel()` call in `src/cli/core.py` reset (both full + soft)
10. [x] Env vars: `SENTINEL_URL`, `SENTINEL_TOKEN` (no-op when unset)
11. [x] Verified: imports work, no-op when unconfigured, CLI still works

### Phase 3: Pipeline Integration ✅
10. [x] Add "Notify sentinel" step to `cron.yml`
11. [x] Add "Signal sentinel" step to `renew.yml`
12. [x] Add `SENTINEL_URL` + `SENTINEL_TOKEN` to tick env + mirror sync env
13. [x] Add `SENTINEL_URL` + `SENTINEL_TOKEN` to SYNCABLE_SECRETS
14. [ ] Reduce cron schedule to `0 */6 * * *` (safety net) — deferred until sentinel proven
15. [ ] Add `SENTINEL_URL` + `SENTINEL_TOKEN` to actual repo secrets (manual)

### Phase 4: Wizard + Setup Automation ✅
16. [x] Create `scripts/setup-sentinel.sh` — fully automated deployment script
17. [x] Add `./manage.sh sentinel` subcommand
18. [x] Add sentinel step to web wizard (between mirror and push)
19. [x] Add SENTINEL_URL + SENTINEL_TOKEN to secrets manager (category + tiers)
20. [x] Register in SECRET_DEFINITIONS for /api/status

### Phase 5: Dashboard ✅
21. [x] Add `/api/sentinel/status` proxy endpoint to routes_core.py
22. [x] Add "🛰️ Sentinel" status card to dashboard
23. [x] Show: configured/active/unreachable, last decision, next due, repo

---

## Resolved Decisions

1. **Worker naming**: `{project-name}-sentinel` (e.g. `my-deadman-sentinel`).
2. **One Worker per project** — a project can have 2 repos (master + mirror).
   The Worker dispatches to whichever repo is currently active. Both repos'
   pipelines push state to the same Worker. Config stores both repos:
   `{ repo: "owner/main", mirrorRepo: "owner/mirror" }`.
3. **Fallback**: GitHub cron stays as a `*/6h` safety net. If sentinel is
   unreachable the engine just doesn't call it (fire-and-forget). The safety
   cron catches anything missed.
4. **Site integration**: Site already polls `status.json` (static file baked
   at build time). Sentinel `/status` is additive — the admin dashboard will
   use it. The public site can optionally poll it later for live "last checked"
   info, but that's a nice-to-have.
