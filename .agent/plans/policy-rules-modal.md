# Implementation Plan — Policy Rules Control (3 Phases)

## The Big Picture

The policy system is built from **three interdependent files**:

```
policy/
├── states.yaml      ← State machine: OK → REMIND_1 → REMIND_2 → PRE_RELEASE → PARTIAL → FULL
├── rules.yaml       ← Transition logic: WHEN (conditions) → THEN (escalate)
│   ├── constants    ← Timing values (6 numbers that control all delays)
│   └── rules[]      ← Individual transition rules (R00-R90)
└── plans/
    └── default.yaml ← Actions per stage: WHO gets notified, HOW
```

**These three files are tightly coupled.** You can't just delete a rule from `rules.yaml`
without considering whether `states.yaml` still references that state, and whether
`plans/default.yaml` still has actions for it.

### What "add/remove" really means

There are **two levels** of control:

1. **Constants** — The 6 timing values. Changing `remind_1_at_minutes: 360` to `0` effectively
   makes REMIND_1 unreachable (the window collapses). This is the safest way to "disable" a stage.
   
2. **Rules** — The actual enable/disable of a transition rule. If you disable `R10_ESCALATE_TO_REMIND_1`,
   the system skips from OK straight to REMIND_2 (or wherever the next matching rule fires).
   More powerful but requires understanding the flow.

3. **States + Plans** — Full structural control: add a new state, remove an existing one,
   define new actions. This is the deepest level — effectively a policy editor.

### Phased Approach (iterate up)

| Phase | Scope | What you can do |
|-------|-------|-----------------|
| **Phase 1** | Constants + Rule enable/disable | Edit timing values, toggle rules on/off |
| **Phase 2** | Full rule editor | Add custom rules, modify conditions |
| **Phase 3** | State/plan editor | Add/remove stages, configure actions |

We build Phase 1 now. Phase 2-3 come later.

---

## Phase 1 Design

### What the modal looks like

```
┌──────────────────────────────────────────────────────────────────┐
│ 📋 Escalation Policy                                      [✕]   │
│                                                                  │
│ ┌─ Presets ───────────────────────────────────────────────────┐  │
│ │ [Default ▼]                           [Apply]              │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ═══ Timing Constants ═══════════════════════════════════════════ │
│                                                                  │
│ ┌─ Reminders (before deadline) ───────────────────────────────┐ │
│ │ 1st reminder ............... [360] min before  (= 6h)       │ │
│ │ 2nd reminder ............... [ 60] min before  (= 1h)       │ │
│ │ Final warning .............. [ 15] min before               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ Disclosure (after deadline) ───────────────────────────────┐ │
│ │ Partial delay .............. [  0] min after   (immediate)  │ │
│ │ Full delay ................. [120] min after   (= 2h)       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ Security ──────────────────────────────────────────────────┐ │
│ │ Max failed attempts ........ [  3]                          │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ═══ Rules (toggle on/off) ══════════════════════════════════════ │
│                                                                  │
│  ☑ R00  Renewal resets to OK                 (always)  🔒       │
│  ☑ R01  Lockout after max failed attempts    (always)  🔒       │
│  ☑ R10  Escalate to REMIND_1        T-360min → T-60min          │
│  ☑ R11  Escalate to REMIND_2        T-60min → T-15min           │
│  ☑ R12  Escalate to PRE_RELEASE     T-15min → T+0               │
│  ☑ R20  Escalate to PARTIAL         T+0min → ...                │
│  ☑ R30  Escalate to FULL            T+120min → ...              │
│  ☑ R90  Enforce monotonic progression        (always)  🔒       │
│                                                                  │
│ 🔒 = locked (cannot be disabled — system integrity rule)         │
│                                                                  │
│ ┌─ Visual Timeline ───────────────────────────────────────────┐ │
│ │  ─OK──┤──R1──┤──R2──┤──PRE──┤──PART──┤──FULL               │ │
│ │       -6h    -1h   -15m    T=0      +2h                    │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                             [Cancel]  [💾 Save & Apply]          │
│  ☐ Git sync after change                                        │
└──────────────────────────────────────────────────────────────────┘
```

