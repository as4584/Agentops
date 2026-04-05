# Sandbox

Reference implementations, experimental projects, and temporary scratch files.

## Structure

| Directory | Purpose |
|-----------|---------|
| `everything-claude-code/` | 119-skill library from Claude Code (submodule, gitignored) |
| `ui-ux-pro-max-skill/` | UI/UX Pro Max design intelligence toolkit (submodule, gitignored) |
| `experimental/` | One-off test scripts moved from repo root |
| `scratch/` | Temporary files, outputs, debug artifacts |
| `tmp/` | Transient workspace |

## Notes

- `everything-claude-code/` and `ui-ux-pro-max-skill/` are gitignored submodules
- Skills from these repos are referenced in `backend/skills/` as manifest skills
- Scratch files are not part of the build or test pipeline
