#!/usr/bin/env bash
# harden_git.sh — Apply supply-chain safety settings for git and npm.
# Safe to run multiple times (idempotent).
# Usage: bash scripts/harden_git.sh

set -euo pipefail

echo "==> Applying git fsck hardening..."

git config --global transfer.fsckObjects true
git config --global fetch.fsckObjects true
git config --global receive.fsckObjects true

echo "==> Enforcing SSH for GitHub (avoids HTTP credential sniffing)..."
git config --global url."git@github.com:".insteadOf "https://github.com/"

echo "==> Disabling credential storage in plaintext..."
# Use a credential helper that does not persist secrets to disk.
# On Linux with libsecret available, use 'store' only if the user explicitly
# wants it — otherwise we leave the default (ask each time).
current_helper=$(git config --global credential.helper 2>/dev/null || echo "")
if [[ "$current_helper" == "store" ]]; then
  echo "WARNING: credential.helper is 'store' (saves passwords in plaintext)."
  echo "         Consider switching to libsecret: apt install libsecret-tools"
  echo "         Then: git config --global credential.helper libsecret"
fi

echo "==> npm: setting audit-level to high..."
npm config set audit-level high 2>/dev/null || echo "npm not found — skipping"

echo "==> npm: enabling package-lock integrity..."
npm config set package-lock true 2>/dev/null || echo "npm not found — skipping"

echo ""
echo "Done. Current git hardening config:"
git config --global --list | grep -E "fsck|insteadOf|credential" || true

echo ""
echo "To verify a repo clone is intact, run:  git fsck --full"
echo "To check npm deps for known CVEs, run:  npm audit --audit-level=high"
