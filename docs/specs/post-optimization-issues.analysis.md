# Post-Optimization Issues — Analysis

> Created: 2026-02-27  
> Context: Issues discovered after completing the 6-step tick-cost-optimization plan.  
> Severity scale: CRITICAL / HIGH / MEDIUM / LOW

---

## Issue 1: Sentinel Staleness False Positive (CRITICAL)

**Category:** Regression introduced by the quiescence optimization  
**Severity:** CRITICAL — could trigger incorrect failover

### Problem

The sentinel health check on the mirror (`.github/workflows/sentinel.yml`, line 53-58)
determines master liveness by reading `state/current.json → meta.updated_at_iso`:

```python
UPDATED_AT=$(python3 -c "
    with open('state/current.json') as f:
        state = json.load(f)
    print(state.get('meta', {}).get('updated_at_iso', ''))
")
```

And comparing its age against `STALENESS_SECONDS` (7200 = 2 hours, line 24):

```bash
if [ "$AGE" -lt "${{ env.STALENESS_SECONDS }}" ]; then
    echo "healthy=true"
else
    echo "healthy=false"
```

With the quiescence optimization, `updated_at_iso` is **no longer bumped** on idle
ticks (`tick.py` Phase 8 — the `state.meta.updated_at_iso = result.ended_at` line
is inside the `if not result.quiescent:` block). This means the timestamp will
become stale after 2 hours of quiescence, causing the sentinel to:

1. Mark the master as unhealthy.
2. Increment the failure counter.
3. After 3 consecutive failures (~1.5 hours), **self-promote to TEMPORARY_MASTER**.

This is a **false positive failover** — the master is running fine, just idle.

### The Same Problem Affects Two Paths

