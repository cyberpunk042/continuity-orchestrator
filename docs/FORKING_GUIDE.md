# Fork & Deploy Your Own

Get your own Continuity Orchestrator running in under 10 minutes.

---

## The 3-Step Process

### 1. Fork & Clone

```bash
# Fork on GitHub, then:
git clone https://github.com/YOUR_USERNAME/continuity-orchestrator.git
cd continuity-orchestrator
```

### 2. Run Setup

```bash
./setup.sh
```

The wizard walks you through everything:
- Choose your use case (deadman switch, scheduled publishing, custom)
- Set your project name and email
- Configure integrations (email, SMS, etc.)
- Set your deadline
- Generate secure renewal codes

### 3. Deploy

**Option A: GitHub Actions (Recommended)**
```bash
# The wizard will show you which secrets to add
# Go to: Settings → Secrets → Actions → Add each secret
```

**Option B: Docker**
```bash
./scripts/docker-local.sh      # Test locally
./scripts/docker-sync.sh       # Production with Git sync
```

---

## After Setup

Use the management interface:

```bash
./manage.sh
```

This gives you a menu for:
- Check status
- Run tick
- Renew deadline
- Trigger release
- Build site
- And more

---

## That's It

- **Demo first?** Run `./demo.sh` before forking
- **Need help?** Check `./manage.sh` for all commands
- **Going live?** Read [SECURITY.md](../SECURITY.md) first

---

*The wizard handles the complexity. You just answer questions.*