### Presets

| Preset | Values | Description |
|--------|--------|-------------|
| **Default** | 360/60/15/0/120/3 | Standard escalation |
| **Testing (fast)** | 5/2/1/0/1/3 | Quick cycle for dev |
| **Direct to FULL** | 0/0/0/0/0/3 | Skip reminders, immediate FULL on overdue |
| **Gentle (slow ramp)** | 1440/360/60/30/240/5 | 24h ramp with extended delays |

### Architecture (following project rules)

```
CLI command ← API (subprocess) ← UI modal
```

#### 1. CLI Command: `policy-constants`

```bash
# Read current constants + rule status
python -m src.main policy-constants --json

# Update constants
python -m src.main policy-constants --set remind_1_at_minutes=120 --set full_after_overdue_minutes=60

# Toggle a rule
python -m src.main policy-constants --disable R10_ESCALATE_TO_REMIND_1
python -m src.main policy-constants --enable R10_ESCALATE_TO_REMIND_1

# Apply a preset
python -m src.main policy-constants --preset testing
```

**Output (JSON mode):**
```json
{
  "constants": {
    "remind_1_at_minutes": 360,
    "remind_2_at_minutes": 60,
    ...
  },
  "rules": [
    {"id": "R00_RENEWAL_SUCCESS_RESETS", "enabled": true, "locked": true, "description": "..."},
    {"id": "R10_ESCALATE_TO_REMIND_1", "enabled": true, "locked": false, "description": "..."},
    ...
  ]
}
```

**How rules are disabled:** Add `enabled: false` to the rule in `rules.yaml`.
The engine's `evaluate_rules()` skips rules with `enabled: false`.
This is the minimal YAML change that preserves the rule definition for re-enabling.

**Locked rules** (R00, R01, R90) cannot be disabled — they protect system integrity.

#### 2. API Endpoints

```python
# In routes_core.py (same blueprint, same pattern as /api/state/*)

GET  /api/policy/constants    → subprocess: policy-constants --json
POST /api/policy/constants    → subprocess: policy-constants --set KEY=VALUE [--disable R10] ...
```

#### 3. UI (HTML in partials, JS in scripts)

**HTML:** Add button + modal to `partials/_tab_debugging.html`
**JS:** Add functions to `scripts/_wizard.html` (same file as resetState, factoryReset, etc.)

---

## Backup/Export Integration

### Current state
- `create_backup_archive()` backs up: state, audit, content (articles + media)
- `restore_from_archive()` restores: state, audit, content
- **Policy files are NOT included**

### What needs to change

Policy files should be included as an **optional component** in backups, just like content.

```python
# New options in create_backup_archive():
include_policy: bool = False

# Adds to archive:
#   policy/rules.yaml
#   policy/states.yaml
#   policy/plans/default.yaml
```

And in the UI backup modal (`openBackupModal()`), add a Policy checkbox:

```
☑ State (state/current.json)
☑ Audit (audit/ledger.ndjson)
☐ Articles (N files)
☐ Media (N files, M KB)
☐ Policy (rules.yaml, states.yaml, plans/default.yaml)   ← NEW
```

### Where this hooks in

| File | Change |
|------|--------|
| `src/cli/backup.py` → `create_backup_archive()` | Add `include_policy` param, pack `policy/` |
| `src/cli/backup.py` → `restore_from_archive()` | Add `restore_policy` param, extract `policy/` |
| `src/cli/backup.py` → `backup_export` CLI | Add `--include-policy` flag |
| `src/cli/backup.py` → `backup_restore` CLI | Add `--restore-policy` flag |
| `src/admin/routes_backup.py` (or wherever backup API lives) | Pass `include_policy` through |
| `scripts/_wizard.html` → `openBackupModal()` | Add policy checkbox |
| `partials/_tab_debugging.html` → backup modal HTML | Add policy checkbox UI |

**This is a separate, follow-up change** — not part of Phase 1 core.
It should be done after the modal is working, as a "complete the integration" step.

