# Tick & Mirror Cost Optimization — Implementation Plan

> Status: **DRAFT — Pending approval**
> Analysis: `docs/specs/tick-cost-optimization.analysis.md`
> Created: 2026-02-27
> Target: 90% cost reduction for idle ticks

## Dependency Order

```
Step 1: Fix skipped-as-terminal (atomic, zero dependencies)
   ↓
Step 2: Fix R90 role (design decision, informs Step 3)
   ↓
Step 3: Tick quiescence detection (depends on Steps 1+2)
   ↓
Step 4: Audit control for idle ticks (depends on Step 3)
   ↓
Step 5: cron.yml pipeline gates (depends on Steps 3+4)
   ↓
Step 6: Mirror fingerprint-aware sync (independent, but last for defense-in-depth)
```

---

## Step 1: Treat `skipped` as Terminal in Idempotency Check

### Why First

This is a one-line bug fix with zero dependencies. It must come first because Step 3
(quiescence detection) needs all actions to reach proper terminal status before it
can determine "nothing to do." Right now `notify_all_webhooks` never reaches terminal
because `skipped` falls through the idempotency gate.

### File

`src/engine/tick.py`

### Current Code (lines 316-320)

```python
if action.id in state.actions.executed:
    prev = state.actions.executed[action.id]
    if prev.status == "ok":
        logger.info(f"Skipping {action.id}: already executed")
        continue
```

### Change

```python
if action.id in state.actions.executed:
    prev = state.actions.executed[action.id]
    if prev.status in ("ok", "skipped"):
        logger.info(f"Skipping {action.id}: already {prev.status}")
        continue
```

### What This Fixes

- `notify_all_webhooks` stops being re-attempted every tick.
- Its `last_executed_iso` stops being updated in the state file.
- The `action_receipt` audit entry for it stops being written.
- The state file has one fewer reason to change on every tick.

### What This Does NOT Fix

- The tick still runs full lifecycle (no quiescence yet).
- The audit still writes tick_start/rule_matched/tick_end.
- The state file still changes via `updated_at_iso`.
- The commit/mirror still run.

### Risks

- If someone later configures webhook URLs, the action won't re-fire because it's
  already marked `skipped` in state. This is the correct behavior — the action was
  evaluated for this escalation cycle and determined to be not applicable.
  A `reset` or `renew` clears all action receipts, at which point the action
  would be re-evaluated with the new configuration.

### Latent Issue to Note (not in scope)

The plan defines `failure_handling.retry_policy.max_attempts: 3` but this is never
enforced by the engine. A `failed` action with `retryable: true` would be
re-attempted infinitely. No actions are currently in `failed` status, so this is
not active, but it should be tracked separately.

---

## Step 2: Clarify R90_ENFORCE_MONOTONIC's Role

### Why Before Quiescence

Step 3 (quiescence) needs to know: when R90 is the only matched rule, does that
mean "nothing to do" or does it mean "important safety work happened"? We need
to resolve this before we can define quiescence correctly.

### Current Reality

R90 is defined in `policy/rules.yaml`:

```yaml
- id: R90_ENFORCE_MONOTONIC
  when:
    always: true
  then:
    enforce:
      monotonic_state_progression: true
  stop: false
```

Facts:
- `enforce:` is never processed by the engine (`src/engine/state.py` only handles
  `set_state`, `set`, `clear`).
- `monotonic_enforced: true` is a static field on the state model
  (`src/models/state.py` line 72), not controlled by R90.
- R90 matches every tick, gets audited, has zero effect on state.
- The monotonic guarantee is already structurally enforced by the escalation rules:
  R10-R30 all use `state_is`/`state_in` conditions that only allow forward transitions.

### Decision Needed

**Option A — Remove R90 from rules.yaml.**
- The monotonic guarantee is structural (rules can only escalate, never downgrade).
- R90 adds noise — it creates audit entries that say "safety rule matched" when it
  did nothing.
- The `monotonic_enforced: true` flag on the state model stays (it's a declaration,
  not something R90 controls).

**Option B — Keep R90 but make it conditional.**
- Change `when: always: true` to something like `when: state_not_in: [FULL]`
  so it only matches during active escalation, not at terminal state.
- This preserves the safety-net intent while eliminating the terminal-state noise.

**Option C — Keep R90 as-is, handle it in quiescence logic.**
- Step 3's quiescence check treats R90 as a known no-op:
  if the only matched rule is R90, that counts as "nothing to do."
- R90 stays in the rules for documentation/intent purposes.

### Recommendation

Option C. R90 is harmless once quiescence handles it. Removing it (Option A) loses
the declarative intent. Making it conditional (Option B) is a rules-level optimization
that quiescence makes unnecessary. The engine should be smart enough to know R90 alone
means idle.

