#!/usr/bin/env bash
# start_higgsfield_mcp.sh — Start the Higgsfield Playwright MCP server
# Usage: ./scripts/start_higgsfield_mcp.sh [--headless]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# Activate venv
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

# Parse flags
HEADLESS=false
for arg in "$@"; do
    case "$arg" in
        --headless) HEADLESS=true ;;
    esac
done

echo "=== Higgsfield MCP Server ==="
echo "Port:     8812"
echo "Headless: $HEADLESS"
echo "Cookies:  data/higgsfield/.session_cookies.json"
echo ""

# Check Playwright is installed
if ! python -c "import playwright" 2>/dev/null; then
    echo "Installing Playwright..."
    pip install playwright
    playwright install chromium
fi

export HIGGSFIELD_HEADLESS="$HEADLESS"
export HF_MCP_PORT=8812

echo "Starting server..."
python -m backend.mcp.higgsfield_playwright_server
