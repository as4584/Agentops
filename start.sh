#!/bin/bash
#
# Agentop — One-click launcher
# Double-click this file or run: ./start.sh
#
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Agentop — Local AI Control Center  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

python3 app.py
