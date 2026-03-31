#!/usr/bin/env bash
# scripts/run_ml_training.sh
# ──────────────────────────────────────────────────────────────────────────────
# Master pipeline: collect training pairs from all 8 strategies and report
# totals. Works 100% offline — no API key needed (uses --raw mode by default).
#
# Usage:
#   ./scripts/run_ml_training.sh               # raw mode (instant, offline)
#   ./scripts/run_ml_training.sh --ollama      # Ollama enhancement pass
#   ./scripts/run_ml_training.sh --show-sample # print 2 random pairs at end
#
# Output:  data/training/combined_<timestamp>.jsonl

set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/data/training"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMBINED="$OUT_DIR/combined_$TIMESTAMP.jsonl"
USE_OLLAMA=false
SHOW_SAMPLE=false

for arg in "$@"; do
  case $arg in
    --ollama)     USE_OLLAMA=true ;;
    --show-sample) SHOW_SAMPLE=true ;;
  esac
done

# ── terminal colors ───────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

section() { echo -e "\n${BLUE}${BOLD}▶ $1${RESET}"; }
ok()      { echo -e "${GREEN}✓ $1${RESET}"; }
info()    { echo -e "${YELLOW}  $1${RESET}"; }

echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         Agentop ML Training Data Pipeline                ║${RESET}"
echo -e "${BOLD}║         $(date '+%Y-%m-%d %H:%M')   $([ "$USE_OLLAMA" = true ] && echo "MODE: ollama" || echo "MODE: raw (offline)")           ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"

cd "$ROOT_DIR"

# ── activate venv if present ──────────────────────────────────────────────────
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  info "venv activated"
fi

mkdir -p "$OUT_DIR"

# ── helper: count lines in a file ────────────────────────────────────────────
count() { [[ -f "$1" ]] && wc -l < "$1" || echo 0; }

# ── Strategy 1: Architecture Q&A (21 hardcoded pairs, instant) ───────────────
section "Strategy 1/8 — Architecture pairs (hardcoded Agentop Q&A)"
python scripts/build_architecture_pairs.py
ok "Architecture pairs complete"

# ── Strategy 2: IBDS spec → implementation pairs ────────────────────────────
section "Strategy 2/8 — IBDS component spec pairs (34 specs)"
python scripts/build_spec_pairs.py --raw
ok "Spec pairs complete"

# ── Strategy 3: Git commit history pairs ────────────────────────────────────
section "Strategy 3/8 — Git diff pairs (last 50 commits)"
python scripts/build_git_pairs.py --raw --limit 50
ok "Git pairs complete"

# ── Strategy 4: Pytest failure pairs ────────────────────────────────────────
section "Strategy 4/8 — Pytest failure pairs"
python scripts/build_pytest_pairs.py --raw || {
  info "Pytest step skipped (no failures or import error)"
}

# ── Strategy 5: Code review pairs ───────────────────────────────────────────
section "Strategy 5/8 — Code review pairs (AST smell detection)"
python scripts/build_review_pairs.py --raw
ok "Review pairs complete"

# ── Strategy 6: 3D web seed pairs ───────────────────────────────────────────
section "Strategy 6/8 — 3D web seed pairs (curated Three.js/GSAP/CSS)"
python scripts/synthesize_training_data.py --domain 3d-web --seeds-only
ok "3D web seeds complete"

# ── Strategy 7: Agentop codebase synthesis (Ollama or skip) ─────────────────
if [[ "$USE_OLLAMA" == true ]]; then
  section "Strategy 7/8 — Agentop backend synthesis via Ollama"
  python scripts/synthesize_training_data.py \
    --domain agentop \
    --backend ollama \
    --budget 50
  ok "Agentop synthesis complete"
else
  info "Strategy 7 (Agentop synthesis) skipped — run with --ollama to enable"
fi

# ── Strategy 8: IBDS synthesis (Ollama or skip) ──────────────────────────────
if [[ "$USE_OLLAMA" == true ]]; then
  section "Strategy 8/8 — IBDS synthesis via Ollama"
  python scripts/synthesize_training_data.py \
    --domain ibds \
    --backend ollama \
    --budget 30
  ok "IBDS synthesis complete"
else
  info "Strategy 8 (IBDS synthesis) skipped — run with --ollama to enable"
fi

# ── Combine all ──────────────────────────────────────────────────────────────
section "Combining all pairs → $COMBINED"
cat "$OUT_DIR"/*.jsonl > "$COMBINED"
TOTAL=$(count "$COMBINED")

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║                  COLLECTION SUMMARY                     ║${RESET}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
for f in "$OUT_DIR"/*.jsonl; do
  fname=$(basename "$f")
  n=$(count "$f")
  printf "${BOLD}║${RESET} %-42s %6s pairs ${BOLD}║${RESET}\n" "$fname" "$n"
done
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}║  TOTAL PAIRS: $TOTAL$(printf '%*s' $((41 - ${#TOTAL})) '')   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"

if [[ "$SHOW_SAMPLE" == "true" ]] && [[ "$TOTAL" -gt 0 ]]; then
  echo ""
  echo -e "${BOLD}Sample pair from combined dataset:${RESET}"
  python3 -c "
import json, random, sys
lines = open('$COMBINED').readlines()
rec = json.loads(random.choice(lines))
turns = rec['conversations']
print('  HUMAN:', turns[0]['value'][:200], '...' if len(turns[0]['value']) > 200 else '')
print('  GPT  :', turns[1]['value'][:300], '...' if len(turns[1]['value']) > 300 else '')
"
fi

echo ""
echo -e "${GREEN}${BOLD}Pipeline complete!${RESET}"
echo -e "Combined dataset: ${BOLD}$COMBINED${RESET}"
echo ""
echo "Next steps:"
echo "  1. Review sample pairs:  python scripts/build_architecture_pairs.py && head -1 $COMBINED | python3 -m json.tool"
echo "  2. Grow with Ollama:     ./scripts/run_ml_training.sh --ollama"
echo "  3. Fine-tune:            See docs/ML_TRAINING_PLAN.md for Unsloth commands"
