#!/usr/bin/env python3
"""
lex_compare — Side-by-side lex-v2 vs lex-v3 routing comparison.
================================================================
Usage:
  python cli/lex_compare.py "Deploy the backend to production"
  python cli/lex_compare.py "Check CPU usage" --v2 lex --v3 lex-v3
  python cli/lex_compare.py --batch 20                  # run 20 random eval samples
  python cli/lex_compare.py --interactive               # REPL mode
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EVAL_SPLIT = ROOT / "output" / "lex-finetune" / "eval_split.jsonl"

VALID_AGENTS = {
    "soul_core",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "cs_agent",
    "it_agent",
    "knowledge_agent",
    "BLOCKED",
}

AGENT_COLORS = {
    "soul_core": "magenta",
    "devops_agent": "blue",
    "monitor_agent": "cyan",
    "self_healer_agent": "red",
    "code_review_agent": "yellow",
    "security_agent": "bright_red",
    "data_agent": "green",
    "comms_agent": "bright_blue",
    "cs_agent": "bright_cyan",
    "it_agent": "bright_yellow",
    "knowledge_agent": "bright_green",
    "BLOCKED": "bright_red",
}

try:
    import typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ── Ollama helpers ─────────────────────────────────────────────────────────

ROUTING_PROMPT = """\
You are Lex, the Agentop router. Given the user message below, respond with \
a JSON object containing "agent_id" (one of: {agents}) and "reasoning" (brief).

