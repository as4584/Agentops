# Git Commit Message Template for Agentop

Use this structure for every commit to `dev`. This ensures your commit history tells a story and feeds into [PROGRESS.md](../PROGRESS.md).

## Format (Conventional Commits + Metrics)

```
<type>(<scope>): <subject>

<body>

<footer>
```

## Examples (Real World)

### Feature with Performance Impact
```
feat(ml): TurboQuant Rust skill port with 30x speedup

- Port TurboQuant quantizer from Python to Rust via ndarray + PyO3
- Quantize 1000 embeddings (dim=384): Python 3s → Rust 100ms
- Add contract tests: JSON schema validation across Python/Rust boundary
- Benchmark: latency graph in docs/benchmarks/turbo-quant.md

Benchmark:
- Python baseline: 100ms/embedding
- Rust optimized: 3ms/embedding (33x faster)
- CI time saved: ~6.3 min/run (200 test → 10s)

Closes #42
```

### Fix with Loss Documentation
```
fix(cors): add strict CORS origin validation at startup

Previously ignored invalid origins (wildcards, paths, query strings).
Now validates all origins against RFC 3986 and raises ValueError immediately
on startup if config is invalid.

Before: Silent failures at runtime when CORS check fails
After: Fail-fast with clear error message during boot

This closes a security gap discovered during manual testing.
```

### Test Coverage Improvement
```
test(ml): add 8 integration tests for ML pipeline — coverage 97%

- test_qdrant_vector_search: 10K vectors, 5 queries, <10ms latency
- test_turbo_quant_quantization: round-trip precision < 0.1%
- test_ml_benchmark_a_b: 100 iterations, confidence intervals
- test_embedding_batch_ops: concurrent batch quantization

Coverage growth: 51% → 97% (ML module)
All tests pass under pytest + CI.
```

### Loss/Incident Log
```
fix(security): remove exposed social media tokens from cache

The file `backend/memory/social_media/tiktok_tokens.json` contained
real API credentials that were committed to git. This was discovered
during routine secrets scan.

Actions taken:
- Removed file from git history (BFG)
- Added .gitignore rule for *.tokens.json
- Created secrets migration script (scripts/migrate_secrets_to_doppler.py)
- Added pre-commit hook to scan for common secret patterns

Loss impact: Brief exposure window (28 days). Tokens rotated.
Prevention: Automated secret scanning now enabled in CI.
```

## Key Fields for Career Fair Storytelling

Always include in commit body if applicable:

| Field | Example | Why |
|---|---|---|
| **Old vs New metric** | "Python 3s → Rust 100ms" | Shows impact |
| **Scope (lines affected)** | "200 lines → 150 lines Rust" | Shows efficiency |
| **Test count** | "8 integration tests added" | Shows rigor |
| **Coverage change** | "51% → 97%" | Shows progress |
| **Latency/throughput** | "<10ms search, 8x compression" | Quantifiable wins |
| **Honest loss** | "Tokens exposed 28 days, now rotated" | Shows integrity |

## Workflow (For Every Merge to `dev`)

1. **Complete the feature/fix**
2. **Write the commit message** using template above
3. **Update [PROGRESS.md](../PROGRESS.md)** with one-liner:
   ```markdown
   - **Date** — Short headline: metric A → B
   ```
4. **Run the analyzer** to validate:
   ```bash
   python scripts/analyze_git_growth.py
   ```
5. **Merge to dev** via PR (CI must pass)
6. **Celebrate** (this is your career fair story!)

## For Career Fair (60-second version)

Pick your top 5 commits:
```
- "Added TurboQuant quantizer: embeddings 8x smaller, <0.1% loss"
- "Ported to Rust: 30-50x speedup on quantization"
- "Built ML pipeline: Qdrant search <10ms, A/B testing framework"
- "Hardened CI: 97% test coverage, zero production incidents"
- "Secured codebase: automated secret scanning + rotation"
```

**Show the numbers.** Interviewers remember metrics, not features.
