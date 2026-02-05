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
read -p "Choose (1-3) [1]: " USE_CASE
USE_CASE="${USE_CASE:-1}"

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

# Check for existing .env to preserve values
EXISTING_PROJECT=""
EXISTING_EMAIL=""
EXISTING_DEADLINE=""
if [ -f ".env" ]; then
    EXISTING_PROJECT=$(grep '^PROJECT_NAME=' .env 2>/dev/null | cut -d= -f2 || true)
    EXISTING_EMAIL=$(grep '^OPERATOR_EMAIL=' .env 2>/dev/null | cut -d= -f2 || true)
    echo -e "${CYAN}Found existing .env - will preserve credentials${NC}"
fi

# Try to get deadline from state if exists
if [ -f "state/current.json" ] && command -v python3 &>/dev/null; then
    EXISTING_DEADLINE=$(python3 -c "
import json
from datetime import datetime, timezone
try:
    with open('state/current.json') as f:
        state = json.load(f)
    deadline = datetime.fromisoformat(state['escalation']['deadline'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    hours = int((deadline - now).total_seconds() / 3600)
    if hours > 0:
        print(hours)
except:
    pass
" 2>/dev/null || true)
fi

# Suggest folder name as default project name
FOLDER_NAME=$(basename "$(pwd)")
DEFAULT_NAME=${EXISTING_PROJECT:-$FOLDER_NAME}

read -p "Project name [${DEFAULT_NAME}]: " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-$DEFAULT_NAME}

DEFAULT_EMAIL=${EXISTING_EMAIL:-"you@example.com"}
read -p "Your email address [${DEFAULT_EMAIL}]: " OPERATOR_EMAIL
OPERATOR_EMAIL=${OPERATOR_EMAIL:-$DEFAULT_EMAIL}

DEFAULT_DEADLINE=${EXISTING_DEADLINE:-48}
read -p "Initial deadline (hours from now) [${DEFAULT_DEADLINE}]: " DEADLINE_HOURS
DEADLINE_HOURS=${DEADLINE_HOURS:-$DEFAULT_DEADLINE}

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
echo -e "${DIM}Existing credentials will be preserved unless you enter new ones.${NC}"
echo ""

# Load existing credentials from .env if present
RESEND_API_KEY=""
TWILIO_SID=""
TWILIO_TOKEN=""
TWILIO_FROM=""
OPERATOR_SMS=""
GITHUB_TOKEN=""
GITHUB_REPO=""
RENEWAL_TRIGGER_TOKEN=""
RENEWAL_SECRET=""
RELEASE_SECRET=""

if [ -f ".env" ]; then
    RESEND_API_KEY=$(grep '^RESEND_API_KEY=' .env 2>/dev/null | cut -d= -f2 || true)
    TWILIO_SID=$(grep '^TWILIO_ACCOUNT_SID=' .env 2>/dev/null | cut -d= -f2 || true)
    TWILIO_TOKEN=$(grep '^TWILIO_AUTH_TOKEN=' .env 2>/dev/null | cut -d= -f2 || true)
    TWILIO_FROM=$(grep '^TWILIO_FROM_NUMBER=' .env 2>/dev/null | cut -d= -f2 || true)
    OPERATOR_SMS=$(grep '^OPERATOR_SMS=' .env 2>/dev/null | cut -d= -f2 || true)
    GITHUB_TOKEN=$(grep '^GITHUB_TOKEN=' .env 2>/dev/null | cut -d= -f2 || true)
    GITHUB_REPO=$(grep '^GITHUB_REPOSITORY=' .env 2>/dev/null | cut -d= -f2 || true)
    RENEWAL_TRIGGER_TOKEN=$(grep '^RENEWAL_TRIGGER_TOKEN=' .env 2>/dev/null | cut -d= -f2 || true)
    RENEWAL_SECRET=$(grep '^RENEWAL_SECRET=' .env 2>/dev/null | cut -d= -f2 || true)
    RELEASE_SECRET=$(grep '^RELEASE_SECRET=' .env 2>/dev/null | cut -d= -f2 || true)
fi

# Track if any real adapter is configured
HAS_REAL_ADAPTER="false"
[ -n "$RESEND_API_KEY" ] || [ -n "$TWILIO_SID" ] || [ -n "$GITHUB_TOKEN" ] && HAS_REAL_ADAPTER="true"

# Helper to show masked key
mask_key() {
    local key="$1"
    if [ -n "$key" ] && [ ${#key} -gt 8 ]; then
        echo "${key:0:4}...${key: -4}"
    elif [ -n "$key" ]; then
        echo "****"
    fi
}

# ─────────────────────────────────────────────────────────────────
# Email (Resend)
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}📧 Email (Resend)${NC}"
if [ -n "$RESEND_API_KEY" ]; then
    echo -e "   ${GREEN}✓ Already configured${NC} [$(mask_key "$RESEND_API_KEY")]"
    read -p "   Replace? (y/N): " REPLACE_EMAIL
    if [[ $REPLACE_EMAIL =~ ^[Yy] ]]; then
        echo -e "${DIM}   Get a free API key at https://resend.com/api-keys${NC}"
        read -p "   New Resend API key: " NEW_KEY
        [ -n "$NEW_KEY" ] && RESEND_API_KEY="$NEW_KEY"
    fi
    HAS_REAL_ADAPTER="true"
else
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
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# SMS (Twilio)
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}📱 SMS (Twilio)${NC}"
if [ -n "$TWILIO_SID" ]; then
    echo -e "   ${GREEN}✓ Already configured${NC} [$(mask_key "$TWILIO_SID")]"
    read -p "   Replace? (y/N): " REPLACE_SMS
    if [[ $REPLACE_SMS =~ ^[Yy] ]]; then
        echo -e "${DIM}   Get credentials at https://console.twilio.com${NC}"
        read -p "   Twilio Account SID: " NEW_SID
        read -p "   Twilio Auth Token: " NEW_TOKEN
        read -p "   From Number (+1234567890): " NEW_FROM
        read -p "   Your phone (+1234567890): " NEW_SMS
        [ -n "$NEW_SID" ] && TWILIO_SID="$NEW_SID"
        [ -n "$NEW_TOKEN" ] && TWILIO_TOKEN="$NEW_TOKEN"
        [ -n "$NEW_FROM" ] && TWILIO_FROM="$NEW_FROM"
        [ -n "$NEW_SMS" ] && OPERATOR_SMS="$NEW_SMS"
    fi
    HAS_REAL_ADAPTER="true"
else
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
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# GitHub Integration
# ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}🐙 GitHub Integration${NC}"
echo ""

# Part 1: Repository (auto-detect from git remote)
echo -e "${BOLD}   📂 Repository${NC}"

# Try to auto-detect from git remote
DETECTED_REPO=""
if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
    REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
    if [ -n "$REMOTE_URL" ]; then
        # Parse owner/repo from various formats:
        # git@github.com:owner/repo.git
        # https://github.com/owner/repo.git
        DETECTED_REPO=$(echo "$REMOTE_URL" | sed -E 's#(git@github\.com:|https://github\.com/)##' | sed 's/\.git$//')
    fi
fi

if [ -n "$GITHUB_REPO" ] && [ "$GITHUB_REPO" != "owner/repo" ]; then
    echo -e "   ${GREEN}✓ Repository: ${GITHUB_REPO}${NC}"
    read -p "   Change? (y/N): " CHANGE_REPO
    if [[ $CHANGE_REPO =~ ^[Yy] ]]; then
        read -p "   Repository (owner/repo) [${DETECTED_REPO:-}]: " NEW_REPO
        NEW_REPO=${NEW_REPO:-$DETECTED_REPO}
        [ -n "$NEW_REPO" ] && GITHUB_REPO="$NEW_REPO"
    fi
elif [ -n "$DETECTED_REPO" ]; then
    echo -e "   ${CYAN}Detected: ${DETECTED_REPO}${NC}"
    read -p "   Use this? (Y/n): " USE_DETECTED
    USE_DETECTED=${USE_DETECTED:-Y}
    if [[ $USE_DETECTED =~ ^[Yy] ]]; then
        GITHUB_REPO="$DETECTED_REPO"
        echo -e "   ${GREEN}✓ Using: ${GITHUB_REPO}${NC}"
    else
        read -p "   Repository (owner/repo): " GITHUB_REPO
    fi
else
    read -p "   Repository (owner/repo): " GITHUB_REPO
fi
echo ""

# Part 2: GITHUB_TOKEN (for backend git sync + API adapter)
echo -e "${BOLD}   🔑 Git Sync Token (GITHUB_TOKEN)${NC}"
echo -e "${DIM}   Required for: Backend/Docker deployment to push state to GitHub${NC}"
echo -e "${DIM}   Also used by: github_surface adapter (create files, releases, gists)${NC}"
echo -e "${DIM}   Permissions: 'repo' (read/write) and 'workflow'${NC}"
echo ""
echo -e "${CYAN}   Who needs this?${NC}"
echo -e "${DIM}   • Docker/backend deployment → YES (for git push to sync state)${NC}"
echo -e "${DIM}   • GitHub Actions only → NO (Actions has its own token)${NC}"
if [ -n "$GITHUB_TOKEN" ]; then
    echo -e "   ${GREEN}✓ Already configured${NC} [$(mask_key "$GITHUB_TOKEN")]"
    read -p "   Replace? (y/N): " REPLACE_TOKEN
    if [[ $REPLACE_TOKEN =~ ^[Yy] ]]; then
        read -p "   GitHub Token: " NEW_TOKEN
        [ -n "$NEW_TOKEN" ] && GITHUB_TOKEN="$NEW_TOKEN"
    fi
    HAS_REAL_ADAPTER="true"
else
    # Check if gh is available to generate token
    if command -v gh &>/dev/null && gh auth status &>/dev/null; then
        echo ""
        echo -e "   ${GREEN}✓ GitHub CLI detected${NC}"
        echo "   Options:"
        echo "     1) Use current gh token (recommended for backend)"
        echo "     2) Enter a different token manually"
        echo "     3) Skip (GitHub Actions only)"
        echo ""
        read -p "   Choose (1/2/3) [1]: " TOKEN_CHOICE
        TOKEN_CHOICE="${TOKEN_CHOICE:-1}"
        
        case "$TOKEN_CHOICE" in
            1)
                GITHUB_TOKEN=$(gh auth token)
                echo -e "   ${GREEN}✓ Using gh token${NC}"
                HAS_REAL_ADAPTER="true"
                ;;
            2)
                read -p "   GitHub Token: " GITHUB_TOKEN
                [ -n "$GITHUB_TOKEN" ] && HAS_REAL_ADAPTER="true"
                ;;
            *)
                echo -e "   ${DIM}Skipped${NC}"
                ;;
        esac
    else
        echo ""
        echo "   Options:"
        echo "     1) Enter token manually"
        echo "     2) Skip (GitHub Actions only)"
        echo ""
        read -p "   Choose (1/2) [2]: " TOKEN_CHOICE
        TOKEN_CHOICE="${TOKEN_CHOICE:-2}"
        
        if [[ "$TOKEN_CHOICE" == "1" ]]; then
            echo -e "${DIM}   Create at: https://github.com/settings/tokens${NC}"
            read -p "   GitHub Token: " GITHUB_TOKEN
            [ -n "$GITHUB_TOKEN" ] && HAS_REAL_ADAPTER="true"
        else
            echo -e "   ${DIM}Skipped${NC}"
        fi
    fi