User message: {message}"""


def _agents_list() -> str:
    return ", ".join(sorted(VALID_AGENTS - {"BLOCKED"})) + ", BLOCKED"


def build_prompt(message: str) -> str:
    return ROUTING_PROMPT.format(agents=_agents_list(), message=message)


def query_ollama(model: str, prompt: str, timeout: int = 30) -> tuple[str, float]:
    """Returns (response_text, latency_ms)."""
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            latency = (time.monotonic() - t0) * 1000
            return data.get("response", "").strip(), round(latency)
    except urllib.error.URLError as e:
        return f"ERROR: {e}", 0
    except TimeoutError:
        return "ERROR: timeout", 0


def extract_agent_id(response: str) -> str | None:
    try:
        obj = json.loads(response)
        return obj.get("agent_id") or obj.get("agent")
    except (json.JSONDecodeError, AttributeError):
        pass
    match = re.search(r'"agent_id"\s*:\s*"([^"]+)"', response)
    if match:
        return match.group(1)
    for line in response.splitlines():
        candidate = line.strip().lower().replace("-", "_")
        if candidate in VALID_AGENTS:
            return candidate
    return None


def extract_reasoning(response: str) -> str:
    try:
        obj = json.loads(response)
        return obj.get("reasoning", "")[:120]
    except (json.JSONDecodeError, AttributeError):
        pass
    match = re.search(r'"reasoning"\s*:\s*"([^"]+)"', response)
    return match.group(1)[:120] if match else response[:120]


# ── Comparison logic ────────────────────────────────────────────────────────


def compare_message(
    message: str,
    v2_model: str,
    v3_model: str,
    expected: str | None = None,
) -> dict:
    prompt = build_prompt(message)
    v2_resp, v2_ms = query_ollama(v2_model, prompt)
    v3_resp, v3_ms = query_ollama(v3_model, prompt)

    v2_agent = extract_agent_id(v2_resp)
    v3_agent = extract_agent_id(v3_resp)
    v2_reasoning = extract_reasoning(v2_resp)
    v3_reasoning = extract_reasoning(v3_resp)

    agree = v2_agent == v3_agent

    return {
        "message": message,
        "expected": expected,
        "v2": {"agent": v2_agent, "reasoning": v2_reasoning, "latency_ms": v2_ms},
        "v3": {"agent": v3_agent, "reasoning": v3_reasoning, "latency_ms": v3_ms},
        "agree": agree,
        "v2_correct": expected and v2_agent == expected,
        "v3_correct": expected and v3_agent == expected,
    }


# ── Rich display ────────────────────────────────────────────────────────────


def _agent_badge(agent: str | None, console_: Console) -> Text:
    """Return a coloured Text badge for an agent name."""
    if not agent:
        return Text("(none)", style="dim")
    color = AGENT_COLORS.get(agent, "white")
    return Text(agent, style=f"bold {color}")


def print_comparison(result: dict, console_: Console) -> None:

    msg = result["message"]
    expected = result.get("expected")
    v2 = result["v2"]
    v3 = result["v3"]

    # Header
    console_.print()
    console_.rule(f"[bold]Message:[/bold] {msg[:80]}")

    if expected:
        console_.print(f"  Expected : [bold]{expected}[/bold]")

    # Side-by-side table
    tbl = Table(show_header=True, header_style="bold", expand=True)
    tbl.add_column("", width=12, style="dim")
    tbl.add_column(f"lex-v2  ({v2['latency_ms']}ms)", style="cyan", ratio=1)
    tbl.add_column(f"lex-v3  ({v3['latency_ms']}ms)", style="green", ratio=1)

    tbl.add_row(
        "Agent",
        _agent_badge(v2["agent"], console_),
        _agent_badge(v3["agent"], console_),
    )
    tbl.add_row("Reasoning", v2["reasoning"] or "—", v3["reasoning"] or "—")

    if expected:
        v2_mark = "✓" if result.get("v2_correct") else "✗"
        v3_mark = "✓" if result.get("v3_correct") else "✗"
        tbl.add_row("Correct?", v2_mark, v3_mark)

    if result["agree"]:
        tbl.add_row("Agreement", "[green]✓ agree[/green]", "[green]✓ agree[/green]")
    else:
        tbl.add_row("Agreement", "[yellow]— disagree[/yellow]", "[yellow]— disagree[/yellow]")

    console_.print(tbl)


def print_comparison_simple(result: dict) -> None:
    """Fallback for when rich is not available."""
    print(f"\nMessage : {result['message']}")
    if result.get("expected"):
        print(f"Expected: {result['expected']}")
    print(f"lex-v2  : {result['v2']['agent']}  ({result['v2']['latency_ms']}ms)")
    print(f"  reason: {result['v2']['reasoning']}")
    print(f"lex-v3  : {result['v3']['agent']}  ({result['v3']['latency_ms']}ms)")
    print(f"  reason: {result['v3']['reasoning']}")
    print(f"Agree   : {'yes' if result['agree'] else 'NO — diverge!'}")


# ── Batch mode (eval split) ─────────────────────────────────────────────────


def run_batch(v2_model: str, v3_model: str, limit: int, console_: Console | None) -> None:
    if not EVAL_SPLIT.exists():
        msg = f"Eval split not found: {EVAL_SPLIT}\nRun: python scripts/finetune_lex.py --prep-only"
        if console_:
            console_.print(f"[red]{msg}[/red]")
        else:
            print(msg)
        return

    records = []
    with open(EVAL_SPLIT) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(records) >= limit:
                break

    if console_:
        console_.print(f"\n[bold]Batch compare:[/bold] {len(records)} samples — {v2_model} vs {v3_model}\n")

    v2_wins = v3_wins = tie = 0

    for rec in records:
        if "user_message" in rec:
            msg = rec["user_message"]
            expected = rec.get("expected_agent")
        elif "conversations" in rec:
            msg = next((c["value"] for c in rec["conversations"] if c.get("from") == "human"), None)
            expected = rec.get("expected_agent")
        else:
            continue

        if not msg:
            continue

        result = compare_message(msg, v2_model, v3_model, expected)

        if console_:
            print_comparison(result, console_)
        else:
            print_comparison_simple(result)

        if result.get("v3_correct") and not result.get("v2_correct"):
            v3_wins += 1
        elif result.get("v2_correct") and not result.get("v3_correct"):
            v2_wins += 1
        else:
            tie += 1

    summary = f"\nBatch summary: v3 wins={v3_wins}  v2 wins={v2_wins}  tie/neither={tie}"
    if console_:
        console_.print(f"\n[bold green]{summary}[/bold green]")
    else:
        print(summary)


# ── Interactive REPL ────────────────────────────────────────────────────────


def run_interactive(v2_model: str, v3_model: str, console_: Console | None) -> None:
    if console_:
        console_.print(
            Panel(
                f"[bold]lex compare REPL[/bold]\n"
                f"v2=[cyan]{v2_model}[/cyan]  v3=[green]{v3_model}[/green]\n"
                f"Type a message to compare routing. [dim]Ctrl+C to exit.[/dim]",
                title="lex-compare",
            )
        )
    else:
        print(f"\nlex-compare REPL  (v2={v2_model}  v3={v3_model})")
        print("Type a message to compare routing. Ctrl+C to exit.\n")

    try:
        while True:
            try:
                msg = input("\n> ").strip()
            except EOFError:
                break
            if not msg:
                continue
            if msg.lower() in ("exit", "quit", "q"):
                break
            result = compare_message(msg, v2_model, v3_model)
            if console_:
                print_comparison(result, console_)
            else:
                print_comparison_simple(result)
    except KeyboardInterrupt:
        pass


# ── CLI entry point ─────────────────────────────────────────────────────────

if HAS_RICH:
    app = typer.Typer(help="Compare lex-v2 vs lex-v3 routing side-by-side.")
    console = Console()

    @app.command()
    def compare(
        message: str = typer.Argument(None, help="User message to route"),
        v2: str = typer.Option("lex-v2", "--v2", help="Ollama model name for lex-v2"),
        v3: str = typer.Option("lex-v3", "--v3", help="Ollama model name for lex-v3"),
        expected: str = typer.Option(None, "--expected", "-e", help="Expected agent_id (for correctness check)"),
        batch: int = typer.Option(0, "--batch", "-b", help="Run N random samples from eval split"),
        interactive: bool = typer.Option(False, "--interactive", "-i", help="REPL mode"),
    ) -> None:
        """Compare lex-v2 vs lex-v3 routing side-by-side."""
        if interactive:
            run_interactive(v2, v3, console)
        elif batch > 0:
            run_batch(v2, v3, batch, console)
        elif message:
            result = compare_message(message, v2, v3, expected)
            print_comparison(result, console)
        else:
            console.print("[yellow]Provide a message, --batch N, or --interactive[/yellow]")
            raise typer.Exit(1)

    if __name__ == "__main__":
        app()

else:
    # Minimal fallback without typer/rich
    import argparse

    def _main() -> None:
        p = argparse.ArgumentParser(description="Compare lex-v2 vs lex-v3 routing")
        p.add_argument("message", nargs="?", help="User message to route")
        p.add_argument("--v2", default="lex-v2")
        p.add_argument("--v3", default="lex-v3")
        p.add_argument("--expected", default=None)
        p.add_argument("--batch", type=int, default=0)
        p.add_argument("--interactive", action="store_true")
        args = p.parse_args()

        if args.interactive:
            run_interactive(args.v2, args.v3, None)
        elif args.batch > 0:
            run_batch(args.v2, args.v3, args.batch, None)
        elif args.message:
            result = compare_message(args.message, args.v2, args.v3, args.expected)
            print_comparison_simple(result)
        else:
            print("Provide a message, --batch N, or --interactive")
            sys.exit(1)

    if __name__ == "__main__":
        _main()
