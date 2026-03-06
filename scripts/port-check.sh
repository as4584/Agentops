#!/bin/bash
# Agentop Port Check Script
# Run before starting services to diagnose potential conflicts

set -e

echo "=========================================="
echo "Agentop Port Conflict Checker"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if a port is in use
check_port() {
    local port=$1
    local name=$2
    
    if lsof -Pi :"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${RED}✗${NC} Port $port ($name) is IN USE"
        local pid
        pid=$(lsof -ti :"$port" | head -1)
        local cmd
        cmd=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        echo "    └─ PID: $pid ($cmd)"
        return 1
    else
        echo -e "${GREEN}✓${NC} Port $port ($name) is available"
        return 0
    fi
}

# Check critical ports
echo "Checking critical ports..."
echo ""

CRITICAL_OK=true
check_port 3000 "Next.js Dashboard" || CRITICAL_OK=false
check_port 8000 "FastAPI Backend" || CRITICAL_OK=false

# Ollama behavior: expected to be running on 11434
if lsof -Pi :11434 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Port 11434 (Ollama LLM) is active"
else
    echo -e "${YELLOW}⚠${NC} Port 11434 (Ollama LLM) is not active"
    echo "    └─ Start with: ollama serve"
fi

echo ""
echo "=========================================="

if [ "$CRITICAL_OK" = true ]; then
    echo -e "${GREEN}All critical ports are available!${NC}"
    echo ""
    echo "You can start services with:"
    echo "  Terminal 1: cd frontend && npm run dev"
    echo "  Terminal 2: python -m backend.port_guard serve backend.server:app --port 8000"
    exit 0
else
    echo -e "${RED}Port conflicts detected!${NC}"
    echo ""
    echo "To resolve:"
    echo "  1. Check running processes: python -m backend.port_guard status"
    echo "  2. Kill conflicting process: python -m backend.port_guard kill <port>"
    echo "  3. Or use alternate port: python -m backend.port_guard serve backend.server:app --port 8765"
    exit 1
fi
