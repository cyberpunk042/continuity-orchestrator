# Project Reference

Everything in this project and where to configure it.

---

## Quick Map

```
.
├── setup.sh            ← START HERE (interactive wizard)
├── manage.sh           ← Daily operations (menu)
├── demo.sh             ← See it work (30 seconds)
│
├── .env                ← Your credentials (created by setup.sh)
├── .env.example        ← All available settings documented
│
├── state/              ← Your current countdown state
│   └── current.json    ← The timer, stage, deadline
│
├── policy/             ← Your rules and actions
│   ├── rules.yaml      ← When to escalate
│   ├── states.yaml     ← Stage definitions  
│   └── plans/          ← What to do at each stage
│
├── content/            ← Your disclosure content
│   ├── articles/       ← Documents to publish (Editor.js JSON)
│   └── manifest.yaml   ← What gets published when
│
├── templates/          ← Message templates
│   ├── html/           ← Site templates
│   └── operator/       ← Email/SMS templates
│
└── public/             ← Generated site (built from content/)
```

---

## Configuration Files

### `.env` — Your Credentials

Created by `./setup.sh` or copy from `.env.example`:

```bash
cp .env.example .env
# Edit .env with your values
```

| Setting | What it does |
|---------|--------------|
| `PROJECT_NAME` | Name shown in notifications |
| `OPERATOR_EMAIL` | Where you receive reminders |
| `ADAPTER_MOCK_MODE` | `true` = testing, `false` = live |
| `RENEWAL_SECRET` | Code to extend deadline |
| `RELEASE_SECRET` | Code to trigger disclosure |

See `.env.example` for all available settings with full documentation.

---

### `policy/rules.yaml` — When to Escalate

Defines when the system transitions between stages:

```yaml
rules:
  - id: R10_WARNING_STAGE
    when:
      - time_to_deadline_minutes <= 1440  # 24 hours
      - escalation_state == "OK"
    then:
      transition_to: WARNING
```

See `policy/README.md` for conditions and examples.

---

### `policy/plans/default.yaml` — What to Do

Defines actions for each stage:

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
      - id: publish_all
        adapter: article_publish
```

---

### `content/articles/` — Your Documents

Place Editor.js JSON files here to publish on disclosure:

```
content/articles/
├── full_disclosure.json    # Your main document
└── about.json              # About page
```

See `content/README.md` for format and examples.

---

### `content/manifest.yaml` — What Gets Published

Controls which articles are visible at which stage:

```yaml
articles:
  - slug: full_disclosure
    title: "Full Disclosure"
    publish_at_stage: FINAL
```

---

## Credentials Setup

### Method 1: Interactive (Recommended)

```bash
./setup.sh
```

Walks through each adapter and saves to `.env`.

### Method 2: Manual

1. Copy example: `cp .env.example .env`
2. Edit `.env` with your keys
3. Run `./manage.sh` → test to verify

### API Keys You Might Need

| Service | Get it at | Used for |
|---------|-----------|----------|
| Resend | [resend.com/api-keys](https://resend.com/api-keys) | Email notifications |
| Twilio | [console.twilio.com](https://console.twilio.com) | SMS alerts |
| GitHub | [github.com/settings/tokens](https://github.com/settings/tokens) | Publishing & state sync |

---

## Daily Operations

Use the management menu:

```bash
./manage.sh
```

| Option | What it does |
|--------|--------------|
| status | Show current countdown |
| renew | Extend deadline |
| tick | Run engine manually |
| reset | Start fresh |
| build-site | Generate HTML |
| test | Verify integrations work |

---

## Deployment

### Option A: GitHub Actions

1. Run `./setup.sh` to configure
2. Push to GitHub
3. Add secrets shown by `./manage.sh` → secrets
4. Enable Actions in repository settings

### Option B: Docker

```bash
./scripts/docker-local.sh     # Test locally
./scripts/docker-sync.sh      # Production with Git sync
```

---

## File Reference Index

| File | Purpose | Documentation |
|------|---------|---------------|
| `.env` | Your credentials | `.env.example` |
| `state/current.json` | Countdown state | Auto-managed |
| `policy/rules.yaml` | Escalation rules | `policy/README.md` |
| `policy/states.yaml` | Stage definitions | `policy/README.md` |
| `policy/plans/*.yaml` | Actions per stage | `policy/README.md` |
| `content/articles/*.json` | Your documents | `content/README.md` |
| `content/manifest.yaml` | Publication schedule | `content/README.md` |
| `templates/operator/*.md` | Email/SMS templates | `templates/README.md` |
| `templates/html/*.html` | Site templates | `templates/README.md` |

---

*Everything starts with `./setup.sh`. Everything else is managed through `./manage.sh`.*
