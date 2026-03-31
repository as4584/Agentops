#!/bin/bash
#
# Agentop — One-click launcher
# Double-click this file or run: ./start.sh
#
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
cd "$ROOT"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Agentop — Local AI Control Center  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

cleanup() {
    echo "  → Shutting down Agentop..."
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    [ -n "$NEXT_PID" ] && kill "$NEXT_PID" 2>/dev/null
    exit 0
}
trap cleanup EXIT INT TERM

# Activate virtual environment if it exists
if [ -f "$ROOT/.venv/bin/activate" ]; then
    echo "  → Activating virtual environment..."
    source "$ROOT/.venv/bin/activate"
fi

# 1) Start FastAPI backend
echo "  → Starting backend (port 8000)..."
python3 app.py &
BACKEND_PID=$!

# 2) Start Next.js frontend
echo "  → Starting frontend (port 3007)..."
cd "$ROOT/frontend"
npx next start -p 3007 &
NEXT_PID=$!
cd "$ROOT"

# 3) Wait for frontend to be ready, then launch Electron
echo "  → Waiting for frontend..."
npx --prefix "$ROOT/frontend" wait-on http://localhost:3007 --timeout 60000 2>/dev/null || true
sleep 1

echo "  → Launching Electron window..."
cd "$ROOT/frontend"
npx electron . --no-sandbox --disable-gpu

# When Electron closes, cleanup fires via trap
