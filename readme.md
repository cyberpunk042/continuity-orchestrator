# continuity-orchestrator

A scheduled orchestration engine that evaluates a renewable countdown and, if not renewed in time, executes preconfigured notifications, publications, and integrations to ensure continuity and visibility.

---

## What This Is

continuity-orchestrator is a **policy-first automation system**.

It runs on a fixed schedule, evaluates state and time, and deterministically executes actions defined in configuration. Once armed, behavior is driven entirely by rules and plans committed to the repository.

---

## How It Works (At a Glance)

1. A scheduled pipeline runs on a fixed interval
2. Current state is loaded and time is evaluated
3. Policy rules determine the current escalation stage
4. Actions for that stage are selected from a plan
5. Integrations are executed through adapters
6. Results are audited and state is persisted

No runtime decisions. No improvisation.

---

## Core Concepts

### Countdown and Renewal
- A countdown must be renewed before expiry
- Renewal uses a pre-known, high-entropy code
- Reminder messages never include renewal entry points
- Failed attempts and lockouts are policy-driven

### Escalation Stages
- Progression is monotonic
- Stages range from reminders to full execution
- Each stage maps to a defined set of actions

### Integrations
- Email and SMS
- Public platforms (X, Reddit)
- GitHub surfaces (documents, pages, releases)
- Webhooks and custom persistence APIs

All integrations are optional and configurable.

---

## Repository Structure

- policy  
  States, rules, and execution plans

- state  
  Current runtime state

- audit  
  Append-only execution log

- src  
  Engine, adapters, persistence

- workflows  
  Scheduled execution pipeline

- templates  
  All human-readable content

---

## Determinism and Auditability

- Each run is a discrete tick
- Decisions are reproducible given the same inputs
- Every action produces an audit record
- Commits represent time advancing

The system itself becomes an artifact.

---

## Configuration-Driven

All intent lives in configuration files:
- states define progression
- rules define transitions
- plans define actions
- templates define content

The engine enforces what is declared.

---

## Demo Scope

This repository is a **demo / prop**:
- minimal
- readable
- realistic
- extensible

It is designed to communicate behavior clearly and credibly.

---

## Status

Initialized and structured.

Policy, state, audit, adapters, engine, templates, and workflow are defined.

---
