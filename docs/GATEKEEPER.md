# Gatekeeper Agent

The `gatekeeper_agent` is a mutation firewall for lower-reasoning model output.

## Validation Rules
- Reject runtime changes without corresponding tests.
- Reject changes when syntax checks fail.
- Reject changes when secret scan fails.
- Reject changes when Lighthouse quality gate regresses.

## Review Payload Contract
- `files_changed`: list of paths included in mutation
- `syntax_ok`: boolean
- `secrets_ok`: boolean
- `lighthouse_ok`: boolean

## Outcome
- `approved=true` only when all gates pass.
- Rejections include machine-readable violation messages for automatic retry/fix loops.
