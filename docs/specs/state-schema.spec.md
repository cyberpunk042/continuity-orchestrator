# state/current.json

## Purpose

This file represents the current runtime state of continuity-orchestrator.
It is the single input/output of each tick.

- The engine reads it at the start of a run
- Applies policy and actions
- Writes it back at the end of a run

It is designed to be:
- deterministic
- auditable
- portable across persistence backends

---

## Schema Overview

Top-level fields:

- meta
- mode
- timer
- renewal
- security
- escalation
- actions
- integrations
- pointers

---

## Field Definitions

meta
- schema_version: integer
- project: string
- state_id: string (opaque identifier for this state record)
- updated_at_iso: string (ISO-8601)
- policy_version: integer
- plan_id: string

mode
- name: string
  - renewable_countdown
  - one_way_fuse
  - manual_arm
- armed: boolean

timer
- deadline_iso: string (ISO-8601)
- grace_minutes: integer
- now_iso: string (ISO-8601, set each tick)
- time_to_deadline_minutes: integer
- overdue_minutes: integer

renewal
- last_renewal_iso: string (ISO-8601)
- renewed_this_tick: boolean
- renewal_count: integer

security
- failed_attempts: integer
- lockout_active: boolean
- lockout_until_iso: string or null (ISO-8601)
- max_failed_attempts: integer
- attempt_window_seconds: integer

escalation
- state: string
  - OK
  - REMIND_1
  - REMIND_2
  - PRE_RELEASE
  - PARTIAL
  - FULL
- state_entered_at_iso: string (ISO-8601)
- last_transition_rule_id: string or null
- monotonic_enforced: boolean

actions
- executed
  - map of action_id to receipt summary
  - used for idempotency so the same stage action does not re-run
- last_tick_actions
  - list of action_id executed during the current tick

integrations
- enabled_adapters
  - email: boolean
  - sms: boolean
  - x: boolean
  - reddit: boolean
  - webhook: boolean
  - github_surface: boolean
  - article_publish: boolean
  - persistence_api: boolean
- routing
  - operator_email: string
  - operator_sms: string
  - custodian_emails: list of strings
  - observer_webhooks: list of strings
  - reddit_targets: list of strings
  - x_account_ref: string

pointers
- persistence
  - primary_backend: string
  - last_persist_iso: string or null
- github_surface
  - last_public_artifact_ref: string or null

---

## Example current.json

{
    "meta": {
        "schema_version": 1,
        "project": "continuity-orchestrator",
        "state_id": "S-0001",
        "updated_at_iso": "2026-02-04T17:00:00Z",
        "policy_version": 1,
        "plan_id": "default"
    },
    "mode": {
        "name": "renewable_countdown",
        "armed": true
    },
    "timer": {
        "deadline_iso": "2026-02-05T17:00:00Z",
        "grace_minutes": 0,
        "now_iso": "2026-02-04T17:00:00Z",
        "time_to_deadline_minutes": 1440,
        "overdue_minutes": 0
    },
    "renewal": {
        "last_renewal_iso": "2026-02-04T17:00:00Z",
        "renewed_this_tick": false,
        "renewal_count": 12
    },
    "security": {
        "failed_attempts": 0,
        "lockout_active": false,
        "lockout_until_iso": null,
        "max_failed_attempts": 3,
        "attempt_window_seconds": 60
    },
    "escalation": {
        "state": "OK",
        "state_entered_at_iso": "2026-02-04T17:00:00Z",
        "last_transition_rule_id": null,
        "monotonic_enforced": true
    },
    "actions": {
        "executed": {
            "remind_email_primary": {
                "status": "ok",
                "last_delivery_id": "email_demo_001",
                "last_executed_iso": "2026-02-01T12:00:00Z"
            }
        },
        "last_tick_actions": []
    },
    "integrations": {
        "enabled_adapters": {
            "email": true,
            "sms": true,
            "x": true,
            "reddit": true,
            "webhook": true,
            "github_surface": true,
            "article_publish": true,
            "persistence_api": true
        },
        "routing": {
            "operator_email": "operator@example.invalid",
            "operator_sms": "+15555550100",
            "custodian_emails": [
                "custodian-a@example.invalid",
                "custodian-b@example.invalid"
            ],
            "observer_webhooks": [
                "https://observer.example.invalid/hook/a",
                "https://observer.example.invalid/hook/b"
            ],
            "reddit_targets": [
                "r/example",
                "u/example_account"
            ],
            "x_account_ref": "x_account_demo"
        }
    },
    "pointers": {
        "persistence": {
            "primary_backend": "persistence_api",
            "last_persist_iso": "2026-02-04T17:00:00Z"
        },
        "github_surface": {
            "last_public_artifact_ref": null
        }
    }
}