fi
echo ""

# Part 3: RENEWAL_TRIGGER_TOKEN (client-side one-click)
echo -e "${BOLD}   🖱️  One-Click Token (RENEWAL_TRIGGER_TOKEN)${NC}"
echo -e "${DIM}   Used by: Website 'Renew Now' button (browser → GitHub API)${NC}"
echo -e "${DIM}   Permissions: ONLY 'Actions: Read and write' for this repo${NC}"
echo -e "${DIM}   Create at: https://github.com/settings/tokens?type=beta${NC}"
echo -e "${YELLOW}   ⚠ This token is embedded in static HTML (exposed to browser)${NC}"
if [ -n "$RENEWAL_TRIGGER_TOKEN" ]; then
    echo -e "   ${GREEN}✓ Already configured${NC} [$(mask_key "$RENEWAL_TRIGGER_TOKEN")]"
    read -p "   Replace? (y/N): " REPLACE_TRIGGER
    if [[ $REPLACE_TRIGGER =~ ^[Yy] ]]; then
        read -p "   Renewal Trigger Token: " NEW_TRIGGER
        [ -n "$NEW_TRIGGER" ] && RENEWAL_TRIGGER_TOKEN="$NEW_TRIGGER"
    fi
else
    read -p "   Renewal Trigger Token (or Enter to skip): " RENEWAL_TRIGGER_TOKEN
