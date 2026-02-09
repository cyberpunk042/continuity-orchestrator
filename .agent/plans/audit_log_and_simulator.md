# Implementation Plan: Audit Log Viewer + What-If Simulator

> **Created**: 2026-02-09
> **Status**: Ready to build
> **Scope**: ~520 lines across 6-8 files

---

## Feature 1: Audit Log Viewer

### Overview
A new modal in the admin dashboard that surfaces the append-only NDJSON audit trail
(`audit/ledger.ndjson`) as a searchable, filterable, color-coded event log.

### Files to Create / Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/admin/routes_core.py` | **Modify** | Add `GET /api/audit` endpoint |
| `src/admin/templates/modals/_audit_log.html` | **Create** | Modal HTML shell |
| `src/admin/templates/scripts/modals/_audit_log.js.html` | **Create** | Fetch, filter, render logic |
| `src/admin/templates/partials/_tab_debugging.html` | **Modify** | Add `📋 Audit Log` button to State Controls card |
| `src/admin/templates/partials/_tab_debugging.html` | **Modify** | Add `{% include "modals/_audit_log.html" %}` |
| `src/admin/templates/scripts/_wizard.html` | **Modify** | Add `{% include "scripts/modals/_audit_log.js.html" %}` |

### Step 1a: Backend — `GET /api/audit`

Add to `routes_core.py`:

```python
@core_bp.route("/api/audit")
def api_audit():
    """Read audit log and return normalized entries."""
    project_root = _project_root()
    audit_path = project_root / "audit" / "ledger.ndjson"
    limit = request.args.get("limit", 500, type=int)

    if not audit_path.exists():
        return jsonify({"entries": [], "total": 0, "summary": {}})

    entries = []
    for line in audit_path.read_text().strip().splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Normalize both schemas into one shape
        entry = {
            "timestamp": raw.get("ts_iso") or raw.get("timestamp", ""),
            "event_id":  raw.get("event_id", ""),
            "tick_id":   raw.get("tick_id", ""),
            "type":      raw.get("type") or raw.get("event_type", "unknown"),
            "level":     raw.get("level", "info"),
            "state":     raw.get("escalation_state")
                         or raw.get("new_state")
                         or raw.get("previous_state", ""),
            "details":   raw.get("details", {}),
        }

        # Merge top-level fields from old-format events into details
        skip = {"ts_iso","timestamp","event_id","tick_id","type","event_type",
                "level","escalation_state","state_id","policy_version","plan_id"}
        for k, v in raw.items():
            if k not in skip and k not in entry["details"]:
                entry["details"][k] = v

        entries.append(entry)

    # Reverse chronological
    entries.reverse()

    # Summary stats
    types = [e["type"] for e in entries]
    summary = {
        "total_events": len(entries),
        "total_ticks": types.count("tick_end"),
        "total_renewals": types.count("renewal"),
        "total_transitions": types.count("state_transition"),
        "total_releases": sum(1 for t in types if t in ("manual_release",)),
        "total_resets": sum(1 for t in types if t in ("factory_reset",)),
    }

    # Find latest timestamps
    for e in entries:
        if e["type"] == "tick_end" and "last_tick_at" not in summary:
            summary["last_tick_at"] = e["timestamp"]
        if e["type"] == "renewal" and "last_renewal_at" not in summary:
            summary["last_renewal_at"] = e["timestamp"]

    return jsonify({
        "entries": entries[:limit],
        "total": len(entries),
        "summary": summary,
    })
```

### Step 1b: Modal HTML — `modals/_audit_log.html`

Follow existing modal pattern (backup/factory-reset/policy):
- `display:none; position:fixed; inset:0; z-index:9999`
- Blur backdrop, click-outside-to-close
- `max-width: 700px` (wider than other modals — log data needs space)

Layout sections:
1. **Header**: `📋 Audit Log` + subtitle with event count + last tick time
2. **Summary cards**: 4 inline mini-cards (Ticks, Renewals, Transitions, Releases) — color-coded counts
3. **Filter bar**: Type dropdown + search input + refresh button
4. **Event list**: Scrollable container (`max-height: 50vh; overflow-y: auto`)
5. **Footer**: Close button

