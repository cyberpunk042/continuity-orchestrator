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
├── src/                    # Core engine
│   ├── engine/             # Tick processor, rule evaluation
│   ├── adapters/           # Email, SMS, X, Reddit, webhooks
│   ├── models/             # State, rules, actions
│   └── site_generator/     # Static site builder
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
├── tests/                  # Test suite (255 tests)
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

### Test Your Adapters

```bash
# See what's configured
python -m src.main test all

# Send a real test email
python -m src.main test email

# Send a real test SMS
python -m src.main test sms

# Verify GitHub token
python -m src.main test github

# Test a webhook
python -m src.main test webhook --url https://example.com/hook
```

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

📖 **[Configuration Guide →](docs/CONFIGURATION.md)**

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

## CLI Commands

```bash
# Check current status
python -m src.main status

# Set deadline (24 hours from now)
python -m src.main set-deadline --hours 24

# Run a tick (evaluate rules, execute actions)
python -m src.main tick

# Dry run (preview without changes)
python -m src.main tick --dry-run

# Reset to OK state
python -m src.main reset

# Build static site
python -m src.main build-site

# Check system health
python -m src.main health
```

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
| [QUICKSTART.md](docs/QUICKSTART.md) | 5-minute setup guide |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | All configuration options |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, GitHub Actions, production |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the engine works |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing guide |

---

## License

MIT — See [LICENSE](LICENSE)

---

<p align="center">
  <sub>Built for continuity. Runs on determinism.</sub>
</p>