### Files

- `policy/rules.yaml` — no change if Option C
- `src/engine/tick.py` — Step 3 will reference R90's semantics

---

## Step 3: Tick Quiescence Detection

### Why

This is the core fix. Once the tick can detect "nothing to do," every downstream
step can be gated on that signal.

### What Changes

#### 3a. Add `quiescent` flag to TickResult

**File:** `src/engine/tick.py`

Add to `TickResult` dataclass:

```python
@dataclass
class TickResult:
    # ... existing fields ...

    # Quiescence: True when the tick determined there was nothing to do.
    # Conditions: no state transition, all selected actions are terminal.
    quiescent: bool = False
```

#### 3b. Detect quiescence after action selection

**File:** `src/engine/tick.py` — between Phase 6 (action selection) and Phase 7
(adapter execution)

After the tick selects actions for the current stage, check:

1. `state_changed == False` (no transition occurred)
2. For every action in `actions_for_stage`: the action is either:
   - Disabled in the plan (`action.enabled == False`), or
   - Already terminal in state (`state.actions.executed[action.id].status in ("ok", "skipped")`)

If both conditions are true → set `result.quiescent = True`.

```python
# --- Phase 6b: Quiescence Check ---
if not result.state_changed and not dry_run:
    all_terminal = True
    for action in actions_for_stage:
        if not action.enabled:
            continue  # Disabled actions don't count
        if action.id in state.actions.executed:
            prev = state.actions.executed[action.id]
            if prev.status in ("ok", "skipped"):
                continue  # Terminal
        # Found a non-terminal action
        all_terminal = False
        break

    if all_terminal:
        result.quiescent = True
        logger.info("Tick is quiescent — nothing to do")
```

#### 3c. Skip adapter execution when quiescent

When `result.quiescent == True`, skip Phase 7 entirely:

```python
# --- Phase 7: Adapter Execution ---
if not dry_run and actions_for_stage and not result.quiescent:
    # ... existing adapter execution loop ...
```

This prevents any adapter calls, any receipt updates, any state mutations.

#### 3d. Skip state persistence when quiescent

**File:** `src/main.py` — `tick()` command

The CLI `tick` command currently always saves state (line 105: `save_state(state, state_path)`).
When quiescent, don't save — the state file should not change:

```python
if not dry_run:
    if result.quiescent:
        click.secho("✓ Quiescent — no changes to persist", fg="cyan")
    else:
        click.echo(f"\nSaving state to {state_path}")
        save_state(state, state_path)
        click.secho("✓ State persisted", fg="green")

    # Notify sentinel (fire-and-forget) — always, for liveness
    from .sentinel import notify_sentinel
    if notify_sentinel(state, result):
        click.secho("✓ Sentinel notified", fg="green")
```

Note: sentinel notification still happens. It's a lightweight HTTP call and provides
liveness monitoring. The sentinel should know the system is alive even when idle.

### What This Achieves

- When quiescent: no adapter calls, no state file mutation, no state save.
- `state/current.json` does not change on disk.
- Combined with Step 1: no action receipts are updated either.
- The tick becomes a lightweight check: load state → evaluate rules → "nothing to do" → done.

### What Remains

- Audit entries are still written (tick_start, rule_matched, tick_end) — addressed in Step 4.
- `cron.yml` doesn't know about quiescence yet — addressed in Step 5.
- `updated_at_iso` is NOT bumped when quiescent. This is intentional — the field means
  "last time something meaningful happened." Liveness is tracked by the sentinel.

---

## Step 4: Audit Control for Idle Ticks

### Why

Even with quiescence detection, the audit writer currently emits 3+ entries per tick
(tick_start, rule_matched, tick_end). These entries cause `audit/ledger.ndjson` to
change on every tick, which triggers git commits even when the tick was idle.

### What Changes

#### 4a. Skip full audit when quiescent

**File:** `src/engine/tick.py`

When `result.quiescent == True`, skip the tick_start, rule_matched, and tick_end
audit entries entirely. The audit ledger should not grow with entries that say
"nothing happened."

The quiescence check happens at Phase 6b (after rule evaluation, after action selection).
But tick_start is emitted at Phase 1, before we know if the tick is quiescent.

**Solution:** Defer audit writes.

Currently:
- `tick_start` emitted immediately (line 168)
- `rule_matched` emitted during rule evaluation (line 198)
- `tick_end` emitted at finalization (line 409)

Change to:
- Collect audit entries in a buffer during the tick.
- At finalization, if quiescent → don't flush.
- If not quiescent → flush all buffered entries to the audit writer.

Alternative (simpler): pass the `quiescent` flag back and let `main.py` decide
whether to create the `AuditWriter` at all. But this doesn't work because we don't
know quiescence until after rules run, and audit entries are emitted during rules.

