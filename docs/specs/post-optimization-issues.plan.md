# Post-Optimization Issues — Implementation Plan

> Created: 2026-02-27  
> Depends on: tick-cost-optimization (all 6 steps complete)  
> Reference: post-optimization-issues.analysis.md  
> Status: **ALL STEPS COMPLETE** — 2026-02-27  
> Tests: 757 passed, 1 pre-existing failure (test_sms_adapter — unrelated)

---

## Dependency Order

```
Step 1: Fix sentinel payload (CRITICAL)  →  no deps
Step 2: Fix audit ordering (HIGH)        →  no deps
Step 3: Remove duplicate sentinel (MED)  →  depends on Step 1
Step 4: Update mirror sentinel (CRITICAL) → depends on Step 1
Step 5: max_attempts enforcement (MED)   →  no deps (separate deployment)
```

Steps 1, 2, 3, 4 should ship together as one deployment.  
Step 5 is independent and can follow separately.  
Issue 5 (audit rotation) is backlog — no step here.

---

## Step 1: Fix Sentinel Payload Timestamp

**Goal:** The Python-side sentinel notification must send a fresh timestamp  
on every tick, including quiescent ones, so the Worker knows the master is alive.

**File:** `src/sentinel/__init__.py`

### Current Code (line 59-68)

```python
payload = {
    "lastTickAt":      state.meta.updated_at_iso,   # ← STALE during quiescence
    "deadline":        state.timer.deadline_iso,
    "stage":           state.escalation.state,
    ...
}
```

### Proposed Change

```python
from datetime import datetime, timezone

payload = {
    "lastTickAt":      datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "lastStateChange": state.meta.updated_at_iso,
    "deadline":        state.timer.deadline_iso,
    "stage":           state.escalation.state,
    "stageEnteredAt":  state.escalation.state_entered_at_iso,
    "renewedThisTick": state.renewal.renewed_this_tick,
    "lastRenewalAt":   state.renewal.last_renewal_iso or "",
    "stateChanged":    tick_result.state_changed if tick_result else False,
    "quiescent":       tick_result.quiescent if tick_result else False,
    "version":         int(time.time()),
}
```

### What Changes

| Field | Before | After |
|-------|--------|-------|
| `lastTickAt` | `state.meta.updated_at_iso` (stale) | `datetime.now()` (always fresh) |
| `lastStateChange` | *(new)* | `state.meta.updated_at_iso` |
| `quiescent` | *(new)* | `tick_result.quiescent` |

### Impact on Cloudflare Worker

The Worker currently stores `lastTickAt` in KV. After this change:
- `lastTickAt` = "when did the master last run?" → always fresh (liveness)
- `lastStateChange` = "when did something actually change?" → context info

The Worker's `/status` endpoint (used by the admin dashboard) will expose
the fresh `lastTickAt`, which the mirror sentinel can use.

**Assumption:** The Worker stores whatever we send. If it already stores
`lastTickAt` and serves it via `/status`, this change is transparent. If
the Worker has validation that rejects unknown fields, the new
`lastStateChange` and `quiescent` fields need to be added to the Worker's
schema. **This should be verified.**

### Risk

- LOW: Payload shape change. The Worker may need a schema update.
- The `routes_secrets.py` `/sentinel/push-state` endpoint (line 530) also
  sends `lastTickAt: meta.updated_at_iso`. This is a manual recovery tool,
  not a tick path, but should be updated for consistency.

---

## Step 2: Fix Audit Entry Ordering

**Goal:** Audit entries must appear in chronological order:  
`tick_start → rule_matched → state_transition → action_receipt → tick_end`

**File:** `src/engine/tick.py`

### Current Problem

Two `state_transition` emits write directly to `audit_writer`:
1. Phase 5, line ~232: Rule-based state transition
2. Phase 5b, line ~276: `MANUAL_RELEASE` state transition

These bypass the `_audit_buffer` and appear BEFORE the buffered
`tick_start` and `rule_matched` entries in the ledger.

### Proposed Change

Route both `state_transition` emits through the buffer:

