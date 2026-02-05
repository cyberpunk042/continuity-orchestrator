#!/bin/bash
# Start git-sync mode (clones from GitHub, pushes changes back)
# Usage: ./docker-sync.sh [--build]

echo "🛑 Stopping existing containers..."
docker compose down 2>/dev/null
docker compose --profile git-sync down -v 2>/dev/null

if [ "$1" = "--build" ] || [ "$1" = "-b" ]; then
  echo "🔨 Rebuilding image..."
  docker compose build --no-cache orchestrator-git-sync
fi

echo "🚀 Starting git-sync mode..."
docker compose --profile git-sync up -d
echo ""
echo "✅ Git-sync mode started"
echo "   → Clones repo from GitHub"
echo "   → Pulls real state, pushes changes back"
echo "   → Site at http://localhost:8080"
echo ""
echo "Tips:"
echo "  --build  Rebuild image if stale"
echo "  Stop:    docker compose --profile git-sync down"
