# Development Guide

This guide covers setting up the development environment, running the system locally, and understanding the codebase architecture.

## Quick Start

```bash
# Clone the repository
git clone <repo-url>
cd continuity-orchestrator

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Run the demo
./demo.sh
```

## Requirements

- **Python**: 3.8+ (tested with 3.8 and 3.12)
- **OS**: Linux, macOS, or WSL
- **Dependencies**: Managed via `pyproject.toml`

### Core Dependencies
| Package | Purpose |
|---------|---------|
| `pydantic` | State and policy schema validation |
| `pyyaml` | Policy file parsing |
| `click` | CLI interface |
| `python-dateutil` | ISO date parsing |

### Optional Dependencies
| Group | Packages | Purpose |
|-------|----------|---------|
| `dev` | pytest, ruff, mypy | Testing and linting |
| `adapters` | httpx, resend | Real adapter implementations |

## Project Structure

```
continuity-orchestrator/
├── src/                   # Python source code (89 modules)
│   ├── __init__.py       # Package root
│   ├── main.py           # CLI entry point (thin, delegates to cli/)
│   ├── cli/              # CLI command modules
│   │   ├── core.py       # tick, status, reset, renew, set-deadline
│   │   ├── mirror.py     # mirror-status, mirror-sync, mirror-clean
│   │   ├── test.py       # test email/sms/webhook/github/all
│   │   ├── backup.py     # backup create/restore/list
│   │   ├── config.py     # check-config
│   │   ├── content.py    # content list/export
│   │   ├── deploy.py     # export-secrets
│   │   ├── init.py       # init wizard
│   │   ├── ops.py        # trigger-release
│   │   ├── policy.py     # policy info/validate
│   │   └── site.py       # build-site
│   ├── admin/            # Web admin dashboard (Flask)
│   │   ├── server.py     # App factory, blueprint registration
│   │   ├── helpers.py    # Shared utilities
│   │   ├── vault.py      # Session encryption vault
│   │   ├── routes_core.py       # Dashboard, status, factory reset
│   │   ├── routes_content.py    # Article CRUD, encryption
│   │   ├── routes_media.py      # Upload, preview, optimize, Editor.js
│   │   ├── routes_media_vault.py # GitHub Release sync for large files
│   │   ├── routes_git.py        # Git status, commit, push
│   │   ├── routes_secrets.py    # GitHub secrets management
│   │   ├── routes_env.py        # .env editing
│   │   ├── routes_vault.py      # Session vault unlock/lock
│   │   ├── routes_backup.py     # Export/import/restore
│   │   ├── routes_archive.py    # Internet Archive integration
│   │   ├── routes_mirror.py     # Multi-repo mirror sync
│   │   ├── routes_docker.py     # Container management
│   │   ├── templates/    # Jinja2 HTML + JS partials
│   │   └── static/css/   # Stylesheet
│   ├── adapters/         # External service integrations (10 adapters)
│   ├── content/          # Media manifest, encryption, optimization
│   ├── config/           # Config loader, validator, system status
│   ├── engine/           # Core tick lifecycle
│   ├── mirror/           # Multi-repo mirroring (config, sync, state)
│   ├── models/           # Pydantic schemas (state, receipt)
│   ├── observability/    # Health checks, Prometheus metrics
│   ├── persistence/      # State and audit storage
│   ├── policy/           # Policy loading and models
│   ├── reliability/      # Retry queue, circuit breakers
│   ├── site/             # Static site generator, token obfuscation
│   └── templates/        # Template resolution
├── policy/               # YAML configuration
│   ├── states.yaml       # Escalation state machine
│   ├── rules.yaml        # Transition rules
│   └── plans/            # Action plans
├── state/                # Runtime state
│   └── current.json      # Current system state
├── audit/                # Audit trail
│   └── ledger.ndjson     # Append-only event log
├── content/              # Your disclosure content
│   ├── articles/         # Editor.js JSON documents
│   ├── media/            # Uploaded media (encrypted, tiered storage)
│   └── manifest.yaml     # Article visibility rules
├── templates/            # Message templates
│   ├── operator/         # Reminder messages
│   ├── custodians/       # Pre-release notices
│   ├── public/           # Public announcements
│   └── articles/         # Long-form content
├── scripts/              # Development utilities
├── docs/                 # Documentation
└── .github/workflows/    # CI/CD
```

## CLI Commands

All commands should be run with the virtual environment activated.

### Execute a Tick

```bash
# Run a tick (evaluates rules, executes actions)
python -m src.main tick

# Dry run (no persistence, no actions)
python -m src.main tick --dry-run

# Custom paths
python -m src.main tick \
  --state-file state/test.json \
  --policy-dir policy \
  --audit-file audit/test.ndjson
```

### Check Status

```bash
python -m src.main status
```

Output:
```
Project:      continuity-orchestrator
State ID:     S-INIT-001
Plan:         default

Escalation:   REMIND_1
Mode:         renewable_countdown
Armed:        True

Deadline:     2026-02-05T12:00:00Z
Last updated: 2026-02-04T22:00:00Z
Time left:    840 minutes (14h 0m)
```

### Set Deadline

