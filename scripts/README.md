# Scripts

Helper scripts for common operations.

## Available Scripts

| Script | Description |
|--------|-------------|
| `docker_init.py` | Initialize state for Docker containers |
| `demo_escalation.sh` | Demonstrate the escalation flow |

## Usage

```bash
# Run escalation demo
./scripts/demo_escalation.sh

# Initialize Docker state
python scripts/docker_init.py /data/state/current.json
```

## Adding New Scripts

Place new scripts here. For Python scripts, ensure they're executable:

```bash
chmod +x scripts/my_script.py
```
