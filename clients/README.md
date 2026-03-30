# clients/

Standalone client campaign and brand projects. Each subdirectory is a
self-contained production project with its own scenes, scripts, assets,
and output — fully isolated from the Agentop platform code.

## Contents

| Folder | Brand | Status |
|---|---|---|
| `probodyforlife/` | ProBodyForLife — XPEL supplement ad campaign | Active |
| `ibds/` | IBDS Innovation — archived brand assets | Archived |

## Rules

- **No platform imports.** Client folders must not import from `backend/`.
  They are consumers of the platform output, not extensions of it.
- **Own output directory.** Each project writes to `<project>/output/`, never
  to the top-level `output/` (which belongs to Agentop platform).
- **Own docs.** Governance and policy docs (e.g. `SYSTEM_POLICY.md`) live
  inside the project folder.

## Adding a new client project

1. Create `clients/<brand-slug>/`
2. Add a `README.md` inside it explaining the brand, campaign scope, and
   asset conventions
3. Add a `SYSTEM_POLICY.md` for any brand-specific content rules
