#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  scripts/train_lex.sh — Master Lex Fine-Tuning Pipeline
# ═══════════════════════════════════════════════════════════════════
#
#  End-to-end pipeline:
#    1. Generate training data (router, tool selection, personal)
#    2. Run SFT fine-tuning (QLoRA) + DPO alignment
#    3. Export to GGUF → Ollama Modelfile
#    4. Import into Ollama
#    5. Run router eval suite
#    6. Log results to PROGRESS.md
#
#  Usage:
#    ./scripts/train_lex.sh              # Full pipeline
#    ./scripts/train_lex.sh --data-only  # Generate data only (no GPU)
#    ./scripts/train_lex.sh --eval-only  # Eval existing model only
#    ./scripts/train_lex.sh --baseline   # Create baseline lex from llama3.2
#
#  Prerequisites:
#    - Ollama running (localhost:11434) with llama3.2 pulled
#    - Python venv activated with requirements.txt installed
#    - For training: GPU + unsloth/trl installed
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[LEX]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }

MODE="${1:---full}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")

# ──────────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────────

log "═══ Lex Training Pipeline ═══"
log "Mode: $MODE"
log "Timestamp: $TIMESTAMP"

# Check Ollama
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    err "Ollama not running. Start with: ollama serve"
    exit 1
fi
ok "Ollama is running"

# Check Python
if ! python -c "import backend.config" 2>/dev/null; then
    err "Backend not importable. Activate venv and install requirements."
    exit 1
fi
ok "Python environment ready"

# ──────────────────────────────────────────────────────────────────
# Baseline mode: create lex from llama3.2 + system prompt
# ──────────────────────────────────────────────────────────────────

if [ "$MODE" = "--baseline" ]; then
    log "Creating baseline Lex model from llama3.2..."
    MODELFILE="$ROOT/backend/ml/models/Modelfile.lex-baseline"
    if [ ! -f "$MODELFILE" ]; then
        err "Modelfile not found: $MODELFILE"
        exit 1
    fi
    ollama create lex -f "$MODELFILE"
    ok "Baseline 'lex' model created. Test with: ollama run lex"

    log "Running quick eval on baseline..."
    python scripts/eval_lex_router.py --model lex --quick --report --verbose || true
    exit 0
fi

# ──────────────────────────────────────────────────────────────────
# Eval-only mode
# ──────────────────────────────────────────────────────────────────

if [ "$MODE" = "--eval-only" ]; then
    log "Running full eval suite on Lex..."
    python scripts/eval_lex_router.py --model lex --report --verbose
    exit $?
fi

# ──────────────────────────────────────────────────────────────────
# Stage 1: Generate training data
# ──────────────────────────────────────────────────────────────────

log ""
log "═══ Stage 1: Training Data Generation ═══"

# Router pairs (~200 hardcoded seeds)
log "Generating router training pairs..."
python scripts/build_router_pairs.py
ok "Router pairs generated"

# Tool selection pairs
log "Generating tool selection pairs..."
python scripts/build_tool_selection_pairs.py
ok "Tool selection pairs generated"

# Personal preference pairs
log "Generating personal preference pairs..."
python scripts/build_personal_pairs.py
ok "Personal preference pairs generated"

# DPO pairs
log "Generating DPO pairs..."
python scripts/build_dpo_pairs.py
ok "DPO pairs generated"

# Count total data
SFT_COUNT=$(cat data/training/*.jsonl 2>/dev/null | wc -l)
DPO_COUNT=$(cat data/dpo/*.jsonl 2>/dev/null | wc -l)
log "Total SFT records: $SFT_COUNT"
log "Total DPO pairs: $DPO_COUNT"

if [ "$MODE" = "--data-only" ]; then
    ok "Data generation complete. Run with --full for training."
    exit 0
fi

# ──────────────────────────────────────────────────────────────────
# Stage 2: Fine-tuning
# ──────────────────────────────────────────────────────────────────

log ""
log "═══ Stage 2: Fine-tuning ═══"

# Check GPU availability
if python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
    GPU_NAME=$(python -c "import torch; print(torch.cuda.get_device_name(0))")
    GPU_VRAM=$(python -c "import torch; print(f'{torch.cuda.get_device_properties(0).total_mem/1024**3:.1f}GB')")
    ok "GPU detected: $GPU_NAME ($GPU_VRAM)"
else
    warn "No GPU detected. Running data prep only."
    python scripts/finetune_lex.py --prep-only
    warn "Transfer output/lex-finetune/ to a GPU machine to continue."
    exit 0
fi

# Check Unsloth
if ! python -c "import unsloth" 2>/dev/null; then
    err "Unsloth not installed. Install with:"
    err "  pip install 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'"
    exit 1
fi
ok "Unsloth available"

# Run full pipeline: SFT + DPO + GGUF export + Ollama import
python scripts/finetune_lex.py
ok "Fine-tuning complete"

# ──────────────────────────────────────────────────────────────────
# Stage 3: Evaluation
# ──────────────────────────────────────────────────────────────────

log ""
log "═══ Stage 3: Evaluation ═══"

# Run full eval suite
python scripts/eval_lex_router.py --model lex --report --verbose

# Compare with baseline if llama3.2 is available
if ollama list | grep -q "llama3.2"; then
    log "Running comparison eval on llama3.2..."
    python scripts/eval_lex_router.py --model llama3.2 --report || true
fi

# ──────────────────────────────────────────────────────────────────
# Stage 4: Log to PROGRESS.md
# ──────────────────────────────────────────────────────────────────

log ""
log "═══ Stage 4: Logging ═══"

PROGRESS_ENTRY="
### Lex Training Run — $TIMESTAMP
- **SFT data**: $SFT_COUNT conversations
- **DPO data**: $DPO_COUNT pairs
- **Pipeline**: data gen → SFT (QLoRA) → DPO → GGUF → Ollama
- **Status**: Complete
"

if [ -f PROGRESS.md ]; then
    echo "$PROGRESS_ENTRY" >> PROGRESS.md
    ok "Logged to PROGRESS.md"
fi

# ──────────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────────

log ""
ok "═══ Lex Training Pipeline Complete ═══"
log "Test your model: ollama run lex"
log "Eval report: reports/lex_router_eval_*.json"
log "Experiment history: backend/ml/experiments/"
