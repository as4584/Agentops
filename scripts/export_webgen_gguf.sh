#!/usr/bin/env bash
# export_webgen_gguf.sh
# Convert the lex-webgen-v1 LoRA adapter to a merged GGUF model and register it with Ollama.
#
# Usage:
#   bash scripts/export_webgen_gguf.sh
#   bash scripts/export_webgen_gguf.sh --quant Q4_K_M  # default is Q5_K_M
#
# Dependencies:
#   - llama.cpp (git clone + make → binary at $LLAMA_CPP_DIR/llama-quantize and convert_hf_to_gguf.py)
#   - ollama CLI in PATH
#   - .venv with transformers + peft installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_MODEL="Qwen/Qwen2.5-Coder-3B-Instruct"
ADAPTER_DIR="models/lex-webgen-v1"
MERGED_DIR="models/lex-webgen-v1-merged"
GGUF_DIR="models/lex-webgen-v1-gguf"
GGUF_NAME="lex-webgen-v1.gguf"
QUANT="Q5_K_M"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
OLLAMA_MODEL_TAG="lex-webgen-v1"

# ── Args ───────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quant) QUANT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "======================================================"
echo "  Exporting lex-webgen-v1 → Ollama"
echo "  Adapter: $ADAPTER_DIR"
echo "  Quant:   $QUANT"
echo "======================================================"

# ── 1. Check adapter exists ────────────────────────────────────────────────────
if [[ ! -d "$ADAPTER_DIR" ]]; then
  echo "[ERROR] Adapter directory not found: $ADAPTER_DIR"
  echo "  Run: python scripts/finetune_webgen.py first."
  exit 1
fi

# ── 2. Merge LoRA adapter into base model ──────────────────────────────────────
echo ""
echo "[1/4] Merging LoRA adapter into base model..."
.venv/bin/python3.12 - <<'PYEOF'
import sys, torch
from peft import AutoPeftModelForCausalLM
from transformers import AutoTokenizer

adapter_dir = "models/lex-webgen-v1"
merged_dir  = "models/lex-webgen-v1-merged"

print(f"Loading adapter from: {adapter_dir}")
model = AutoPeftModelForCausalLM.from_pretrained(
    adapter_dir,
    device_map="auto",
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
)
print("Merging weights...")
model = model.merge_and_unload()
model.save_pretrained(merged_dir, safe_serialization=True)

tokenizer = AutoTokenizer.from_pretrained(adapter_dir, trust_remote_code=True)
tokenizer.save_pretrained(merged_dir)
print(f"Merged model saved to: {merged_dir}")
PYEOF

# ── 3. Convert to GGUF ────────────────────────────────────────────────────────
echo ""
echo "[2/4] Converting merged model to GGUF (float16 base)..."
mkdir -p "$GGUF_DIR"

CONVERT_SCRIPT="$LLAMA_CPP_DIR/convert_hf_to_gguf.py"
if [[ ! -f "$CONVERT_SCRIPT" ]]; then
  echo "[ERROR] llama.cpp convert script not found at: $CONVERT_SCRIPT"
  echo "  Clone and build llama.cpp: https://github.com/ggerganov/llama.cpp"
  echo "  Set LLAMA_CPP_DIR env var to point to your llama.cpp directory."
  exit 1
fi

.venv/bin/python3.12 "$CONVERT_SCRIPT" \
  "$MERGED_DIR" \
  --outtype f16 \
  --outfile "$GGUF_DIR/lex-webgen-v1-f16.gguf"

# ── 4. Quantize ───────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Quantizing to $QUANT..."
QUANTIZE_BIN="$LLAMA_CPP_DIR/build/bin/llama-quantize"
if [[ ! -f "$QUANTIZE_BIN" ]]; then
  # Fallback older path
  QUANTIZE_BIN="$LLAMA_CPP_DIR/quantize"
fi

"$QUANTIZE_BIN" \
  "$GGUF_DIR/lex-webgen-v1-f16.gguf" \
  "$GGUF_DIR/$GGUF_NAME" \
  "$QUANT"

echo "GGUF written: $GGUF_DIR/$GGUF_NAME"

# ── 5. Create Ollama Modelfile and register ───────────────────────────────────
echo ""
echo "[4/4] Registering with Ollama as '$OLLAMA_MODEL_TAG'..."

cat > "$GGUF_DIR/Modelfile" <<EOF
FROM ./$GGUF_NAME

PARAMETER temperature 0.4
PARAMETER top_p 0.9
PARAMETER num_ctx 4096

SYSTEM """You are lex-webgen-v1, an expert frontend developer specializing in beautiful, conversion-focused websites. Generate clean, semantic, responsive HTML using Tailwind CSS utility classes. Output ONLY raw HTML code."""
EOF

cd "$GGUF_DIR"
ollama create "$OLLAMA_MODEL_TAG" -f Modelfile
cd "$PROJECT_ROOT"

echo ""
echo "======================================================"
echo "  Done! Model registered as: $OLLAMA_MODEL_TAG"
echo "  Test: ollama run $OLLAMA_MODEL_TAG 'Generate a hero section for a restaurant'"
echo "======================================================"
