# Integration Setup Wizard Plan

## Overview

Create a unified, guided setup experience for all integrations - both CLI and Web UI.
Make it simple, straightforward, and help users understand requirements upfront.

---

## 1. Deployment Mode Selection (First Step)

Before configuring integrations, user must choose their deployment mode:

### Option A: GitHub Pages (Recommended)
- **Free Tier**: Public repo only (site + code both public)
- **Pro/Team**: Private repo with public GitHub Pages
- **Requirements**:
  - GitHub account
  - Repository (new or fork)
  - GitHub Actions enabled
  - Pages enabled in repo settings

### Option B: Docker git-sync (Self-Hosted)
- For users who can't/don't want GitHub Pro
- Syncs to a separate public repo for the site only
- **Requirements**:
  - Docker + Docker Compose
  - Two repos: private (code) + public (site)
  - OR: Single public repo for site only

### Option C: Docker Standalone (Fully Self-Hosted)
- No public website, just the orchestrator
- Notifications only (email, SMS, webhooks)
- **Requirements**:
  - Docker + Docker Compose
  - No GitHub needed

---

## 2. Integration Cards

Each integration has a setup card with:

```
┌─────────────────────────────────────────────────────────────┐
│ [ICON] Integration Name                     [STATUS BADGE] │
├─────────────────────────────────────────────────────────────┤
│ Description of what this integration does                   │
│                                                             │
│ 📋 REQUIREMENTS                                              │
│ • Requirement 1 (with link if external)                     │
│ • Requirement 2                                              │
│                                                             │
│ 📖 SETUP GUIDE (collapsible)                                 │
│ 1. Step one with instructions                               │
│ 2. Step two...                                              │
│                                                             │
│ 🔑 CONFIGURATION                                             │
│ SECRET_NAME: [input] [👁️]                                    │
│ ANOTHER_KEY: [input] [👁️]                                    │
│                                                             │
│ [Test Connection]  [Save to Local]  [Save to GitHub]        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Integration Definitions

### Core (Required)

#### GitHub Repository
- **Purpose**: Core deployment and CI/CD
- **Requirements**:
  - GitHub account
  - Repository (fork or new)
  - `gh` CLI for easy token generation
- **Secrets**:
  - `GITHUB_TOKEN` - Personal access token (or use gh auth)
  - `GITHUB_REPOSITORY` - owner/repo format
- **Setup Steps**:
  1. Fork or create repository
  2. Enable GitHub Actions (Settings → Actions)
  3. Enable GitHub Pages (Settings → Pages → Source: GitHub Actions)
  4. Generate token: `gh auth token` or create PAT
- **Test**: `gh api repos/{owner}/{repo}`

---

### Notifications

#### Email (Resend)
- **Purpose**: Send email notifications
- **Requirements**:
  - Resend account (free: 100 emails/day, 3000/month)
  - Verified domain (optional, can use resend.dev)
- **Secrets**:
  - `RESEND_API_KEY` - API key from dashboard
  - `RESEND_FROM_EMAIL` - Verified sender email
- **Setup Steps**:
  1. Create account at resend.com
  2. Verify domain (or use onboarding@resend.dev for testing)
  3. Create API key in dashboard
- **Test**: Send test email to OPERATOR_EMAIL
- **Link**: https://resend.com/signup

#### SMS (Twilio)
- **Purpose**: Send SMS notifications
- **Requirements**:
  - Twilio account (free trial includes credits)
  - Verified phone number
- **Secrets**:
  - `TWILIO_ACCOUNT_SID` - Account SID
  - `TWILIO_AUTH_TOKEN` - Auth token
  - `TWILIO_FROM_NUMBER` - Twilio phone number
  - `OPERATOR_SMS` - Your phone number
- **Setup Steps**:
  1. Create account at twilio.com
  2. Get free trial number
  3. Verify your phone number
  4. Copy credentials from dashboard
- **Test**: Send test SMS to OPERATOR_SMS
- **Link**: https://www.twilio.com/try-twilio

---

### Social Media

#### X (Twitter)
- **Purpose**: Post to X/Twitter
- **Requirements**:
  - X Developer account (free tier available)
  - App with read/write permissions
- **Secrets**:
  - `X_API_KEY` - API Key
  - `X_API_SECRET` - API Key Secret
  - `X_ACCESS_TOKEN` - Access Token
  - `X_ACCESS_SECRET` - Access Token Secret
- **Setup Steps**:
  1. Apply for developer account at developer.twitter.com
  2. Create a project and app
  3. Set app permissions to "Read and Write"
  4. Generate access tokens
- **Test**: Post test tweet (dry run)
- **Link**: https://developer.twitter.com/en/portal/dashboard
- **Note**: Free tier limited to 1,500 tweets/month

#### Reddit
- **Purpose**: Post to Reddit
- **Requirements**:
  - Reddit account
  - Reddit app (script type)
- **Secrets**:
  - `REDDIT_CLIENT_ID` - App client ID
  - `REDDIT_CLIENT_SECRET` - App secret
  - `REDDIT_USERNAME` - Reddit username
  - `REDDIT_PASSWORD` - Reddit password
- **Setup Steps**:
  1. Go to reddit.com/prefs/apps
  2. Create app (type: script)
  3. Note the client ID (under app name)
  4. Copy the secret
- **Test**: Verify authentication
- **Link**: https://www.reddit.com/prefs/apps

---

### Future Integrations (Placeholders)

#### Discord Webhook
- **Status**: Planned
- **Secrets**: `DISCORD_WEBHOOK_URL`

#### Slack Webhook
- **Status**: Planned
- **Secrets**: `SLACK_WEBHOOK_URL`

#### Telegram Bot
- **Status**: Planned
- **Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

#### Matrix/Element
- **Status**: Planned
- **Secrets**: `MATRIX_HOMESERVER`, `MATRIX_TOKEN`, `MATRIX_ROOM_ID`

---

## 4. UI Structure

### Web Admin - New "Setup" Tab

```
┌──────────────────────────────────────────────────────────────┐
│  🏠 Dashboard │ 🔐 Secrets │ ⚙️ Setup │ ⚡ Commands │ 🧙 Wizard │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ⚙️ Integration Setup                                        │
│  Configure your deployment and integrations                  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 🚀 Deployment Mode                        [GitHub Pages]│ │
│  │ ─────────────────────────────────────────────────────  │ │
│  │ ○ GitHub Pages (requires Pro for private repo)         │ │
│  │ ○ Docker git-sync (self-hosted, syncs to public repo)  │ │
│  │ ○ Docker standalone (no public site)                   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  📦 CORE                                                     │
│  ┌──────────────────┐                                        │
│  │ 🐙 GitHub        │  ← GitHub integration card            │
│  └──────────────────┘                                        │
│                                                              │
│  📬 NOTIFICATIONS                                            │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ 📧 Email (Resend)│  │ 📱 SMS (Twilio)  │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
│  📢 SOCIAL MEDIA                                             │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ 🐦 X (Twitter)   │  │ 🤖 Reddit        │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
│  🔮 COMING SOON                                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ 💬 Discord       │  │ 💬 Slack         │                 │
│  │ (planned)        │  │ (planned)        │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. CLI Integration (setup.sh)

