#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install-hooks.sh — installs Agentop git hooks for the current clone
#
# Usage:
#   bash scripts/install-hooks.sh
#
# What it does:
#   • Symlinks scripts/hooks/pre-push  →  .git/hooks/pre-push
#   • Makes the hook executable
#   • Verifies act is installed; prints first-run instructions if not
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

echo ""
echo "Installing Agentop git hooks..."
echo ""

# ── pre-push ─────────────────────────────────────────────────────────────────
mkdir -p "$HOOKS_DST"
ln -sf "$HOOKS_SRC/pre-push" "$HOOKS_DST/pre-push"
chmod +x "$HOOKS_SRC/pre-push"
echo "  ✓ pre-push  →  .git/hooks/pre-push"

# ── Check act is available ───────────────────────────────────────────────────
echo ""
if command -v act &>/dev/null; then
    echo "  ✓ act $(act --version 2>/dev/null | head -1) found"
    echo ""
    echo "  Pull the runner image once (only needed on first install):"
    echo "    act push -W .github/workflows/ci.yml --pull"
else
    echo "  ⚠  'act' is not installed — hook will block all pushes until it is."
    echo ""
    echo "  Install act:"
    echo "    curl -s https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash"
    echo ""
    echo "  Then pull the runner image:"
    echo "    act push -W .github/workflows/ci.yml --pull"
fi

echo ""
echo "Done. Every 'git push' will now run the CI gate locally via act."
echo "To bypass in an emergency: git push --no-verify"
echo ""
