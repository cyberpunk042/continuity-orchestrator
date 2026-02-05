# continuity-orchestrator — Project Startup

## Purpose

continuity-orchestrator is a demo / prop GitHub project that models a scheduled automation system which:

- evaluates a countdown and rule set on a fixed interval (CRON-style)
- confirms whether the operator is still alive via a renewal mechanism
- if renewal does not happen in time, executes a staged set of actions through multiple integrations:
  - emails and SMS
  - public posts (X, Reddit, etc.)
  - article-style publications
  - creation of new public-facing files or documents on a GitHub app / site surface (even if the repo itself is private)
  - calls to custom APIs for persistent data and distanciation from any single platform

This document defines the project direction and current understanding for a fresh conversation.

---

## What This Project Is

continuity-orchestrator is a policy-first orchestration engine.

It does not decide truth, store large payloads, or improvise behavior.

It:
- evaluates state
- evaluates time
- evaluates predefined rules
- executes integrations deterministically

Everything important is configured ahead of time.

---

## Core Idea

The system converts time and configuration into action.

Once armed and running:
- no interaction is required
- no approval is requested
- no improvisation occurs

Time advances. Rules fire. Integrations execute.

---

## High-Level Architecture

GitHub Repository (policies, plans, configuration)
→ Scheduled CRON Pipeline
→ Policy Evaluation Engine
→ Orchestration Layer
→ Adapters (email, SMS, X, Reddit, GitHub surfaces, APIs)

The repository itself acts as:
- configuration authority
- execution timeline
- audit surface

---

## Countdown and Renewal Model

### Countdown Timer

A renewable timer evaluated on every scheduled run.

Properties:
- deadline timestamp
- renewal window
- optional grace period
- escalation stage derived from remaining or overdue time

### Alive Confirmation

A renewal action resets or extends the countdown.

Characteristics:
- performed by entering a high-entropy secret code
- the code is never guessable
- the confirmation entry point is pre-known to the operator
- the confirmation path is never included in reminders

### Reminder Channel

A separate communication path used only to notify the operator.

Reminders:
- email and/or SMS
- contain no link, identifier, or entry point
- only instruct the operator to renew within a time window using their offline procedure

---

## Lockout and Attempt Rules

The renewal mechanism supports configurable defensive behavior:

- maximum failed attempts
- rate limiting between attempts
- temporary or permanent lockout
- optional escalation if attempts exceed limits

Lockout behavior is expressed as policy outcomes and is fully logged.

---

## Escalation Stages

The system escalates behavior as the countdown approaches or passes expiry.

Illustrative stages:
- Stage 0: normal, no action
- Stage 1: reminder sent
- Stage 2: stronger reminder via secondary channel
- Stage 3: pre-release notifications
- Stage 4: partial public actions
- Stage 5: full execution of all configured integrations

Stages are data-driven and defined in policy files.

---

## Integrations (Adapters)

All external actions are implemented as adapters. Each adapter can be enabled or disabled per stage.

### Operator Notifications
- email adapter (for example, Resend)
- SMS adapter
- optional push notification adapter

### Public Dissemination
- X posting adapter
- Reddit posting adapter
- webhook adapter
- article or blog publication adapter

### GitHub Surface Outputs
- creation or update of public documents
- GitHub Pages or App Site updates
- release notes, tags, or other visible artifacts

### Persistence and Distanciation
- custom persistence API adapter
- mirrored receipt storage
- append-only audit replication

Adapters are designed to be redundant and independent.

---

## Modes

### Renewable Countdown (Default)

- a countdown duration is configured
- the operator must renew before expiry
- renewal extends or resets the timer
- failure to renew triggers escalation

### One-Way Fuse (Optional)

- once armed, cannot be disabled
- only renewals allowed until final expiry
- intended for irreversible scenarios

### Manual Arm + Auto Escalate (Optional)

- operator explicitly arms the system
- escalation proceeds if renewal does not occur

Modes are configuration only; the engine remains unchanged.

---

## Execution Loop

On every scheduled run:

1. Load persistent state
2. Evaluate countdown and renewal status
3. Apply policy rules
4. Transition escalation stage if needed
5. Execute integrations for the current stage
6. Record receipts and audit entries
7. Persist updated state

Execution is deterministic and idempotent.

---

## Persistent State

State is abstracted behind a persistence layer.

Tracked data includes:
- timer and renewal metadata
- current escalation stage
- failed attempt counters and lockout status
- executed actions and receipts
- policy version references

Primary persistence target:
- custom API endpoint

Secondary (optional):
- repository-mirrored state for visibility

---

## Repository Layout Target

continuity-orchestrator
- README.md
- STARTUP.md
- policy
  - states.yaml
  - rules.yaml
  - plans
- state
  - current.json
- audit
  - ledger.ndjson
- src
  - engine
  - adapters
  - persistence
- workflows
  - scheduled pipeline
- config
  - example environment and adapter toggles

---