#!/bin/bash
# Start local mode (uses local state from repo)
# Usage: ./docker-local.sh [--build]

echo "🛑 Stopping existing containers..."
docker compose --profile git-sync down 2>/dev/null
docker compose down 2>/dev/null

if [ "$1" = "--build" ] || [ "$1" = "-b" ]; then
  echo "🔨 Rebuilding image..."
  docker compose build --no-cache orchestrator
fi

echo "🚀 Starting local mode..."
docker compose up -d
echo ""
echo "✅ Local mode started"
echo "   → Uses ./state/current.json from your repo"
echo "   → Site at http://localhost:8080"
echo ""
echo "Tips:"
echo "  --build  Rebuild image if stale"
echo "  Stop:    docker compose down"
