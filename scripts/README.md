# Scripts

Helper scripts for common operations.

---

## Docker Scripts

| Script | Description | Usage |
|--------|-------------|-------|
| `docker-local.sh` | Run in standalone mode (state in Docker volumes) | `./scripts/docker-local.sh [--build]` |
| `docker-sync.sh` | Run with Git sync (state persists to repo) | `./scripts/docker-sync.sh [--build]` |

### Docker Modes

**Standalone (Local Testing):**
```bash
./scripts/docker-local.sh
# Opens http://localhost:8080
# State lives in Docker volumes only
```

**Git-Synced (Production):**
```bash
./scripts/docker-sync.sh
# State commits back to repository
# Requires GITHUB_TOKEN configured
```

**Rebuild after code changes:**
```bash
./scripts/docker-local.sh --build
./scripts/docker-sync.sh --build
```

---

## Development Scripts

| Script | Description | Usage |
|--------|-------------|-------|
| `rebuild-site.sh` | Rebuild static site locally | `./scripts/rebuild-site.sh` |
| `docker_init.py` | Initialize state for Docker containers | (Internal use) |

### Rebuild Site

```bash
# Rebuild and serve locally
./scripts/rebuild-site.sh
python -m http.server -d public 8080
```

---

## Deprecated Scripts

| Script | Status | Alternative |
|--------|--------|-------------|
| `run_tick.sh` | Deprecated | Use `python -m src.main tick` |
| `demo_escalation.sh` | Deprecated | Use `./demo.sh` from project root |

---

## Creating New Scripts

1. Place script in this directory
2. Make executable: `chmod +x scripts/my_script.sh`
3. Add entry to this README
4. Follow existing patterns:
   - Source `.venv/bin/activate` if using Python
   - Use consistent color codes
   - Handle errors with `set -e`
