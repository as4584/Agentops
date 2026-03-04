# TDD Guide

- Every runtime code mutation must include test updates in `frontend/tests/` or `backend/tests/`.
- Gatekeeper rejects mutations that touch runtime code without tests.
- Playwright and LHCI checks are blocking quality gates in CI.
- Sandbox promotion only occurs after Lighthouse thresholds are met.
- Use `scripts/hooks/pre-commit` as your local commit gate (`cp scripts/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`).
