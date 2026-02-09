# Project Reference

Everything in this project and where to configure it.

---

## Quick Map

```
.
├── setup.sh            ← START HERE (interactive wizard)
├── manage.sh           ← Daily operations (menu + CLI)
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
│   ├── media/          ← Uploaded media (encrypted, tiered storage)
│   │   ├── *.enc       ← Git-tracked encrypted files (<50 MB)
│   │   └── large/      ← GitHub Release-backed files (>50 MB)
│   └── manifest.yaml   ← What gets published when
│
├── templates/          ← Message templates
│   ├── html/           ← Site templates (countdown, articles)
│   ├── operator/       ← Email/SMS reminder templates
│   ├── custodians/     ← Pre-release notice templates
│   ├── public/         ← Public announcement templates
│   └── articles/       ← Long-form content templates
│
├── public/             ← Generated site (built from content/)
│
├── src/admin/          ← Web admin dashboard (Flask)
│   ├── server.py       ← App factory, blueprint registration
│   ├── routes_*.py     ← 12 API route blueprints
│   ├── templates/      ← Jinja2 HTML + JS partials
│   └── static/css/     ← Admin stylesheet
│
└── tests/              ← Test suite (639 tests)
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
| `CONTENT_ENCRYPTION_KEY` | Key for media/article encryption at rest |

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

Author documents in the admin dashboard (Editor.js) or place JSON files directly:

```
content/articles/
├── full_disclosure.json    # Your main document
├── about.json              # About page
└── notice.json             # Formal notice
```

See `content/README.md` for format and the [Authoring Guide](AUTHORING.md) for block types.

---

### `content/manifest.yaml` — What Gets Published

Controls which articles are visible at which stage:

```yaml
articles:
  - slug: full_disclosure
    title: "Full Disclosure"
    visibility:
      min_stage: FULL
      include_in_nav: true
```

---

### `content/media/` — Uploaded Media

Media files uploaded through the admin dashboard:

| Storage Tier | Location | Size Limit | Sync |
|-------------|----------|------------|------|
| `git` | `content/media/*.enc` | <50 MB | Normal git push |
| `large` | `content/media/large/*.enc` | <1 GB | GitHub Release (`media-vault` tag) |

Media is auto-optimized on upload (images → WebP, video → H.264, audio → AAC).

---

## Admin Dashboard

The web admin runs locally at `http://localhost:5050`:

```bash
./manage.sh web        # Start admin server
./manage.sh web --debug  # With debug logging
```

| Feature | Description |
|---------|-------------|
| **Dashboard** | System status, git info, health |
| **Content Editor** | Author articles with Editor.js |
| **Media Manager** | Upload, preview, encrypt media |
| **Secrets** | Push GitHub secrets from browser |
| **Policy Editor** | Edit rules/plans with timeline preview |
| **Backup/Restore** | Export/import system state |
| **Mirror Sync** | Multi-repo streaming sync |
| **Git Operations** | Commit, push from browser |
| **Docker** | Container management |
| **Vault** | Encrypt/decrypt .env on disk |

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
| X (Twitter) | [developer.x.com](https://developer.x.com) | Social posting |
| Reddit | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) | Social posting |

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
| web | Launch admin dashboard |
| backup | Create/restore backups |

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

See [DEPLOYMENT.md](DEPLOYMENT.md) for full details.

---

## File Reference Index

| File | Purpose | Documentation |
|------|---------|---------------|
| `.env` | Your credentials | `.env.example` |
| `state/current.json` | Countdown state | Auto-managed |
| `policy/rules.yaml` | Escalation rules | `policy/README.md` |
| `policy/states.yaml` | Stage definitions | `policy/README.md` |
| `policy/plans/*.yaml` | Actions per stage | `policy/README.md` |
| `content/articles/*.json` | Your documents | [AUTHORING.md](AUTHORING.md) |
| `content/media/manifest.json` | Media registry | Auto-managed |
| `content/manifest.yaml` | Publication schedule | `content/README.md` |
| `templates/operator/*.md` | Email/SMS templates | `templates/README.md` |
| `templates/html/*.html` | Site templates | `templates/README.md` |
| `src/admin/routes_*.py` | Admin API routes | [DEVELOPMENT.md](DEVELOPMENT.md) |

---

*Everything starts with `./setup.sh`. Everything else is managed through `./manage.sh`.*
