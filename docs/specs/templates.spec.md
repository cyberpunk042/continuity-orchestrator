# templates

## Purpose

Templates define all human-readable content emitted by continuity-orchestrator.

They control:
- wording
- tone
- structure
- safety guarantees

Templates contain **no logic**.
They are resolved and rendered by the engine using a fixed input context.

---

## Design Rules

Templates must obey these rules:

- No template may include a renewal entry point
- No template may include a link or identifier to a confirmation mechanism
- Operator reminders must be informational only
- Public templates must be stage-appropriate and scoped
- Templates must be deterministic for a given input

Templates are versioned implicitly through repository history.

---

## Template Categories

Templates are grouped by intent, not by adapter.

### Operator Reminder Templates
Used only in REMIND stages.

Examples:
- reminder_basic
- reminder_strong
- reminder_sms

Characteristics:
- short
- neutral
- no links
- no calls to action beyond “renew using your offline procedure”

---

### Custodian / Observer Templates
Used in PRE_RELEASE and higher stages.

Examples:
- pre_release_notice
- escalation_notice

Characteristics:
- factual
- time-bounded
- no speculation
- no sensitive payloads

---

### Public Notice Templates
Used in PARTIAL and FULL stages.

Examples:
- partial_notice
- full_release

Characteristics:
- scoped to the stage
- avoid absolute claims
- may reference that further material exists without linking renewal mechanisms

---

### Article Templates
Used only in FULL stage.

Examples:
- full_article

Characteristics:
- long-form
- structured
- may reference documents or artifacts published via GitHub surface adapter
- never references the operator or renewal mechanics

---

## Template Resolution

Templates are referenced by name in plans.

Resolution order:
1. stage-specific override
2. plan-level template
3. default template

If a template cannot be resolved:
- the action is skipped
- a constraint_violation receipt is recorded

---

## Rendering Context

Templates receive a read-only context object:

meta
- project
- plan_id
- policy_version
- tick_id
- now_iso

stage
- name
- entered_at_iso

time
- time_to_deadline_minutes
- overdue_minutes

signals
- escalation_state
- mode_name

safe_fields
- static labels
- predefined text blocks
- whitelisted references

No template receives:
- secrets
- entry points
- internal routing identifiers

---

## Example Templates (Illustrative)

### reminder_basic

Subject:
Status reminder

Body:
This is a scheduled reminder.
Please complete your renewal using your offline procedure.
No action is required if already completed.

---

### reminder_strong

Subject:
Action required

Body:
This is a follow-up reminder.
If renewal is not completed before the configured deadline, escalation will proceed automatically.

---

### partial_notice

Body:
A previously configured continuity process has entered an automated phase.
Additional information may become available if escalation continues.

---

### full_release

Body:
This publication marks the final execution stage of a preconfigured continuity process.
Associated documents and artifacts are now available through public channels.

---

### full_article

Title:
Continuity Execution Summary

Body:
This article consolidates materials released as part of an automated continuity process.
The process operated according to predeclared rules and timelines.
All artifacts referenced here were generated automatically.

---

## Safety Guarantees

The template system enforces:

- no accidental leakage of renewal paths
- no dynamic content injection
- no adaptive messaging

Templates are static inputs rendered with bounded data.

---

## Where Templates Live

Proposed layout:

templates
- operator
  - reminder_basic.md
  - reminder_strong.md
  - reminder_sms.txt
- custodians
  - pre_release_notice.md
- public
  - partial_notice.md
  - full_release.md
- articles
  - full_article.md

The engine treats all templates as data.

