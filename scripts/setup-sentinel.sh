#!/usr/bin/env bash
#
# setup-sentinel.sh — Automated Cloudflare Sentinel Worker deployment
#
# What this does:
#   1. Checks prerequisites (node, npm, wrangler, wrangler auth)
#   2. Detects your GitHub repository from git remote
#   3. Installs Worker dependencies (npm ci)
#   4. Creates a KV namespace (or reuses an existing one)
#   5. Patches wrangler.toml with the real KV namespace ID
#   6. Generates a secure auth token
#   7. Sets Worker secrets (AUTH_TOKEN, GITHUB_TOKEN)
#   8. Deploys the Worker
#   9. Writes SENTINEL_URL and SENTINEL_TOKEN to your .env
#  10. Verifies the /health endpoint
#
# Usage:
#   ./scripts/setup-sentinel.sh              # interactive
#   ./scripts/setup-sentinel.sh --github-token ghp_xxx  # supply token
#

set -euo pipefail

# Trap errors to keep terminal open so the user can read the output
trap 'echo ""; echo -e "\033[0;31m✗ Setup failed. See error above.\033[0m"; echo ""; read -p "Press Enter to close…"' ERR

# ── Colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Paths ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$PROJECT_ROOT/worker/sentinel"
WRANGLER_TOML="$WORKER_DIR/wrangler.toml"
ENV_FILE="$PROJECT_ROOT/.env"

# ── Parse args ──────────────────────────────────────────────────────
GITHUB_TOKEN_ARG=""
SKIP_CONFIRM=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --github-token) GITHUB_TOKEN_ARG="$2"; shift 2 ;;
        -y|--yes) SKIP_CONFIRM="true"; shift ;;
        *) echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}🛰️  Sentinel Worker Setup${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}This will deploy a Cloudflare Worker that monitors your project"
echo -e "and replaces the GitHub Actions cron schedule with minute-level checks.${NC}"
echo ""

# ── Step 1: Prereqs ─────────────────────────────────────────────────
echo -e "${BOLD}Checking prerequisites…${NC}"

ERRORS=0

if ! command -v node &>/dev/null; then
    echo -e "  ${RED}✗ node not found — install from https://nodejs.org${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "  ${GREEN}✓ node $(node -v)${NC}"
fi

if ! command -v npm &>/dev/null; then
    echo -e "  ${RED}✗ npm not found${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "  ${GREEN}✓ npm $(npm -v 2>/dev/null)${NC}"
fi

# Check wrangler — install locally if missing
if ! command -v wrangler &>/dev/null && ! npx wrangler --version &>/dev/null 2>&1; then
    echo -e "  ${YELLOW}⚠ wrangler not found — installing via npx…${NC}"
    npm install -g wrangler 2>/dev/null || true
fi

if command -v wrangler &>/dev/null; then
    echo -e "  ${GREEN}✓ wrangler $(wrangler --version 2>/dev/null | head -1)${NC}"
elif npx wrangler --version &>/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ wrangler (via npx)${NC}"
    # alias doesn't work in non-interactive scripts — use a function instead
    wrangler() { npx wrangler "$@"; }
    export -f wrangler
else
    echo -e "  ${RED}✗ wrangler not available${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [[ $ERRORS -gt 0 ]]; then
    echo ""
    echo -e "${RED}Fix the above issues and re-run this script.${NC}"
    exit 1
fi

# Check wrangler auth
echo ""
echo -e "${BOLD}Checking Cloudflare auth…${NC}"

