#!/usr/bin/env bash
# log_cost.sh — manually log a generation run
# Usage: log_cost --model kling_v1_6_pro --clips 7 --seconds 5 --campaign xpel_ad --notes "first pass"
cd "$(dirname "$0")/.." && source .venv/bin/activate 2>/dev/null
python -m backend.utils.cost_logger "$@"