---

## Policy Scaffold / Template

### Current state
- `init` command creates: state, audit, content manifest
- Policy files (`rules.yaml`, `states.yaml`, `plans/default.yaml`) ship with the repo
- There is no `scaffold` for policy — if you delete `rules.yaml`, things break

### What should exist
A "reset policy to defaults" action, analogous to content scaffold.
Useful after an accidental bad edit or as a "factory reset for rules only".

**Implementation:** Add to the policy-constants CLI:
```bash
python -m src.main policy-constants --reset-defaults
```
This copies a template `rules.yaml` from an embedded resource or generates it programmatically.

**In the modal:** The "Default" preset + Save effectively does this.
But a dedicated "Reset to factory policy" button could be added in Phase 2.

---

## Execution Plan (for Phase 1)

### Step 1: Engine change — support `enabled: false` in rules
**File:** `src/engine/rules.py` → `evaluate_rules()`

```python
for rule in rules_policy.rules:
    if not getattr(rule, 'enabled', True):  # skip disabled rules
        continue
    if evaluate_rule(rule, state, rules_policy.constants):
        ...
```

**File:** `src/policy/models.py` → `Rule` class

```python
class Rule(BaseModel):
    id: str
    description: str
    when: Dict[str, Any]
    then: Dict[str, Any]
    stop: bool = False
    enabled: bool = True      # ← NEW field
```

### Step 2: CLI command (`src/cli/policy.py`)

New file implementing `policy-constants` click command.

Operations:
- `--json`: Read constants + rules status, output JSON
- `--set KEY=VALUE`: Update constant(s)
- `--enable RULE_ID` / `--disable RULE_ID`: Toggle rule
- `--preset NAME`: Apply preset values

YAML round-trip: Use `pyyaml` — read, modify dict, write.
Comments will be lost on modified sections, but that's acceptable for constants block.

### Step 3: Register CLI command
**File:** `src/main.py`

```python
from .cli.policy import policy_constants
cli.add_command(policy_constants)
```

### Step 4: API endpoints
**File:** `src/admin/routes_core.py`

Two endpoints following the exact same subprocess pattern as `/api/state/reset`.

### Step 5: UI — Button + Modal HTML
**File:** `src/admin/templates/partials/_tab_debugging.html`

Button in State Controls section + modal HTML after the factory-reset modal.

### Step 6: UI — JavaScript
**File:** `src/admin/templates/scripts/_wizard.html`

Functions: `openPolicyModal()`, `closePolicyModal()`, `loadPolicyConstants()`,
`applyPolicyPreset()`, `savePolicyConstants()`, `renderPolicyTimeline()`.

### Files Changed Summary

| # | File | Change |
|---|------|--------|
| 1 | `src/policy/models.py` | Add `enabled: bool = True` to `Rule` |
| 2 | `src/engine/rules.py` | Skip disabled rules in `evaluate_rules()` |
| 3 | `src/cli/policy.py` | **NEW** — CLI command |
| 4 | `src/main.py` | Register command |
| 5 | `src/admin/routes_core.py` | 2 API endpoints |
| 6 | `partials/_tab_debugging.html` | Button + modal HTML |
| 7 | `scripts/_wizard.html` | JS functions |

### Validation checklist (from /before-any-change)

- [x] No new env vars needed (local files only)
- [x] Server uses subprocess only (no domain imports)
- [x] CLI command exists in main.py
- [x] Every JS function called from HTML exists in scripts/
- [x] No `<script>` tags in scripts/ files
- [x] Following same modal pattern as Factory Reset
- [x] No cron.yml changes needed (local admin panel feature)
- [x] Policy files committed to git → pipeline reads same rules.yaml

---

## Phase 2 (future): Full Rule Editor
- Add/edit individual rules (conditions + actions)
- Visual condition builder
- Rule reordering
- Add policy to backup/export/import

## Phase 3 (future): State/Plan Editor
- Add/remove escalation states
- Configure actions per stage
- Adapter configuration per action
