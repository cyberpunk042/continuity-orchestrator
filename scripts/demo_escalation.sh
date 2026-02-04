#!/usr/bin/env bash
# Demonstrate escalation through stages
#
# This script sets a short deadline and runs ticks at intervals
# to show the escalation progression.
#
# Usage:
#   ./scripts/demo_escalation.sh

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Activate venv if present
if [[ -d .venv ]]; then
    source .venv/bin/activate
fi

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Continuity Orchestrator — Escalation Demo              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Reset state
echo "🔄 Resetting state to OK..."
python -m src.main reset
echo ""

# Set a deadline that puts us in REMIND_1 (5 hours = 300 min, between 60-360)
echo "⏱  Setting deadline to 5 hours from now..."
python -m src.main set-deadline --hours 5
echo ""

# Show initial status
echo "📊 Initial state:"
python -m src.main status
echo ""

# Run first tick - should escalate to REMIND_1
echo "═══════════════════════════════════════════════════════════"
echo "▶ Running tick #1..."
python -m src.main tick
echo ""

echo "📊 State after tick #1:"
python -m src.main status
echo ""

# Set a shorter deadline to trigger REMIND_2
echo "═══════════════════════════════════════════════════════════"
echo "⏱  Setting deadline to 30 minutes from now..."
python -m src.main set-deadline --hours 0.5
echo ""

# Run second tick - should escalate to REMIND_2
echo "▶ Running tick #2..."
python -m src.main tick
echo ""

echo "📊 State after tick #2:"
python -m src.main status
echo ""

# Set an even shorter deadline for PRE_RELEASE
echo "═══════════════════════════════════════════════════════════"
echo "⏱  Setting deadline to 10 minutes from now..."
python -m src.main set-deadline --hours 0.16
echo ""

# Run third tick - should escalate to PRE_RELEASE
echo "▶ Running tick #3..."
python -m src.main tick
echo ""

echo "📊 State after tick #3:"
python -m src.main status
echo ""

# Show final audit summary
echo "═══════════════════════════════════════════════════════════"
echo "📜 Recent audit entries (last 5):"
tail -5 audit/ledger.ndjson | jq -r '"[\(.type)] \(.details | if .rule_id then "rule: " + .rule_id elif .from then .from + " → " + .to else "" end)"' 2>/dev/null || tail -5 audit/ledger.ndjson
echo ""

echo "✅ Demo complete!"
echo ""
echo "To continue escalation, run: python -m src.main tick"
echo "To reset: python -m src.main reset"
