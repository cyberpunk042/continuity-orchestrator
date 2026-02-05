#!/bin/bash
#
# setup.sh — Interactive setup wizard
#
# Walks you through configuration step by step.
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
NC='\033[0m'

clear

echo ""
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         CONTINUITY ORCHESTRATOR — SETUP WIZARD                ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${DIM}This wizard will help you set up your orchestrator.${NC}"
echo -e "${DIM}Answer a few questions, and we'll generate your configuration.${NC}"
echo ""

# Check environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Setting up Python environment...${NC}"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -e .
    pip install -q resend httpx 2>/dev/null || true
    echo -e "${GREEN}✓ Environment ready${NC}"
else
    source .venv/bin/activate
    echo -e "${GREEN}✓ Environment found${NC}"
fi

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STEP 1: What do you want to use this for?${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  1) Deadman switch — Release info if I don't check in"
echo "  2) Scheduled publishing — Publish content on a timer"
echo "  3) Custom — I'll configure it myself"
echo ""
read -p "Choose (1-3): " USE_CASE

case $USE_CASE in
    1) TEMPLATE="deadman-switch" ;;
    2) TEMPLATE="newsletter" ;;
    *) TEMPLATE="minimal" ;;
esac

echo ""
echo -e "${GREEN}✓ Using ${TEMPLATE} template${NC}"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STEP 2: Basic Information${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

read -p "Project name (e.g., my-deadman): " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-"my-project"}

read -p "Your email address: " OPERATOR_EMAIL
OPERATOR_EMAIL=${OPERATOR_EMAIL:-"you@example.com"}

read -p "Initial deadline (hours from now, default 48): " DEADLINE_HOURS
DEADLINE_HOURS=${DEADLINE_HOURS:-48}

echo ""
echo -e "${GREEN}✓ Project: ${PROJECT_NAME}${NC}"
echo -e "${GREEN}✓ Email: ${OPERATOR_EMAIL}${NC}"
echo -e "${GREEN}✓ Deadline: ${DEADLINE_HOURS} hours${NC}"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STEP 3: Configure Adapters${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Configure each adapter or skip to set up later.${NC}"
echo -e "${DIM}You can always edit .env to add credentials.${NC}"
echo ""

# Initialize variables
RESEND_API_KEY=""
TWILIO_SID=""
TWILIO_TOKEN=""
TWILIO_FROM=""
OPERATOR_SMS=""
GITHUB_TOKEN=""
GITHUB_REPO=""

# Track if any real adapter is configured
HAS_REAL_ADAPTER="false"

# ─────────────────────────────────────────────────────────────────
# Email (Resend)
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}📧 Email (Resend)${NC}"
read -p "   Configure email notifications? (Y/n): " ENABLE_EMAIL
ENABLE_EMAIL=${ENABLE_EMAIL:-Y}

if [[ $ENABLE_EMAIL =~ ^[Yy] ]]; then
    echo -e "${DIM}   Get a free API key at https://resend.com/api-keys${NC}"
    read -p "   Resend API key (or Enter to skip): " RESEND_API_KEY
    if [ -n "$RESEND_API_KEY" ]; then
        HAS_REAL_ADAPTER="true"
        echo -e "${GREEN}   ✓ Email configured${NC}"
    else
        echo -e "${YELLOW}   ⚠ Skipped (mock mode)${NC}"
    fi
else
    echo -e "${DIM}   Skipped${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# SMS (Twilio)
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}📱 SMS (Twilio)${NC}"
read -p "   Configure SMS notifications? (y/N): " ENABLE_SMS

if [[ $ENABLE_SMS =~ ^[Yy] ]]; then
    echo -e "${DIM}   Get credentials at https://console.twilio.com${NC}"
    read -p "   Twilio Account SID: " TWILIO_SID
    read -p "   Twilio Auth Token: " TWILIO_TOKEN
    read -p "   From Number (+1234567890): " TWILIO_FROM
    read -p "   Your phone (+1234567890): " OPERATOR_SMS
    if [ -n "$TWILIO_SID" ] && [ -n "$TWILIO_TOKEN" ] && [ -n "$TWILIO_FROM" ]; then
        HAS_REAL_ADAPTER="true"
        echo -e "${GREEN}   ✓ SMS configured${NC}"
    else
        echo -e "${YELLOW}   ⚠ Incomplete (mock mode)${NC}"
    fi
else
    echo -e "${DIM}   Skipped${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# GitHub
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}🐙 GitHub (for publishing & state sync)${NC}"
read -p "   Configure GitHub? (y/N): " ENABLE_GITHUB

if [[ $ENABLE_GITHUB =~ ^[Yy] ]]; then
    echo -e "${DIM}   Create a token at https://github.com/settings/tokens${NC}"
    echo -e "${DIM}   (needs 'repo' and 'workflow' permissions)${NC}"
    read -p "   GitHub Token: " GITHUB_TOKEN
    read -p "   Repository (owner/repo): " GITHUB_REPO
    if [ -n "$GITHUB_TOKEN" ]; then
        HAS_REAL_ADAPTER="true"
        echo -e "${GREEN}   ✓ GitHub configured${NC}"
        
        # One-click renewal token
        echo ""
        echo -e "${BOLD}   🔐 One-Click Renewal (optional)${NC}"
        echo -e "${DIM}   Allows renewing directly from the countdown page.${NC}"
        echo -e "${DIM}   Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta${NC}"
        echo -e "${DIM}   With ONLY 'Actions: Read and write' permission for this repo.${NC}"
        read -p "   Renewal Trigger Token (or skip): " RENEWAL_TRIGGER_TOKEN
        if [ -n "$RENEWAL_TRIGGER_TOKEN" ]; then
            echo -e "${GREEN}   ✓ One-click renewal enabled${NC}"
        fi
    else
        echo -e "${YELLOW}   ⚠ Skipped (mock mode)${NC}"
    fi
