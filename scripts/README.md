# Scripts

Helper scripts for common operations.

## Available Scripts

| Script | Description |
|--------|-------------|
| `rebuild-site.sh` | Rebuild static site and optionally deploy |
| `demo_escalation.sh` | Demonstrate the escalation flow |
| `docker_init.py` | Initialize state for Docker containers |
| `run_tick.sh` | Run a single tick of the engine |

## Usage

```bash
# Rebuild the static site
./scripts/rebuild-site.sh

# Rebuild and deploy to gh-pages
./scripts/rebuild-site.sh --deploy

# Preview locally
python -m http.server -d public 8080

# Run escalation demo
./scripts/demo_escalation.sh

# Initialize Docker state
python scripts/docker_init.py /data/state/current.json
```

## Adding New Scripts

Place new scripts here. For shell scripts, ensure they're executable:

```bash
chmod +x scripts/my_script.sh
```