# First check if CLOUDFLARE_API_TOKEN is in .env
if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]] && [[ -f "$ENV_FILE" ]]; then
    CF_TOKEN_FROM_ENV=$(grep '^CLOUDFLARE_API_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$CF_TOKEN_FROM_ENV" ]]; then
        export CLOUDFLARE_API_TOKEN="$CF_TOKEN_FROM_ENV"
        echo -e "  ${GREEN}✓ CLOUDFLARE_API_TOKEN loaded from .env${NC}"
    fi
fi

WHOAMI_OUTPUT=$(wrangler whoami 2>&1) && WHOAMI_EXIT=0 || WHOAMI_EXIT=$?

if [[ $WHOAMI_EXIT -ne 0 ]] || echo "$WHOAMI_OUTPUT" | grep -qi "not authenticated\|error\|necessary to set"; then
    echo -e "  ${YELLOW}⚠ Not logged in to Cloudflare.${NC}"

    if [[ -t 0 ]]; then
        # Interactive terminal — can run wrangler login
        echo -e "  ${DIM}Running wrangler login — a browser window will open.${NC}"
        echo ""
        wrangler login
        echo ""
    else
        # Non-interactive (spawned from web UI) — need API token
        echo -e "  ${DIM}This terminal was spawned from the web UI — wrangler login requires a browser.${NC}"
        echo ""
        echo -e "  ${BOLD}Option 1:${NC} Set CLOUDFLARE_API_TOKEN in .env"
        echo -e "  ${DIM}Create one at: https://dash.cloudflare.com/profile/api-tokens${NC}"
        echo -e "  ${DIM}Template: \"Edit Cloudflare Workers\" or custom with Workers KV + Workers Scripts${NC}"
        echo ""
        read -sp "  Paste Cloudflare API Token (or press Enter to abort): " CF_TOKEN_INPUT
        echo ""
        if [[ -n "$CF_TOKEN_INPUT" ]]; then
            export CLOUDFLARE_API_TOKEN="$CF_TOKEN_INPUT"
            # Save to .env for next time
            if [[ -f "$ENV_FILE" ]]; then
                sed -i '/^CLOUDFLARE_API_TOKEN=/d' "$ENV_FILE"
            fi
            echo "CLOUDFLARE_API_TOKEN=${CF_TOKEN_INPUT}" >> "$ENV_FILE"
            echo -e "  ${GREEN}✓ Token saved to .env${NC}"
        else
            echo -e "${RED}Aborted. Run ./manage.sh sentinel from a regular terminal, or set CLOUDFLARE_API_TOKEN in .env.${NC}"
            exit 1
        fi
    fi

    # Verify auth after login/token
    WHOAMI_OUTPUT=$(wrangler whoami 2>&1) && WHOAMI_EXIT=0 || WHOAMI_EXIT=$?
    if [[ $WHOAMI_EXIT -ne 0 ]]; then
        echo -e "  ${RED}✗ Still not authenticated. Check your token/login.${NC}"
        echo -e "  ${DIM}${WHOAMI_OUTPUT}${NC}"
        exit 1
    fi
fi

CF_USER=$(echo "$WHOAMI_OUTPUT" | grep -oP '(?<=email: ).*' || echo "authenticated")
echo -e "  ${GREEN}✓ Cloudflare: ${CF_USER}${NC}"

# ── Step 2: Detect repository ───────────────────────────────────────
echo ""
echo -e "${BOLD}Detecting repository…${NC}"

GITHUB_REPO=""
if command -v git &>/dev/null && git -C "$PROJECT_ROOT" rev-parse --git-dir &>/dev/null; then
    REMOTE_URL=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || true)
    if [[ -n "$REMOTE_URL" ]]; then
        GITHUB_REPO=$(echo "$REMOTE_URL" | sed -E 's#.*github\.com[:/]##' | sed 's/\.git$//')
    fi
fi

if [[ -z "$GITHUB_REPO" ]]; then
    read -p "  Repository (owner/repo): " GITHUB_REPO
else
    echo -e "  ${GREEN}✓ Detected: ${GITHUB_REPO}${NC}"
    if [[ "$SKIP_CONFIRM" != "true" ]]; then
        read -p "  Use this? (Y/n): " CONFIRM_REPO
        CONFIRM_REPO="${CONFIRM_REPO:-Y}"
        if [[ ! "$CONFIRM_REPO" =~ ^[Yy] ]]; then
            read -p "  Repository (owner/repo): " GITHUB_REPO
        fi
    fi
