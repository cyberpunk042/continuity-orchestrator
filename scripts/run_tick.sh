#!/usr/bin/env bash
# Local tick runner for development
#
# Usage:
#   ./scripts/run_tick.sh          # Normal tick
#   ./scripts/run_tick.sh --dry-run  # Dry run

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Activate venv if present
if [[ -d .venv ]]; then
    source .venv/bin/activate
fi

# Default to mock mode
export ADAPTER_MOCK_MODE="${ADAPTER_MOCK_MODE:-true}"

# Parse arguments
DRY_RUN=""
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
fi

# Ensure dependencies
if ! python -c "import click" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -e .
fi

# Run tick
echo "Running continuity tick..."
python -m src.main tick $DRY_RUN

# Show state summary
echo ""
echo "Current state:"
python -m src.main status
