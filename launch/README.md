# launch/

One-click launchers for the full Agentop stack. All three wrappers do the
same thing — pick the one for your OS.

| File | OS | How to use |
|---|---|---|
| `start.sh` | Linux / macOS | `bash launch/start.sh` or double-click |
| `Agentop.bat` | Windows (WSL) | Double-click |
| `Agentop.desktop` | Linux (XDG) | Copy to `~/.local/share/applications/` for app-launcher integration |

All launchers `cd` to the project root and call `python3 app.py`.
