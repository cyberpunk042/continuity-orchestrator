# Quickstart Guide

Get Continuity Orchestrator running in 5 minutes.

---

## Prerequisites

- Python 3.11+ **or** Docker
- Git

---

## Option A: Docker (Easiest)

### 1. Clone the repository

```bash
git clone https://github.com/cyberpunk042/continuity-orchestrator.git
cd continuity-orchestrator
```

### 2. Start in test mode

```bash
docker compose up
```

You'll see:
```
┌─────────────────────────────────────────────────────────────────┐
│   ⚠️  CONTINUITY ORCHESTRATOR — TEST MODE ⚠️                    │
│   State is stored in Docker volumes ONLY.                       │
└─────────────────────────────────────────────────────────────────┘

📦 Initializing test state...
✅ State initialized
🧪 Starting test tick loop (every 15 minutes)...
```

### 3. View the dashboard

Open http://localhost:8080 in your browser.

### 4. Stop and clean up

```bash
# Stop containers
docker compose down

# Stop and delete all data
docker compose down -v
```

---

## Option B: Local Python

### 1. Clone and setup

```bash
git clone https://github.com/cyberpunk042/continuity-orchestrator.git
cd continuity-orchestrator

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .
```

### 2. Initialize

```bash
python -m src.main init
```

Follow the prompts to set:
- Project name
- GitHub repository
- Initial deadline
- Operator email

### 3. Check status

```bash
python -m src.main status
```

Output:
```
╔══════════════════════════════════════════════════════════════════╗
║                    CONTINUITY ORCHESTRATOR                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Project: my-project                                              ║
║  State: OK                                                        ║
║  Mode: ARMED                                                      ║
║  Deadline: 2026-02-06T19:47:00Z (47h 59m remaining)              ║
╚══════════════════════════════════════════════════════════════════╝
```

### 4. Run a tick

```bash
# Dry run first (no changes)
python -m src.main tick --dry-run

# Real tick
python -m src.main tick
```

---

## Next Steps

### Configure Notifications

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Add your API keys:
   ```bash
   # .env
   RESEND_API_KEY=re_your_key_here
   TWILIO_ACCOUNT_SID=AC_your_sid
   TWILIO_AUTH_TOKEN=your_token
   ```

3. Or use the master config:
   ```bash
   python -m src.main generate-config
   ```

### Customize Rules

Edit `policy/rules.yaml` to define when escalation happens:

```yaml
rules:
  - id: MY_WARNING
    description: "Warn at 12 hours before deadline"
    when:
      - time_to_deadline_minutes <= 720
      - escalation_state == "OK"
    then:
      transition_to: WARNING
```

### Deploy to Production

**GitHub Actions (Recommended):**
1. Push to GitHub
2. Add secrets in Settings → Secrets → Actions
3. Enable the workflow

**Docker Production:**
```bash
docker compose --profile git-sync up -d
```

---

## Common Commands

| Command | Description |
|---------|-------------|
| `status` | Show current state and countdown |
| `tick` | Run one evaluation cycle |
| `tick --dry-run` | Preview without changes |
| `set-deadline --hours 24` | Set deadline to 24h from now |
| `reset` | Reset to OK state |
| `renew` | Renew the countdown |
| `build-site` | Generate static site |
| `health` | Check system health |

---

## Troubleshooting

### "No state file found"

Run `python -m src.main init` to create initial state.

### "Adapter not configured"

Set the required environment variables. Run `python -m src.main health` to see what's missing.

### Docker port conflict

If port 8080 is in use:
```bash
# Edit docker-compose.yml, change "8080:80" to "8888:80"
docker compose up
```

---

## Learn More

- [Configuration Guide](CONFIGURATION.md) — All options explained
- [Deployment Guide](DEPLOYMENT.md) — Production setup
- [Architecture](ARCHITECTURE.md) — How the engine works
