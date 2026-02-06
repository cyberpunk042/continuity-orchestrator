# Quickstart

Get Continuity Orchestrator running in 5 minutes.

---

## See It First (30 seconds)

```bash
git clone https://github.com/cyberpunk042/continuity-orchestrator.git
cd continuity-orchestrator
./demo.sh
```

Watch the full escalation: **OK → WARNING → CRITICAL → FINAL**

---

## Set Up Your Own (5 minutes)

```bash
./setup.sh
```

The wizard will:
1. Ask what you want to use it for
2. Get your project name and email
3. Help configure notifications
4. Set your deadline
5. Generate your renewal codes

---

## Run It

### Docker (Easiest)

```bash
./scripts/docker-local.sh
# Open http://localhost:8080
```

### GitHub Actions (Production)

The wizard shows which secrets to add. Then push to GitHub — it runs automatically.

---

## Manage It

```bash
./manage.sh
```

Menu-driven interface for:
- **status** — See current countdown
- **renew** — Extend your deadline
- **tick** — Run the engine manually
- **reset** — Start fresh
- And more

---

## Key Files

| What | Where |
|------|-------|
| Setup wizard | `./setup.sh` |
| Management menu | `./manage.sh` |
| Your config | `.env` |
| Your state | `state/current.json` |
| Your rules | `policy/rules.yaml` |

---

## Next Steps

- Review [SECURITY.md](../SECURITY.md) before going live
- Customize `policy/rules.yaml` for your timing
- Add content to `content/articles/`

---

*Questions? Run `./manage.sh` and explore.*
