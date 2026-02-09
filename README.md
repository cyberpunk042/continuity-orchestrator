# Continuity Orchestrator

> **Policy-first automation for deadman switches, scheduled publishing, and timed escalations.**

[![Tests](https://github.com/cyberpunk042/continuity-orchestrator/actions/workflows/cron.yml/badge.svg)](https://github.com/cyberpunk042/continuity-orchestrator/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

> ⚠️ **IMPORTANT:** This is automated disclosure software. Actions triggered by this system may be **irreversible**.
> Please read the [DISCLAIMER](DISCLAIMER.md) and [SECURITY](SECURITY.md) documents before use.

---

## What is this?

A scheduled engine that watches a countdown. If you don't renew it in time, it executes preconfigured actions — emails, SMS, social posts, webhooks, or document publishing.

**Use cases:**
- 🔐 **Deadman switch** — Release information if you don't check in
- 📰 **Scheduled publishing** — Publish articles on a countdown
- ⏰ **Timed notifications** — Escalating alerts as deadlines approach
- 🔔 **Continuity assurance** — Ensure stakeholders are notified

---

## Try It Now

### 🎬 See it work (30 seconds)

```bash
git clone https://github.com/cyberpunk042/continuity-orchestrator.git
cd continuity-orchestrator
./demo.sh
```

Watch the full escalation cycle: **OK → WARNING → CRITICAL → FINAL**

No configuration needed. Just run it.

### 🚀 Set up your own

```bash
./setup.sh
```

Interactive wizard that asks what you need and generates your config.

### 🐳 Or just Docker

```bash
docker compose up
```

Runs in test mode. Open http://localhost:8080 to see the dashboard.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTINUITY ORCHESTRATOR                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │  TIMER   │───▶│  RULES   │───▶│ ACTIONS  │              │
│  │          │    │          │    │          │              │
│  │ Deadline │    │ Evaluate │    │ Execute  │              │
│  │ Renewal  │    │ Escalate │    │ Notify   │              │
│  └──────────┘    └──────────┘    └──────────┘              │
│       │                               │                     │
│       ▼                               ▼                     │
│  ┌──────────┐                  ┌──────────┐                │
│  │  STATE   │                  │  AUDIT   │                │
│  │          │                  │          │                │
│  │ current  │                  │ ledger   │                │
│  │ .json    │                  │ .ndjson  │                │
│  └──────────┘                  └──────────┘                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

1. **Timer** tracks a deadline
2. **Rules** evaluate the current stage (OK → WARNING → CRITICAL → FINAL)
3. **Actions** execute when stages transition
4. **State** persists; **Audit** logs everything

---

## Features

| Feature | Description |
|---------|-------------|
| ⏱️ **Renewable Countdown** | Set a deadline. Renew it with a secret code. |
| 📊 **Escalation Stages** | OK → WARNING → CRITICAL → FINAL |
| ✉️ **Email Notifications** | Via Resend API |
| 📱 **SMS Alerts** | Via Twilio |
| 🐦 **Social Publishing** | X (Twitter) and Reddit |
| 🌐 **Webhooks** | Custom integrations |
| 📄 **Document Publishing** | GitHub Pages static site |
| 🔒 **Security** | Lockouts, high-entropy renewal codes |
| 📝 **Audit Trail** | Every action logged |

---

## Project Structure

```
continuity-orchestrator/
├── src/                    # Python source (89 modules, 22k+ lines)
│   ├── engine/             # Tick processor, rule evaluation, time calc
│   ├── adapters/           # 10 adapters (email, SMS, X, Reddit, etc.)
│   ├── admin/              # Flask web admin (12 route blueprints)
│   ├── cli/                # CLI commands (10 modules)
│   ├── content/            # Media management, encryption
│   ├── config/             # Config loader, validator
│   ├── mirror/             # Multi-repo mirroring
│   ├── models/             # Pydantic state & receipt schemas
│   ├── site/               # Static site generator
│   ├── persistence/        # State file + audit storage
│   ├── reliability/        # Retry queue, circuit breakers
│   ├── observability/      # Health checks, metrics
│   ├── policy/             # Policy loader & models
│   └── templates/          # Template resolution
│
├── policy/                 # Configuration (YAML)
│   ├── rules.yaml          # Escalation rules
│   ├── states.yaml         # Stage definitions
│   └── plans/              # Action plans
│
├── templates/              # Message templates (Markdown)
├── content/                # Your content to publish
├── state/                  # Runtime state (gitignored)
├── audit/                  # Execution logs
│
├── examples/               # Ready-to-use configurations
├── scripts/                # Helper scripts
├── tests/                  # Test suite (639 tests)
└── docs/                   # Documentation
```

---

## Configuration

### Set Your Credentials

```bash
# Run the wizard (recommended)
./setup.sh

# Or manually edit .env
cp .env.example .env
nano .env
```

### Daily Operations

```bash
./manage.sh
```

Menu-driven interface for:
- Check status
- Run tick / dry-run
- Renew deadline
- Test adapters
- Build site

### Configure Rules

Edit `policy/rules.yaml`:
```yaml
rules:
  - id: R10_WARNING_STAGE
    description: "Enter warning at 24h before deadline"
    when:
      - time_to_deadline_minutes <= 1440
      - escalation_state == "OK"
    then:
      transition_to: WARNING
```

📖 **[Project Reference →](docs/PROJECT_REFERENCE.md)** — See where everything configures

---

## Deployment Options

### 🐳 Docker (Test Mode)
```bash
docker compose up
```
State lives in Docker volumes. Great for testing.

### 🐳 Docker (Production)
```bash
docker compose --profile git-sync up -d
```
State commits back to your Git repo.

### ⚡ GitHub Actions (Recommended)

1. Push to GitHub
2. Add secrets:
   ```bash
   # See what secrets you need
   python -m src.main export-secrets
   ```
3. Enable the workflow — runs every 15 minutes

📖 **[Deployment Guide →](docs/DEPLOYMENT.md)**

---

## Operations

All operations are available through the management interface:

```bash
./manage.sh
```

Or use direct CLI for automation:

| Command | What it does |
|---------|--------------|
| `./manage.sh` | Interactive menu |
| `python -m src.main status` | Current state |
| `python -m src.main tick` | Run engine |
| `python -m src.main renew` | Extend deadline |
| `python -m src.main export-secrets` | Show GitHub secrets needed |

---

## Examples

### Minimal Deadman Switch

```yaml
# policy/rules.yaml - just the essentials
rules:
  - id: DEADLINE_PASSED
    when: [overdue_minutes > 0]
    then:
      transition_to: FINAL
      
# policy/plans/default.yaml
stages:
  FINAL:
    - action: email
      to: "{{operator_email}}"
      template: final_notice
```

### Newsletter with Countdown

See `examples/newsletter/` for a complete setup.

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Type checking
mypy src

# Linting
ruff check src
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [DISCLAIMER.md](DISCLAIMER.md) | ⚠️ **Read first** — Legal disclaimer and warnings |
| [SECURITY.md](SECURITY.md) | Security best practices |
| [PROJECT_REFERENCE.md](docs/PROJECT_REFERENCE.md) | **Where everything is** — .env, policy, content, templates |
| [QUICKSTART.md](docs/QUICKSTART.md) | 5-minute setup guide |
| [FORKING_GUIDE.md](docs/FORKING_GUIDE.md) | Fork and deploy your own |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, GitHub Actions, production |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the engine works |
| [AUTHORING.md](docs/AUTHORING.md) | Content authoring guide |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Developer setup, testing, codebase |
| [ROADMAP.md](docs/ROADMAP.md) | Development phases & status |

---

## License

MIT — See [LICENSE](LICENSE)

---

<p align="center">
  <sub>Built for continuity. Runs on determinism.</sub>
</p>