### Step 1c: Modal JS — `scripts/modals/_audit_log.js.html`

Functions:
- `openAuditLogModal()` — fetch `/api/audit`, populate summary, render list
- `closeAuditLogModal()` — hide modal
- `filterAuditEvents()` — client-side filter by type dropdown + search text
- `renderAuditEvents(entries)` — build HTML rows
- `toggleAuditDetail(eventId)` — expand/collapse detail JSON

Event row design:
```
[icon] [HH:MM] [type badge] [state badge] [summary text] [▸]
```

Color mapping:
| Type | Icon | Badge color |
|------|------|-------------|
| `tick_start`/`tick_end` | 🔄 | `--text-dim` (subtle gray) |
| `rule_matched` | ⚡ | `--warning` (amber) |
| `state_transition` | 🔀 | `--info` (blue) |
| `renewal` | ✅ | `--success` (green) |
| `manual_release` | 🔴 | `--error` (red) |
| `factory_reset` | 🗑️ | `--text-dim` (gray) |

Expanded detail: nested card with `<pre>` showing the full details JSON, plus tick_id and event_id.

### Step 1d: Wire into templates

In `_tab_debugging.html` State Controls card, add button:
```html
<button class="btn" onclick="openAuditLogModal()" style="width: 100%; margin-top: 0.25rem;">
    📋 Audit Log
</button>
```

At bottom of `_tab_debugging.html`, add include:
```html
{% include "modals/_audit_log.html" %}
```

In `scripts/_wizard.html`, add include near other modal JS:
```html
{% include "scripts/modals/_audit_log.js.html" %}
```

---

## Feature 2: What-If Tick Simulator

### Overview
A real simulation that runs the engine forward in time using actual policy rules,
showing exactly when each escalation stage would trigger if the user doesn't renew.

### Files to Create / Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/cli/deploy.py` | **Modify** | Rewrite `simulate_timeline()` to use real engine evaluation |
| `src/admin/routes_core.py` | **Modify** | Add `POST /api/simulate` endpoint |
| `src/admin/templates/modals/_simulator.html` | **Create** | Simulator modal HTML |
| `src/admin/templates/scripts/modals/_simulator.js.html` | **Create** | Simulation UI logic |
| `src/admin/templates/partials/_tab_commands.html` | **Modify** | Add `⏩ What-If...` button to Preview card |

### Step 2a: Rewrite CLI simulation — `src/cli/deploy.py`

Replace the current hardcoded `simulate_timeline()` with real engine evaluation:

```python
def _run_simulation(state, policy_dir, hours=72, step_minutes=30):
    """Run simulated ticks forward in time and return transition events."""
    import copy
    from ..persistence.state_file import load_state
    from ..policy.loader import load_policy
    from ..engine.rules import evaluate_rules
    from ..engine.time_eval import compute_time_fields

    policy = load_policy(policy_dir)
    sim_state = copy.deepcopy(state)
    now = datetime.now(timezone.utc)

    events = []
    current_stage = sim_state.escalation.state

    for minute in range(0, hours * 60 + 1, step_minutes):
        sim_time = now + timedelta(minutes=minute)

        # Recompute time fields
        compute_time_fields(sim_state, sim_time)

        # Evaluate rules
        matched = evaluate_rules(sim_state, policy.rules)

        # Apply state mutations from matched rules
        for rule in matched:
            new_stage = rule.then.get("set_state") or rule.then.get("escalation.state")
            if new_stage and new_stage != sim_state.escalation.state:
                old = sim_state.escalation.state
                sim_state.escalation.state = new_stage
                events.append({
                    "minute": minute,
                    "time": sim_time.isoformat(),
                    "from_state": old,
                    "to_state": new_stage,
                    "rule": rule.id,
                })

    return {
        "simulation": {
            "from": now.isoformat(),
            "to": (now + timedelta(hours=hours)).isoformat(),
            "current_state": state.escalation.state,
            "deadline": state.timer.deadline_iso,
            "hours": hours,
        },
        "events": events,
    }
```

Keep the existing CLI output format but use this function internally.
Add `--json` flag for machine-readable output.