**Recommended approach:** Add a `suppress_on_quiescent` mode to the audit writer,
or buffer entries in `run_tick()` and only flush at the end.

```python
# At the start of run_tick:
pending_audit_entries = []

# Replace direct audit_writer.emit_* calls with:
pending_audit_entries.append(("tick_start", {...}))

# At finalization:
if not result.quiescent and audit_writer:
    for entry_type, entry_data in pending_audit_entries:
        audit_writer.emit(entry_type, **entry_data)
```

#### 4b. What about audit completeness?

Concern: skipping audit for idle ticks means the ledger has gaps. Someone reading
the ledger can't tell if the system was running or not during a gap.

This is acceptable because:
- Sentinel provides liveness monitoring (independent of audit).
- The last `tick_end` entry in the ledger shows the state was `FULL` with
  `state_changed: false` — that's sufficient to know the system was idle.
- An optional periodic heartbeat entry could be added (e.g., once per hour)
  to confirm liveness in the audit trail, without writing entries every 30 minutes.

### What This Achieves

- `audit/ledger.ndjson` stops growing when the system is quiescent.
- Combined with Step 3: both `state/` and `audit/` are untouched during idle ticks.
- `git status --porcelain state/ audit/` returns empty → commit step finds nothing → skips.

---

## Step 5: cron.yml Pipeline Gates

### Why

Even with the engine-level fixes (Steps 1-4), the `cron.yml` pipeline structure needs
to respect the tick's output. Currently it has no mechanism to read the tick result
and gate downstream steps.

### What Changes

#### 5a. Tick command outputs quiescence signal

**File:** `src/main.py` — `tick()` command

After the tick runs, write a GitHub Actions output variable:

```python
# After tick runs, output for GitHub Actions
import os
github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a") as f:
        f.write(f"quiescent={'true' if result.quiescent else 'false'}\n")
        f.write(f"state_changed={'true' if result.state_changed else 'false'}\n")
```

This makes `steps.tick.outputs.quiescent` and `steps.tick.outputs.state_changed`
available to subsequent steps in the workflow.

#### 5b. Gate commit step on non-quiescence

**File:** `.github/workflows/cron.yml`

Current condition (line 145):
```yaml
if: steps.role.outputs.mirror_role != 'SLAVE' && inputs.dry_run != 'true'
```

New condition:
```yaml
if: |
  steps.role.outputs.mirror_role != 'SLAVE' &&
  inputs.dry_run != 'true' &&
  steps.tick.outputs.quiescent != 'true'
```

#### 5c. Gate mirror sync on non-quiescence

**File:** `.github/workflows/cron.yml`

Current condition (lines 204-207):
```yaml
if: |
  steps.role.outputs.mirror_role != 'SLAVE' &&
  inputs.dry_run != 'true' &&
  vars.MIRROR_ENABLED == 'true'
```

New condition:
```yaml
if: |
  steps.role.outputs.mirror_role != 'SLAVE' &&
  inputs.dry_run != 'true' &&
  vars.MIRROR_ENABLED == 'true' &&
  steps.tick.outputs.quiescent != 'true'
```

#### 5d. Sentinel notify — keep or gate?

**Observation:** Sentinel is notified in TWO places:
1. `src/main.py` line 108-111 — Python-level, inside the tick command
2. `.github/workflows/cron.yml` lines 245-277 — shell-level, after commit

The Python-level notify (1) happens regardless of quiescence (per Step 3d design).
The shell-level notify (2) in cron.yml is redundant — it does the same thing as (1)
but with a `jq` + `curl` pipeline.

**Change:** Gate the cron.yml sentinel step on non-quiescence too, since the
Python-level notify already handles it:

```yaml
if: |
  steps.role.outputs.mirror_role != 'SLAVE' &&
  inputs.dry_run != 'true' &&
  steps.tick.outputs.quiescent != 'true'
```

When quiescent, only the Python-side sentinel notify fires (lightweight, 3s timeout).
When active, both fire (belt-and-suspenders for reliability).

### What This Achieves

When quiescent:
- ❌ Commit step: skipped (no file changes anyway, but now explicitly gated)
- ❌ Mirror sync: skipped entirely
- ❌ cron.yml sentinel step: skipped (Python-side already sent it)
- ❌ Site build: already skipped (existing gate on `state_changed`)
- ❌ Deploy: already skipped
- ✅ Tick runs (lightweight check)
- ✅ Python-side sentinel: fires (liveness)

The runner still spins up, installs, and runs the tick. But the tick itself is fast
(~100ms), and everything after it is skipped. The runner cost drops from ~3-5 minutes
to ~1-2 minutes (dominated by setup, not by our code).