**Phase 5 (line ~231-240):**
```python
# Before:
if audit_writer:
    audit_writer.emit_state_transition(...)

# After:
if audit_writer:
    _audit_buffer.append((
        "state_transition",
        dict(
            tick_id=tick_id,
            state_id=state_id,
            from_state=previous_state,
            to_state=result.new_state,
            rule_id=matched[-1].id if matched else "unknown",
            policy_version=state.meta.policy_version,
            plan_id=state.meta.plan_id,
        ),
    ))
```

**Phase 5b (line ~275-284):** Same pattern for MANUAL_RELEASE transition.

**Phase 8 flush:** Extend the buffer dispatch to handle `state_transition`:
```python
for entry_type, entry_kwargs in _audit_buffer:
    if entry_type == "tick_start":
        audit_writer.emit_tick_start(**entry_kwargs)
    elif entry_type == "rule_matched":
        audit_writer.emit_rule_matched(**entry_kwargs)
    elif entry_type == "state_transition":
        audit_writer.emit_state_transition(**entry_kwargs)
```

### Risk

- LOW: Same pattern as existing buffer entries.
- Edge case: Phase 7 `action_receipt` entries (line ~403) are emitted 
  directly. They don't need buffering because Phase 7 only runs when not
  quiescent (the buffer WILL flush). They are emitted after the
  state_transition buffer entries, so ordering is correct:
  `tick_start, rule_matched, state_transition, action_receipt, tick_end`.

---

## Step 3: Remove Duplicate Sentinel Shell Step

**Goal:** Eliminate the redundant `cron.yml` sentinel notification.

**File:** `.github/workflows/cron.yml`

### What to Remove

Lines ~249-284 (the entire "Notify sentinel" step):

```yaml
      # ── Notify Sentinel ─────────────────────────────────────
      - name: Notify sentinel
        if: |
          steps.role.outputs.mirror_role != 'SLAVE' &&
          inputs.dry_run != 'true' &&
          steps.tick.outputs.quiescent != 'true'
        continue-on-error: true
        env:
          SENTINEL_URL: ${{ secrets.SENTINEL_URL }}
          SENTINEL_TOKEN: ${{ secrets.SENTINEL_TOKEN }}
        run: |
          if [ -n "$SENTINEL_URL" ]; then
            STATE_PAYLOAD=$(jq -c '{...}' state/current.json)
            RESP=$(curl ... "$STATE_PAYLOAD" ...)
            ...
          fi
```

### Why It's Safe

- The Python-side `notify_sentinel()` fires on every tick (line ~123 in 
  `main.py`), including quiescent ones.
- After Step 1, the Python-side sends a fresh timestamp.
- The shell step was redundant even before our optimization — it was a 
  belt-and-suspenders approach. With the Python-side correctly handling 
  liveness, the shell step provides no additional value.
- The shell step also had `"stateChanged": true` hardcoded, which was 
  always wrong for non-transition ticks.

### Risk

- LOW: Python-side notification is already in place.
- If `httpx` fails to import in CI (unlikely — it's in `[adapters]` 
  extras), sentinel notification would silently fail. But this is the 
  existing behavior — the Python-side was already the primary path.

---

## Step 4: Update Mirror Sentinel Health Check

**Goal:** The mirror's `sentinel.yml` must determine master liveness from
the Cloudflare Worker, not from the local (potentially stale) state file.

**File:** `.github/workflows/sentinel.yml`

### Current Check (Primary — lines 36-111)

```bash
# Read updated_at_iso from local state/current.json
UPDATED_AT=$(python3 -c "...state.get('meta', {}).get('updated_at_iso', '')...")
# Compare age against STALENESS_SECONDS (7200)
if [ "$AGE" -lt "${{ env.STALENESS_SECONDS }}" ]; then
    echo "healthy=true"
```

This breaks with quiescence because `updated_at_iso` stops updating AND
the state file stops being pushed to the mirror.

### Proposed Change

Replace the primary heartbeat check with a query to the Cloudflare Worker:

```bash
- name: Check master heartbeat
  if: env.MIRROR_ROLE == 'SLAVE'
  id: heartbeat
  run: |
    echo "🔍 Checking master heartbeat via Sentinel Worker..."
    
    # Primary check: Query the Cloudflare Worker for last-heard-from
    if [ -n "$SENTINEL_URL" ]; then
      WORKER_RESP=$(curl -s -m 5 \
        -H "Authorization: Bearer ${SENTINEL_TOKEN}" \
        "${SENTINEL_URL}/status" 2>/dev/null || echo "{}")
      
      LAST_TICK=$(echo "$WORKER_RESP" | python3 -c "
      import json, sys
      try:
          d = json.load(sys.stdin)
          print(d.get('lastTickAt', ''))
      except: print('')
      " 2>/dev/null)
      
      if [ -n "$LAST_TICK" ]; then
        AGE=$(python3 -c "
        from datetime import datetime, timezone
        ts = '$LAST_TICK'.replace('+00:00', 'Z').rstrip('Z')
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
            try:
                dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                print(int((datetime.now(timezone.utc) - dt).total_seconds()))
                break
            except ValueError: continue
        else: print(-1)
        ")
        
        echo "⏱️ Worker says last tick: ${AGE}s ago (threshold: ${{ env.STALENESS_SECONDS }}s)"
        
        if [ "$AGE" -ge 0 ] && [ "$AGE" -lt "${{ env.STALENESS_SECONDS }}" ]; then
          echo "✅ Master is alive (Worker heard from it ${AGE}s ago)"
          echo "healthy=true" >> $GITHUB_OUTPUT
          echo "source=worker" >> $GITHUB_OUTPUT
          echo "age=$AGE" >> $GITHUB_OUTPUT
          exit 0
        fi
      fi
      echo "⚠️ Worker check inconclusive, falling back to state file..."
    fi
    
    # Fallback: Check local state/current.json (pre-quiescence behavior)
    if [ -f "state/current.json" ]; then
      UPDATED_AT=$(python3 -c "
      import json
      with open('state/current.json') as f:
          print(json.load(f).get('meta', {}).get('updated_at_iso', ''))
      " 2>/dev/null)
      
      if [ -n "$UPDATED_AT" ]; then
        AGE=$(python3 -c "
        from datetime import datetime, timezone
        ts = '$UPDATED_AT'.replace('+00:00', 'Z').rstrip('Z')
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
            try:
                dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                print(int((datetime.now(timezone.utc) - dt).total_seconds()))
                break
            except ValueError: continue
        else: print(-1)
        ")
        
        if [ "$AGE" -ge 0 ] && [ "$AGE" -lt "${{ env.STALENESS_SECONDS }}" ]; then
          echo "✅ Master is alive (state file updated ${AGE}s ago)"
          echo "healthy=true" >> $GITHUB_OUTPUT
          echo "source=state_file" >> $GITHUB_OUTPUT
          echo "age=$AGE" >> $GITHUB_OUTPUT
          exit 0
        fi
        
        echo "⚠️ State file is stale (${AGE}s ago)"
      fi
    fi
    
    echo "⚠️ Master appears stale or unreachable"
    echo "healthy=false" >> $GITHUB_OUTPUT
    echo "reason=stale" >> $GITHUB_OUTPUT
  env:
    SENTINEL_URL: ${{ secrets.SENTINEL_URL }}
    SENTINEL_TOKEN: ${{ secrets.SENTINEL_TOKEN }}
```

### Key Design Decisions

1. **Worker is primary, state file is fallback.** Worker gets a fresh POST
   every 30 minutes (even during quiescence). State file only updates 
   during active ticks. If Worker is unreachable, fall back to state file.

2. **Same `STALENESS_SECONDS` threshold.** A miss of 2+ hours means 4+
   consecutive tick failures → genuine concern.

3. **Uses secrets that are already synced.** `SENTINEL_URL` and 
   `SENTINEL_TOKEN` are in the `SYNCABLE_SECRETS` list and pushed to the
   mirror by `mirror-sync`.

4. **`source` output for traceability.** Downstream steps can see whether
   liveness was determined from the Worker or the state file.

### Risk

- MEDIUM: The Worker must be reachable from GitHub Actions runners. If the
  Worker is down simultaneously with the master, the mirror correctly 
  promotes (this is desired behavior — redundancy).