The CLI wizard follows the same flow:

```bash
╔══════════════════════════════════════════════════════════════╗
║           CONTINUITY ORCHESTRATOR — SETUP WIZARD             ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1: Deployment Mode
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

How do you want to deploy?

  1) GitHub Pages — Public site via GitHub (recommended)
     • Free: Public repo only
     • Pro/Team: Private repo + public site
     
  2) Docker git-sync — Self-hosted, syncs to public repo
     • No GitHub Pro needed
     • You host the orchestrator
     
  3) Docker standalone — Notifications only, no public site
     • Fully self-hosted
     • No public website

Choose (1-3) [1]: 

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2: Core Setup (GitHub)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[... continues with guided setup ...]
```

---

## 6. Implementation Order

### Phase 1: Foundation
- [ ] Create integration definitions data structure
- [ ] Add new "Setup" tab to web admin
- [ ] Create deployment mode selector

### Phase 2: Integration Cards
- [ ] Build reusable integration card component
- [ ] Implement GitHub integration card
- [ ] Implement Resend integration card
- [ ] Implement Twilio integration card

### Phase 3: Social Media
- [ ] Implement X/Twitter integration card
- [ ] Implement Reddit integration card

### Phase 4: Testing & Polish
- [ ] Add "Test Connection" for each integration
- [ ] Add inline help/tooltips
- [ ] Sync with CLI wizard

### Phase 5: Future
- [ ] Add Discord webhook
- [ ] Add Slack webhook
- [ ] Add Telegram bot
- [ ] Add Matrix/Element

---

## 7. Data Structure

```python
INTEGRATIONS = {
    "github": {
        "name": "GitHub",
        "icon": "🐙",
        "category": "core",
        "required": True,
        "description": "Repository and CI/CD deployment",
        "requirements": [
            "GitHub account",
            "Repository (fork or create new)",
            "GitHub CLI (gh) for easy setup",
        ],
        "secrets": [
            {"name": "GITHUB_TOKEN", "label": "GitHub Token", "type": "password"},
            {"name": "GITHUB_REPOSITORY", "label": "Repository", "type": "text", "placeholder": "owner/repo"},
        ],
        "setup_url": "https://github.com/settings/tokens",
        "docs_url": "/docs/GITHUB_SETUP.md",
        "test_command": "gh api user",
    },
    "resend": {
        "name": "Email (Resend)",
        "icon": "📧",
        "category": "notifications",
        "required": False,
        "description": "Send email notifications",
        # ...
    },
    # ...
}
```

---

## Next Steps

1. **Review this plan** - Does this cover everything?
2. **Start with Phase 1** - Foundation and Setup tab
3. **Iterate** - Add integrations one by one
