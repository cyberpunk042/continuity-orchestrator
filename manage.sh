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
    echo -e "  ${RED}!)${NC}  trigger-release Emergency disclosure trigger"
    echo ""
    echo -e "  ${CYAN}h)${NC}  help           Show all CLI commands"
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
    echo -e "\n${BOLD}=== CLI Help ===${NC}\n"
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

run_push_secrets() {
    echo -e "\n${BOLD}=== Push Secrets to GitHub ===${NC}\n"
    
    # Load secrets from .env first
    if [ ! -f ".env" ]; then
        echo -e "${RED}Error: .env file not found. Run setup first.${NC}"
        return 1
    fi
    source .env
    
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
        echo "  1) Install gh: https://cli.github.com/"
        echo "  2) Manually add secrets at:"
        echo "     https://github.com/${REPO}/settings/secrets/actions"
        echo ""
        echo -e "${BOLD}Your secrets (copy these values):${NC}"
        echo ""
        [ -n "$RESEND_API_KEY" ] && echo "RESEND_API_KEY=$RESEND_API_KEY"
        [ -n "$TWILIO_ACCOUNT_SID" ] && echo "TWILIO_ACCOUNT_SID=$TWILIO_ACCOUNT_SID"
        [ -n "$TWILIO_AUTH_TOKEN" ] && echo "TWILIO_AUTH_TOKEN=$TWILIO_AUTH_TOKEN"
        [ -n "$TWILIO_FROM_NUMBER" ] && echo "TWILIO_FROM_NUMBER=$TWILIO_FROM_NUMBER"
        [ -n "$OPERATOR_SMS" ] && echo "OPERATOR_SMS=$OPERATOR_SMS"
        [ -n "$RENEWAL_SECRET" ] && echo "RENEWAL_SECRET=$RENEWAL_SECRET"
        [ -n "$RELEASE_SECRET" ] && echo "RELEASE_SECRET=$RELEASE_SECRET"
        [ -n "$RENEWAL_TRIGGER_TOKEN" ] && echo "RENEWAL_TRIGGER_TOKEN=$RENEWAL_TRIGGER_TOKEN"
        echo ""
        return 0
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
    echo -e "${BOLD}Secrets to push:${NC}"
    
    # List what we'll push
    [ -n "$RESEND_API_KEY" ] && echo -e "  ✓ RESEND_API_KEY"
    [ -n "$TWILIO_ACCOUNT_SID" ] && echo -e "  ✓ TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER"
    [ -n "$RENEWAL_SECRET" ] && echo -e "  ✓ RENEWAL_SECRET"
    [ -n "$RELEASE_SECRET" ] && echo -e "  ✓ RELEASE_SECRET"
    [ -n "$RENEWAL_TRIGGER_TOKEN" ] && echo -e "  ✓ RENEWAL_TRIGGER_TOKEN"
    [ -n "$GITHUB_TOKEN" ] && echo -e "  ✓ GITHUB_TOKEN (as GH_TOKEN)"
    
    echo ""
    read -p "Push these secrets to ${REPO}? (Y/n): " confirm
    confirm="${confirm:-Y}"
    if [[ ! "$confirm" =~ ^[Yy] ]]; then
        echo "Cancelled."
        return 0
    fi
    
    echo ""
    echo "Pushing secrets..."
    
    # Push each secret
    push_secret() {
        local name="$1"
        local value="$2"
        if [ -n "$value" ]; then
            echo "$value" | gh secret set "$name" -R "$REPO" && \
                echo -e "  ${GREEN}✓${NC} $name" || \
                echo -e "  ${RED}✗${NC} $name failed"
        fi
    }
    
    push_secret "RESEND_API_KEY" "$RESEND_API_KEY"
    push_secret "TWILIO_ACCOUNT_SID" "$TWILIO_ACCOUNT_SID"
    push_secret "TWILIO_AUTH_TOKEN" "$TWILIO_AUTH_TOKEN"
    push_secret "TWILIO_FROM_NUMBER" "$TWILIO_FROM_NUMBER"
    push_secret "OPERATOR_SMS" "$OPERATOR_SMS"
    push_secret "RENEWAL_SECRET" "$RENEWAL_SECRET"
    push_secret "RELEASE_SECRET" "$RELEASE_SECRET"
    push_secret "RENEWAL_TRIGGER_TOKEN" "$RENEWAL_TRIGGER_TOKEN"
    
    echo ""
    echo -e "${GREEN}Done!${NC} Secrets pushed to ${REPO}"
    echo ""
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
            '!'|trigger) run_trigger_release ;;
            h|help) show_help ;;
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