- The Worker's `/status` endpoint must expose `lastTickAt`. Confirmed via
  admin panel code (`routes_core.py` line 682: 
  `resp = httpx.get(f"{url}/status", ...)`).

### Prerequisite

Step 1 must be deployed first (or simultaneously). The Worker must be
receiving fresh `lastTickAt` values from the Python-side POST before the
mirror starts relying on it.

---

## Step 5: Enforce `max_attempts` Retry Policy

**Goal:** Failed retryable actions must stop retrying after `max_attempts`.

**Files:** `src/models/state.py`, `src/engine/tick.py`

This is a separate deployment. Not coupled to Steps 1-4.

### 5a: Add attempt_count to ActionReceipt

**File:** `src/models/state.py`

```python
class ActionReceipt(BaseModel):
    status: str = ""
    last_delivery_id: Optional[str] = None
    last_executed_iso: Optional[str] = None
    attempt_count: int = 0  # ← NEW
```

### 5b: Read max_attempts from plan

**File:** `src/engine/tick.py` — Phase 7 action loop

Before executing a `failed` action, check:

```python
# In the action loop, after the idempotency check:
if action.id in state.actions.executed:
    prev = state.actions.executed[action.id]
    if prev.status in ("ok", "skipped"):
        logger.info(f"Skipping {action.id}: already {prev.status}")
        continue
    if prev.status == "failed":
        max_attempts = policy.plan.failure_handling.retry_policy.max_attempts
        if prev.attempt_count >= max_attempts:
            logger.warning(
                f"Skipping {action.id}: exhausted after {prev.attempt_count} attempts"
            )
            continue
```

After execution, record the attempt:

```python
state.actions.executed[action.id] = ActionReceipt(
    status=receipt.status,
    last_delivery_id=receipt.delivery_id,
    last_executed_iso=receipt.ts_iso,
    attempt_count=(
        state.actions.executed.get(action.id, ActionReceipt()).attempt_count + 1
        if receipt.status == "failed"
        else 0  # Reset on success/skip
    ),
)
```

### 5c: Quiescence check update

Treat exhausted (failed + max_attempts reached) as terminal:

```python
# In Phase 6b quiescence check:
if prev.status in ("ok", "skipped"):
    continue  # Terminal
if prev.status == "failed":
    max_attempts = policy.plan.failure_handling.retry_policy.max_attempts
    if prev.attempt_count >= max_attempts:
        continue  # Exhausted = terminal
```

### 5d: Model compatibility

The plan's `failure_handling` section needs to be parsed. Check if
`policy.plan.failure_handling` exists as a model:

**Check needed:** Does `src/policy/models.py` already parse
`failure_handling`? If not, add:

```python
class RetryPolicy(BaseModel):
    max_attempts: int = 3
    backoff_seconds: int = 60

class FailureHandling(BaseModel):
    retry_policy: RetryPolicy = RetryPolicy()
    on_exhausted: dict = {}

class Plan(BaseModel):
    ...
    failure_handling: FailureHandling = FailureHandling()
```

### Risk

- MEDIUM: Requires model migration. Existing state files without
  `attempt_count` will default to `0` (safe — Pydantic default).
- `failure_handling` parsing needs verification against the actual plan
  model.

---

## Summary

| Step | Severity | Files | Lines Changed | Risk |
|------|----------|-------|---------------|------|
| 1 | CRITICAL | `src/sentinel/__init__.py` | ~5 | LOW |
| 2 | HIGH | `src/engine/tick.py` | ~15 | LOW |
| 3 | MEDIUM | `.github/workflows/cron.yml` | -30 | LOW |
| 4 | CRITICAL | `.github/workflows/sentinel.yml` | ~50 | MEDIUM |
| 5 | MEDIUM | `src/models/state.py`, `src/engine/tick.py` | ~30 | MEDIUM |

### Deployment Groups

**Group A (ship together):** Steps 1 + 2 + 3 + 4  
- Fixes both regressions and the redundancy.
- All must ship before the quiescence optimization goes live.

**Group B (separate):** Step 5  
- Independent, not blocking. Ship when convenient.

**Backlog:** Audit rotation (Issue 5 from analysis)  
- Monitor audit growth after quiescence. Implement if needed.
