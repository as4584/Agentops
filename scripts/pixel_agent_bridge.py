#!/usr/bin/env python3
"""
Pixel Agents ↔ GitHub Copilot Bridge  (v2 – with subagent task simulation)
───────────────────────────────────────────────────────────────────────────
Watches the workspace for file-system changes and writes Claude Code-compatible
JSONL transcript events so Pixel Agents animates while Copilot is working.

Subagent logic:
  • 1-2 files changed  → simple Edit/Write tool on the main agent
  • 3+ files in a burst → treated as a coordinated Task: main agent spawns a
    Task tool, then progress records drive a sub-character for each file,
    giving the nested subagent animation in Pixel Agents.

Usage:
    python scripts/pixel_agent_bridge.py [--workspace /path/to/workspace]

Stop with Ctrl+C.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
WORKSPACE = Path("/root/studio/testing/Agentop")
IDLE_TIMEOUT_SEC   = 8    # quiet seconds after last change → turn ends (waiting)
BURST_WINDOW_SEC   = 2.5  # accumulate changes this long before deciding task vs simple
TASK_THRESHOLD     = 3    # ≥ this many files in burst → emit Task + subagent
POLL_INTERVAL_SEC  = 0.4
SUB_TOOL_DELAY_SEC = 0.25 # pacing between sub-tool events so animation is visible

IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".next",
                "dist", "build", "output", ".cache", "vscode-extension",
                ".claude", "pixel-agents"}
IGNORED_EXTS = {".pyc", ".pyo", ".log", ".tmp", ".swp", ".lock", ".jsonl"}

CODE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml",
    ".md", ".html", ".css", ".sh", ".toml", ".env",
}

# ── Path helpers ─────────────────────────────────────────────────────────────

def project_dir(workspace: Path) -> Path:
    """Mirror the Pixel Agents TS logic: replace non-alnum/hyphen → '-'."""
    dir_name = re.sub(r"[^a-zA-Z0-9-]", "-", str(workspace))
    return Path.home() / ".claude" / "projects" / dir_name


def new_session_file(pdir: Path) -> Path:
    session_id = str(uuid.uuid4())
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir / f"{session_id}.jsonl"


def rel(path_str: str, workspace: Path) -> str:
    p = Path(path_str)
    try:
        return str(p.relative_to(workspace))
    except ValueError:
        return p.name


# ── JSONL helpers ────────────────────────────────────────────────────────────

def write_line(fh, record: dict):
    fh.write(json.dumps(record) + "\n")
    fh.flush()


def mk_tool_id() -> str:
    return "toolu_" + uuid.uuid4().hex[:16]


# ── Record factories ──────────────────────────────────────────────────────────

def rec_user_text(text: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def rec_assistant_text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def rec_tool_use(name: str, input_: dict) -> tuple[str, dict]:
    tid = mk_tool_id()
    return tid, {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": input_}]},
    }


def rec_tool_result(tool_id: str, content: str = "ok") -> dict:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]},
    }


def rec_turn_duration(ms: int = 500) -> dict:
    return {"type": "system", "subtype": "turn_duration", "duration_ms": ms}


# ── Subagent (progress) record factories ─────────────────────────────────────
# These drive the nested sub-character animation in Pixel Agents.
# See transcriptParser.ts → processProgressRecord()

def rec_progress_subtool_start(parent_tool_id: str, sub_tool_id: str,
                                name: str, input_: dict) -> dict:
    """Emit a sub-agent tool_use inside a Task progress stream."""
    return {
        "type": "progress",
        "parentToolUseID": parent_tool_id,
        "data": {
            "type": "agent_progress",
            "message": {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": sub_tool_id,
                                 "name": name, "input": input_}]
                },
            },
        },
    }


def rec_progress_subtool_done(parent_tool_id: str, sub_tool_id: str) -> dict:
    """Complete a sub-agent tool inside a Task progress stream."""
    return {
        "type": "progress",
        "parentToolUseID": parent_tool_id,
        "data": {
            "type": "agent_progress",
            "message": {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result",
                                 "tool_use_id": sub_tool_id,
                                 "content": "done"}]
                },
            },
        },
    }


# ── File classification ───────────────────────────────────────────────────────

def classify(path_str: str, workspace: Path) -> tuple[str, dict]:
    """Return (tool_name, input_dict) for a changed file path."""
    p = Path(path_str)
    r = rel(path_str, workspace)
    ext = p.suffix.lower()
    if ext in CODE_EXTS:
        return "Edit", {"file_path": r, "old_string": "", "new_string": ""}
    return "Write", {"file_path": r, "content": ""}


# ── Workspace snapshot ────────────────────────────────────────────────────────

def snapshot(workspace: Path) -> dict[str, float]:
    state: dict[str, float] = {}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fname in files:
            if Path(fname).suffix in IGNORED_EXTS:
                continue
            fp = Path(root) / fname
            try:
                state[str(fp)] = fp.stat().st_mtime
            except OSError:
                pass
    return state


# ── Emission helpers ──────────────────────────────────────────────────────────

def emit_simple_changes(fh, changed: list[str], workspace: Path):
    """1-2 files: emit plain tool_use / tool_result on the main agent."""
    for fp in changed[:2]:
        name, inp = classify(fp, workspace)
        tid, use_rec = rec_tool_use(name, inp)
        write_line(fh, use_rec)
        time.sleep(SUB_TOOL_DELAY_SEC)
        write_line(fh, rec_tool_result(tid))


def emit_task_burst(fh, burst: list[str], workspace: Path):
    """3+ files: wrap in a Task + progress subagent records."""
    # Describe what changed for the task description
    names = [Path(f).name for f in burst[:5]]
    desc = f"Apply changes: {', '.join(names)}" + (" …" if len(burst) > 5 else "")

    task_tid, task_rec = rec_tool_use("Task", {"description": desc})
    write_line(fh, task_rec)

    # Drive sub-tools through progress records
    sub_ids: list[str] = []
    for fp in burst[:6]:   # cap sub-tools to 6 to avoid overwhelming animation
        name, inp = classify(fp, workspace)
        sub_tid = mk_tool_id()
        sub_ids.append(sub_tid)
        write_line(fh, rec_progress_subtool_start(task_tid, sub_tid, name, inp))
        time.sleep(SUB_TOOL_DELAY_SEC)

    # Complete sub-tools
    for sub_tid in sub_ids:
        write_line(fh, rec_progress_subtool_done(task_tid, sub_tid))
        time.sleep(0.1)

    # Complete the Task itself
    time.sleep(0.2)
    write_line(fh, rec_tool_result(task_tid, f"Task complete: {len(burst)} files updated"))


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(workspace: Path):
    pdir = project_dir(workspace)
    session_file = new_session_file(pdir)

    print(f"[bridge] workspace : {workspace}")
    print(f"[bridge] session   : {session_file.name}")
    print(f"[bridge] JSONL     : {session_file}")
    print(f"[bridge] v2 — subagent Task simulation enabled (burst ≥ {TASK_THRESHOLD} files)")
    print(f"[bridge] Add agent in Pixel Agents panel → it will animate.")
    print(f"[bridge] Stop with Ctrl+C.\n")

    prev = snapshot(workspace)
    last_activity  = time.monotonic()
    burst_start    = None   # time when current burst began
    burst_files: list[str] = []
    waiting   = True
    turn_open = False

    with open(session_file, "w") as fh:
        write_line(fh, rec_user_text("GitHub Copilot session started"))
        write_line(fh, rec_assistant_text("Ready. Watching for Copilot activity…"))
        write_line(fh, rec_turn_duration(100))

        while True:
            time.sleep(POLL_INTERVAL_SEC)
            curr = snapshot(workspace)
            now  = time.monotonic()

            # ── Detect new changes ───────────────────────────────────────────
            changed = []
            for fp, mtime in curr.items():
                if fp not in prev or prev[fp] != mtime:
                    changed.append(fp)
            for fp in prev:
                if fp not in curr:
                    changed.append(fp)
            prev = curr

            if changed:
                last_activity = now

                # Start a new turn if we were waiting
                if waiting:
                    write_line(fh, rec_user_text("Copilot is making changes"))
                    waiting   = False
                    turn_open = True
                    burst_start = now
                    burst_files = []

                # Accumulate into burst
                for fp in changed:
                    if fp not in burst_files:
                        burst_files.append(fp)

            # ── Flush burst once window expires ──────────────────────────────
            if burst_files and burst_start is not None:
                burst_age = now - burst_start
                quiet_age = now - last_activity

                flush = (quiet_age >= BURST_WINDOW_SEC) or (burst_age >= BURST_WINDOW_SEC * 2)
                if flush:
                    ts = datetime.now().strftime("%H:%M:%S")
                    n  = len(burst_files)
                    if n >= TASK_THRESHOLD:
                        print(f"[bridge] {ts} task burst  ({n} files) → Task + subagent")
                        emit_task_burst(fh, burst_files, workspace)
                    else:
                        print(f"[bridge] {ts} simple edit ({n} file{'s' if n>1 else ''})")
                        emit_simple_changes(fh, burst_files, workspace)
                    burst_files = []
                    burst_start = None

            # ── End turn after sustained idle ────────────────────────────────
            elif turn_open and not burst_files and (now - last_activity) >= IDLE_TIMEOUT_SEC:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[bridge] {ts} idle → waiting")
                write_line(fh, rec_turn_duration(int((now - last_activity) * 1000)))
                turn_open = False
                waiting = True


def main():
    parser = argparse.ArgumentParser(description="Pixel Agents ↔ GitHub Copilot bridge")
    parser.add_argument("--workspace", default=str(WORKSPACE),
                        help="Path to the VS Code workspace root")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        print(f"[bridge] ERROR: workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    try:
        run(workspace)
    except KeyboardInterrupt:
        print("\n[bridge] stopped.")


if __name__ == "__main__":
    main()
