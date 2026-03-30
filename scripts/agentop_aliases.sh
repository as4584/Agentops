#!/usr/bin/env bash
# agentop_aliases.sh
# Source this file once to get short terminal commands for the Agentop workspace.
#
# Add this to your ~/.bashrc or ~/.zshrc:
#   source /root/studio/testing/Agentop/scripts/agentop_aliases.sh
#
# Or run once in any terminal session:
#   source /root/studio/testing/Agentop/scripts/agentop_aliases.sh

AGENTOP_ROOT="/root/studio/testing/Agentop"

# ── Cost tracking ──────────────────────────────────────────────────────────────

# check token usage / check costs — print full cost summary
# Bash doesn't support spaces in alias names, so two options are provided:
#   check_token_usage   (type this)
#   check-costs         (type this)
check_token_usage() {
  bash "$AGENTOP_ROOT/scripts/check_costs.sh"
}
alias check-costs="bash $AGENTOP_ROOT/scripts/check_costs.sh"
alias ccu="bash $AGENTOP_ROOT/scripts/check_costs.sh"   # shortest version

# log-cost — manually log a generation run
# Example: log-cost --model kling_v2_master --clips 5 --seconds 6 --campaign xpel_ad
alias log-cost="bash $AGENTOP_ROOT/scripts/log_cost.sh"

# ── Quick activations ──────────────────────────────────────────────────────────

# activate the project venv from anywhere
alias agentop="cd $AGENTOP_ROOT && source .venv/bin/activate"

echo "Agentop aliases loaded. Commands available:"
echo "  check_token_usage   — full cost summary (function)"
echo "  check-costs         — same, alias"
echo "  ccu                 — same, shortest"
echo "  log-cost [args]     — manual cost log entry"
echo "  agentop             — cd to project + activate venv"
