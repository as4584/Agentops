#!/usr/bin/env bash
# Build the Agentop sandbox Docker image
# Usage:  bash sandbox/build.sh [tag]
set -euo pipefail

IMAGE="${1:-agentop/sandbox:latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[sandbox] Building image: $IMAGE"
docker build -t "$IMAGE" "$SCRIPT_DIR"
echo "[sandbox] Build complete: $IMAGE"

echo "[sandbox] Verifying image..."
docker run --rm "$IMAGE" bash -c 'echo "sandbox ok: $(python3 --version)"'
echo "[sandbox] Image verified."
