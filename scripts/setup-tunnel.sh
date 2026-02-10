#!/usr/bin/env bash
#
# setup-tunnel.sh — Automated Cloudflare Tunnel setup
#
# What this does:
#   1. Checks prerequisites (node, npm, wrangler)
#   2. Authenticates via wrangler (same flow as setup-sentinel.sh)
#   3. Detects your Cloudflare account ID
#   4. Lists existing tunnels — lets you pick one or create new
#   5. Optionally configures a public hostname (DNS route)
#   6. Fetches the tunnel connector token
#   7. Writes CLOUDFLARE_TUNNEL_TOKEN to .env
#
# Usage:
#   ./scripts/setup-tunnel.sh              # interactive
#   ./scripts/setup-tunnel.sh -y           # auto-confirm
#   ./scripts/setup-tunnel.sh --name my-tunnel --hostname my.example.com
#

set -euo pipefail

# ── Signal file for web UI polling ──────────────────────────────────
SIGNAL_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.tunnel-setup-result"
rm -f "$SIGNAL_FILE"
echo '{"status":"running","ts":"'"$(date -Iseconds)"'"}' > "$SIGNAL_FILE"

# Trap errors to keep terminal open so the user can read the output
trap 'echo "{\"status\":\"failed\",\"ts\":\"'"$(date -Iseconds)"'\"}" > "$SIGNAL_FILE"; echo ""; echo -e "\033[0;31m✗ Setup failed. See error above.\033[0m"; echo ""; read -p "Press Enter to close…"' ERR

# ── Colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Paths ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# ── Parse args ──────────────────────────────────────────────────────
SKIP_CONFIRM=""
TUNNEL_NAME_ARG=""
HOSTNAME_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) SKIP_CONFIRM="true"; shift ;;
        --name) TUNNEL_NAME_ARG="$2"; shift 2 ;;
        --hostname) HOSTNAME_ARG="$2"; shift 2 ;;
        *) echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}🔒 Cloudflare Tunnel Setup${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}This will create (or select) a Cloudflare Tunnel and write the"
echo -e "connector token to .env. The cloudflared container does the rest.${NC}"
echo ""

# ════════════════════════════════════════════════════════════════════
# Step 1: Prerequisites — identical to setup-sentinel.sh
# ════════════════════════════════════════════════════════════════════
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
    wrangler() { npx wrangler "$@"; }
    export -f wrangler
else
    echo -e "  ${RED}✗ wrangler not available${NC}"
    ERRORS=$((ERRORS + 1))
fi

if ! command -v curl &>/dev/null; then
    echo -e "  ${RED}✗ curl not found${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "  ${GREEN}✓ curl${NC}"
fi

if [[ $ERRORS -gt 0 ]]; then
    echo ""
    echo -e "${RED}Fix the above issues and re-run this script.${NC}"
    exit 1
fi