NOTE: The actual mutation logic may need adjustment based on how `rule.then`
is structured. Need to study `src/engine/state.py` `apply_rules()` for the
exact mutation format. The key insight is that we only care about state
transitions, not adapter execution.

### Step 2b: API endpoint — `POST /api/simulate`

Add to `routes_core.py`:

```python
@core_bp.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Run escalation simulation and return timeline."""
    project_root = _project_root()
    data = request.json or {}
    hours = min(data.get("hours", 72), 720)  # Cap at 30 days

    state = load_state(project_root / "state" / "current.json")
    result = _run_simulation(state, project_root / "policy", hours=hours)
    return jsonify(result)
```

### Step 2c: Simulator UI

**Entry point**: New button in `_tab_commands.html` Preview card:
```html
<button class="btn" onclick="openSimulatorModal()" style="width: 100%;">
    ⏩ What-If Simulator
</button>
```

**Modal** (`modals/_simulator.html`):
- Compact — `max-width: 640px`
- Duration picker: pill-style toggle buttons (24h / 48h / 72h / 1 week)
- Auto-runs simulation on open with default 72h
- Re-runs on duration change (no explicit "Run" button needed)

Layout:
```
┌──────────────────────────────────────────────────────┐
│  ⏩ What-If Simulator                                │
│  "What happens if you don't renew?"                  │
│                                                      │
│  Duration: [24h] [48h] [●72h●] [1 week]             │
│                                                      │
│  ┌─ Timeline Bar ──────────────────────────────────┐ │
│  │  (reuses policy modal's visual language)        │ │
│  │  color-coded segments with NOW cursor           │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─ Transition Events ─────────────────────────────┐ │
│  │  Each row: date/time · from → to · rule · Δtime │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ⚠️ FULL disclosure in ~48h 53m if not renewed      │
│                                              [Close] │
└──────────────────────────────────────────────────────┘
```

**Timeline bar**: Reuse `renderPolicyTimeline()` visual approach but driven by
simulation data rather than constant inputs. Each segment's width is proportional
to the actual time spent in that state.

**Event list**: Each row is a card-style element:
```
  📅 Tue 11 Feb 03:53 UTC
  OK → REMIND_1  (rule R10)
  ⏱ in 42h from now
```

**Footer warning**: Bold, color-coded summary:
- 🟢 "System stays OK for the full simulation window" (if no transitions)
- 🟡 "First reminder in 42h 53m" (if transitions but no FULL)
- 🔴 "FULL disclosure in 48h 53m if not renewed" (if FULL reached)

---

## Implementation Order

| # | Task | Est. lines | Depends on |
|---|------|-----------|------------|
| 1a | `GET /api/audit` endpoint | ~60 | — |
| 1b | `_audit_log.html` modal HTML | ~110 | — |
| 1c | `_audit_log.js.html` modal JS | ~160 | 1a |
| 1d | Wire includes + button | ~6 | 1b, 1c |
| 2a | Rewrite `simulate_timeline` + `_run_simulation()` | ~100 | — |
| 2b | `POST /api/simulate` endpoint | ~25 | 2a |
| 2c | `_simulator.html` + `_simulator.js.html` | ~150 | 2b |
| 2d | Wire includes + button | ~6 | 2c |

**Feature 1 total**: ~336 lines
**Feature 2 total**: ~281 lines

### Testing

Both features need tests:
- `test_routes_core.py`: Add tests for `GET /api/audit` (empty log, populated log, normalization)
- `test_routes_core.py`: Add tests for `POST /api/simulate` (basic simulation, duration capping)

---

## Design Decisions

1. **Modal vs Inline**: Audit Log is a modal because it's a "reference view" you open, browse, and close.
   Simulator could be either — went with modal for consistency, but it's compact.

2. **Client-side filtering**: The audit log loads all entries (up to 500) and filters in JS.
   For a personal project with ~33K events/year max, this is fine. No pagination needed.

3. **Real simulation vs hardcoded**: The current `simulate` CLI is fake (hardcoded stage list).
   We replace it with real engine evaluation to make results accurate and policy-dependent.

4. **Shared timeline visual**: The simulator reuses the policy modal's timeline bar aesthetic
   so users see a familiar visual language.