1. **sentinel.yml on the mirror** — reads `state/current.json` from its own repo 
   (which was pushed there by the master's mirror-sync). Since mirror-sync is also 
   gated by quiescence, the file never gets pushed during idle periods.

2. **Python-side sentinel notification** (`src/sentinel/__init__.py`, line 60) — 
   sends `"lastTickAt": state.meta.updated_at_iso`. During quiescence, this sends 
   the OLD timestamp (from the last non-quiescent tick). The Cloudflare Worker 
   receiving this could also consider the master stale.

### Root Cause

Two timestamps are conflated:
- **"When was the state last changed?"** — answers "is there new data?"
- **"When did the tick last run?"** — answers "is the master alive?"

`updated_at_iso` was serving both purposes. The quiescence optimization correctly 
stopped updating it for the first purpose but broke the second.

### Proposed Solutions

**Option A — Separate heartbeat timestamp**

Add a new field to state: `meta.last_tick_at_iso`. This always gets bumped, even 
during quiescence. `updated_at_iso` keeps its semantic meaning ("last state 
mutation"). The sentinel checks `last_tick_at_iso` instead.

- Pros: Clean separation of concerns, explicit semantics.
- Cons: The state file still changes every tick → git diff → back to the commit 
  problem. Defeats the purpose of quiescence for the commit step.

**Option B — Sentinel uses Python-side notification, not file timestamp**

Stop relying on `updated_at_iso` for liveness. Instead:
- The Python-side sentinel notification already fires on every tick (including 
  quiescent). Add a `"tickAt"` field that uses `datetime.now()` instead of 
  `state.meta.updated_at_iso`.
- The Cloudflare Worker tracks liveness from the POST timestamp.
- The mirror's `sentinel.yml` workflow adds a secondary check: query the 
  Cloudflare Worker's `/health` endpoint to get the last-heard-from timestamp.

- Pros: No state file mutation needed. Fully decoupled.
- Cons: Requires the Cloudflare Worker to expose a health endpoint. Adds a 
  network dependency to the sentinel check.

**Option C — Heartbeat file (not state)**

Write a lightweight heartbeat file (e.g., `state/heartbeat`) that contains only 
a timestamp. Always write it, even during quiescence. Exclude it from the git 
commit step (don't `git add` it). The sentinel on the mirror can't use it 
(it's not pushed), but the Cloudflare Worker receives liveness via POST.

For the mirror sentinel: rely on the Cloudflare Worker as the liveness source 
(Option B's secondary check).

- Pros: State file stays clean. Heartbeat is separate.
- Cons: Introduces a new file. Mirror sentinel needs refactoring.

**Recommendation: Option B** — make the Python-side sentinel POST contain a 
fresh `tickAt` timestamp (just `datetime.now()`), and have the sentinel.yml 
workflow check liveness via the Cloudflare Worker instead of the file. This 
keeps quiescence fully clean while maintaining liveness detection.

---

## Issue 2: Audit Entry Ordering Regression (HIGH)

**Category:** Regression introduced by the audit buffering change  
**Severity:** HIGH — produces out-of-order audit entries on active ticks

### Problem

Before the optimization, audit entries were emitted in chronological order:
```
tick_start  →  rule_matched  →  state_transition  →  action_receipt  →  tick_end
```

After the buffering change, `tick_start` and `rule_matched` are buffered, but
`state_transition` (Phase 5, line 232) and `MANUAL_RELEASE` state_transition 
(Phase 5b, line 276) emit directly to the audit writer. The buffer is flushed 
at Phase 8 (finalization). This produces:

```
state_transition  →  tick_start  →  rule_matched  →  tick_end
```

The `state_transition` appears BEFORE `tick_start` in the ledger.

### Who is affected?

- Only active ticks where a state transition occurs.
- Quiescent ticks are unaffected (no audit at all).
- Active ticks without state transitions are unaffected (no state_transition 
  entry, buffer flushes in correct order).

### Root Cause

The state_transition emits in Phase 5 were not included in the buffering 
strategy. They remained as direct calls to `audit_writer.emit_state_transition()`.

### Proposed Solution

Route the two `state_transition` emits (lines 232 and 276) through the same 
audit buffer. The buffer then flushes in insertion order at Phase 8:
`tick_start → rule_matched → state_transition → action_receipt → tick_end`.

The `action_receipt` entries (Phase 7, line 403) are only emitted during active 
ticks and happen after Phase 6b's quiescence check, so they don't need 
buffering — they're emitted in the correct position. But for consistency, they 
could also be buffered.

**Recommendation:** Buffer state_transition entries. This is a straightforward 
extension of the existing buffer mechanism.

---

## Issue 3: Duplicate Sentinel Notification on Active Ticks (MEDIUM)

**Category:** Pre-existing redundancy  
**Severity:** MEDIUM — wasteful, minor data inconsistency

### Problem

When a tick is NOT quiescent, the sentinel is notified twice:

1. **Python-side** (`src/main.py`, line ~123): `notify_sentinel(state, result)` — 
   sends a structured JSON payload via `httpx.post()`.
2. **Shell-side** (`.github/workflows/cron.yml`, lines 258-277): `curl` POST — 
   sends a `jq`-constructed payload from `state/current.json`.

The shell-side has a hardcoded `"stateChanged": true` (line 262) regardless of 
whether the state actually changed. The Python-side correctly uses 
`tick_result.state_changed`.

### Root Cause

The shell step was the original notification mechanism. The Python-side was added 
later for reliability. The shell step was never removed.

### Impact

- Two POST requests to the Cloudflare Worker per active tick.
- The Worker receives potentially conflicting `stateChanged` values.
- Minor cost (two HTTP calls).

### Proposed Solution

Remove the shell-side sentinel notification from `cron.yml` entirely. The 
Python-side is more accurate, is already gated correctly, and fires on every 
tick (including quiescent ones for liveness).

After removing it, the sentinel step in cron.yml can be deleted. The quiescence 
gate we added becomes unnecessary for this step since the step itself is gone.

**Recommendation:** Remove the cron.yml "Notify sentinel" step entirely.

---

## Issue 4: `max_attempts` Retry Policy Not Enforced (MEDIUM)

**Category:** Pre-existing latent bug  
**Severity:** MEDIUM — not currently triggered, but violates declared contract

### Problem

`policy/plans/default.yaml` declares a retry policy (lines 123-129):

```yaml
failure_handling:
  retry_policy:
    max_attempts: 3
    backoff_seconds: 60
  on_exhausted:
    record_failure: true
    continue_execution: true
```

The tick engine (`src/engine/tick.py`) never reads `max_attempts`. The 
idempotency check (line 321) treats `ok` and `skipped` as terminal, but 
`failed` falls through — meaning a failed retryable action is re-attempted 
on every subsequent tick with no attempt counter and no limit.

### Current Exposure

None. No adapters are currently producing `failed` receipts in production. 
All actions either succeed (`ok`) or skip (`skipped`). But if an adapter 
starts failing, the action would retry indefinitely.

### What Would Be Needed

1. Add an `attempt_count` field to `ActionReceipt` in `src/models/state.py`.
2. In the tick engine's action loop (Phase 7), before executing a `failed` 
   action:
   - Read the existing receipt's `attempt_count`.
   - Compare against `policy.plan.failure_handling.retry_policy.max_attempts`.
   - If exhausted: mark as terminal (new status like `"exhausted"` or just 
     set status to `"failed"` with a flag), skip execution.
   - Otherwise: increment `attempt_count`, execute.

### Proposed Solution

Implement `max_attempts` enforcement. This requires:
- `src/models/state.py`: Add `attempt_count: int = 0` to `ActionReceipt`.
- `src/engine/tick.py`: Read max_attempts from plan, check count before 
  re-executing failed actions.
- `src/engine/tick.py`: Quiescence check should treat exhausted actions as 
  terminal.

**Recommendation:** Implement. Low risk, prevents a real problem.

---

## Issue 5: Audit Ledger Unbounded Growth (LOW)

**Category:** Pre-existing technical debt  
**Severity:** LOW — mitigated by quiescence optimization

### Problem

`audit/ledger.ndjson` is append-only with no rotation or archival mechanism 
(`src/persistence/audit.py`). Over time, the file grows without bound. This:

1. Increases git repository size with every commit.
2. Slows `git status`, `git add`, and `git push` as the file grows.
3. Makes audit inspection harder (grepping a large NDJSON file).

### Current Mitigation

The quiescence optimization significantly reduces audit growth:
- Quiescent ticks produce zero audit entries (buffer is discarded).
- Only active ticks (state changes, action executions) produce entries.
- In steady state (FULL, all actions terminal), zero audit growth.

### Remaining Exposure

When the system IS active (during escalation), audit entries accumulate. 
A typical active tick produces: tick_start + N×rule_matched + M×action_receipt 
+ tick_end = ~5-10 entries. Over a multi-day escalation with 48 ticks/day, 
this could be ~300-500 entries/day (~50-100KB/day).

### Proposed Solution

Implement audit rotation:
- After each active tick commit, if `audit/ledger.ndjson` exceeds N lines 
  (e.g., 1000), archive the older entries to `audit/archive/YYYY-MM.ndjson` 
  and truncate the ledger.
- The archive files are committed once and then don't change.
- Alternatively, implement a max-age policy: entries older than 30 days are 
  pruned.

**Recommendation:** Low priority. The quiescence fix already eliminates the 
main source of growth. Consider implementing when the system has been through 
several full escalation cycles and the ledger size is measurable.

---

## Summary Table

| # | Issue | Severity | Type | Blocks? |
|---|-------|----------|------|---------|
| 1 | Sentinel staleness false positive | **CRITICAL** | Regression | Yes — could cause false failover |
| 2 | Audit entry ordering | **HIGH** | Regression | No — cosmetic, but violates contract |
| 3 | Duplicate sentinel notification | **MEDIUM** | Pre-existing | No — wasteful but harmless |
| 4 | `max_attempts` not enforced | **MEDIUM** | Pre-existing | No — latent, not triggered |
| 5 | Audit ledger unbounded growth | **LOW** | Pre-existing | No — mitigated by quiescence |

## Recommended Priority Order

1. **Issue 1** (sentinel staleness) — must fix before deploying quiescence 
   optimization to production. Without this, the mirror will falsely promote 
   within ~2 hours of quiescence.
2. **Issue 2** (audit ordering) — should fix before deployment. Clean fix, 
   low risk, extends existing buffer mechanism.
3. **Issue 3** (duplicate sentinel) — fix during same deployment. Simple 
   removal of cron.yml step.
4. **Issue 4** (max_attempts) — separate deployment. Requires model change.
5. **Issue 5** (audit rotation) — backlog. Monitor first.
