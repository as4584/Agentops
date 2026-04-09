#!/usr/bin/env bash
# Kills any running Agentop processes (backend, Next.js, Electron) and relaunches everything.
# Usage: bash scripts/relaunch.sh
#
# Port strategy: always use port_guard to kill/serve the backend.
# Never use pkill/fuser against uvicorn — it bypasses the port reservation state.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Stopping backend (port_guard) ==="
cd "$ROOT"
python -m backend.port_guard kill 8000 && echo "  Backend stopped" || echo "  Backend was not running"

echo "=== Stopping Next.js ==="
# fuser is safe here — Next.js is not managed by port_guard
fuser -k 3007/tcp 2>/dev/null && echo "  Killed port 3007" || echo "  Port 3007 clear"

echo "=== Stopping Electron ==="
pkill -f "electron.*agentop" 2>/dev/null && echo "  Killed Electron" || echo "  No Electron running"

# Grace period for ports to free
sleep 1

echo "=== Starting backend (port_guard, loopback-only) ==="
cd "$ROOT"
python -m backend.port_guard serve backend.server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "  Backend PID=$BACKEND_PID"

echo "=== Launching frontend ==="
cd "$ROOT/frontend"
exec npm run electron:dev