# ════════════════════════════════════════════════════════════════════
# Step 2: Cloudflare auth — identical to setup-sentinel.sh
# ════════════════════════════════════════════════════════════════════
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
        # Interactive terminal
        # If a bad API token is in the env, unset it first — wrangler login
        # refuses to run OAuth when CLOUDFLARE_API_TOKEN is set.
        if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
            echo -e "  ${DIM}Current CLOUDFLARE_API_TOKEN is invalid — clearing it.${NC}"
            unset CLOUDFLARE_API_TOKEN
            # Also remove the bad token from .env
            if [[ -f "$ENV_FILE" ]]; then
                sed -i '/^CLOUDFLARE_API_TOKEN=/d' "$ENV_FILE"
            fi
        fi
        echo ""
        echo -e "  ${BOLD}How would you like to authenticate?${NC}"
        echo -e "  ${DIM}1) Paste a Cloudflare API Token${NC}"
        echo -e "  ${DIM}2) Open browser for OAuth login (wrangler login)${NC}"
        echo ""
        read -rp "  Choice [1/2]: " AUTH_CHOICE
        echo ""
        if [[ "$AUTH_CHOICE" == "1" ]]; then
            read -sp "  Paste Cloudflare API Token: " CF_TOKEN_INPUT
            echo ""
            if [[ -n "$CF_TOKEN_INPUT" ]]; then
                export CLOUDFLARE_API_TOKEN="$CF_TOKEN_INPUT"
                # Save to .env
                if [[ -f "$ENV_FILE" ]]; then
                    sed -i '/^CLOUDFLARE_API_TOKEN=/d' "$ENV_FILE"
                fi
                echo "CLOUDFLARE_API_TOKEN=${CF_TOKEN_INPUT}" >> "$ENV_FILE"
                echo -e "  ${GREEN}✓ Token saved to .env${NC}"
            else
                echo -e "${RED}Aborted.${NC}"
                exit 1
            fi
        else
            echo -e "  ${DIM}Running wrangler login — a browser window will open.${NC}"
            echo ""
            wrangler login
            echo ""
        fi
    else
        # Non-interactive (spawned from web UI) — need API token
        echo -e "  ${DIM}This terminal was spawned from the web UI — wrangler login requires a browser.${NC}"
        echo ""
        echo -e "  ${BOLD}Option 1:${NC} Set CLOUDFLARE_API_TOKEN in .env"
        echo -e "  ${DIM}Create one at: https://dash.cloudflare.com/profile/api-tokens${NC}"
        echo -e "  ${DIM}Template: \"Edit Cloudflare Workers\" or custom with Account:Cloudflare Tunnel:Edit + Zone:DNS:Edit${NC}"
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
            echo -e "${RED}Aborted. Run ./manage.sh tunnel from a regular terminal, or set CLOUDFLARE_API_TOKEN in .env.${NC}"
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

# ── Extract the API token for curl calls ────────────────────────────
# wrangler stores OAuth tokens internally, but we need a bearer token for
# the Tunnel API. If CLOUDFLARE_API_TOKEN is set, use it directly.
# Otherwise, extract the OAuth token from wrangler's config.
CF_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
if [[ -z "$CF_TOKEN" ]]; then
    # Wrangler v3 stores config at ~/.config/.wrangler (note the dot prefix)
    for config_path in \
        "${XDG_CONFIG_HOME:-$HOME/.config}/.wrangler/config/default.toml" \
        "$HOME/.config/.wrangler/config/default.toml" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/wrangler/config/default.toml" \
        "$HOME/.wrangler/config/default.toml"; do
        if [[ -f "$config_path" ]]; then
            CF_TOKEN=$(grep -oP '(?<=oauth_token = ").*(?=")' "$config_path" 2>/dev/null || true)
            if [[ -n "$CF_TOKEN" ]]; then
                echo -e "  ${GREEN}✓ OAuth token loaded from wrangler config${NC}"
                break
            fi
        fi
    done
fi

if [[ -z "$CF_TOKEN" ]]; then
    echo -e "  ${RED}✗ Could not extract API/OAuth token for Cloudflare API calls${NC}"
    echo -e "  ${DIM}Set CLOUDFLARE_API_TOKEN in .env or run wrangler login in a terminal${NC}"
    exit 1
fi

# Persist the token to .env so the admin panel can resolve tunnel URLs
if [[ -n "$CF_TOKEN" ]] && [[ -f "$ENV_FILE" ]]; then
    EXISTING_TOKEN=$(grep '^CLOUDFLARE_API_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ "$EXISTING_TOKEN" != "$CF_TOKEN" ]]; then
        sed -i '/^CLOUDFLARE_API_TOKEN=/d' "$ENV_FILE"
        echo "CLOUDFLARE_API_TOKEN=${CF_TOKEN}" >> "$ENV_FILE"
        echo -e "  ${GREEN}✓ CLOUDFLARE_API_TOKEN saved to .env${NC}"
    fi
fi

# ── Helper: CF API call ─────────────────────────────────────────────
cf_api() {
    local method="$1"
    local path="$2"
    local data="${3:-}"
    local args=(-s -X "$method" "https://api.cloudflare.com/client/v4${path}" \
        -H "Authorization: Bearer ${CF_TOKEN}" \
        -H "Content-Type: application/json")
    if [[ -n "$data" ]]; then
        args+=(-d "$data")
    fi
    curl "${args[@]}"
}

# ════════════════════════════════════════════════════════════════════
# Step 3: Get account ID
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}Detecting Cloudflare account…${NC}"

