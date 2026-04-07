#!/usr/bin/env bash
# Kills any running Agentop processes (backend, Next.js, Electron) and relaunches everything.
# Usage: bash scripts/relaunch.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Killing old processes ==="
fuser -k 8000/tcp 2>/dev/null && echo "  Killed port 8000" || echo "  Port 8000 clear"
fuser -k 3007/tcp 2>/dev/null && echo "  Killed port 3007" || echo "  Port 3007 clear"
pkill -f "electron.*agentop" 2>/dev/null && echo "  Killed Electron" || echo "  No Electron running"

# Small grace period for ports to free
sleep 0.5

echo "=== Launching Agentop ==="
cd "$ROOT/frontend"
exec npm run electron:dev
