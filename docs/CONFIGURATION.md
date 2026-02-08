# Configuration Guide

This document covers all configuration options for Continuity Orchestrator.

---

## 📋 Quick Start

```bash
# Initialize a new project
python -m src.main init

# Check adapter configuration
python -m src.main check-config

# View current status
python -m src.main status
```

---

## 🔐 GitHub Secrets

Configure these secrets in your repository: **Settings → Secrets and variables → Actions**

| Secret | Required | Description |
|--------|----------|-------------|
| `RENEWAL_SECRET` | ✅ Yes | Your renewal code (used to extend the deadline) |
| `RESEND_API_KEY` | For email | Resend API key for email notifications |
| `TWILIO_ACCOUNT_SID` | For SMS | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | For SMS | Twilio auth token |
| `TWILIO_FROM_NUMBER` | For SMS | Twilio sender phone number |
| `GITHUB_TOKEN` | Auto | Automatically provided by GitHub Actions |

---

## 🌍 Environment Variables

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ADAPTER_MOCK_MODE` | `false` | If true, adapters log actions without executing |

### Email (Resend)

| Variable | Required | Description |
|----------|----------|-------------|
| `RESEND_API_KEY` | ✅ | API key from [resend.com](https://resend.com/api-keys) |
| `RESEND_FROM_EMAIL` | ❌ | Verified sender email (defaults to state routing) |

### SMS (Twilio)

| Variable | Required | Description |
|----------|----------|-------------|
| `TWILIO_ACCOUNT_SID` | ✅ | Account SID from Twilio console |
| `TWILIO_AUTH_TOKEN` | ✅ | Auth token from Twilio console |
| `TWILIO_FROM_NUMBER` | ✅ | Verified Twilio phone number |

### Webhook

| Variable | Required | Description |
|----------|----------|-------------|
| `WEBHOOK_TIMEOUT` | ❌ | Request timeout in seconds (default: 30) |

Webhook URLs are configured in `state/current.json` under `integrations.routing.observer_webhooks`.

### Persistence API

| Variable | Required | Description |
|----------|----------|-------------|
| `PERSISTENCE_API_URL` | ✅ | URL of your persistence endpoint |
| `PERSISTENCE_API_KEY` | ❌ | API key for authentication |
| `PERSISTENCE_API_TIMEOUT` | ❌ | Request timeout in seconds |

### GitHub Surface

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | ✅ | PAT or GITHUB_TOKEN from Actions |
| `GITHUB_REPOSITORY` | ❌ | Override repository (default: from state) |

---

## 📁 State Configuration

The main state file is `state/current.json`. Key sections:

### Meta

```json
{
  "meta": {
    "schema_version": 1,
    "project": "my-project",
    "state_id": "S-INIT-20260204",
    "updated_at_iso": "2026-02-04T12:00:00Z",
    "policy_version": 1,
    "plan_id": "default"
  }
}
```

### Timer

```json
{
  "timer": {
    "deadline_iso": "2026-02-06T12:00:00Z",
    "grace_minutes": 0,
    "time_to_deadline_minutes": 2880,
    "overdue_minutes": 0
  }
}
```

### Integrations

```json
{
  "integrations": {
    "enabled_adapters": {
      "email": true,
      "sms": false,
      "webhook": true,
      "github_surface": true,
      "article_publish": true
    },
    "routing": {
      "github_repository": "owner/repo",
      "operator_email": "operator@example.com",
      "operator_sms": "+15555550100",
      "custodian_emails": ["custodian@example.com"],
      "observer_webhooks": ["https://webhook.example.com/hook"]
    }
  }
}
```

---

## 📰 Content Manifest

The content manifest (`content/manifest.yaml`) controls article visibility:

```yaml
version: 1

articles:
  - slug: about
    title: "About This System"
    visibility:
      min_stage: OK          # Always visible
      include_in_nav: true
      pin_to_top: false
      
  - slug: notice
    title: "Formal Notice"
    visibility:
      min_stage: PARTIAL     # Only visible at PARTIAL or FULL
      include_in_nav: true
      pin_to_top: true       # Shows at top of article list

defaults:
  visibility:
    min_stage: FULL          # Default for unlisted articles
    include_in_nav: false

stages:
  OK:
    show_countdown: false
  REMIND_1:
    banner: "⏰ Deadline approaching"
    banner_class: warning
    show_countdown: true
  PARTIAL:
    banner: "📢 Partial disclosure active"
    banner_class: critical
    show_countdown: true
```

### Stage Order

Stages are ordered from least to most severe:

1. `OK` - Normal operation
2. `REMIND_1` - First reminder
3. `REMIND_2` - Second reminder
4. `PRE_RELEASE` - Pre-release warning
5. `PARTIAL` - Limited disclosure
6. `FULL` - Full disclosure

An article with `min_stage: PARTIAL` is visible at PARTIAL and FULL stages.

---

## 📋 Policy Configuration

### Rules (`policy/rules.yaml`)

Define state transition rules:

```yaml
rules:
  - id: overdue_to_partial
    description: "Transition to partial release when overdue"
    conditions:
      - type: time_past_deadline
        threshold_minutes: 0
      - type: current_state
        is_one_of: [REMIND_2, PRE_RELEASE]
    actions:
      - set_state: PARTIAL
```

### Plans (`policy/plans/default.yaml`)

Define actions for each stage:

```yaml
stages:
  REMIND_1:
    - id: remind_operator
      adapter: email
      channel: operator
      template: reminder_first
      constraints:
        idempotent: true
        no_links: true
```

---

## 🔄 GitHub Actions Workflows

### Tick Workflow (`.github/workflows/tick.yml`)

Runs on schedule to check state and execute actions:

```yaml
on:
  schedule:
    - cron: '0 * * * *'  # Every hour
  workflow_dispatch:       # Manual trigger
```

### Renewal Workflow (`.github/workflows/renew.yml`)

Manually triggered to extend the deadline:

```yaml
on:
  workflow_dispatch:
    inputs:
      renewal_code:
        description: 'Renewal code (secret)'
        required: true
```

---

## 🔍 Troubleshooting

### "Adapter not configured"

Run `python -m src.main check-config` to see missing configuration.

### "State file not found"

Run `python -m src.main init` to create initial state.

### "Invalid renewal code"

Ensure `RENEWAL_SECRET` is set correctly in GitHub Secrets.

### Articles not appearing

Check `content/manifest.yaml` - the article's `min_stage` may be higher than current stage.

---

## 📚 Related Documentation

- [Content Authoring Guide](AUTHORING.md)
- [Roadmap](ROADMAP.md)