```bash
# Set deadline to 24 hours from now
python -m src.main set-deadline --hours 24

# Set deadline to 30 minutes from now
python -m src.main set-deadline --hours 0.5
```

### Reset State

```bash
# Reset to OK, clear all executed actions
python -m src.main reset
```

## Tick Lifecycle

The tick is the atomic unit of execution. Each tick follows these phases:

### Phase 1: Initialization
- Load state from JSON file
- Load policy from YAML files
- Generate unique tick ID

### Phase 2: Time Evaluation
- Calculate `time_to_deadline_minutes`
- Calculate `overdue_minutes`
- Apply grace period

### Phase 3: Renewal Check
- (Prototype: manual via `set-deadline`)
- Future: Check external signal

### Phase 4: Rule Evaluation
- Evaluate rules top-to-bottom
- Match conditions against state
- Collect matched rules

### Phase 5: State Mutation
- Apply mutations from matched rules
- Handle `set_state`, `set`, `clear`
- Record state transitions

### Phase 6: Action Selection
- Get actions for current stage from plan
- Check idempotency (skip already-executed)

### Phase 7: Adapter Execution
- Build execution context
- Resolve template content
- Execute via adapter registry
- Record receipts

### Phase 8: Finalization
- Persist state
- Write audit entries
- Return result

## Policy Configuration

### states.yaml

Defines the escalation state machine:

```yaml
states:
  - name: OK
    order: 0
    description: Normal operation
    flags:
      outward_actions_allowed: false
      reminders_allowed: true
```

### rules.yaml

Defines transition conditions:

```yaml
rules:
  - id: R10_ESCALATE_TO_REMIND_1
    description: Enter REMIND_1 when within 6 hours
    when:
      state_is: OK
      time.time_to_deadline_minutes_lte: 360
      time.time_to_deadline_minutes_gt: 60
    then:
      set_state: REMIND_1
    stop: true
```

**Condition operators:**
- `_lte`: Less than or equal
- `_lt`: Less than
- `_gte`: Greater than or equal
- `_gt`: Greater than
- `state_is`: Exact state match
- `state_in`: State in list

### plans/default.yaml

Defines actions per stage:

```yaml
stages:
  REMIND_1:
    description: First reminder
    actions:
      - id: remind_email_primary
        adapter: email
        channel: operator
        template: reminder_basic
```

## Adding a New Adapter

1. Create `src/adapters/your_adapter.py`:

```python
from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt

class YourAdapter(Adapter):
    @property
    def name(self) -> str:
        return "your_adapter"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        # Check if configured
        return True
    
    def validate(self, context: ExecutionContext) -> tuple:
        # Validate action can execute
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        # Do the thing
        return Receipt.ok(
            adapter=self.name,
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id="unique-id",
        )
```

2. Register in `src/adapters/registry.py`:

```python
from .your_adapter import YourAdapter

# In AdapterRegistry.__init__:
if not mock_mode:
    self.register(YourAdapter())
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONTINUITY_ENV` | Environment (dev/prod) | `dev` |
| `ADAPTER_MOCK_MODE` | Use mock adapters | `true` |
| `RESEND_API_KEY` | Email API key | — |
| `TWILIO_*` | SMS credentials | — |

## Testing

```bash
# Run all tests (639 tests)
pytest

# Run with coverage
pytest --cov=src

# Run specific test
pytest tests/test_rules.py::test_time_evaluation
```

## Linting

```bash
# Check code style
ruff check src/

# Auto-fix issues
ruff check --fix src/

# Type checking
mypy src/
```

## Common Tasks

### Simulate Escalation

```bash
# Set short deadline and run ticks
python -m src.main reset
python -m src.main set-deadline --hours 5  # REMIND_1 range
python -m src.main tick                     # → REMIND_1
python -m src.main set-deadline --hours 0.5 # REMIND_2 range
python -m src.main tick                     # → REMIND_2
```

### View Audit Log

```bash
# Last 5 events
tail -5 audit/ledger.ndjson | jq .

# Filter by type
jq 'select(.type == "state_transition")' audit/ledger.ndjson
```

### Debug Rule Matching

Add `--dry-run` and check output:
```bash
python -m src.main tick --dry-run
```

Check rule conditions in `policy/rules.yaml` and compare to state values in `state/current.json`.

## Troubleshooting

### "No actions executed"
- Check if action was already executed (idempotency)
- Verify action is defined for current stage in plan
- Check state file `actions.executed`

### "Rule didn't match"
- Verify conditions in `rules.yaml`
- Check `time.` → `timer.` path mapping
- Review constants in `rules.yaml`

### "Template not found"
- Check template name matches file in `templates/`
- Verify file extension (.md, .txt, .html)
- Check subdirectory (operator/, public/, etc.)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI (main.py)                       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Engine (tick.py)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │time_eval │ │  rules   │ │  state   │ │   templates   │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└─────────────────────────────┬───────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────────┐
│    Adapters    │  │   Persistence  │  │      Policy        │
│ (mock/real)    │  │ (state, audit) │  │ (states, rules,    │
│                │  │                │  │  plans)            │
└────────────────┘  └────────────────┘  └────────────────────┘
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run linting and tests
5. Submit pull request

See [ROADMAP.md](./ROADMAP.md) for planned work.