fi
echo ""

# Part 4: Secret Codes (passwords)
echo -e "${BOLD}   🔐 Secret Codes${NC}"
echo -e "${DIM}   These are passwords you create. Users type them to renew/release.${NC}"
echo -e "${DIM}   Store in GitHub Secrets AND .env (for local testing).${NC}"
echo ""

# RENEWAL_SECRET
echo -e "   ${CYAN}RENEWAL_SECRET${NC} — Code to extend the deadline"
if [ -n "$RENEWAL_SECRET" ]; then
    echo -e "   ${GREEN}✓ Already set${NC} [$(mask_key "$RENEWAL_SECRET")]"
    read -p "   Replace? (y/N): " REPLACE_RENEW_SECRET
    if [[ $REPLACE_RENEW_SECRET =~ ^[Yy] ]]; then
        read -p "   New renewal secret: " NEW_SECRET
        [ -n "$NEW_SECRET" ] && RENEWAL_SECRET="$NEW_SECRET"
    fi
else
    read -p "   Create renewal secret (or Enter to generate): " RENEWAL_SECRET
    if [ -z "$RENEWAL_SECRET" ]; then
        RENEWAL_SECRET=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))")
        echo -e "   ${GREEN}Generated: ${RENEWAL_SECRET}${NC}"
    fi