else
    echo -e "${DIM}   Skipped${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# X (Twitter) — Skip for now, can add later
# ─────────────────────────────────────────────────────────────────
echo -e "${DIM}   ℹ️  X, Reddit, Webhooks can be configured later in .env${NC}"
echo ""

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}STEP 4: Generating Configuration${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Determine mock mode
if [ "$HAS_REAL_ADAPTER" = "true" ]; then
    MOCK_MODE="false"
else
    MOCK_MODE="true"
fi

# Create .env file
cat > .env << ENVFILE
# Continuity Orchestrator Configuration
# Generated by setup.sh on $(date)

# ═══════════════════════════════════════════════════════════════
# PROJECT SETTINGS
# ═══════════════════════════════════════════════════════════════
PROJECT_NAME=${PROJECT_NAME}
OPERATOR_EMAIL=${OPERATOR_EMAIL}

# ═══════════════════════════════════════════════════════════════
# ADAPTER MODE
# Set to 'true' to disable real notifications (for testing)
# Set to 'false' to enable real notifications
# ═══════════════════════════════════════════════════════════════
ADAPTER_MOCK_MODE=${MOCK_MODE}

# ═══════════════════════════════════════════════════════════════
# EMAIL (Resend) — https://resend.com/api-keys
# ═══════════════════════════════════════════════════════════════
RESEND_API_KEY=${RESEND_API_KEY}
RESEND_FROM_EMAIL=onboarding@resend.dev

# ═══════════════════════════════════════════════════════════════
# SMS (Twilio) — https://console.twilio.com
# ═══════════════════════════════════════════════════════════════
TWILIO_ACCOUNT_SID=${TWILIO_SID}
TWILIO_AUTH_TOKEN=${TWILIO_TOKEN}
TWILIO_FROM_NUMBER=${TWILIO_FROM}
OPERATOR_SMS=${OPERATOR_SMS}

# ═══════════════════════════════════════════════════════════════
# GITHUB — https://github.com/settings/tokens
# ═══════════════════════════════════════════════════════════════
GITHUB_TOKEN=${GITHUB_TOKEN}
GITHUB_REPOSITORY=${GITHUB_REPO:-owner/repo}

# One-click renewal from website (fine-grained PAT with only Actions:write)
RENEWAL_TRIGGER_TOKEN=${RENEWAL_TRIGGER_TOKEN}

# ═══════════════════════════════════════════════════════════════
# X (Twitter) — https://developer.twitter.com/en/portal
# ═══════════════════════════════════════════════════════════════
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_SECRET=

# ═══════════════════════════════════════════════════════════════
# REDDIT — https://www.reddit.com/prefs/apps
# ═══════════════════════════════════════════════════════════════
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=

# ═══════════════════════════════════════════════════════════════
# WEBHOOKS
# ═══════════════════════════════════════════════════════════════
WEBHOOK_TIMEOUT=30
ENVFILE

echo -e "${GREEN}✓ Created .env file${NC}"

# Copy template files if they don't exist
if [ -d "examples/${TEMPLATE}/policy" ]; then
    echo -e "${DIM}Applying ${TEMPLATE} template...${NC}"
    # Don't overwrite existing policy files
    if [ ! -f "policy/rules.yaml" ] || [ ! -s "policy/rules.yaml" ]; then
        cp examples/${TEMPLATE}/policy/*.yaml policy/ 2>/dev/null || true
    fi
fi

echo -e "${GREEN}✓ Policy files ready${NC}"

# Initialize state
echo -e "${DIM}Initializing state...${NC}"
python -m src.main init \
    --project "$PROJECT_NAME" \
    --operator-email "$OPERATOR_EMAIL" \
    --deadline-hours "$DEADLINE_HOURS" \
    --github-repo "${GITHUB_REPO:-owner/repo}" \
    --force 2>/dev/null || true

echo -e "${GREEN}✓ State initialized${NC}"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}SETUP COMPLETE!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Show status
python -m src.main status 2>/dev/null || echo "(status command unavailable)"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}NEXT STEPS${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${BOLD}1. Test your adapters:${NC}"
echo -e "   ${CYAN}python -m src.main test all${NC}      # See what's configured"
echo -e "   ${CYAN}python -m src.main test email${NC}    # Send a test email"
echo ""

echo -e "${BOLD}2. Preview the engine:${NC}"
echo -e "   ${CYAN}python -m src.main tick --dry-run${NC}"
echo ""

echo -e "${BOLD}3. Run for real:${NC}"
echo -e "   ${CYAN}python -m src.main tick${NC}"
echo ""

if [ "$MOCK_MODE" = "true" ]; then
    echo -e "${YELLOW}⚠️  Running in MOCK MODE${NC}"
    echo -e "${DIM}   No real notifications will be sent.${NC}"
    echo -e "${DIM}   Add credentials to .env to enable real adapters.${NC}"
    echo ""
fi

echo -e "${BOLD}4. Deploy to GitHub Actions:${NC}"
echo -e "   ${CYAN}python -m src.main export-secrets${NC}  # Get secrets to add"
echo ""
echo -e "${DIM}   Then go to: https://github.com/${GITHUB_REPO:-owner/repo}/settings/secrets/actions${NC}"
echo ""
