# adapters

## Purpose

Adapters are the integration layer of continuity-orchestrator.

The engine:
- evaluates policy
- chooses actions from a plan
- sends each action to an adapter

Adapters:
- perform the external side effect
- return a normalized receipt
- never decide escalation logic

All adapter behavior is:
- deterministic given inputs
- auditable
- idempotent through action receipts

---

## Adapter Interface

Each adapter implements:

- name
- enabled check
- validate(action, context)
- execute(action, context) -> receipt

Where:
- action is a plan action entry
- context includes state, policy versions, stage, routing, and tick metadata
- receipt is written into:
  - audit ledger
  - state actions.executed map for idempotency

---

## Common Payload Model

Every action execution receives a normalized payload object:

payload
- meta
  - tick_id
  - state_id
  - policy_version
  - plan_id
  - escalation_state
  - now_iso
- action
  - action_id
  - stage
  - adapter
  - channel
  - template or payload reference
  - constraints
- routing
  - operator_email
  - operator_sms
  - custodian_emails
  - observer_webhooks
  - reddit_targets
  - x_account_ref
- data
  - time_to_deadline_minutes
  - overdue_minutes
  - failed_attempts
  - lockout_active
  - last_renewal_iso

---

## Receipt Format

Every adapter returns a receipt with the same structure:

receipt
- status
  - ok
  - skipped
  - failed
- adapter
- action_id
- channel
- delivery_id
- ts_iso
- details
- error
  - code
  - message
  - retryable
  - retry_in_seconds

Receipt rules:
- delivery_id is required for ok, optional otherwise
- skipped is used when:
  - adapter disabled
  - action already executed (idempotency)
  - constraints prevent execution
- failed must include error fields

---

## Idempotency Contract

The engine must ensure:
- an action_id is executed at most once per stage unless configured otherwise

Mechanism:
- state actions.executed stores:
  - last_executed_iso
  - status
  - last_delivery_id

Before executing:
- if actions.executed contains action_id with status ok, skip

If an action is retryable and failed:
- retry policy is controlled by plan failure_handling
- retries must still produce receipts per attempt

---

## Constraints Contract

Plans can specify constraints to enforce in adapters.

Common constraints:
- no_links
- no_entrypoint_reference
- limited_scope
- visibility public or private
- max_length for posts
- allow_mentions false

Adapters must validate constraints before sending.

If constraints cannot be met:
- return skipped with error.code constraint_violation

---

## Adapter List

continuity-orchestrator supports these adapter names in plans:

- email
- sms
- x
- reddit
- webhook
- github_surface
- article_publish
- persistence_api

Adapters are optional and can be disabled by environment toggles.
A disabled adapter must return skipped receipts, not errors.

---

## Adapter Responsibilities

### email adapter
Goal:
- send operator reminders and custodian notices

Inputs:
- template name
- recipients from routing fields

Rules:
- operator reminders must enforce:
  - no_links true
  - no_entrypoint_reference true

Receipt:
- delivery_id is message id

### sms adapter
Goal:
- send short operator reminders

Rules:
- no_links and no_entrypoint_reference must be enforced

Receipt:
- delivery_id is provider message id

### x adapter
Goal:
- publish public notices

Rules:
- respect max_length
- avoid including any renewal entry point
- allow staging by stage templates

Receipt:
- delivery_id is post id

### reddit adapter
Goal:
- publish public notices to configured targets

Rules:
- target list from routing reddit_targets
- content controlled by template

Receipt:
- delivery_id is post or comment id

### webhook adapter
Goal:
- send structured signals to observers

Inputs:
- payload name such as pre_release_signal or full_release_signal

Receipt:
- delivery_id is request id or response hash

### github_surface adapter
Goal:
- create or update visible artifacts on a GitHub surface

Artifacts:
- documents
- bundles
- releases
- site updates

Receipt:
- delivery_id is artifact reference such as release tag, page path, or document id

### article_publish adapter
Goal:
- publish long-form content to a configured endpoint

Receipt:
- delivery_id is article id or URL reference string

### persistence_api adapter
Goal:
- write state snapshots, receipts, and pointers to a custom persistence backend

Receipt:
- delivery_id is persistence record id

---

## Templates and Content

Templates are referenced by name in plans.
They are resolved by the engine from a templates directory.

Template resolution must support:
- operator reminder templates
- custodian notice templates
- public notice templates
- full release templates
- article templates

Template rendering inputs:
- meta
- stage
- safe timing data
- optional static content blocks
