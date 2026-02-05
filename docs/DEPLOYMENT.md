# Deployment Guide

This guide covers deploying the Continuity Orchestrator to production environments.

## Quick Start Options

| Method | Best For | Complexity |
|--------|----------|------------|
| [Docker Compose](#docker-compose) | Self-hosted, full control | ⭐⭐ |
| [GitHub Actions](#github-actions-scheduled) | Free, serverless | ⭐ |
| [Systemd Service](#systemd-service) | Linux servers | ⭐⭐ |
| [Kubernetes](#kubernetes) | Enterprise scale | ⭐⭐⭐ |

---

## Docker Compose

The recommended deployment method for self-hosted environments.

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_ORG/continuity-orchestrator.git
   cd continuity-orchestrator
   ```

2. **Create environment file:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Build and start:**
   ```bash
   docker compose up -d
   ```

4. **Verify it's running:**
   ```bash
   docker compose logs -f orchestrator
   ```

### Docker Compose Configuration

The default `docker-compose.yml` includes:

- **orchestrator**: Main application with cron-based ticks
- **nginx**: Static site server
- **volumes**: Persistent state and audit logs

### Environment Variables

Required in `.env`:

```bash
# Core
STATE_FILE=/data/state/current.json
POLICY_DIR=/app/policy
ADAPTER_MOCK_MODE=false

# Email (Resend)
RESEND_API_KEY=re_xxxxx

# SMS (Twilio)
TWILIO_ACCOUNT_SID=ACxxxxx
TWILIO_AUTH_TOKEN=xxxxx
TWILIO_FROM_NUMBER=+15551234567

# X (Twitter)
X_API_KEY=xxxxx
X_API_SECRET=xxxxx
X_ACCESS_TOKEN=xxxxx
X_ACCESS_SECRET=xxxxx

# Reddit
REDDIT_CLIENT_ID=xxxxx
REDDIT_CLIENT_SECRET=xxxxx
REDDIT_USERNAME=xxxxx
REDDIT_PASSWORD=xxxxx

# GitHub (for surface artifacts)
GITHUB_TOKEN=ghp_xxxxx
GITHUB_REPOSITORY=owner/repo
```

---

## GitHub Actions (Scheduled)

Run ticks on a schedule using GitHub Actions — no server required.

### Setup

1. **Create workflow file** `.github/workflows/tick.yml`:
   ```yaml
   name: Tick
   
   on:
     schedule:
       - cron: '*/15 * * * *'  # Every 15 minutes
     workflow_dispatch:        # Manual trigger
   
   jobs:
     tick:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         
         - uses: actions/setup-python@v5
           with:
             python-version: '3.11'
         
         - name: Install dependencies
           run: pip install -e .
         
         - name: Run tick
           env:
             RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
             TWILIO_ACCOUNT_SID: ${{ secrets.TWILIO_ACCOUNT_SID }}
             TWILIO_AUTH_TOKEN: ${{ secrets.TWILIO_AUTH_TOKEN }}
             TWILIO_FROM_NUMBER: ${{ secrets.TWILIO_FROM_NUMBER }}
           run: python -m src.main tick
         
         - name: Commit state changes
           run: |
             git config user.name "github-actions[bot]"
             git config user.email "github-actions[bot]@users.noreply.github.com"
             git add state/ audit/
             git diff --staged --quiet || git commit -m "Tick $(date -u +%Y-%m-%dT%H:%M:%SZ)"
             git push
   ```

2. **Add secrets** in repository Settings → Secrets → Actions:
   
   **Required:**
   - `RENEWAL_SECRET` — The code users enter to renew (you create this)
   
   **For One-Click Renewal (recommended):**
   - `RENEWAL_TRIGGER_TOKEN` — Fine-grained PAT with only Actions:write permission
     (See "One-Click Renewal" section below)
   
   **For Adapters (as needed):**
   - `RESEND_API_KEY` — Email notifications
   - `TWILIO_ACCOUNT_SID` — SMS notifications
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_FROM_NUMBER`
   - `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` — Twitter/X
   - `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`

### Renewal Workflow

Create `.github/workflows/renew.yml`:

```yaml
name: Renew

on:
  workflow_dispatch:
    inputs:
      renewal_code:
        description: 'Renewal code'
        required: true
        type: string

jobs:
  renew:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -e .
      
      - name: Renew
        run: python -m src.main renew "${{ inputs.renewal_code }}"
      
      - name: Build site
        run: python -m src.main build-site
      
      - name: Commit changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/ audit/ public/
          git commit -m "Renewed $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          git push
```

### One-Click Renewal from Website

Enable direct renewal from the countdown page without navigating to GitHub:

1. **Create a fine-grained PAT:**
   - Go to https://github.com/settings/tokens?type=beta
   - Click "Generate new token"
   - Name: `Continuity Renewal Trigger`
   - Repository access: Select only your repository
   - Permissions: **Actions** → **Read and write** (ONLY this permission!)
   - Generate and copy the token

2. **Add to environment:**
   ```bash
   # In your .env file
   RENEWAL_TRIGGER_TOKEN=github_pat_xxxxx
   ```

3. **Rebuild the site:**
   ```bash
   python -m src.main build-site
   ```

**How it works:**

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY MODEL                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  RENEWAL_TRIGGER_TOKEN (in static JS)                       │
│  ├── Can: Trigger workflows via GitHub API                  │
│  └── Cannot: Read code, access secrets, modify repo         │
│                                                              │
│  RENEWAL_SECRET (in GitHub Secrets)                         │
│  └── Required to actually validate and extend deadline      │
│                                                              │
│  Even if someone discovers the trigger token, they can      │
│  only spam workflow runs (which fail without the secret).   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**User flow with one-click:**

1. User enters renewal code on countdown page
2. Clicks "🚀 Renew Now"  
3. JavaScript calls GitHub API directly
4. Workflow runs and validates the code
5. User sees success/failure status inline

**Fallback without token:**

If `RENEWAL_TRIGGER_TOKEN` is not set, the page falls back to:
1. Copy code to clipboard
2. Open GitHub Actions page
3. User pastes code manually

---

## Systemd Service

For Linux servers without Docker.

### Setup

1. **Create service file** `/etc/systemd/system/continuity-orchestrator.service`:
   ```ini
   [Unit]
   Description=Continuity Orchestrator Tick Service
   After=network.target
   
   [Service]
   Type=oneshot
   User=continuity
   WorkingDirectory=/opt/continuity-orchestrator
   EnvironmentFile=/opt/continuity-orchestrator/.env
   ExecStart=/opt/continuity-orchestrator/.venv/bin/python -m src.main tick
   
   [Install]
   WantedBy=multi-user.target
   ```

2. **Create timer** `/etc/systemd/system/continuity-orchestrator.timer`:
   ```ini
   [Unit]
   Description=Run Continuity Orchestrator every 15 minutes
   
   [Timer]
   OnBootSec=5min
   OnUnitActiveSec=15min
   Unit=continuity-orchestrator.service
   
   [Install]
   WantedBy=timers.target
   ```

3. **Enable and start:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now continuity-orchestrator.timer
   ```

4. **Check status:**
   ```bash
   systemctl status continuity-orchestrator.timer
   journalctl -u continuity-orchestrator.service -f
   ```

---

## Kubernetes

For enterprise deployments with high availability.

### CronJob Manifest

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: continuity-tick
  namespace: continuity
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: orchestrator
              image: your-registry/continuity-orchestrator:latest
              command: ["python", "-m", "src.main", "tick"]
              envFrom:
                - secretRef:
                    name: continuity-secrets
              volumeMounts:
                - name: state
                  mountPath: /data/state
                - name: audit
                  mountPath: /data/audit
          volumes:
            - name: state
              persistentVolumeClaim:
                claimName: continuity-state
            - name: audit
              persistentVolumeClaim:
                claimName: continuity-audit
```

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: continuity-secrets
  namespace: continuity
type: Opaque
stringData:
  RESEND_API_KEY: "re_xxxxx"
  TWILIO_ACCOUNT_SID: "ACxxxxx"
  TWILIO_AUTH_TOKEN: "xxxxx"
  TWILIO_FROM_NUMBER: "+15551234567"
```

---

## Static Site Hosting

### GitHub Pages

1. Enable Pages in repository settings
2. Set source to `gh-pages` branch or `/public` folder
3. Build and push:
   ```bash
   python -m src.main build-site
   git add public/
   git commit -m "Update site"
   git push
   ```

### Vercel

1. Connect repository to Vercel
2. Set build command: `python -m src.main build-site`
3. Set output directory: `public`

### Netlify

1. Connect repository
2. Build command: `pip install -e . && python -m src.main build-site`
3. Publish directory: `public`

---

## Monitoring

### Health Checks

Add to your monitoring system:

```bash
# Check last tick ran recently
python -m src.main status --json | jq '.last_tick_age_minutes < 30'
```

### Alerts

Configure your monitoring to alert on:

- **Tick age > 30 minutes**: Tick not running
- **State = FULL**: Maximum escalation reached
- **Audit log errors**: Check `audit/ledger.ndjson` for failures

### Prometheus Metrics

Coming soon in a future release.

---

## Backup Strategy

### State File

```bash
# Daily backup
cp state/current.json backups/state-$(date +%Y%m%d).json
```

### Audit Log

```bash
# Compress and archive
gzip -k audit/ledger.ndjson
mv audit/ledger.ndjson.gz backups/
```

### Automated Backup Script

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/continuity/$(date +%Y/%m)"
mkdir -p "$BACKUP_DIR"

# State
cp state/current.json "$BACKUP_DIR/state-$(date +%Y%m%d-%H%M).json"

# Audit (rotate if > 10MB)
if [ $(stat -c%s audit/ledger.ndjson) -gt 10000000 ]; then
    mv audit/ledger.ndjson "$BACKUP_DIR/ledger-$(date +%Y%m%d).ndjson"
    gzip "$BACKUP_DIR/ledger-$(date +%Y%m%d).ndjson"
fi
```

---

## Security Considerations

### Secrets Management

- **Never commit** `.env` files or secrets to git
- Use environment variables or secret management tools
- Rotate credentials regularly

### File Permissions

```bash
chmod 600 .env
chmod 600 state/current.json
chmod 700 audit/
```

### Network

- Use HTTPS for all webhook endpoints
- Restrict access to admin endpoints
- Consider VPN for internal services

---

## Troubleshooting

### Common Issues

**Tick not running:**
```bash
# Check logs
docker compose logs orchestrator
journalctl -u continuity-orchestrator.service
```

**Adapter failures:**
```bash
# Check configuration
python -m src.main check-config
```

**State corruption:**
```bash
# Validate state
python -m src.main status

# Reset if needed
python -m src.main reset
```

### Getting Help

- Check `docs/DEVELOPMENT.md` for debugging tips
- Review `audit/ledger.ndjson` for recent events
- Open an issue on GitHub
