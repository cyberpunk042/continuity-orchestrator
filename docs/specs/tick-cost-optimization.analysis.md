# Tick & Mirror Cost Optimization — Analysis

> Status: **DRAFT — Discussion document**
> Created: 2026-02-27
> Last updated: 2026-02-27

## Context

The orchestration system runs a cron tick every 30 minutes via `.github/workflows/cron.yml`.
Once the system reaches its terminal escalation state (`FULL`) and all configured integrations
have succeeded (or been permanently skipped), the tick continues to run the full pipeline
producing zero value. Six distinct issues compound to create this waste.

---

## Issue 1: R90_ENFORCE_MONOTONIC Is a No-Op That Always Matches

### Where

- `policy/rules.yaml` lines 129–136
- `src/engine/rules.py` — `evaluate_rules()` always matches it
- `src/engine/state.py` — `apply_rule_mutation()` never processes its `enforce:` directive

### What Happens

R90 is defined as:

```yaml
- id: R90_ENFORCE_MONOTONIC
  when:
    always: true
  then:
    enforce:
      monotonic_state_progression: true
  stop: false
```

- `always: true` → matches on every tick, unconditionally.
- `stop: false` → does not terminate rule evaluation (irrelevant since it's the last rule).
- Its `then:` block uses `enforce:` — but the engine only processes `set_state`, `set`, and `clear`
  in `apply_rule_mutation()` (`state.py` lines 114–138). `enforce:` is **never handled**.
- Confirmed: `grep -r "enforce" src/engine/` returns zero hits.
  `grep -r "monotonic" src/engine/` also returns zero hits.
- The rule's description says "handled by engine" but no code implements it.

### Consequence

- R90 matches every tick, gets audited as `rule_matched`, but has **zero effect** on state.
- Once the system is at `FULL`, R90 is the **only** rule that matches (all escalation rules
  require `state_is: OK` or `state_in: [OK, REMIND_1, ...]`).
- Every tick's `matched_rules` list is `["R90_ENFORCE_MONOTONIC"]` — this creates audit entries
  that create file changes that create commits that trigger downstream work.

### Root Cause

The monotonic enforcement is a design intent documented in the rule but never implemented
in the engine. The `monotonic_enforced: true` field in `state.escalation` is a static flag
set at init time (`src/models/state.py` line 72), not something R90 controls.

---

## Issue 2: The Tick Engine Has No Quiescence Detection

### Where

- `src/engine/tick.py` — `run_tick()` function (lines 93–437)

### What Happens

`run_tick()` always executes the full lifecycle:

1. Initialize context (reset ephemeral flags, sync env vars)
2. Emit `tick_start` audit entry
3. Compute time fields
4. Evaluate rules
5. Apply mutations
6. Select actions for current stage
7. Loop through actions (check idempotency, execute if needed)
8. Emit `tick_end` audit entry

There is no checkpoint that says: "Nothing can change. Short-circuit."

Even when:
- No state transition occurred (`state_changed: false`)
- All selected actions are already terminal (`ok` or `skipped`)
- The only matched rule was the no-op R90

...the tick still:
- Writes `tick_start` + `rule_matched` + `tick_end` to the audit ledger (3 entries minimum)
- Updates `state.meta.updated_at_iso` (mutates the state file)
- Returns a result, which the caller treats as a normal completed tick

### Consequence

- The state file changes every tick (`updated_at_iso`) even when nothing meaningful happened.
- The audit file grows by 3+ entries every tick.
- These file changes guarantee that `git status --porcelain state/ audit/` always shows changes,
  which triggers the commit step, which triggers mirror sync.
- There is no signal to the caller (CLI/cron) that the tick was idle.

---

## Issue 3: `skipped` Is Not Treated as a Terminal Status

### Where

- `src/engine/tick.py` lines 316–320 (idempotency check)
- `src/adapters/registry.py` line 213–219 (`execute_action` returns `Receipt.skipped()`)
- `src/adapters/webhook.py` line 88 (webhook adapter returns `skipped` when no URLs configured)
- `state/current.json` — `notify_all_webhooks` has `status: "skipped"`

### What Happens

The idempotency check in `tick.py`:

```python
if action.id in state.actions.executed:
    prev = state.actions.executed[action.id]
    if prev.status == "ok":
        logger.info(f"Skipping {action.id}: already executed")
        continue
```

Only `"ok"` is recognized as terminal. When `prev.status == "skipped"`, the check falls through
and the action is re-attempted.

The `notify_all_webhooks` action flow on each tick:

1. Idempotency check: `status == "skipped"` → not `"ok"` → **falls through**
2. `action.enabled` check: `True` (no `enabled: false` in the plan) → proceeds
3. Registry `execute_action()`:
   - `adapter.is_enabled()`: returns `False` (no observer webhooks configured)
   - Returns `Receipt.skipped(reason="adapter_disabled")`
4. Receipt stored: `state.actions.executed["notify_all_webhooks"]` updated with new `last_executed_iso`
5. `actions_executed` list grows by 1

### Consequence

- `notify_all_webhooks` is re-attempted and re-skipped every single tick, forever.
- Each re-skip updates `last_executed_iso` in the state file → state file changes → commit → mirror.
- The audit writes an `action_receipt` entry for each re-skip → audit file changes too.
- Current state shows: `"last_executed_iso": "2026-02-27T17:05:21.980913+00:00"` — less than an
  hour ago — confirming this is actively happening.

### What About `failed`?

The plan declares `failure_handling.retry_policy.max_attempts: 3`, but this policy is never read
or enforced by the tick engine. `grep -r "max_attempts" src/engine/` returns zero hits.
A `failed` action with `retryable: true` is also re-attempted indefinitely because the
idempotency check only considers `"ok"`. However, in the current state no actions are in
`"failed"` status, so this is a latent problem, not an active one.

---

## Issue 4: Audit Entries Are Written for No-Op Ticks

### Where

- `src/engine/tick.py` — `tick_start` (line 168), `rule_matched` (line 198), `tick_end` (line 409)
- `src/persistence/audit.py` — `AuditWriter`
- `audit/ledger.ndjson` — grows by 3+ lines per tick

### What Happens

Every tick emits at minimum:

```
{"type": "tick_start", ...}
{"type": "rule_matched", "details": {"rule_id": "R90_ENFORCE_MONOTONIC"}}
{"type": "tick_end", "details": {"actions_executed": 0, "state_changed": false, ...}}
```

Plus an `action_receipt` entry for the `notify_all_webhooks` re-skip (Issue 3).

These entries are appended to `audit/ledger.ndjson` before the commit step runs.

### Consequence

- `audit/ledger.ndjson` grows indefinitely with entries that say "nothing happened."
- Since the file always changes, `git status --porcelain audit/` always shows modifications.
- Combined with `state/current.json` always changing (Issue 2: `updated_at_iso` bump),
  the commit step in `cron.yml` (line 147: `if git status --porcelain state/ audit/ | grep -q .`)
  **always succeeds**.
- This guarantees a new commit every tick → triggers all downstream steps.

### Chain Reaction

```
tick writes no-op audit → audit file changes → commit step finds changes →
  commit + push → mirror sync runs → secrets/variables/code re-synced →
  sentinel notified → cost accumulates
```

---

## Issue 5: Mirror Sync Re-Syncs Unchanged Values

### Where

- `.github/workflows/cron.yml` lines 203–240 (mirror sync step)
- `src/cli/mirror.py` — `mirror_sync()` command (lines 113–273)
- `src/mirror/github_sync.py` — `sync_secret()`, `sync_variable()` (individual subprocess calls)
- `src/mirror/git_sync.py` — `push_to_mirror()` (`git push --force`)

### What Happens

The `mirror-sync` command unconditionally performs three operations:

**Code push (`git push --force`):**
- Runs even when git reports "Everything up-to-date"
- The mirror state already stores the last synced commit hash in `slave.code.detail`
- This hash is never compared against current HEAD before pushing

**Secrets sync (all SYNCABLE_SECRETS — 16+ values):**
- Every secret is set via a subprocess call: `gh secret set SECRET_NAME -R repo`
- Each call takes ~2-5 seconds (HTTP round-trip to GitHub API)
- 16 secrets × ~3s = ~48 seconds per tick just for secrets
- The fingerprinting function `secrets_fingerprint()` exists in `github_sync.py` (line 116)
- The `SyncStatus.fingerprint` field exists and is populated after a successful sync
- But `mirror-sync` **never reads the stored fingerprint** before syncing — it always syncs everything

**Variables sync (5+ values):**
- Same pattern: each variable set via subprocess call
- Fingerprinting exists (`variables_fingerprint()`, line 132) but never consulted

### Existing Infrastructure Not Used

```python
# github_sync.py — these exist but are only used by mirror-status, NOT mirror-sync:
def secrets_fingerprint(mirror_num: str = "1") -> str: ...
def variables_fingerprint() -> str: ...

# mirror/state.py — SyncStatus has:
fingerprint: Optional[str] = None  # hash of synced values (for staleness detection)
```

The `mirror-status` command uses these to detect staleness (lines 51-60 of `cli/mirror.py`).
The `mirror-sync` command ignores them entirely.

### Consequence

Per tick with mirroring enabled:
- 1 `git push --force` subprocess (~5-10s)
- 16+ `gh secret set` subprocess calls (~48s)
- 5+ `gh variable set` subprocess calls (~15s)
- Total: ~70+ seconds of subprocess overhead per tick
- At 48 ticks/day: **56+ minutes of pure API calls/day** doing nothing useful

---

## Issue 6: The cron.yml Pipeline Has No Meaningful Gates

### Where

- `.github/workflows/cron.yml` — step conditions (lines 97–340)

### What Happens

Pipeline flow and conditions:

| Step | Condition | Runs When Idle? |
|------|-----------|-----------------|
| Run tick | `mirror_role != SLAVE` | ✅ Always |
| Commit state/audit | `mirror_role != SLAVE && !dry_run` | ✅ Always (audit always changes) |
| Mirror sync | `mirror_role != SLAVE && !dry_run && MIRROR_ENABLED` | ✅ Always |
| Sentinel notify | `mirror_role != SLAVE && !dry_run` | ✅ Always |
| Build site | `state_changed == true OR force_deploy` | ❌ Correctly skipped |
| Deploy pages | `site_built == true` | ❌ Correctly skipped |

The site build step is the **only** one with a meaningful gate based on tick results.
The commit step checks for file changes in `state/` and `audit/`, but these always exist
(Issue 4). Mirror sync has no gate at all. Sentinel notify has no gate.

### Consequence

Even when the tick had nothing to do, the pipeline:
1. Spins up a runner (~30-60s)
2. Installs Python + uv + package (~30-60s)
3. Runs the full tick (~2-5s)
4. Commits audit entries for the no-op tick (~5s)
5. Pushes to origin (~5s)
6. Runs full mirror sync (~70s of subprocess calls)
7. Notifies sentinel (~2s)

Total per idle tick: ~3-5 minutes of runner time.
At 48 ticks/day: **2.5-4 hours of runner time/day** producing zero value.

---

## How the Issues Compound

```
Issue 1 (R90 always matches)
  + Issue 2 (no quiescence detection)
  = Tick always runs full pipeline, always writes to audit
  
  + Issue 3 (skipped not terminal)
  = notify_all_webhooks re-attempted every tick, mutates state file
  
  + Issue 4 (audit entries for no-ops)
  = Both state/ and audit/ always show git changes
  
  + Issue 6 (no pipeline gates)
  = Commit always runs, push always happens
  
  + Issue 5 (mirror re-syncs unchanged values)
  = 16+ secrets + 5+ variables re-set every tick via individual API calls
```

Each issue is independently fixable, but they form a chain where each one
feeds into the next. Fixing any single issue reduces cost, but fixing all six
eliminates the waste entirely.

---

## Summary of Issues

| # | Issue | Type | Where | Active Now? |
|---|-------|------|-------|-------------|
| 1 | R90 `enforce:` never implemented; always matches as no-op | Design gap | `policy/rules.yaml`, `src/engine/state.py` | ✅ Yes |
| 2 | Tick has no quiescence detection; always runs full lifecycle | Missing feature | `src/engine/tick.py` | ✅ Yes |
| 3 | `skipped` not treated as terminal; action re-attempted forever | Bug | `src/engine/tick.py` line 318 | ✅ Yes |
| 4 | Audit entries written for no-op ticks; files always change | Design gap | `src/engine/tick.py`, `src/persistence/audit.py` | ✅ Yes |
| 5 | Mirror sync ignores existing fingerprint infrastructure | Missing feature | `src/cli/mirror.py`, `src/mirror/github_sync.py` | ✅ Yes |
| 6 | cron.yml has no gates between tick result and downstream steps | Missing feature | `.github/workflows/cron.yml` | ✅ Yes |

---

## Notes for Solution Design

> **This section is a placeholder. The actual solution plan will be drafted after discussion.**

Points established so far:

- The tick should check if there's anything to do. If there isn't, it should signal that clearly.
- `skipped` is terminal — same as `ok` for idempotency purposes.
- Mirror sync should use existing fingerprint infrastructure to skip unchanged sync layers.
- The cron pipeline needs gates that respect the tick's "nothing to do" signal.
- Audit should not grow with entries that say "nothing happened."
- The target is 90% cost reduction.

### Open Questions

1. Should the tick still bump `updated_at_iso` when idle? (heartbeat value vs file-change cost)
2. Should `failed` with `retryable: true` also have max-attempt enforcement? (latent issue)
3. What should the sentinel receive when the tick is idle? (monitoring visibility)
4. Does R90 need to exist at all if its `enforce:` directive is never processed?
