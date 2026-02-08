# Continuity Orchestrator — Architecture

> A policy-first automation engine for scheduled continuity operations.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Entry Points                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ CLI (click)  │  │ Admin Web UI │  │ GitHub Actions       │   │
│  │ src/cli/*    │  │ src/admin/*  │  │ .github/workflows/   │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                        Engine Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  tick.py    │  │  rules.py   │  │    time_eval.py         │  │
│  │ (lifecycle) │  │ (matching)  │  │ (deadline calculation)  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                       Policy Layer                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ states.yaml │  │ rules.yaml  │  │     plans/*.yaml        │  │
│  │ (FSM def)   │  │ (conditions)│  │ (actions per stage)     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                       Adapter Layer                              │
│  ┌───────┐ ┌─────┐ ┌───────┐ ┌────────┐ ┌──────┐ ┌──────────┐  │
│  │ Email │ │ SMS │ │ X/Twt │ │ Reddit │ │ Hook │ │ GitHub   │  │
│  └───────┘ └─────┘ └───────┘ └────────┘ └──────┘ └──────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Archive (IA) │  │ Persistence  │  │ Article Publish       │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                     Persistence Layer                            │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐  │
│  │   state/current.json    │  │    audit/ledger.ndjson       │  │
│  │   (runtime state)       │  │    (append-only log)         │  │
│  └─────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### 1. Tick Lifecycle

A **tick** is a single execution cycle. Each tick runs through 8 phases:

| Phase | Name | Description |
|-------|------|-------------|
| 1 | **Initialization** | Generate tick ID, load state |
| 2 | **Time Evaluation** | Calculate deadline proximity |
| 3 | **Renewal Check** | Check for renewal signals |
| 4 | **Rule Evaluation** | Match rules against state |
| 5 | **State Mutation** | Apply matched rule effects |
| 6 | **Action Selection** | Determine actions for current stage |
| 7 | **Adapter Execution** | Execute actions through adapters |
| 8 | **Finalization** | Persist state, write audit entry |

### 2. Escalation State Machine

States progress monotonically through the escalation ladder:

```
OK → REMIND_1 → REMIND_2 → PRE_RELEASE → PARTIAL → FULL
```

- **OK**: Normal operation, no action needed
- **REMIND_1**: First reminder (6 hours before deadline)
- **REMIND_2**: Second reminder with SMS (1 hour before)
- **PRE_RELEASE**: Final warning to custodians (15 minutes before)
- **PARTIAL**: Initial public disclosure
- **FULL**: Complete disclosure

### 3. Policy-Driven Behavior

All system behavior is defined in YAML configuration:

```
policy/
├── states.yaml      # State definitions and flags
├── rules.yaml       # Transition conditions
└── plans/
    └── default.yaml # Actions per escalation stage
```

---

## Key Design Principles

### Determinism

Given the same state and policy, a tick will always produce the same result.
No randomness, no external dependencies in core logic.

### Idempotency

Actions track execution status. Re-running a tick will not re-execute
already-completed actions.

### Monotonicity

Escalation can only progress forward. A state cannot regress without
an explicit reset operation.

### Auditability

Every tick writes to an append-only NDJSON ledger with:
- Tick ID and timestamp
- State before/after
- Rules matched
- Actions executed

---

## Module Reference

### CLI (`src/cli/`)

| Module | Purpose |
|--------|---------|
| `core.py` | tick, status, set-deadline, reset, renew |
| `release.py` | trigger-release |
| `config.py` | check-config, config-status, generate-config |
| `health.py` | health, metrics, retry-queue, circuit-breakers |
| `mirror.py` | mirror-status, mirror-sync, mirror-clean |
| `init.py` | Project scaffolding wizard |
| `test.py` | Adapter integration tests |
| `deploy.py` | export-secrets, explain-stages, simulate-timeline |
| `site.py` | build-site |

### Engine (`src/engine/`)

| Module | Purpose |
|--------|---------|
| `tick.py` | Main tick lifecycle orchestration |
| `time_eval.py` | Deadline and time calculations |
| `rules.py` | Rule matching and condition evaluation |
| `state.py` | State mutations (set, clear) |

### Admin Dashboard (`src/admin/`)

| Module | Purpose |
|--------|---------|
| `server.py` | Flask app factory, startup |
| `helpers.py` | Shared utilities (_fresh_env, _gh_repo_flag) |
| `routes_core.py` | Dashboard, run command, status API |
| `routes_env.py` | .env read/write API |
| `routes_secrets.py` | GitHub secrets/variables sync |
| `routes_git.py` | Git status, sync, fetch |
| `routes_mirror.py` | Mirror sync/clean with streaming |
| `routes_archive.py` | Internet Archive (Wayback) |
| `templates/` | Jinja2 partials (8 HTML + 12 JS scripts) |

### Adapters (`src/adapters/`)

| Module | Purpose |
|--------|---------|
| `base.py` | Abstract adapter interface |
| `registry.py` | Adapter lookup and execution |
| `mock.py` | Mock implementations for testing |
| `email_resend.py` | Email notifications (Resend API) |
| `sms_twilio.py` | SMS alerts (Twilio) |
| `x_adapter.py` | X/Twitter posts (OAuth 1.0a) |
| `reddit.py` | Reddit posts (PRAW) |
| `webhook.py` | Generic HTTP POST webhooks |
| `github_surface.py` | GitHub file/gist/release operations |
| `internet_archive.py` | Wayback Machine archival |
| `persistence_api.py` | Remote state sync |
| `article_publish.py` | Stage-based content publishing |

### Models (`src/models/`)

| Module | Purpose |
|--------|---------|
| `state.py` | Pydantic models for runtime state |
| `receipt.py` | Adapter execution receipts |

### Policy (`src/policy/`)

| Module | Purpose |
|--------|---------|
| `loader.py` | YAML policy file loading |
| `models.py` | Pydantic models for policy schemas |

### Persistence (`src/persistence/`)

| Module | Purpose |
|--------|---------|
| `state_file.py` | Atomic state file read/write |
| `audit.py` | Append-only audit ledger |

### Templates (`src/templates/`)

| Module | Purpose |
|--------|---------|
| `resolver.py` | Template file lookup and rendering |
| `context.py` | Build template context from state |

---

## Data Flow

```
┌────────────┐
│   CRON     │
│  (GitHub   │
│  Actions)  │
└──────┬─────┘
       ▼
┌──────────────┐    ┌──────────────┐
│   CLI        │───▶│    tick.py   │
│  `continuity │    │  (lifecycle) │
│   tick`      │    └──────┬───────┘
└──────────────┘           │
                           ▼
                    ┌──────────────┐
                    │ time_eval.py │
                    │ (calculate   │
                    │  deadline)   │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  rules.py    │
                    │ (match       │
                    │  conditions) │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │Adapter Layer │
                    │ (email, SMS, │
                    │  webhooks)   │
                    └──────┬───────┘
                           │
              ┌────────────┴─────────────┐
              ▼                          ▼
       ┌──────────────┐         ┌──────────────┐
       │ state.json   │         │ ledger.ndjson│
       │ (next state) │         │ (audit log)  │
       └──────────────┘         └──────────────┘
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONTINUITY_ENV` | Environment (dev/prod) | `dev` |
| `ADAPTER_MOCK_MODE` | Use mock adapters | `true` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FORMAT` | Output format (text/json) | `text` |
| `RESEND_API_KEY` | Resend email API key | - |
| `GITHUB_TOKEN` | GitHub API token | - |
| `GITHUB_REPOSITORY` | GitHub repo (owner/repo) | - |

### Policy Constants

Defined in `rules.yaml`:

```yaml
constants:
  remind_1_at_minutes: 360    # 6 hours
  remind_2_at_minutes: 60     # 1 hour
  pre_release_at_minutes: 15  # 15 minutes
  partial_at_minutes: 0       # At deadline
  full_at_overdue_minutes: 1440  # 24 hours overdue
```

---

## Security Considerations

1. **Renewal codes** are high-entropy, not guessable
2. **Reminder messages** never include direct entry points
3. **State file** is the single source of truth (no distributed state)
4. **Audit ledger** is append-only for integrity
5. **Secrets** are injected via environment variables

---

## Extension Points

### Adding a New Adapter

1. Create `src/adapters/my_adapter.py`
2. Extend `Adapter` base class
3. Implement `name`, `is_enabled`, `validate`, `execute`
4. Register in `AdapterRegistry._register_real_adapters()`

### Adding a New Escalation Stage

1. Add state to `policy/states.yaml`
2. Add transition rule to `policy/rules.yaml`
3. Add stage actions to `policy/plans/default.yaml`
4. Create templates in `templates/{stage}/`

### Adding a New Rule Operator

1. Add operator to `OPERATORS` dict in `rules.py`
2. Add tests in `tests/test_rules.py`

---

## Testing Strategy

| Test Type | Coverage | Location |
|-----------|----------|----------|
| Unit | Time evaluation, rules, state mutations | `tests/test_*.py` |
| Integration | Tick lifecycle end-to-end | `tests/test_tick_integration.py` |
| Policy | YAML loading, validation | `tests/test_policy.py` |
| Validation | Input validation | `tests/test_validation.py` |

Run all tests:
```bash
pytest
```

---

## Deployment

### GitHub Actions

The system runs via scheduled GitHub Actions:

```yaml
on:
  schedule:
    - cron: '*/5 * * * *'  # Every 5 minutes
```

State is persisted to the repository itself, creating a self-contained system.

### Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run a tick
python -m src.main tick --dry-run

# Check status
python -m src.main status
```

---

*Last Updated: 2026-02-07*
