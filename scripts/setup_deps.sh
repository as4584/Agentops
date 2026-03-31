#!/usr/bin/env bash
# scripts/setup_deps.sh — Verify and install Agentop dependencies.
# Run from the project root:  bash scripts/setup_deps.sh
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo "═══════════════════════════════════════════"
echo " Agentop Dependency Setup"
echo "═══════════════════════════════════════════"
echo ""

# ── Python ────────────────────────────────────────────────────────────────────
echo "1. Python environment"
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    ok "Python: $PY_VER"
else
    fail "Python3 not found — install Python 3.11+"
    exit 1
fi

# ── pip dependencies ──────────────────────────────────────────────────────────
echo ""
echo "2. Python packages"
if [ -f requirements.txt ]; then
    pip install -q -r requirements.txt 2>/dev/null && ok "pip install -r requirements.txt" || fail "pip install failed"
else
    warn "requirements.txt not found"
fi

# ── Node.js / npm ─────────────────────────────────────────────────────────────
echo ""
echo "3. Node.js & frontend"
if command -v node &>/dev/null; then
    ok "Node: $(node --version)"
else
    warn "Node.js not found — frontend won't build"
fi

if [ -d frontend ] && [ -f frontend/package.json ]; then
    (cd frontend && npm ci --silent 2>/dev/null) && ok "npm ci (frontend)" || warn "npm ci failed"
else
    warn "frontend/package.json not found"
fi

# ── Ollama ────────────────────────────────────────────────────────────────────
echo ""
echo "4. Ollama (LLM backend)"
if command -v ollama &>/dev/null; then
    ok "Ollama CLI found"
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        ok "Ollama server reachable at :11434"
    else
        warn "Ollama not running — start with: ollama serve"
    fi
else
    warn "Ollama not installed — see https://ollama.com/download"
fi

# ── FFmpeg ────────────────────────────────────────────────────────────────────
echo ""
echo "5. FFmpeg (content pipeline)"
if command -v ffmpeg &>/dev/null; then
    ok "FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    warn "FFmpeg not found — content pipeline video features unavailable"
    echo "       Install: sudo apt install ffmpeg"
fi

# ── Docker ────────────────────────────────────────────────────────────────────
echo ""
echo "6. Docker (MCP bridge)"
if command -v docker &>/dev/null; then
    ok "Docker: $(docker --version 2>&1)"
    if docker info &>/dev/null 2>&1; then
        ok "Docker daemon running"
    else
        warn "Docker daemon not running"
    fi
else
    warn "Docker not installed — MCP tools unavailable"
fi

# ── Ruff ──────────────────────────────────────────────────────────────────────
echo ""
echo "7. Ruff (linter)"
if command -v ruff &>/dev/null; then
    ok "Ruff: $(ruff version 2>&1)"
else
    warn "Ruff not found — install with: pip install ruff"
fi

# ── Mypy ──────────────────────────────────────────────────────────────────────
echo ""
echo "8. Mypy (type checker)"
if command -v mypy &>/dev/null; then
    ok "Mypy: $(mypy --version 2>&1)"
else
    warn "Mypy not found — install with: pip install mypy"
fi

# ── Directory structure ───────────────────────────────────────────────────────
echo ""
echo "9. Data directories"
for dir in data/agents data/training backend/logs backend/memory/webgen_projects; do
    if [ -d "$dir" ]; then
        ok "$dir exists"
    else
        mkdir -p "$dir"
        ok "$dir created"
    fi
done

echo ""
echo "═══════════════════════════════════════════"
echo " Setup complete. Run tests with:"
echo "   python -m pytest backend/tests/ deerflow/tests/ -x --tb=short -q"
echo "═══════════════════════════════════════════"