ACCOUNTS_RESP=$(cf_api GET "/accounts?per_page=5")
ACCOUNT_ID=$(echo "$ACCOUNTS_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('result', [])
if results:
    print(results[0]['id'])
else:
    print('')
" 2>/dev/null || true)

ACCOUNT_NAME=$(echo "$ACCOUNTS_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('result', [])
if results:
    print(results[0].get('name', ''))
" 2>/dev/null || true)

if [[ -z "$ACCOUNT_ID" ]]; then
    echo -e "  ${RED}✗ Could not determine Cloudflare account ID${NC}"
    echo -e "  ${DIM}Ensure your token has Account access${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓ Account: ${ACCOUNT_NAME} (${ACCOUNT_ID:0:8}…)${NC}"

# ── Verify tunnel API permissions ───────────────────────────────────
# The wrangler OAuth token may not include tunnel scopes.
# Test with a tunnel token fetch — this requires Edit access, not just Read.
# First grab any existing tunnel ID to test against.
TUNNEL_PEEK=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel?is_deleted=false&per_page=1")
PEEK_TID=$(echo "$TUNNEL_PEEK" | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',[]); print(r[0]['id'] if r else '')" 2>/dev/null || true)

HAS_FULL_ACCESS="false"
if [[ -n "$PEEK_TID" ]]; then
    TOKEN_PEEK=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${PEEK_TID}/token")
    TOKEN_PEEK_OK=$(echo "$TOKEN_PEEK" | python3 -c "import sys,json; print('ok' if json.load(sys.stdin).get('success') else 'fail')" 2>/dev/null || echo "fail")
    if [[ "$TOKEN_PEEK_OK" == "ok" ]]; then
        HAS_FULL_ACCESS="true"
    fi
fi

# ════════════════════════════════════════════════════════════════════
# Branch: full API access vs. limited OAuth (dashboard fallback)
# ════════════════════════════════════════════════════════════════════

if [[ "$HAS_FULL_ACCESS" == "true" ]]; then
    # ── FULL ACCESS PATH: use API for everything ──────────────────

    # ── Step 4: List / choose / create tunnel ──
    echo ""
    echo -e "${BOLD}Tunnel selection…${NC}"

    TUNNELS_RESP=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel?is_deleted=false&per_page=50")

    TUNNEL_LIST=$(echo "$TUNNELS_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tunnels = data.get('result', [])
for i, t in enumerate(tunnels):
    name = t.get('name', 'unnamed')
    tid = t.get('id', '')
    status = t.get('status', 'unknown')
    conns = len(t.get('connections', []))
    print(f'{i+1}|{tid}|{name}|{status}|{conns}')
" 2>/dev/null || true)

    TUNNEL_COUNT=$(echo "$TUNNEL_LIST" | grep -c '|' 2>/dev/null || echo "0")
    TUNNEL_ID=""
    TUNNEL_NAME=""

    if [[ $TUNNEL_COUNT -gt 0 ]]; then
        echo ""
        echo -e "  ${BOLD}Existing tunnels:${NC}"
        echo ""
        while IFS='|' read -r num tid tname tstatus tconns; do
            [[ -z "$num" ]] && continue
            status_icon="⚪"
            [[ "$tstatus" == "healthy" ]] && status_icon="✅"
            [[ "$tstatus" == "inactive" ]] && status_icon="⏹"
            echo -e "    ${BOLD}${num})${NC} ${tname}  ${status_icon} ${tstatus}  ${DIM}(${tid:0:8}…, ${tconns} connectors)${NC}"
        done <<< "$TUNNEL_LIST"
        echo ""
        echo -e "    ${BOLD}N)${NC} Create a new tunnel"
        echo ""

        if [[ "$SKIP_CONFIRM" == "true" ]]; then
            CHOSEN=$(echo "$TUNNEL_LIST" | grep -i "continuity" | head -1 || echo "$TUNNEL_LIST" | head -1)
            TUNNEL_ID=$(echo "$CHOSEN" | cut -d'|' -f2)
            TUNNEL_NAME=$(echo "$CHOSEN" | cut -d'|' -f3)
            echo -e "  ${GREEN}✓ Auto-selected: ${TUNNEL_NAME}${NC}"
        else
            read -p "  Choose tunnel number (or N for new): " CHOICE
            CHOICE="${CHOICE:-1}"

            if [[ "$CHOICE" =~ ^[Nn] ]]; then
                TUNNEL_ID=""  # will create below
            else
                CHOSEN=$(echo "$TUNNEL_LIST" | sed -n "${CHOICE}p")
                if [[ -n "$CHOSEN" ]]; then
                    TUNNEL_ID=$(echo "$CHOSEN" | cut -d'|' -f2)
                    TUNNEL_NAME=$(echo "$CHOSEN" | cut -d'|' -f3)
                    echo -e "  ${GREEN}✓ Selected: ${TUNNEL_NAME} (${TUNNEL_ID:0:8}…)${NC}"
                else
                    echo -e "  ${YELLOW}⚠ Invalid choice — will create new tunnel${NC}"
                fi
            fi
        fi
    fi

    # Create new tunnel if needed
    if [[ -z "$TUNNEL_ID" ]]; then
        if [[ -n "$TUNNEL_NAME_ARG" ]]; then
            TUNNEL_NAME="$TUNNEL_NAME_ARG"
        else
            DEFAULT_NAME="continuity-orchestrator"
            if [[ "$SKIP_CONFIRM" == "true" ]]; then
                TUNNEL_NAME="$DEFAULT_NAME"
            else
                read -p "  New tunnel name [${DEFAULT_NAME}]: " TUNNEL_NAME
                TUNNEL_NAME="${TUNNEL_NAME:-$DEFAULT_NAME}"
            fi
        fi

        echo -e "  ${DIM}Creating tunnel '${TUNNEL_NAME}'…${NC}"
        TUNNEL_SECRET=$(openssl rand -base64 32)
        CREATE_RESP=$(cf_api POST "/accounts/${ACCOUNT_ID}/cfd_tunnel" \
            "{\"name\":\"${TUNNEL_NAME}\",\"tunnel_secret\":\"${TUNNEL_SECRET}\",\"config_src\":\"cloudflare\"}")

        TUNNEL_ID=$(echo "$CREATE_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data.get('success'):
    print(data['result']['id'])
else:
    print('')
" 2>/dev/null || true)

        if [[ -z "$TUNNEL_ID" ]]; then
            echo -e "  ${RED}✗ Failed to create tunnel${NC}"
            echo -e "  ${DIM}$(echo "$CREATE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('errors',[{}])[0].get('message',''))" 2>/dev/null || echo "$CREATE_RESP")${NC}"
            exit 1
        fi
        echo -e "  ${GREEN}✓ Created tunnel: ${TUNNEL_NAME} (${TUNNEL_ID:0:8}…)${NC}"
    fi

    # ── Step 5: Configure ingress (public hostname) ──
    echo ""
    echo -e "${BOLD}Public hostname…${NC}"
    echo -e "${DIM}The tunnel needs an ingress rule mapping a hostname to your service.${NC}"

    EXISTING_CONFIG=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations")
    EXISTING_HOSTNAME=$(echo "$EXISTING_CONFIG" | python3 -c "
import sys, json
data = json.load(sys.stdin)
config = data.get('result', {}).get('config', {})
ingress = config.get('ingress', [])
for rule in ingress:
    h = rule.get('hostname', '')
    if h:
        print(h)
        break
" 2>/dev/null || true)

    HOSTNAME=""
    if [[ -n "$EXISTING_HOSTNAME" ]]; then
        echo -e "  ${GREEN}✓ Already configured: ${EXISTING_HOSTNAME}${NC}"
        HOSTNAME="$EXISTING_HOSTNAME"
        if [[ "$SKIP_CONFIRM" != "true" ]]; then
            read -p "  Keep this hostname? (Y/n): " KEEP_HOST
            KEEP_HOST="${KEEP_HOST:-Y}"
            if [[ ! "$KEEP_HOST" =~ ^[Yy] ]]; then
                HOSTNAME=""
            fi
        fi
    fi

    if [[ -z "$HOSTNAME" ]]; then
        if [[ -n "$HOSTNAME_ARG" ]]; then
            HOSTNAME="$HOSTNAME_ARG"
        elif [[ "$SKIP_CONFIRM" == "true" ]]; then
            echo -e "  ${DIM}Skipped — no hostname provided. Add one later from the Cloudflare dashboard.${NC}"
        else
            echo ""
            echo -e "  Enter the hostname for your site (e.g. ${CYAN}continuity.yourdomain.com${NC})"
            echo -e "  ${DIM}The domain must already be on your Cloudflare account.${NC}"
            echo ""
            read -p "  Hostname (or Enter to skip): " HOSTNAME
        fi
    fi

    if [[ -n "$HOSTNAME" ]]; then
        echo -e "  ${DIM}Configuring tunnel ingress for ${HOSTNAME} → http://nginx:80${NC}"

        CONFIG_RESP=$(cf_api PUT "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" \
            "{\"config\":{\"ingress\":[{\"hostname\":\"${HOSTNAME}\",\"service\":\"http://nginx:80\",\"originRequest\":{}},{\"service\":\"http_status:404\"}]}}")

        CONFIG_OK=$(echo "$CONFIG_RESP" | python3 -c "import sys,json; print('ok' if json.load(sys.stdin).get('success') else 'fail')" 2>/dev/null || echo "fail")
        if [[ "$CONFIG_OK" == "ok" ]]; then
            echo -e "  ${GREEN}✓ Ingress configured: ${HOSTNAME} → http://nginx:80${NC}"
        else
            echo -e "  ${YELLOW}⚠ Ingress config may have failed — check the Cloudflare dashboard${NC}"
            echo -e "  ${DIM}$(echo "$CONFIG_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('errors',[{}])[0].get('message',''))" 2>/dev/null)${NC}"
        fi

        # Create DNS CNAME
        echo -e "  ${DIM}Setting up DNS CNAME…${NC}"
        BASE_DOMAIN=$(echo "$HOSTNAME" | rev | cut -d. -f1-2 | rev)
        ZONE_RESP=$(cf_api GET "/zones?name=${BASE_DOMAIN}&per_page=1")
        ZONE_ID=$(echo "$ZONE_RESP" | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',[]); print(r[0]['id'] if r else '')" 2>/dev/null || true)

        if [[ -n "$ZONE_ID" ]]; then
            DNS_CHECK=$(cf_api GET "/zones/${ZONE_ID}/dns_records?type=CNAME&name=${HOSTNAME}")
            EXISTING_DNS=$(echo "$DNS_CHECK" | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',[]); print(r[0]['id'] if r else '')" 2>/dev/null || true)

            CNAME_TARGET="${TUNNEL_ID}.cfargotunnel.com"
            if [[ -n "$EXISTING_DNS" ]]; then
                cf_api PUT "/zones/${ZONE_ID}/dns_records/${EXISTING_DNS}" \
                    "{\"type\":\"CNAME\",\"name\":\"${HOSTNAME}\",\"content\":\"${CNAME_TARGET}\",\"proxied\":true}" > /dev/null
                echo -e "  ${GREEN}✓ DNS CNAME updated: ${HOSTNAME} → tunnel${NC}"
            else
                DNS_CREATE=$(cf_api POST "/zones/${ZONE_ID}/dns_records" \
                    "{\"type\":\"CNAME\",\"name\":\"${HOSTNAME}\",\"content\":\"${CNAME_TARGET}\",\"proxied\":true}")
                DNS_OK=$(echo "$DNS_CREATE" | python3 -c "import sys,json; print('ok' if json.load(sys.stdin).get('success') else 'fail')" 2>/dev/null || echo "fail")
                if [[ "$DNS_OK" == "ok" ]]; then
                    echo -e "  ${GREEN}✓ DNS CNAME created: ${HOSTNAME} → tunnel${NC}"
                else
                    echo -e "  ${YELLOW}⚠ DNS creation failed — you may need to add a CNAME manually${NC}"
                    echo -e "  ${DIM}  ${HOSTNAME} → ${CNAME_TARGET}${NC}"
                fi
            fi
        else
            echo -e "  ${YELLOW}⚠ Zone not found for '${BASE_DOMAIN}' — add CNAME manually:${NC}"
            echo -e "  ${DIM}  ${HOSTNAME} CNAME ${TUNNEL_ID}.cfargotunnel.com${NC}"
        fi
    else
        echo -e "  ${DIM}Skipped hostname config. You can add it later from the Cloudflare dashboard.${NC}"
    fi

    # ── Step 6: Get tunnel token via API ──
    echo ""
    echo -e "${BOLD}Fetching connector token…${NC}"

    TOKEN_RESP=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/token")
    TUNNEL_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data.get('success'):
    print(data['result'])
else:
    print('')
" 2>/dev/null || true)

    if [[ -z "$TUNNEL_TOKEN" ]]; then
        echo -e "  ${RED}✗ Failed to fetch tunnel token${NC}"
        echo -e "  ${DIM}$(echo "$TOKEN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('errors',[{}])[0].get('message',''))" 2>/dev/null)${NC}"
        exit 1
    fi

    echo -e "  ${GREEN}✓ Token retrieved (${#TUNNEL_TOKEN} chars)${NC}"

else
    # ── LIMITED ACCESS PATH: use dashboard to get tunnel token ────
    # OAuth can list tunnels but can't fetch tokens or create tunnels.
    # Open the tunnel's dashboard page where the token is visible.
    echo ""
    echo -e "  ${YELLOW}⚠ OAuth token has limited tunnel permissions.${NC}"
    echo -e "  ${DIM}Let's pick your tunnel and grab the token from the dashboard.${NC}"
    echo ""

    # List tunnels (this works with OAuth)
    echo -e "${BOLD}Tunnel selection…${NC}"
    TUNNELS_RESP=$(cf_api GET "/accounts/${ACCOUNT_ID}/cfd_tunnel?is_deleted=false&per_page=50")

    TUNNEL_LIST=$(echo "$TUNNELS_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tunnels = data.get('result', [])
for i, t in enumerate(tunnels):
    name = t.get('name', 'unnamed')
    tid = t.get('id', '')
    status = t.get('status', 'unknown')
    conns = len(t.get('connections', []))
    print(f'{i+1}|{tid}|{name}|{status}|{conns}')
" 2>/dev/null || true)

    TUNNEL_COUNT=$(echo "$TUNNEL_LIST" | grep -c '|' 2>/dev/null || echo "0")

    if [[ $TUNNEL_COUNT -eq 0 ]]; then
        echo -e "  ${YELLOW}⚠ No tunnels found. You need to create one first.${NC}"
        echo ""
        echo -e "  ${BOLD}To create a tunnel:${NC}"
        echo -e "    ${CYAN}1.${NC} Go to ${BOLD}Cloudflare Zero Trust${NC} dashboard"
        echo -e "    ${CYAN}2.${NC} Navigate to ${BOLD}Networks → Tunnels${NC}"
        echo -e "    ${CYAN}3.${NC} Click ${BOLD}Create a tunnel${NC}"
        echo -e "    ${CYAN}4.${NC} Name it (e.g. ${CYAN}continuity-orchestrator${NC})"
        echo -e "    ${CYAN}5.${NC} After creation, re-run this script"
        echo ""

        CREATE_URL="https://one.dash.cloudflare.com/${ACCOUNT_ID}/networks/connectors/add"
        BROWSER_OPENED="false"
        for opener in xdg-open open sensible-browser; do
            if command -v "$opener" &>/dev/null; then
                "$opener" "$CREATE_URL" 2>/dev/null &
                BROWSER_OPENED="true"
                break
            fi
        done

        if [[ "$BROWSER_OPENED" != "true" ]]; then
            echo -e "  ${DIM}Open this URL:${NC}"
            echo -e "  ${CYAN}${CREATE_URL}${NC}"
        fi

        # Write signal so web UI knows what happened
        echo "{\"status\":\"no_tunnels\",\"create_url\":\"${CREATE_URL}\",\"ts\":\"$(date -Iseconds)\"}" > "$SIGNAL_FILE"
        exit 1
    fi

    TUNNEL_ID=""
    TUNNEL_NAME=""

    echo ""
    echo -e "  ${BOLD}Existing tunnels:${NC}"
    echo ""
    while IFS='|' read -r num tid tname tstatus tconns; do
        [[ -z "$num" ]] && continue
        status_icon="⚪"
        [[ "$tstatus" == "healthy" ]] && status_icon="✅"
        [[ "$tstatus" == "inactive" ]] && status_icon="⏹"
        echo -e "    ${BOLD}${num})${NC} ${tname}  ${status_icon} ${tstatus}  ${DIM}(${tid:0:8}…, ${tconns} connectors)${NC}"
    done <<< "$TUNNEL_LIST"
    echo ""

    if [[ $TUNNEL_COUNT -eq 1 ]]; then
        # Only one tunnel — auto-select it
        CHOSEN=$(echo "$TUNNEL_LIST" | head -1)
        TUNNEL_ID=$(echo "$CHOSEN" | cut -d'|' -f2)
        TUNNEL_NAME=$(echo "$CHOSEN" | cut -d'|' -f3)
        echo -e "  ${GREEN}✓ Auto-selected: ${TUNNEL_NAME} (only tunnel)${NC}"
    else
        read -p "  Choose tunnel number: " CHOICE
        CHOICE="${CHOICE:-1}"
        CHOSEN=$(echo "$TUNNEL_LIST" | sed -n "${CHOICE}p")
        if [[ -n "$CHOSEN" ]]; then
            TUNNEL_ID=$(echo "$CHOSEN" | cut -d'|' -f2)
            TUNNEL_NAME=$(echo "$CHOSEN" | cut -d'|' -f3)
            echo -e "  ${GREEN}✓ Selected: ${TUNNEL_NAME} (${TUNNEL_ID:0:8}…)${NC}"
        else
            echo -e "  ${RED}✗ Invalid choice${NC}"
            exit 1
        fi
    fi

    # Open the tunnel's dashboard page — the token is shown on the install tab
    TUNNEL_DASH="https://one.dash.cloudflare.com/${ACCOUNT_ID}/networks/connectors/cloudflare-tunnels/cfd_tunnel/${TUNNEL_ID}/edit?tab=install"
    echo ""
    echo -e "  ${BOLD}Opening tunnel dashboard…${NC}"
    echo ""

    BROWSER_OPENED="false"
    for opener in xdg-open open sensible-browser; do
        if command -v "$opener" &>/dev/null; then
            "$opener" "$TUNNEL_DASH" 2>/dev/null &
            BROWSER_OPENED="true"
            break
        fi
    done

    if [[ "$BROWSER_OPENED" != "true" ]]; then
        echo -e "  ${DIM}Open this URL:${NC}"
        echo -e "  ${CYAN}${TUNNEL_DASH}${NC}"
        echo ""
    fi

    # Write needs_token signal so the web UI can show a paste input
    echo "{\"status\":\"needs_token\",\"tunnel_id\":\"${TUNNEL_ID}\",\"tunnel_name\":\"${TUNNEL_NAME}\",\"dashboard_url\":\"${TUNNEL_DASH}\",\"ts\":\"$(date -Iseconds)\"}" > "$SIGNAL_FILE"

    echo -e "  ${DIM}Waiting for the tunnel token…${NC}"
    echo -e "  ${DIM}Paste the install command in the web UI, or here:${NC}"
    echo ""

    # Poll for the token: either the web UI writes it to .env, or the user pastes here
    TOKEN_WAIT_FILE="${PROJECT_ROOT}/.tunnel-token-provided"
    rm -f "$TOKEN_WAIT_FILE" 2>/dev/null

    # Use a background read with poll loop so the script can also detect web UI input
    TUNNEL_TOKEN=""

    # Disable ERR trap during the poll loop — read timeouts and grep misses
    # are expected, not errors.
    trap '' ERR

    # Try terminal read with a timeout, checking for web UI signal every 2s
    while true; do
        # Check if web UI already provided the token
        if [[ -f "$TOKEN_WAIT_FILE" ]]; then
            TUNNEL_TOKEN=$(cat "$TOKEN_WAIT_FILE")
            rm -f "$TOKEN_WAIT_FILE" 2>/dev/null
            echo ""
            echo -e "  ${GREEN}✓ Token received from web UI${NC}"
            break
        fi

        # Check if .env already has the token (web UI route writes directly)
        if [[ -f "$ENV_FILE" ]]; then
            EXISTING=$(grep '^CLOUDFLARE_TUNNEL_TOKEN=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)
            if [[ -n "$EXISTING" ]]; then
                TUNNEL_TOKEN="$EXISTING"
                echo ""
                echo -e "  ${GREEN}✓ Token found in .env (set via web UI)${NC}"
                break
            fi
        fi

        # Try to read from terminal with a 2s timeout
        RAW_TOKEN_INPUT=""
        read -t 2 -p "  > " RAW_TOKEN_INPUT 2>/dev/null || true
        if [[ -n "$RAW_TOKEN_INPUT" ]]; then
            # Extract eyJ... token from pasted command
            TUNNEL_TOKEN=$(echo "$RAW_TOKEN_INPUT" | grep -oP 'eyJ[A-Za-z0-9_=+/.-]+' | head -1 || true)
            if [[ -z "$TUNNEL_TOKEN" ]]; then
                TUNNEL_TOKEN="$RAW_TOKEN_INPUT"
            fi
            echo -e "  ${GREEN}✓ Token received (${#TUNNEL_TOKEN} chars)${NC}"
            break
        fi
    done

    # Re-enable ERR trap
    trap 'echo "{\"status\":\"failed\",\"ts\":\"'"$(date -Iseconds)"'\"}" > "$SIGNAL_FILE"; echo ""; echo -e "\033[0;31m✗ Setup failed. See error above.\033[0m"; echo ""; read -p "Press Enter to close…"' ERR

    if [[ -z "$TUNNEL_TOKEN" ]]; then
        echo -e "  ${RED}✗ No token provided.${NC}"
        exit 1
    fi

    HOSTNAME=""
fi

# ════════════════════════════════════════════════════════════════════
# Step 7: Write to .env
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}Saving to .env…${NC}"

if [[ -f "$ENV_FILE" ]]; then
    sed -i '/^CLOUDFLARE_TUNNEL_TOKEN=/d' "$ENV_FILE"
    sed -i '/^# ── Cloudflare Tunnel/d' "$ENV_FILE"
fi

cat >> "$ENV_FILE" <<EOF

# ── Cloudflare Tunnel ────────────────────────────────────────────────
CLOUDFLARE_TUNNEL_TOKEN=${TUNNEL_TOKEN}
EOF

echo -e "  ${GREEN}✓ CLOUDFLARE_TUNNEL_TOKEN written to .env${NC}"

# ── Done ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ Tunnel is ready!${NC}"
echo ""
echo -e "  ${DIM}Tunnel:   ${TUNNEL_NAME:-selected tunnel} (${TUNNEL_ID:0:12}…)${NC}"
if [[ -n "$HOSTNAME" ]]; then
echo -e "  ${DIM}URL:      https://${HOSTNAME}${NC}"
fi
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo -e "  1. Start the tunnel container:"
echo -e "     ${CYAN}docker compose --profile git-sync --profile tunnel up -d${NC}"
if [[ -n "$HOSTNAME" ]]; then
echo -e "  2. Visit your site at ${CYAN}https://${HOSTNAME}${NC}"
else
echo -e "  2. Add a public hostname from the Cloudflare dashboard"
fi
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Write success signal
SIGNAL_DATA="{\"status\":\"success\",\"tunnel_name\":\"${TUNNEL_NAME:-selected}\",\"tunnel_id\":\"${TUNNEL_ID}\""
if [[ -n "$HOSTNAME" ]]; then
    SIGNAL_DATA="${SIGNAL_DATA},\"hostname\":\"${HOSTNAME}\""
fi
# Include the token in the signal so the wizard UI can auto-populate it
SIGNAL_DATA="${SIGNAL_DATA},\"token\":\"${TUNNEL_TOKEN}\""
SIGNAL_DATA="${SIGNAL_DATA},\"ts\":\"$(date -Iseconds)\"}"
echo "$SIGNAL_DATA" > "$SIGNAL_FILE"
