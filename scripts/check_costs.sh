#!/usr/bin/env bash
# check_costs.sh — print full cost tracker summary
# Usage: check_costs
cd "$(dirname "$0")/.." && source .venv/bin/activate 2>/dev/null
python -m backend.utils.cost_logger --summary
