#!/bin/bash
#
# demo.sh — See Continuity Orchestrator work in 30 seconds
#
# No configuration needed. Just run it.
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

clear

echo ""
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         CONTINUITY ORCHESTRATOR — LIVE DEMO                   ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${DIM}This demo simulates a countdown going from OK → WARNING → CRITICAL → FINAL${NC}"
echo -e "${DIM}No real notifications are sent. Watch the escalation happen in real-time.${NC}"
echo ""
echo -e "${CYAN}Press Enter to start...${NC}"
read -r

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Setting up environment (first time only)...${NC}"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -e .
else
    source .venv/bin/activate
fi

# Create temporary demo state
DEMO_DIR=$(mktemp -d)
DEMO_STATE="$DEMO_DIR/state/current.json"
DEMO_AUDIT="$DEMO_DIR/audit/ledger.ndjson"
mkdir -p "$DEMO_DIR/state" "$DEMO_DIR/audit"

cleanup() {
    rm -rf "$DEMO_DIR"
}
trap cleanup EXIT

# Create initial state with very short deadline
NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
python3 << EOF
import json
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
# Set deadline to 3 seconds from now for demo
deadline = now + timedelta(seconds=3)

state = {
    "meta": {
        "schema_version": 1,
        "project": "demo-project",
        "state_id": "DEMO-001",
        "updated_at_iso": now.isoformat(),
        "policy_version": 1,
        "plan_id": "default"
    },
    "mode": {"name": "renewable_countdown", "armed": True},
    "timer": {
        "deadline_iso": deadline.isoformat(),
        "grace_minutes": 0,
        "now_iso": now.isoformat(),
        "time_to_deadline_minutes": 0,
        "overdue_minutes": 0
    },
    "renewal": {
        "last_renewal_iso": now.isoformat(),
        "renewed_this_tick": False,
        "renewal_count": 0
    },
    "security": {"failed_attempts": 0, "lockout_active": False, "lockout_until_iso": None, "max_failed_attempts": 3, "lockout_minutes": 60},
    "escalation": {"state": "OK", "state_entered_at_iso": now.isoformat(), "last_transition_rule_id": None},
    "actions": {"executed": {}, "last_tick_actions": []},
    "integrations": {
        "enabled_adapters": {"email": False, "sms": False, "x": False, "reddit": False, "webhook": False, "github_surface": False, "article_publish": False, "persistence_api": False},
        "routing": {"github_repository": "demo/repo", "operator_email": "demo@example.com", "operator_sms": None, "custodian_emails": [], "observer_webhooks": [], "reddit_targets": [], "x_account_ref": None}
    },
    "pointers": {"persistence": {"primary_backend": "file", "last_persist_iso": None}, "github_surface": {"last_public_artifact_ref": None}}
}

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

echo '{}' > "$DEMO_AUDIT"

# Function to show state
show_state() {
    local state=$(python3 -c "import json; s=json.load(open('$DEMO_STATE')); print(s['escalation']['state'])")
    local deadline=$(python3 -c "import json; s=json.load(open('$DEMO_STATE')); print(s['timer']['deadline_iso'][:19])")
    local ttd=$(python3 -c "import json; s=json.load(open('$DEMO_STATE')); print(s['timer']['time_to_deadline_minutes'])")
    local overdue=$(python3 -c "import json; s=json.load(open('$DEMO_STATE')); print(s['timer']['overdue_minutes'])")
    
    local color=$GREEN
    case $state in
        WARNING) color=$YELLOW ;;
        CRITICAL) color=$RED ;;
        FINAL) color=$RED ;;
    esac
    
    echo ""
    echo -e "┌──────────────────────────────────────────────────┐"
    echo -e "│  ${BOLD}State:${NC} ${color}${BOLD}$state${NC}                                     "
    echo -e "│  ${BOLD}Deadline:${NC} $deadline                   "
    if [ "$overdue" != "0" ]; then
        echo -e "│  ${BOLD}Overdue:${NC} ${RED}${overdue} minutes${NC}                           "
    else
        echo -e "│  ${BOLD}Time left:${NC} $ttd minutes                        "
    fi
    echo -e "└──────────────────────────────────────────────────┘"
}

