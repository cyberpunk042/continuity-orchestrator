#!/usr/bin/env bash
#
# Continuity Orchestrator — Management Interface
# A friendly entrypoint for all available commands
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Ensure venv is activated
if [[ ! -d ".venv" ]]; then
    echo -e "${RED}Error: Virtual environment not found. Run ./setup.sh first.${NC}"
    exit 1
fi
source .venv/bin/activate

show_banner() {
    echo -e "${BOLD}${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           CONTINUITY ORCHESTRATOR — MANAGER                  ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

show_menu() {
    echo -e "${BOLD}Available Commands:${NC}"
    echo ""
    echo -e "  ${GREEN}1)${NC} status          Show current system status"
    echo -e "  ${GREEN}2)${NC} tick            Run a single tick (evaluate + execute)"
    echo -e "  ${GREEN}3)${NC} tick --dry-run  Preview tick without changes"
    echo ""
    echo -e "  ${YELLOW}4)${NC} renew           Extend deadline (interactive)"
    echo -e "  ${YELLOW}5)${NC} set-deadline    Set specific deadline"
    echo -e "  ${YELLOW}6)${NC} reset           Reset escalation state to OK"
    echo -e "  ${YELLOW}7)${NC} reset --full    Full factory reset (with backup)"
    echo ""
    echo -e "  ${BLUE}8)${NC} build-site      Generate static site"
    echo -e "  ${BLUE}9)${NC} test            Test adapters/integrations"
    echo -e "  ${BLUE}0)${NC} setup           Run setup wizard (reconfigure)"
    echo -e "  ${BLUE}s)${NC} secrets         Push all secrets to GitHub repo"
    echo ""
    echo -e "  ${CYAN}w)${NC}  web            Open web admin panel (--debug for verbose logs)"
    echo -e "  ${CYAN}c)${NC}  config-status  Show comprehensive status"
    echo ""
    echo -e "  ${RED}!)${NC}  trigger-release Emergency disclosure trigger"
    echo ""
    echo -e "  ${CYAN}h)${NC}  help           Show all CLI commands"
    echo -e "  ${CYAN}n)${NC}  sentinel       Deploy/update Sentinel Worker"
    echo -e "  ${CYAN}t)${NC}  tunnel         Setup Cloudflare Tunnel"
    echo -e "  ${CYAN}q)${NC}  quit           Exit"
    echo ""
}

run_status() {
    echo -e "\n${BOLD}=== Current Status ===${NC}\n"
    python -m src.main status
}

run_tick() {
    local dry_run="${1:-}"
    echo -e "\n${BOLD}=== Running Tick ===${NC}\n"
    if [[ "$dry_run" == "--dry-run" ]]; then
        python -m src.main tick --dry-run
    else
        python -m src.main tick
    fi
}

run_renew() {
    echo -e "\n${BOLD}=== Renew Deadline ===${NC}\n"
    read -p "Hours to extend (default 48): " hours
    hours="${hours:-48}"
    python -m src.main renew --hours "$hours"
}

run_set_deadline() {
    echo -e "\n${BOLD}=== Set Deadline ===${NC}\n"
    read -p "Hours from now: " hours
    if [[ -n "$hours" ]]; then
        python -m src.main set-deadline --hours "$hours"
    else
        echo "Cancelled."
    fi
}

run_reset() {
    echo -e "\n${BOLD}=== Reset State ===${NC}\n"
    python -m src.main reset
}

run_full_reset() {
    echo -e "\n${BOLD}=== Full Factory Reset ===${NC}\n"
    read -p "Hours for initial deadline (default 48): " hours
    hours="${hours:-48}"
    python -m src.main reset --full --hours "$hours"
}

run_build_site() {
    echo -e "\n${BOLD}=== Building Site ===${NC}\n"
    python -m src.main build-site --output public
    echo -e "\n${GREEN}Site built to public/${NC}"
    echo "Files:"
    ls public/*.html 2>/dev/null | head -10
}

run_test() {
    echo -e "\n${BOLD}=== Test Integrations ===${NC}\n"
    echo "Available tests:"
    echo "  all, email, sms, twitter, reddit, webhook"
    read -p "Which test? (default: all): " test_name
    test_name="${test_name:-all}"
    python -m src.main test "$test_name"
}

run_trigger_release() {
    echo -e "\n${RED}${BOLD}=== EMERGENCY RELEASE TRIGGER ===${NC}\n"
    echo -e "${RED}⚠️  This will trigger full disclosure!${NC}"
    read -p "Are you sure? (type 'yes' to confirm): " confirm
    if [[ "$confirm" == "yes" ]]; then
        read -p "Delay in minutes (0=immediate): " delay
        delay="${delay:-0}"
        python -m src.main trigger-release --stage FULL --delay "$delay"
    else
        echo "Cancelled."
    fi
}

show_help() {
    echo -e "\n${BOLD}=== Manager Commands ===${NC}\n"
    echo -e "  ${BOLD}./manage.sh ${GREEN}<command>${NC} [options]"
    echo ""
    echo -e "  ${GREEN}status${NC}             Show current system status"
    echo -e "  ${GREEN}tick${NC}               Run a single tick (evaluate + execute)"
    echo -e "  ${GREEN}tick --dry-run${NC}      Preview tick without changes"
    echo -e "  ${YELLOW}renew${NC}              Extend deadline (interactive)"
    echo -e "  ${YELLOW}set-deadline${NC}       Set specific deadline"
    echo -e "  ${YELLOW}reset${NC}              Reset escalation state to OK"
    echo -e "  ${YELLOW}reset --full${NC}        Full factory reset (with backup)"
    echo -e "  ${BLUE}build-site${NC}         Generate static site"
    echo -e "  ${BLUE}test${NC}               Test adapters/integrations"
    echo -e "  ${BLUE}setup${NC}              Run setup wizard (reconfigure)"
    echo -e "  ${BLUE}secrets${NC}            Push all secrets to GitHub repo"
    echo -e "  ${CYAN}web${NC}                Open web admin panel (--debug for verbose)"
    echo -e "  ${CYAN}config-status${NC}      Show comprehensive status"
    echo -e "  ${CYAN}sentinel [-y]${NC}      Deploy/update Sentinel Worker"
    echo -e "  ${CYAN}tunnel [-y]${NC}        Setup Cloudflare Tunnel"
    echo -e "    ${DIM}-y, --yes        Auto-confirm all prompts${NC}"
    echo -e "  ${RED}trigger-release${NC}    Emergency disclosure trigger"
    echo ""
    echo -e "${BOLD}=== Python CLI ===${NC}\n"
    python -m src.main --help
    echo ""
    echo -e "${BOLD}Command details:${NC}"
    echo "  python -m src.main <command> --help"
}

run_setup() {
    echo -e "\n${BOLD}=== Running Setup Wizard ===${NC}\n"
    echo -e "${CYAN}This will let you reconfigure the project.${NC}"
    echo -e "${CYAN}Your existing credentials will be preserved.${NC}"
    echo ""
    read -p "Continue? (Y/n): " confirm
    confirm="${confirm:-Y}"
    if [[ "$confirm" =~ ^[Yy] ]]; then
        ./setup.sh
    else
        echo "Cancelled."
    fi
}

run_admin() {
    local extra_args="${@}"
    echo -e "\n${BOLD}=== Web Admin Panel ===${NC}\n"
    echo -e "${CYAN}Opening browser to local admin panel...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop  |  Press SPACE to live-reload${NC}"
    if [[ "$extra_args" == *"--debug"* ]]; then
        echo -e "${RED}Debug mode enabled — verbose logging active${NC}"
    fi
    echo ""

    local server_pid=""

    # Cleanup on exit
    cleanup_admin() {
        if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
            kill "$server_pid" 2>/dev/null
            wait "$server_pid" 2>/dev/null
        fi
        stty sane 2>/dev/null  # restore terminal
    }
    trap cleanup_admin EXIT INT TERM

    while true; do
        # Start server in background
        python -m src.admin $extra_args &
        server_pid=$!

        # Wait for keypress or server exit
        while kill -0 "$server_pid" 2>/dev/null; do
            # Read a single char with 0.5s timeout
            if read -rsn1 -t 0.5 key 2>/dev/null; then
                if [[ "$key" == " " ]]; then
                    echo ""
                    echo -e "${CYAN}♻  Reloading server...${NC}"
                    echo ""
                    kill "$server_pid" 2>/dev/null
                    wait "$server_pid" 2>/dev/null
                    sleep 0.3
                    break  # restart the while-true loop
                fi
            fi
        done

        # If server exited on its own (not spacebar), exit the loop
        if ! kill -0 "$server_pid" 2>/dev/null; then
            wait "$server_pid" 2>/dev/null
            local exit_code=$?
            # If we broke out via spacebar, the process is already dead — continue
            # If it died on its own (crash or Ctrl+C), stop
            if [[ "$key" != " " ]]; then
                break
            fi
        fi
        key=""
    done
}

run_config_status() {
    echo -e "\n${BOLD}=== Configuration Status ===${NC}\n"
    python -m src.main config-status
}

run_push_secrets() {
    echo -e "\n${BOLD}=== Push Secrets to GitHub ===${NC}\n"
    
    # Load secrets from .env first (export so python can read them)
    if [ ! -f ".env" ]; then
        echo -e "${RED}Error: .env file not found. Run setup first.${NC}"
        return 1
    fi
    set -a  # Export all variables
    source .env
    set +a
    
    # Detect repo
    REPO="${GITHUB_REPOSITORY:-}"
    if [ -z "$REPO" ] || [ "$REPO" == "owner/repo" ]; then
        REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#(git@github\.com:|https://github\.com/)##' | sed 's/\.git$//')
    fi
    
    # Check for gh CLI
    if ! command -v gh &>/dev/null; then
        echo -e "${YELLOW}GitHub CLI (gh) not installed${NC}"
        echo ""
        echo "Options:"
        echo "  1) Install gh CLI now (recommended)"
        echo "  2) Show JSON to copy manually"
        echo ""
        read -p "Choose (1/2) [1]: " gh_choice
        gh_choice="${gh_choice:-1}"
        
        case "$gh_choice" in
            1)
                echo ""
                echo "Installing GitHub CLI..."
                (type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
                    && sudo mkdir -p -m 755 /etc/apt/keyrings \
                    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                    && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
                    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
                    && sudo mkdir -p -m 755 /etc/apt/sources.list.d \
                    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
                    && sudo apt update \
                    && sudo apt install gh -y
                
                if ! command -v gh &>/dev/null; then
                    echo -e "${RED}Installation failed${NC}"
                    return 1
                fi
                echo -e "${GREEN}✓ GitHub CLI installed${NC}"
                echo ""
                # Continue to push secrets below
                ;;
            2)
                echo ""
                echo -e "${BOLD}Create a secret named: CONTINUITY_CONFIG${NC}"
                echo -e "At: https://github.com/${REPO}/settings/secrets/actions"
                echo ""
                echo -e "${BOLD}With this JSON value:${NC}"
                echo ""
                python3 -c "
import json
import os

config = {}
for key in ['RESEND_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 
            'TWILIO_FROM_NUMBER', 'OPERATOR_SMS', 'RENEWAL_SECRET', 
            'RELEASE_SECRET', 'RENEWAL_TRIGGER_TOKEN', 'GITHUB_TOKEN',
            'OPERATOR_EMAIL', 'PROJECT_NAME']:
    val = os.environ.get(key, '')
    if val:
        config[key] = val

print(json.dumps(config, indent=2))
"
                echo ""
                return 0
                ;;
            *)
                echo "Cancelled."
                return 0
                ;;
        esac
    fi
    
    # Check gh auth
    if ! gh auth status &>/dev/null; then
        echo -e "${YELLOW}GitHub CLI not authenticated. Running 'gh auth login'...${NC}"
        gh auth login
    fi
    
    if [ -z "$REPO" ]; then
        echo -e "${RED}Error: Could not determine repository${NC}"
        return 1
    fi
    
    echo -e "Repository: ${CYAN}${REPO}${NC}"
    echo ""
    echo -e "${BOLD}How do you want to store secrets?${NC}"
    echo ""
    echo "  1) Master JSON (recommended)"
    echo "     → Single secret: CONTINUITY_CONFIG"
    echo "     → Cleaner, all-in-one"
    echo ""
    echo "  2) Individual secrets"
    echo "     → Multiple secrets: RENEWAL_SECRET, RELEASE_SECRET, etc."
    echo "     → Traditional approach"
    echo ""
    echo -e "${YELLOW}⚠ Note: If CONTINUITY_CONFIG exists, it overrides individual secrets${NC}"
    echo ""
    read -p "Choose (1/2) [1]: " secret_mode
    secret_mode="${secret_mode:-1}"
    
    echo ""
    
    push_secret() {
        local name="$1"
        local value="$2"
        if [ -n "$value" ]; then
            echo "$value" | gh secret set "$name" -R "$REPO" 2>/dev/null && \
                echo -e "  ${GREEN}✓${NC} $name" || \
                echo -e "  ${RED}✗${NC} $name"
        fi
    }
    
    if [[ "$secret_mode" == "1" ]]; then
        # Master JSON mode
        MASTER_JSON=$(python3 -c "
import json
import os

config = {}
for key in ['RESEND_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 
            'TWILIO_FROM_NUMBER', 'OPERATOR_SMS', 'RENEWAL_SECRET', 
            'RELEASE_SECRET', 'RENEWAL_TRIGGER_TOKEN', 'GITHUB_TOKEN',
            'OPERATOR_EMAIL', 'PROJECT_NAME']:
    val = os.environ.get(key, '')
    if val:
        config[key] = val

print(json.dumps(config, indent=2))
")
        
        echo -e "${BOLD}Pushing CONTINUITY_CONFIG:${NC}"
        echo "$MASTER_JSON"
        echo ""
        
        echo "$MASTER_JSON" | gh secret set "CONTINUITY_CONFIG" -R "$REPO" && \
            echo -e "${GREEN}✓${NC} CONTINUITY_CONFIG pushed" || \
            echo -e "${RED}✗${NC} Failed"
        
    else
        # Individual secrets mode
        echo "Pushing individual secrets..."
        echo ""
        
        push_secret "RESEND_API_KEY" "$RESEND_API_KEY"
        push_secret "TWILIO_ACCOUNT_SID" "$TWILIO_ACCOUNT_SID"
        push_secret "TWILIO_AUTH_TOKEN" "$TWILIO_AUTH_TOKEN"
        push_secret "TWILIO_FROM_NUMBER" "$TWILIO_FROM_NUMBER"
        push_secret "OPERATOR_SMS" "$OPERATOR_SMS"
        push_secret "RENEWAL_SECRET" "$RENEWAL_SECRET"
        push_secret "RELEASE_SECRET" "$RELEASE_SECRET"
        push_secret "RENEWAL_TRIGGER_TOKEN" "$RENEWAL_TRIGGER_TOKEN"
    fi
    
    echo ""
    echo -e "${GREEN}Done!${NC}"
    echo "View at: https://github.com/${REPO}/settings/secrets/actions"
}
# Main loop
main() {
    show_banner
    
    # If argument provided, run directly
    if [[ $# -gt 0 ]]; then
        case "$1" in
            status) run_status ;;
            tick) run_tick "${2:-}" ;;
            renew) run_renew ;;
            reset) 
                if [[ "${2:-}" == "--full" ]]; then
                    run_full_reset
                else
                    run_reset
                fi
                ;;
            build|build-site) run_build_site ;;
            test) run_test ;;
            trigger|trigger-release) run_trigger_release ;;
            setup|wizard) run_setup ;;
            secrets|push-secrets) run_push_secrets ;;
            sentinel) shift; ./scripts/setup-sentinel.sh "$@" ;;
            tunnel) shift; ./scripts/setup-tunnel.sh "$@" ;;
            web|admin) shift; run_admin "$@" ;;
            config-status|cs) run_config_status ;;
            help) show_help ;;
            *) 
                echo "Unknown command: $1"
                show_menu
                ;;
        esac
        exit 0
    fi
    
    # Interactive mode
    while true; do
        show_menu
        read -p "Select option: " choice
        
        case "$choice" in
            1|status) run_status ;;
            2|tick) run_tick ;;
            3) run_tick --dry-run ;;
            4|renew) run_renew ;;
            5|set-deadline) run_set_deadline ;;
            6|reset) run_reset ;;
            7) run_full_reset ;;
            8|build) run_build_site ;;
            9|test) run_test ;;
            0|setup) run_setup ;;
            s|secrets) run_push_secrets ;;
            w|web|admin) run_admin ;;
            c|config-status|cs) run_config_status ;;
            '!'|trigger) run_trigger_release ;;
            h|help) show_help ;;
            n|sentinel) ./scripts/setup-sentinel.sh ;;
            t|tunnel) ./scripts/setup-tunnel.sh ;;
            q|quit|exit) 
                echo "Goodbye!"
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option. Try again.${NC}"
                ;;
        esac
        
        echo ""
        read -p "Press Enter to continue..."
        clear
        show_banner
    done
}

main "$@"
