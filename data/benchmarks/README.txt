This directory stores all benchmark output for Agentop model evaluation.

Files created here:
  openrouter_free_models.json          — full free model catalog from OpenRouter API
  openrouter_selected_models.json      — 5 selected models across 3 molds
  openrouter_reference_benchmarks.json — published MMLU/HellaSWAG/ARC scores
  lex_v2_vs_v3_<date>.jsonl            — per-task routing eval: lex-v2 vs lex-v3
  summary.json                         — latest scorecard (accuracy, latency, winner)

Generate with:
  python scripts/fetch_openrouter_models.py
  python scripts/eval_lex.py
