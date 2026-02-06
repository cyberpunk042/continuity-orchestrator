# Forking & Deploying Your Own Instance

This guide walks you through forking Continuity Orchestrator and running your own fully independent instance.

---

## Table of Contents

1. [Overview](#overview)
2. [Step 1: Fork the Repository](#step-1-fork-the-repository)
3. [Step 2: Configure Secrets](#step-2-configure-secrets)
4. [Step 3: Customize Your Policy](#step-3-customize-your-policy)
5. [Step 4: Initialize State](#step-4-initialize-state)
6. [Step 5: Enable the Workflow](#step-5-enable-the-workflow)
7. [Step 6: Test Everything](#step-6-test-everything)
8. [Step 7: Go Live](#step-7-go-live)
9. [Ongoing Maintenance](#ongoing-maintenance)

---

## Overview

### What You'll Get

After completing this guide, you'll have:

- ✅ Your own private repository
- ✅ Automated tick every 30 minutes via GitHub Actions
- ✅ A live dashboard at `https://yourusername.github.io/your-repo/`
- ✅ Configured notifications (email, SMS, etc.)
- ✅ Full control over escalation rules

### Time Required

| Step | Time |
|------|------|
| Fork and clone | 2 minutes |
| Configure secrets | 10 minutes |
| Customize policy | 15 minutes |
| Initialize and test | 10 minutes |
| **Total** | **~40 minutes** |

---

## Step 1: Fork the Repository

### 1.1 Create Your Fork

1. Go to [github.com/cyberpunk042/continuity-orchestrator](https://github.com/cyberpunk042/continuity-orchestrator)
2. Click **Fork** (top right)
3. Choose your account/organization
4. ✅ Keep "Copy the `main` branch only" checked
5. Click **Create fork**

### 1.2 Make It Private (Recommended)

If your content is sensitive:

1. Go to your fork's **Settings**
2. Scroll to **Danger Zone**
3. Click **Change visibility**
4. Select **Private**
5. Confirm

### 1.3 Clone Locally

```bash
git clone https://github.com/YOUR_USERNAME/continuity-orchestrator.git
cd continuity-orchestrator
```

---

## Step 2: Configure Secrets

### 2.1 Generate Your Secret Codes

```bash
# Generate renewal code (use this to extend your deadline)
python3 -c "import secrets; print('RENEWAL_SECRET:', secrets.token_hex(32))"

# Generate release code (use this to trigger immediate disclosure)
python3 -c "import secrets; print('RELEASE_SECRET:', secrets.token_hex(32))"

# Generate renewal trigger token (for dashboard)
python3 -c "import secrets; print('RENEWAL_TRIGGER_TOKEN:', secrets.token_hex(16))"
```

**Save these somewhere secure** (password manager recommended).

### 2.2 Add Secrets to GitHub

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each:

| Secret Name | Description | Required |
|-------------|-------------|----------|
| `RENEWAL_SECRET` | Code to renew deadline | ✅ Yes |
| `RELEASE_SECRET` | Code to trigger disclosure | ✅ Yes |
| `RENEWAL_TRIGGER_TOKEN` | Token for dashboard renewal | ✅ Yes |
| `RESEND_API_KEY` | Email via Resend | If using email |
| `TWILIO_ACCOUNT_SID` | SMS via Twilio | If using SMS |
| `TWILIO_AUTH_TOKEN` | SMS via Twilio | If using SMS |
| `TWILIO_FROM_NUMBER` | Your Twilio phone | If using SMS |

### 2.3 Get API Keys (If Needed)

| Service | Get Key | Free Tier |
|---------|---------|-----------|
| **Resend** (Email) | [resend.com/api-keys](https://resend.com/api-keys) | 100 emails/day |
| **Twilio** (SMS) | [console.twilio.com](https://console.twilio.com) | Trial credits |

---

## Step 3: Customize Your Policy

### 3.1 Edit Escalation Rules

The default rules trigger:
- **WARNING** at 24 hours before deadline
- **CRITICAL** at 6 hours before deadline
- **FINAL** when deadline passes

Edit `policy/rules.yaml` to customize:

```yaml
rules:
  - id: R10_WARNING_STAGE
    description: "Warn at 12 hours before deadline"
    when:
      - time_to_deadline_minutes <= 720  # 12 hours
      - escalation_state == "OK"
    then:
      transition_to: WARNING
```

### 3.2 Configure Actions

Edit `policy/plans/default.yaml` to define what happens at each stage:

```yaml
stages:
  WARNING:
    actions:
      - id: warn_email
        adapter: email
        channel: operator
        template: warning_email

  FINAL:
    actions:
      - id: final_email
        adapter: email
        channel: operator
        template: final_notice
      - id: publish_site
        adapter: article_publish
```

### 3.3 Add Your Content (Optional)

Place documents in `content/articles/`:

```
content/
├── articles/
│   ├── my-document.md
│   └── important-info.md
└── manifest.yaml
```

Update `content/manifest.yaml`:

```yaml
articles:
  - slug: my-document
    title: "My Important Document"
    publish_at_stage: FINAL
```

---

## Step 4: Initialize State

### 4.1 Set Up Locally

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .

# Create .env with your email
cat > .env << 'EOF'
PROJECT_NAME=my-project
OPERATOR_EMAIL=your-email@example.com
ADAPTER_MOCK_MODE=true
EOF
```

### 4.2 Initialize Project

```bash
python -m src.main init \
  --project "my-project" \
  --github-repo "YOUR_USERNAME/continuity-orchestrator" \
  --deadline-hours 48 \
  --operator-email "your-email@example.com"
```

### 4.3 Commit Initial State

```bash
git add state/ audit/ content/
git commit -m "Initialize my continuity orchestrator"
git push
```

---

## Step 5: Enable the Workflow

### 5.1 Enable GitHub Actions

1. Go to your repository → **Actions**
2. Click **I understand my workflows, go ahead and enable them**

### 5.2 Enable GitHub Pages

1. Go to **Settings** → **Pages**
2. Source: **GitHub Actions**
3. Save

### 5.3 Trigger First Run

1. Go to **Actions** → **continuity-tick**
2. Click **Run workflow** → **Run workflow**
3. Watch it complete

### 5.4 Verify Dashboard

Open `https://YOUR_USERNAME.github.io/continuity-orchestrator/`

You should see your dashboard with:
- Current stage (OK)
- Countdown timer
- Deadline

---

## Step 6: Test Everything

### 6.1 Test in Mock Mode (Safe)

The default has `ADAPTER_MOCK_MODE=true`, meaning no real notifications.

Run a test tick:
```bash
python -m src.main tick --dry-run
```

### 6.2 Test Email (If Configured)

```bash
# Add your Resend key to .env
echo "RESEND_API_KEY=re_your_key" >> .env

# Send test email
python -m src.main test email --to your@email.com
```

### 6.3 Test Full Flow

```bash
# See what happens at each stage
python -m src.main explain-stages

# Simulate timeline
python -m src.main simulate-timeline --hours 72
```

### 6.4 Test Renewal

1. Open your dashboard
2. Navigate to `/countdown.html`
3. Enter your `RENEWAL_SECRET`
4. Verify deadline extends

---

## Step 7: Go Live

### 7.1 Arm the System

Update GitHub Actions environment variable:

1. **Settings** → **Variables and secrets** → **Actions** → **Variables**
2. Add: `ADAPTER_MOCK_MODE` = `false`

Or add to repository secrets:
- `ADAPTER_MOCK_MODE` = `false`

### 7.2 Set Production Deadline

```bash
# Set real deadline (e.g., 1 week)
python -m src.main set-deadline --hours 168

# Commit the new state
git add state/
git commit -m "Set production deadline"
git push
```

### 7.3 Verify Notifications Work

Wait for next tick (or trigger manually) and check:
- ✅ No errors in Actions log
- ✅ State commits happening
- ✅ Dashboard updates

### 7.4 Save Your Renewal Code

**Critical:** Store your `RENEWAL_SECRET` in:
- Password manager
- Physical safe
- With a trusted contact

---

## Ongoing Maintenance

### Renewing Your Deadline

You have several options:

1. **Dashboard** — Enter code at `/countdown.html`
2. **GitHub Actions** — Run "Renew Deadline" workflow
3. **CLI** — `python -m src.main renew --hours 48`

### Monitoring

- Check GitHub Actions runs weekly
- Ensure dashboard is accessible
- Verify email/SMS are still working

### Updating from Upstream

To get new features:

```bash
# Add upstream remote (one time)
git remote add upstream https://github.com/cyberpunk042/continuity-orchestrator.git

# Fetch and merge updates
git fetch upstream
git merge upstream/main

# Resolve any conflicts in policy/ or content/
git push
```

### Backup Your State

Your state is already in Git, but for extra safety:

```bash
# Export state periodically
cp state/current.json ~/backups/continuity-$(date +%Y%m%d).json
```

---

## Troubleshooting

### Actions Not Running

1. Check Actions are enabled
2. Verify workflow file exists at `.github/workflows/cron.yml`
3. Check for syntax errors in workflow

### Dashboard Not Loading

1. Verify GitHub Pages is enabled
2. Check Actions completed successfully
3. Look for `public/` in the latest Action artifacts

### Renewal Not Working

1. Verify secret matches exactly
2. Check for copy/paste issues (trailing spaces)
3. Look at Action logs for errors

### Email Not Sending

1. Verify `RESEND_API_KEY` is set in secrets
2. Check `ADAPTER_MOCK_MODE` is `false`
3. Test locally: `python -m src.main test email`

---

## Security Reminders

- ✅ Keep repository private if content is sensitive
- ✅ Store renewal code in password manager
- ✅ Share renewal code with trusted backup person
- ✅ Review [SECURITY.md](SECURITY.md) thoroughly
- ✅ Rotate secrets annually

---

## Questions?

Open an issue on GitHub or check existing documentation:
- [QUICKSTART.md](docs/QUICKSTART.md)
- [CONFIGURATION.md](docs/CONFIGURATION.md)
- [DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

*Welcome to continuity.*
