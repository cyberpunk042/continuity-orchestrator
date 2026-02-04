# engine

## Purpose

The engine is the deterministic core of continuity-orchestrator.

It:
- loads state
- loads policy
- evaluates rules
- transitions escalation state
- selects actions from the active plan
- executes adapters
- records audit entries
- persists updated state

The engine does not contain business intent.
All intent lives in configuration.

---

## Tick Lifecycle

Each scheduled run is a tick.

A tick is:
- isolated
- repeatable
- auditable
- idempotent

Tick phases execute in a fixed order.

---

## Phase 1: Initialization

Inputs:
- state/current.json
- policy files
- runtime configuration
- current timestamp

Actions:
- generate tick_id
- stamp now_iso
- validate state schema
- validate policy versions

Failures here abort the tick and emit an error audit entry.

---

## Phase 2: Time Evaluation

The engine computes time-derived fields:

- time_to_deadline_minutes
- overdue_minutes
- grace handling

Rules:
- now_iso is authoritative for the tick
- overdue_minutes never goes negative
- grace_minutes delays overdue calculations if configured

Results are written to in-memory state only.

---

## Phase 3: Renewal and Security Evaluation

The engine evaluates renewal and security flags:

- renewed_this_tick
- failed_attempts
- lockout_active
- lockout_until_iso

Rules:
- lockout suppresses renewal acceptance
- failed attempts increment only on invalid renewal attempts
- renewal success clears failed attempts unless policy says otherwise

No external actions occur in this phase.

---

## Phase 4: Policy Evaluation

Rules are evaluated in declared order.

For each rule:
- evaluate conditions against current in-memory state
- if matched:
  - apply mutations
  - emit rule_matched audit entry
  - honor stop behavior

Constraints:
- monotonic escalation is enforced unless explicitly overridden
- only one state transition is allowed per tick

The resulting escalation state becomes authoritative for the remainder of the tick.

---

## Phase 5: Action Selection

Based on:
- current escalation state
- active plan
- adapter enablement
- idempotency records

The engine builds an ordered action list.

Rules:
- only actions for the active stage are considered
- actions already executed with status ok are skipped
- skipped actions still produce receipts

Action order:
- reminders
- notifications
- public dissemination
- persistence and mirrors

Order is deterministic.

---

## Phase 6: Adapter Execution

For each selected action:

1. Validate adapter enabled
2. Validate constraints
3. Build normalized payload
4. Execute adapter
5. Capture receipt
6. Append receipt to audit
7. Update state actions.executed

Failures:
- retryable failures follow plan retry policy
- non-retryable failures are logged and execution continues
- adapter failures never stop the tick unless explicitly fatal

---

## Phase 7: Persistence

After all actions:

- write updated state to primary persistence backend
- mirror state to repository if configured
- emit persistence_write audit entry

Persistence failures:
- are logged
- do not roll back executed actions
- may trigger warnings

---

## Phase 8: Finalization

The engine emits:
- tick_end audit entry
- summary metrics:
  - duration
  - actions attempted
  - actions succeeded
  - actions failed
  - state transitions

The tick then terminates.

---

## Determinism Guarantees

Given:
- identical state
- identical policy
- identical time input

The engine will:
- select the same rules
- choose the same actions
- execute adapters in the same order

External side effects may vary, but decisions do not.

---

## Error Handling Philosophy

Errors are:
- recorded
- localized
- non-blocking by default

The system prefers partial execution over silence.

Only these abort a tick:
- unreadable state
- unreadable policy
- invalid schema
- unrecoverable engine error

---

## State Mutation Rules

During a tick:
- state mutations are staged in memory
- only the final state is persisted

Allowed mutations:
- escalation.state
- escalation.state_entered_at_iso
- security counters
- action receipts
- timestamps

Disallowed mutations:
- policy definitions
- plan definitions
- adapter lists

---

## Audit Emission Rules

Every significant step emits an audit entry.

Minimum per tick:
- tick_start
- zero or more rule_matched
- zero or more action_attempt
- zero or
