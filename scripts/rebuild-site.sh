#!/bin/bash
#
# rebuild-site.sh — Rebuild and optionally deploy the static site
#
# Usage:
#   ./scripts/rebuild-site.sh              # Build to public/
#   ./scripts/rebuild-site.sh --deploy     # Build and push to gh-pages
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

cd "$(dirname "$0")/.."

# Ensure venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${YELLOW}No .venv found, using system Python${NC}"
fi

echo -e "${CYAN}Building static site...${NC}"
python -m src.main build-site --output public

echo -e "${GREEN}✓ Site built to public/${NC}"
ls -la public/

if [ "$1" == "--deploy" ]; then
    echo ""
    echo -e "${CYAN}Deploying to gh-pages...${NC}"
    
    # Check if we're in a git repo
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        echo "Not in a git repository"
        exit 1
    fi
    
    # Use gh-pages branch
    git add public/
    git stash push -m "site-deploy" -- public/
    
    # Switch to gh-pages, update, switch back
    CURRENT_BRANCH=$(git branch --show-current)
    git checkout gh-pages 2>/dev/null || git checkout -b gh-pages
    git stash pop
    cp -r public/* .
    git add .
    git commit -m "site: Rebuild $(date -u +%Y-%m-%dT%H:%M:%SZ)" || true
    git push origin gh-pages
    git checkout "$CURRENT_BRANCH"
    
    echo -e "${GREEN}✓ Deployed to gh-pages${NC}"
else
    echo ""
    echo "To deploy: ./scripts/rebuild-site.sh --deploy"
    echo "To preview locally: python -m http.server -d public 8080"
fi
