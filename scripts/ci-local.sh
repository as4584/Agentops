#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# ci-local.sh — Run the exact same checks as GitHub Actions CI Gate
# ──────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/ci-local.sh          # run all checks
#   ./scripts/ci-local.sh python   # run only python checks
#   ./scripts/ci-local.sh frontend # run only frontend checks
#   ./scripts/ci-local.sh quick    # skip pip-audit + npm audit (faster)
#
# Exit codes: 0 = all green, 1 = failure (stops on first failing step)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-all}"
PASSED=0
FAILED=0
SKIPPED=0

step() {
  echo -e "\n${CYAN}━━━ $1 ━━━${NC}"
}

pass() {
  echo -e "${GREEN}✓ $1${NC}"
  ((PASSED++))
}

fail() {
  echo -e "${RED}✗ $1${NC}"
  ((FAILED++))
}

skip() {
  echo -e "${YELLOW}⊘ $1 (skipped)${NC}"
  ((SKIPPED++))
}

# ── Python checks ─────────────────────────────────────────────────────
run_python() {
  step "Ruff — lint"
  if ruff check .; then pass "ruff check"; else fail "ruff check"; return 1; fi

  step "Ruff — format check"
  if ruff format --check .; then pass "ruff format"; else fail "ruff format"; return 1; fi

  step "Mypy — type check"
  if mypy backend/ deerflow/ --ignore-missing-imports; then pass "mypy"; else fail "mypy"; return 1; fi

  step "Pytest + coverage (≥58% required)"
  if pytest backend/tests/ deerflow/tests/ \
    --ignore=backend/tests/test_scheduler_routes.py \
    -o "addopts=" \
    -x --tb=short -q \
    --cov=backend --cov=deerflow \
    --cov-report=term-missing \
    --cov-fail-under=58; then
    pass "pytest"
  else
    fail "pytest"; return 1
  fi

  if [[ "$MODE" != "quick" ]]; then
    step "pip-audit — CVE scan"
    if pip install --upgrade pip --quiet 2>/dev/null && \
       pip install pip-audit --quiet 2>/dev/null && \
       pip-audit --skip-editable; then
      pass "pip-audit"
    else
      fail "pip-audit"; return 1
    fi
  else
    skip "pip-audit"
  fi
}

# ── Frontend checks ───────────────────────────────────────────────────
run_frontend() {
  if [[ ! -d frontend ]]; then
    skip "frontend (no frontend/ directory)"
    return 0
  fi

  pushd frontend > /dev/null

  if [[ "$MODE" != "quick" ]]; then
    step "npm audit — CVE scan"
    if npm audit --audit-level=critical --production 2>/dev/null; then
      pass "npm audit"
    else
      fail "npm audit"; popd > /dev/null; return 1
    fi
  else
    skip "npm audit"
  fi

  step "ESLint"
  if npm run lint; then pass "eslint"; else fail "eslint"; popd > /dev/null; return 1; fi

  step "TypeScript — type check"
  if npx tsc --noEmit; then pass "tsc"; else fail "tsc"; popd > /dev/null; return 1; fi

  step "Next.js — build"
  if npm run build; then pass "next build"; else fail "next build"; popd > /dev/null; return 1; fi

  popd > /dev/null
}

# ── Secret scan ───────────────────────────────────────────────────────
run_secrets() {
  step "detect-secrets scan"
  if command -v detect-secrets &>/dev/null; then
    if detect-secrets scan \
      --exclude-files '\.env\.example$' \
      --exclude-files '\.actrc$' \
      --baseline .secrets.baseline 2>/dev/null; then
      pass "detect-secrets"
    else
      fail "detect-secrets"; return 1
    fi
  else
    skip "detect-secrets (not installed)"
  fi
}

# ── ML Pipeline (mirrors ml-pipeline.yml) ─────────────────────────────
run_ml() {
  step "ML tests + coverage (≥80% required)"
  if pytest backend/tests/test_ml_*.py \
    -o "addopts=" \
    -x --tb=short -q \
    --cov=backend/ml \
    --cov-report=term-missing \
    --cov-fail-under=80; then
    pass "ml tests"
  else
    fail "ml tests"; return 1
  fi
}

# ── Dispatch ──────────────────────────────────────────────────────────
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Agentop Local CI — mode: ${MODE}$(printf '%*s' $((10 - ${#MODE})) '')║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"

EXIT=0

case "$MODE" in
  python)
    run_python || EXIT=1
    ;;
  frontend)
    run_frontend || EXIT=1
    ;;
  ml)
    run_ml || EXIT=1
    ;;
  secrets)
    run_secrets || EXIT=1
    ;;
  quick)
    run_python || EXIT=1
    if [[ $EXIT -eq 0 ]]; then run_frontend || EXIT=1; fi
    ;;
  all)
    run_python || EXIT=1
    if [[ $EXIT -eq 0 ]]; then run_frontend || EXIT=1; fi
    if [[ $EXIT -eq 0 ]]; then run_secrets || EXIT=1; fi
    if [[ $EXIT -eq 0 ]]; then run_ml || EXIT=1; fi
    ;;
  *)
    echo "Usage: $0 [all|python|frontend|ml|secrets|quick]"
    exit 1
    ;;
esac

# ── Summary ───────────────────────────────────────────────────────────
echo -e "\n${CYAN}━━━ Summary ━━━${NC}"
echo -e "  ${GREEN}Passed:  ${PASSED}${NC}"
[[ $SKIPPED -gt 0 ]] && echo -e "  ${YELLOW}Skipped: ${SKIPPED}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  ${RED}Failed:  ${FAILED}${NC}"

if [[ $EXIT -eq 0 ]]; then
  echo -e "\n${GREEN}▶ All checks passed — safe to push${NC}"
else
  echo -e "\n${RED}▶ CI would fail — fix issues before pushing${NC}"
fi

exit $EXIT
