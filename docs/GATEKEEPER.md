# Gatekeeper Agent

The `gatekeeper_agent` is a mutation firewall for lower-reasoning model output.

## Validation Rules
- Reject runtime changes without corresponding tests.
- Reject changes when syntax checks fail.
- Reject changes when secret scan fails.
- Reject changes when Lighthouse quality gate regresses.
- Reject local-model releases that are not staged in sandbox/playbox.
- Require 3 release checks for local-model output: `tests_ok`, `playwright_ok`, `lighthouse_mobile_ok`.

## Local LLM Enforcement Flow
1. Generate files into sandbox workspace (`/tmp/ai-sandbox/session-*/workspace`).
2. Stage files into playbox (`playground/local-llm/<session>/staged`) via `/sandbox/{session_id}/stage`.
3. Release files via `/sandbox/{session_id}/release`.
4. Release is blocked unless all required checks pass and Gatekeeper approves.

## Review Payload Contract
- `files_changed`: list of paths included in mutation
- `syntax_ok`: boolean
- `secrets_ok`: boolean
- `lighthouse_ok`: boolean
- `source_model`: model name (`local`, `ollama`, etc.)
- `sandbox_session_id`: required for local-model releases
- `staged_in_playbox`: required `true` for local-model releases
- `tests_ok`, `playwright_ok`, `lighthouse_mobile_ok`: required `true` for local-model releases

## Outcome
- `approved=true` only when all gates pass.
- Rejections include machine-readable violation messages for automatic retry/fix loops.