fi

# ── Step 3: GitHub PAT ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}GitHub Token for dispatch${NC}"
echo -e "${DIM}The sentinel needs a fine-grained PAT with Actions (write) scope"
echo -e "to trigger workflow_dispatch on ${GITHUB_REPO}.${NC}"

# Try to find existing token — prefer RENEWAL_TRIGGER_TOKEN (fine-grained, Actions scope)
# then fall back to GITHUB_TOKEN (classic PAT, may have workflow scope)
DISPATCH_TOKEN=""
if [[ -n "$GITHUB_TOKEN_ARG" ]]; then
    DISPATCH_TOKEN="$GITHUB_TOKEN_ARG"
    echo -e "  ${GREEN}✓ Provided via --github-token${NC}"
elif [[ -f "$ENV_FILE" ]]; then
    # First: check RENEWAL_TRIGGER_TOKEN — this is the fine-grained PAT with Actions (write) scope
    RENEWAL_TOKEN=$(grep '^RENEWAL_TRIGGER_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$RENEWAL_TOKEN" ]]; then
        MASKED="${RENEWAL_TOKEN:0:7}…${RENEWAL_TOKEN: -4}"
        echo -e "  ${GREEN}✓ Found RENEWAL_TRIGGER_TOKEN in .env: ${MASKED}${NC}"
        echo -e "  ${DIM}(Fine-grained PAT with Actions scope — exactly what sentinel needs)${NC}"
        if [[ "$SKIP_CONFIRM" == "true" ]]; then
            DISPATCH_TOKEN="$RENEWAL_TOKEN"
        else
            read -p "  Use this token? (Y/n): " USE_EXISTING
            USE_EXISTING="${USE_EXISTING:-Y}"
            if [[ "$USE_EXISTING" =~ ^[Yy] ]]; then
                DISPATCH_TOKEN="$RENEWAL_TOKEN"
            fi
        fi
    fi

    # Fallback: check GITHUB_TOKEN
    if [[ -z "$DISPATCH_TOKEN" ]]; then
        EXISTING_GH_TOKEN=$(grep '^GITHUB_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
        if [[ -n "$EXISTING_GH_TOKEN" ]]; then
            MASKED="${EXISTING_GH_TOKEN:0:7}…${EXISTING_GH_TOKEN: -4}"
            echo -e "  ${YELLOW}⚠ Found GITHUB_TOKEN in .env: ${MASKED}${NC}"
            echo -e "  ${DIM}(Classic PAT — may work if it has 'workflow' scope)${NC}"
            read -p "  Use this token? (y/N): " USE_CLASSIC
            USE_CLASSIC="${USE_CLASSIC:-N}"
            if [[ "$USE_CLASSIC" =~ ^[Yy] ]]; then
                DISPATCH_TOKEN="$EXISTING_GH_TOKEN"
            fi
        fi
    fi
fi

if [[ -z "$DISPATCH_TOKEN" ]]; then
    echo ""
    echo -e "  ${DIM}Create one at: https://github.com/settings/tokens?type=beta${NC}"
    echo -e "  ${DIM}Scope: repository → ${GITHUB_REPO} → Actions (Read and write)${NC}"
    echo ""
    read -sp "  GitHub PAT: " DISPATCH_TOKEN
    echo ""
fi

if [[ -z "$DISPATCH_TOKEN" ]]; then
    echo -e "${RED}Error: GitHub token is required${NC}"
    exit 1
fi

# ── Step 4: Install deps ────────────────────────────────────────────
echo ""
echo -e "${BOLD}Installing Worker dependencies…${NC}"
cd "$WORKER_DIR"
npm ci --silent 2>/dev/null || npm install --silent
echo -e "  ${GREEN}✓ Dependencies installed${NC}"

# ── Step 5: Create KV namespace ─────────────────────────────────────
echo ""
echo -e "${BOLD}Setting up KV namespace…${NC}"

CURRENT_KV_ID=$(grep -oP 'id = "\K[^"]+' "$WRANGLER_TOML" 2>/dev/null || true)

if [[ "$CURRENT_KV_ID" != "REPLACE_ME" && -n "$CURRENT_KV_ID" ]]; then
    echo -e "  ${GREEN}✓ Already configured: ${CURRENT_KV_ID:0:12}…${NC}"
    KV_ID="$CURRENT_KV_ID"
else
    echo -e "  ${DIM}Creating KV namespace…${NC}"
    KV_OUTPUT=$(wrangler kv namespace create SENTINEL_KV 2>&1) && KV_EXIT=0 || KV_EXIT=$?
    if [[ $KV_EXIT -ne 0 ]]; then
        echo -e "  ${YELLOW}⚠ wrangler kv namespace create returned exit ${KV_EXIT}${NC}"
        echo -e "  ${DIM}${KV_OUTPUT}${NC}"
    fi
    KV_ID=$(echo "$KV_OUTPUT" | grep -oP 'id = "\K[^"]+' || true)

    if [[ -z "$KV_ID" ]]; then
        # Try alternative grep pattern
        KV_ID=$(echo "$KV_OUTPUT" | grep -oP '"id":\s*"\K[^"]+' || true)
    fi

    if [[ -z "$KV_ID" ]]; then
        echo -e "  ${RED}✗ Failed to create KV namespace${NC}"
        echo -e "  ${DIM}Output: ${KV_OUTPUT}${NC}"
        echo ""
        read -p "  Enter KV namespace ID manually: " KV_ID
    fi

    if [[ -z "$KV_ID" ]]; then
        echo -e "${RED}Error: KV namespace ID required${NC}"
        exit 1
    fi

    # Patch wrangler.toml
    sed -i "s/id = \"REPLACE_ME\"/id = \"${KV_ID}\"/" "$WRANGLER_TOML"
    echo -e "  ${GREEN}✓ KV namespace created: ${KV_ID:0:12}…${NC}"
    echo -e "  ${GREEN}✓ wrangler.toml updated${NC}"
fi

# ── Step 6: Generate auth token ─────────────────────────────────────
echo ""
echo -e "${BOLD}Generating auth token…${NC}"

# Check if .env already has one
SENTINEL_TOKEN=""
if [[ -f "$ENV_FILE" ]]; then
    SENTINEL_TOKEN=$(grep '^SENTINEL_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
fi

if [[ -n "$SENTINEL_TOKEN" ]]; then
    echo -e "  ${GREEN}✓ Reusing existing token from .env${NC}"
else
    SENTINEL_TOKEN=$(openssl rand -hex 32)
    echo -e "  ${GREEN}✓ Generated new 256-bit token${NC}"
fi

# ── Step 7: Set Worker secrets ──────────────────────────────────────
echo ""
echo -e "${BOLD}Setting Worker secrets…${NC}"

echo "$SENTINEL_TOKEN" | wrangler secret put AUTH_TOKEN --name continuity-sentinel 2>/dev/null && \
    echo -e "  ${GREEN}✓ AUTH_TOKEN set${NC}" || \
    echo -e "  ${YELLOW}⚠ AUTH_TOKEN may already be set (non-fatal)${NC}"

echo "$DISPATCH_TOKEN" | wrangler secret put GITHUB_TOKEN --name continuity-sentinel 2>/dev/null && \
    echo -e "  ${GREEN}✓ GITHUB_TOKEN set${NC}" || \
    echo -e "  ${YELLOW}⚠ GITHUB_TOKEN may already be set (non-fatal)${NC}"

# Set GITHUB_REPO as a var in wrangler.toml if not already
if ! grep -q "GITHUB_REPO" "$WRANGLER_TOML"; then
    sed -i "/^\[vars\]/a GITHUB_REPO = \"${GITHUB_REPO}\"" "$WRANGLER_TOML"
    echo -e "  ${GREEN}✓ GITHUB_REPO added to wrangler.toml${NC}"
fi

# ── Step 8: Summary & confirm ───────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}Ready to deploy${NC}"
echo ""
echo -e "  Worker name:   ${CYAN}continuity-sentinel${NC}"
echo -e "  KV namespace:  ${CYAN}${KV_ID:0:16}…${NC}"
echo -e "  Dispatches to: ${CYAN}${GITHUB_REPO}${NC}"
echo -e "  Cron schedule: ${CYAN}every 1 minute${NC}"
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [[ "$SKIP_CONFIRM" != "true" ]]; then
    echo ""
    read -p "Deploy now? (Y/n): " CONFIRM
    CONFIRM="${CONFIRM:-Y}"
    if [[ ! "$CONFIRM" =~ ^[Yy] ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# ── Step 9: Deploy ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Deploying…${NC}"
# || true prevents the ERR trap from firing — set +e does NOT suppress it
DEPLOY_OUTPUT=$(wrangler deploy 2>&1) && DEPLOY_EXIT=0 || DEPLOY_EXIT=$?
echo "$DEPLOY_OUTPUT"

if [[ $DEPLOY_EXIT -ne 0 ]]; then
    # Check if it's the "register workers.dev subdomain" error
    if echo "$DEPLOY_OUTPUT" | grep -qi "workers.dev subdomain"; then
        echo ""
        echo -e "  ${YELLOW}⚠ Your Cloudflare account needs a workers.dev subdomain (one-time setup).${NC}"

        # Extract account ID from the deploy output URL
        ACCOUNT_ID=$(echo "$DEPLOY_OUTPUT" | grep -oP 'cloudflare\.com/\K[a-f0-9]{32}' | head -1 || true)

        if [[ -n "$ACCOUNT_ID" ]] && [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
            # Derive a subdomain from the GitHub username
            SUGGESTED_SUB=$(echo "$GITHUB_REPO" | cut -d/ -f1 | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')
            echo ""
            if [[ "$SKIP_CONFIRM" == "true" ]]; then
                SUBDOMAIN="$SUGGESTED_SUB"
            else
                read -p "  Choose your workers.dev subdomain [${SUGGESTED_SUB}]: " SUBDOMAIN
                SUBDOMAIN="${SUBDOMAIN:-$SUGGESTED_SUB}"
            fi

            echo -e "  ${DIM}Registering ${SUBDOMAIN}.workers.dev via API…${NC}"
            REG_OUTPUT=$(curl -s -X PUT \
                "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/workers/subdomain" \
                -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
                -H "Content-Type: application/json" \
                --data "{\"subdomain\":\"${SUBDOMAIN}\"}" 2>&1) || true

            if echo "$REG_OUTPUT" | grep -q '"success":true'; then
                echo -e "  ${GREEN}✓ Subdomain registered: ${SUBDOMAIN}.workers.dev${NC}"
            else
                echo -e "  ${YELLOW}⚠ API response: ${REG_OUTPUT}${NC}"
                echo -e "  ${DIM}Try a different subdomain name, or register manually:${NC}"
                echo -e "  ${DIM}  https://dash.cloudflare.com → Workers & Pages → Overview${NC}"
                echo ""
                read -p "  Press Enter to retry deploy after registering manually…"
            fi
        else
            echo -e "  ${DIM}Register a subdomain at: https://dash.cloudflare.com → Workers & Pages → Overview${NC}"
            echo ""
            read -p "  Press Enter after you've registered your subdomain to retry deploy…"
        fi

        echo ""
        echo -e "${BOLD}Retrying deploy…${NC}"
        DEPLOY_OUTPUT=$(wrangler deploy 2>&1) && DEPLOY_EXIT=0 || DEPLOY_EXIT=$?
        echo "$DEPLOY_OUTPUT"
    fi

    if [[ $DEPLOY_EXIT -ne 0 ]]; then
        echo ""
        echo -e "  ${RED}✗ Deploy failed (exit ${DEPLOY_EXIT})${NC}"
        echo -e "  ${DIM}Check the error above. Common fixes:${NC}"
        echo -e "  ${DIM}  - Verify CLOUDFLARE_API_TOKEN has Workers Scripts permissions${NC}"
        echo -e "  ${DIM}  - Check wrangler.toml for syntax errors${NC}"
        echo -e "  ${DIM}  - Run 'wrangler deploy' manually from worker/sentinel/ for details${NC}"
        exit 1
    fi
fi

# Extract worker URL from deploy output
SENTINEL_URL=$(echo "$DEPLOY_OUTPUT" | grep -oP 'https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev' | head -1 || true)

if [[ -z "$SENTINEL_URL" ]]; then
    # Try backup pattern
    SENTINEL_URL=$(echo "$DEPLOY_OUTPUT" | grep -oP 'https://[^\s]+\.workers\.dev' | head -1 || true)
fi

if [[ -z "$SENTINEL_URL" ]]; then
    echo -e "  ${YELLOW}⚠ Could not auto-detect Worker URL from deploy output${NC}"
    read -p "  Enter Worker URL: " SENTINEL_URL
fi

echo ""
echo -e "  ${GREEN}✓ Deployed to: ${SENTINEL_URL}${NC}"

# ── Step 10: Write to .env ──────────────────────────────────────────
echo ""
echo -e "${BOLD}Updating .env…${NC}"

# Remove old values if present
if [[ -f "$ENV_FILE" ]]; then
    sed -i '/^SENTINEL_URL=/d' "$ENV_FILE"
    sed -i '/^SENTINEL_TOKEN=/d' "$ENV_FILE"
fi

# Append new values
cat >> "$ENV_FILE" <<EOF

# ── Sentinel Worker ──────────────────────────────────────────────────
SENTINEL_URL=${SENTINEL_URL}
SENTINEL_TOKEN=${SENTINEL_TOKEN}
EOF

echo -e "  ${GREEN}✓ SENTINEL_URL and SENTINEL_TOKEN written to .env${NC}"

# ── Step 11: Verify ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Verifying deployment…${NC}"

sleep 2  # Give CF a moment to propagate

if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${SENTINEL_URL}/health" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo -e "  ${GREEN}✓ /health returned 200 — Worker is live!${NC}"
    else
        echo -e "  ${YELLOW}⚠ /health returned ${HTTP_CODE} — may need a moment to propagate${NC}"
    fi

    HEALTH_BODY=$(curl -s "${SENTINEL_URL}/health" 2>/dev/null || echo "{}")
    echo -e "  ${DIM}Response: ${HEALTH_BODY}${NC}"
else
    echo -e "  ${DIM}(curl not available — skip health check)${NC}"
fi

# ── Done ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ Sentinel is deployed and configured!${NC}"
echo ""
echo -e "  ${DIM}Worker URL:  ${SENTINEL_URL}${NC}"
echo -e "  ${DIM}Dashboard:   ${SENTINEL_URL}/status${NC}"
echo -e "  ${DIM}Health:      ${SENTINEL_URL}/health${NC}"
echo ""
echo -e "  ${DIM}The engine will now notify the sentinel after every tick and state change.${NC}"
echo -e "  ${DIM}The sentinel checks every minute and dispatches ticks when needed.${NC}"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo -e "  1. Push SENTINEL_URL and SENTINEL_TOKEN to GitHub secrets"
echo -e "     ${DIM}→ Run: ./manage.sh secrets${NC}"
echo -e "  2. Check the dashboard's Sentinel card for live status"
echo -e "     ${DIM}→ Run: ./manage.sh web${NC}"
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
