# cli/

Developer-facing command-line interfaces for the two main Agentop platform
pipelines. Always run from the **project root**, not from inside this folder.

## Tools

| Script | Pipeline | Purpose |
|---|---|---|
| `content_cli.py` | Content Creation | Run, approve, or reject content pipeline jobs |
| `webgen_cli.py` | Website Generation | Generate sites, manage templates, browse projects |

## Usage

```bash
# Always run from the project root:
python cli/content_cli.py --help
python cli/webgen_cli.py --help

# Examples
python cli/content_cli.py run --tests-ok --playwright-ok --lighthouse-mobile-ok
python cli/webgen_cli.py generate --name "Acme Corp" --type restaurant
```

> **Important:** Both scripts import from `backend/` using bare module names
> resolved from `cwd`. Running them from inside `cli/` will fail with
> `ModuleNotFoundError: No module named 'backend'`.