fi

# RELEASE_SECRET
echo -e "   ${CYAN}RELEASE_SECRET${NC} — Code to trigger emergency release"
if [ -n "$RELEASE_SECRET" ]; then
    echo -e "   ${GREEN}✓ Already set${NC} [$(mask_key "$RELEASE_SECRET")]"
    read -p "   Replace? (y/N): " REPLACE_RELEASE_SECRET
    if [[ $REPLACE_RELEASE_SECRET =~ ^[Yy] ]]; then
        read -p "   New release secret: " NEW_SECRET
        [ -n "$NEW_SECRET" ] && RELEASE_SECRET="$NEW_SECRET"
    fi
else
    read -p "   Create release secret (or Enter to generate): " RELEASE_SECRET
    if [ -z "$RELEASE_SECRET" ]; then
        RELEASE_SECRET=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))")
        echo -e "   ${GREEN}Generated: ${RELEASE_SECRET}${NC}"
    fi
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# Other adapters
# ─────────────────────────────────────────────────────────────────
echo -e "${DIM}ℹ️  X, Reddit, Webhooks can be configured later in .env${NC}"
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

# Backup existing .env if exists (credentials already loaded earlier)
if [ -f ".env" ]; then
    BACKUP_DIR="backups"
    mkdir -p "$BACKUP_DIR"
    cp .env "$BACKUP_DIR/env_$(date +%Y%m%dT%H%M%S).bak"
    echo -e "${CYAN}Backed up existing .env${NC}"
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

# ═══════════════════════════════════════════════════════════════
# SECRETS — Generate: python -c "import secrets; print(secrets.token_hex(16))"
# ═══════════════════════════════════════════════════════════════
RENEWAL_SECRET=${RENEWAL_SECRET}
RELEASE_SECRET=${RELEASE_SECRET}
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