---

## Step 6: Mirror Fingerprint-Aware Sync

### Why

This is defense in depth. After Steps 1-5, mirror sync won't run during quiescent
ticks. But when it DOES run (active ticks with real state changes), it should still
skip layers where nothing changed. If someone changes a secret but the state also
changed, the tick is not quiescent, mirror sync runs, but only the changed secrets
should actually sync.

### What Changes

#### 6a. Skip secrets sync when fingerprint matches

**File:** `src/cli/mirror.py` — `mirror_sync()` command, secrets block (lines 191-232)

Before iterating over secrets, check fingerprint:

```python
# --- SECRETS ---
if sync_all or secrets_only:
    from ..mirror.github_sync import (
        RENAMED_SECRETS, SYNCABLE_SECRETS,
        secrets_fingerprint, sync_secret,
    )

    mirror_num = mirror.id.replace("mirror-", "")
    current_fp = secrets_fingerprint(mirror_num)

    # Skip if fingerprint matches — nothing changed
    if slave.secrets.status == "ok" and slave.secrets.fingerprint == current_fp:
        emit({"step": "secrets", "status": "ok",
              "detail": "unchanged (fingerprint match)",
              "progress": "skipped", "mirror_id": mirror.id})
    else:
        # ... existing sync loop ...
```

#### 6b. Skip variables sync when fingerprint matches

**File:** `src/cli/mirror.py` — `mirror_sync()` command, variables block (lines 234-271)

Same pattern:

```python
# --- VARIABLES ---
if sync_all or vars_only:
    from ..mirror.github_sync import sync_variable, variables_fingerprint

    current_fp = variables_fingerprint()

    if slave.variables.status == "ok" and slave.variables.fingerprint == current_fp:
        emit({"step": "variables", "status": "ok",
              "detail": "unchanged (fingerprint match)",
              "progress": "skipped", "mirror_id": mirror.id})
    else:
        # ... existing sync loop ...
```

#### 6c. Skip code push when HEAD matches stored commit

**File:** `src/cli/mirror.py` — `mirror_sync()` command, code block (lines 177-188)

```python
# --- CODE ---
if sync_all or code_only:
    import subprocess
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5, cwd=str(root)
    ).stdout.strip()[:12]

    if slave.code.status == "ok" and slave.code.detail == head:
        emit({"step": "code", "status": "ok",
              "detail": f"unchanged ({head})",
              "mirror_id": mirror.id})
    else:
        # ... existing push logic ...
```

### What This Achieves

Even when mirror sync runs (non-quiescent tick), individual layers skip if unchanged:
- Secrets fingerprint match → 0 `gh secret set` calls instead of 16+
- Variables fingerprint match → 0 `gh variable set` calls instead of 5+
- HEAD matches → 0 `git push` calls

This brings mirror sync from ~70 seconds down to ~0.1 seconds when nothing changed
in the specific layer being synced.

---

## Execution Summary

| Step | Issue | Scope | Files | Risk |
|------|-------|-------|-------|------|
| 1 | `skipped` not terminal | Bug fix | `tick.py` | Very low |
| 2 | R90 role | Design decision | None (if Option C) | None |
| 3 | Quiescence detection | New feature | `tick.py`, `main.py` | Medium — behavioral change |
| 4 | Audit control | Enhancement | `tick.py` | Low — audit gaps acceptable |
| 5 | Pipeline gates | Enhancement | `main.py`, `cron.yml` | Low — gates are additive |
| 6 | Mirror fingerprint | Enhancement | `cli/mirror.py` | Low — skip logic is safe |

## Expected Cost Impact

| Metric | Before | After |
|--------|--------|-------|
| Tick duration (idle) | ~3-5 min | ~1-2 min (setup only) |
| State file changes per idle tick | 2+ fields | 0 |
| Audit entries per idle tick | 4+ | 0 |
| Git commits per idle tick | 1 | 0 |
| Mirror API calls per idle tick | 21+ subprocess calls | 0 |
| Mirror sync duration per idle tick | ~70s | 0 |
| Sentinel notifications per idle tick | 2 (duplicate) | 1 (Python-side only) |

Runner setup time (~1-2 min) remains. This is the floor — the cron schedule causes
the runner to spin up regardless. But all meaningful compute and API calls are eliminated.

### Reduction Estimate

Active compute per idle tick drops from ~180s to ~5s → **97% reduction in billable work**.
Total runner time drops from ~3-5 min to ~1-2 min → **50-60% reduction in runner minutes**.
GitHub API calls drop from ~21/tick to 0/tick → **100% reduction in API pressure**.

Combined with the fact that idle ticks are the vast majority of all ticks once the
system reaches FULL: overall cost reduction target of **90%** is achievable.