run_tick() {
    echo -e "${CYAN}Running tick...${NC}"
    python -m src.main tick \
        --state-file "$DEMO_STATE" \
        --policy-dir policy \
        --audit-file "$DEMO_AUDIT" \
        --dry-run 2>&1 | grep -E "(State:|Actions|Matched|transition)" || true
}

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STAGE 1: OK STATE${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
show_state
echo ""
echo -e "${DIM}Countdown is running. Everything is normal.${NC}"
echo ""
echo -e "${CYAN}Press Enter to advance time...${NC}"
read -r

# Simulate time passing - set deadline to past
python3 << EOF
import json
from datetime import datetime, timezone, timedelta

with open("$DEMO_STATE") as f:
    state = json.load(f)

# Set deadline to 23 hours ago (so we're at ~23h remaining = WARNING)
now = datetime.now(timezone.utc)
state["timer"]["deadline_iso"] = (now + timedelta(hours=23)).isoformat()
state["timer"]["now_iso"] = now.isoformat()
state["timer"]["time_to_deadline_minutes"] = 23 * 60

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STAGE 2: TIME ADVANCES → WARNING${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Deadline is now 23 hours away (< 24h threshold).${NC}"
echo -e "${DIM}Running tick to evaluate rules...${NC}"
echo ""
run_tick
show_state

# Actually transition to WARNING
python3 << EOF
import json
from datetime import datetime, timezone

with open("$DEMO_STATE") as f:
    state = json.load(f)

state["escalation"]["state"] = "WARNING"
state["escalation"]["state_entered_at_iso"] = datetime.now(timezone.utc).isoformat()
state["escalation"]["last_transition_rule_id"] = "R10_WARNING_STAGE"

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

show_state
echo ""
echo -e "${YELLOW}⚠️  In real mode, you'd receive a reminder email now.${NC}"
echo ""
echo -e "${CYAN}Press Enter to advance time more...${NC}"
read -r

# Advance to CRITICAL
python3 << EOF
import json
from datetime import datetime, timezone, timedelta

with open("$DEMO_STATE") as f:
    state = json.load(f)

now = datetime.now(timezone.utc)
state["timer"]["deadline_iso"] = (now + timedelta(hours=5)).isoformat()
state["timer"]["time_to_deadline_minutes"] = 5 * 60

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STAGE 3: MORE TIME PASSES → CRITICAL${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Deadline is now 5 hours away (< 6h threshold).${NC}"
echo -e "${DIM}Running tick...${NC}"
echo ""
run_tick

python3 << EOF
import json
from datetime import datetime, timezone

with open("$DEMO_STATE") as f:
    state = json.load(f)

state["escalation"]["state"] = "CRITICAL"
state["escalation"]["state_entered_at_iso"] = datetime.now(timezone.utc).isoformat()
state["escalation"]["last_transition_rule_id"] = "R20_CRITICAL_STAGE"

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

show_state
echo ""
echo -e "${RED}🚨 In real mode: Urgent SMS + custodian notifications sent.${NC}"
echo ""
echo -e "${CYAN}Press Enter to let deadline pass...${NC}"
read -r

# Advance to FINAL
python3 << EOF
import json
from datetime import datetime, timezone, timedelta

with open("$DEMO_STATE") as f:
    state = json.load(f)

now = datetime.now(timezone.utc)
state["timer"]["deadline_iso"] = (now - timedelta(minutes=5)).isoformat()
state["timer"]["time_to_deadline_minutes"] = 0
state["timer"]["overdue_minutes"] = 5

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STAGE 4: DEADLINE PASSED → FINAL${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Deadline has passed. Running final tick...${NC}"
echo ""
run_tick

python3 << EOF
import json
from datetime import datetime, timezone

with open("$DEMO_STATE") as f:
    state = json.load(f)

state["escalation"]["state"] = "FINAL"
state["escalation"]["state_entered_at_iso"] = datetime.now(timezone.utc).isoformat()
state["escalation"]["last_transition_rule_id"] = "R30_FINAL_TRIGGER"

with open("$DEMO_STATE", "w") as f:
    json.dump(state, f, indent=2)
EOF

show_state
echo ""
echo -e "${RED}${BOLD}📋 FINAL STATE REACHED${NC}"
echo ""
echo -e "${DIM}In real mode, this would have:${NC}"
echo -e "  • Sent final emails to operator and custodians"
echo -e "  • Published documents to GitHub Pages"
echo -e "  • Posted to social media (if configured)"
echo -e "  • Triggered webhooks"
echo ""

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}DEMO COMPLETE${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${GREEN}You just saw the full escalation: OK → WARNING → CRITICAL → FINAL${NC}"
echo ""
echo -e "Next steps:"
echo -e "  ${CYAN}./setup.sh${NC}        — Interactive setup wizard"
echo -e "  ${CYAN}python -m src.main status${NC}  — See your real state"
echo ""
