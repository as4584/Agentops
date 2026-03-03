#!/usr/bin/env python3
"""
Agentop Desktop App — One-click launcher.
==========================================
Launches the full Agentop stack in a native desktop window:
  1. FastAPI backend  (port 8000)
  2. Next.js frontend (port 3007)
  3. Native desktop window via pywebview

Click to launch. Close window to shut everything down.
Works like Ollama's desktop app — tray-style, self-contained.
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

# ---------------------------------------------------------------------------
# Service Management
# ---------------------------------------------------------------------------
_processes: list[subprocess.Popen] = []


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_for_port(port: int, timeout: int = 60, label: str = "") -> bool:
    """Block until a port is open or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if _is_port_open(port):
            print(f"  ✓ {label or f'Port {port}'} ready")
            return True
        time.sleep(0.5)
    print(f"  ✗ {label or f'Port {port}'} timed out after {timeout}s")
    return False


def _start_process(cmd: list[str], cwd: Path, label: str, env: dict | None = None) -> subprocess.Popen:
    """Start a subprocess and register it for cleanup."""
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        preexec_fn=os.setsid,  # Create new process group for clean kill
    )
    _processes.append(proc)
    # Stream output in background
    threading.Thread(target=_stream_output, args=(proc, label), daemon=True).start()
    print(f"  → {label} started (PID {proc.pid})")
    return proc


def _stream_output(proc: subprocess.Popen, label: str) -> None:
    """Stream process stdout to console with label prefix."""
    try:
        for line in iter(proc.stdout.readline, b""):  # type: ignore
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"  [{label}] {text}")
    except Exception:
        pass


def cleanup() -> None:
    """Kill all child processes on exit."""
    print("\n⏹  Shutting down Agentop...")
    for proc in reversed(_processes):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    # Give processes a moment, then force kill
    time.sleep(1)
    for proc in reversed(_processes):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    print("  ✓ All services stopped. Goodbye.")


atexit.register(cleanup)


# ---------------------------------------------------------------------------
# Splash / Status Display
# ---------------------------------------------------------------------------

BANNER = """
╔═══════════════════════════════════════════════╗
║                                               ║
║       █████╗  ██████╗ ███████╗███╗   ██╗      ║
║      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║      ║
║      ███████║██║  ███╗█████╗  ██╔██╗ ██║      ║
║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║      ║
║      ██║  ██║╚██████╔╝███████╗██║ ╚████║      ║
║      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝      ║
║              T O P                            ║
║                                               ║
║    Local AI Control Center  v1.0              ║
║    No Cloud · No Telemetry · Your Data        ║
║                                               ║
╚═══════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(BANNER)

    # ---- Check Ollama ----
    print("🔍 Checking services...")
    ollama_ok = _is_port_open(11434)
    if ollama_ok:
        print("  ✓ Ollama is running")
    else:
        print("  ⚠ Ollama not detected on :11434")
        try:
            _start_process(["ollama", "serve"], cwd=ROOT, label="ollama")
            time.sleep(3)
            if _is_port_open(11434):
                print("  ✓ Ollama started")
            else:
                print("  ⚠ Ollama started but not responding yet — agents may retry")
        except (FileNotFoundError, PermissionError, OSError) as e:
            print(f"  ⚠ Could not start Ollama ({e})")
            print("    Dashboard will work. Chat requires Ollama running separately:")
            print("    → ollama serve")

    # ---- Start Backend ----
    print("\n🚀 Starting backend...")
    if _is_port_open(8000):
        print("  ✓ Backend already running on :8000")
    else:
        _start_process(
            [sys.executable, "-m", "uvicorn", "backend.server:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=ROOT,
            label="backend",
        )
        _wait_for_port(8000, timeout=30, label="Backend :8000")

    # ---- Start Frontend ----
    print("\n🎨 Starting dashboard...")
    if _is_port_open(3007):
        print("  ✓ Dashboard already running on :3007")
    else:
        # Check if node_modules exists
        if not (FRONTEND_DIR / "node_modules").exists():
            print("  → Installing frontend dependencies (first run)...")
            subprocess.run(
                ["npm", "install"],
                cwd=str(FRONTEND_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _start_process(
            ["npx", "next", "dev", "-p", "3007"],
            cwd=FRONTEND_DIR,
            label="dashboard",
        )
        _wait_for_port(3007, timeout=45, label="Dashboard :3007")

    # ---- Open Native Window ----
    print("\n🖥️  Opening Agentop window...\n")

    # Detect WSL — Electron works natively on Windows display, pywebview doesn't
    is_wsl = "microsoft" in (Path("/proc/version").read_text().lower() if Path("/proc/version").exists() else "")

    if is_wsl or os.environ.get("AGENTOP_USE_ELECTRON"):
        print("  WSL detected → launching Electron native window...")
        try:
            electron_proc = _start_process(
                ["npx", "electron", ".", "--no-sandbox", "--disable-gpu"],
                cwd=FRONTEND_DIR,
                label="electron",
            )
            # Block until Electron exits
            electron_proc.wait()
        except (FileNotFoundError, OSError) as e:
            print(f"  ✗ Electron failed ({e}), opening in browser...")
            import webbrowser
            webbrowser.open("http://localhost:3007")
            print("\n  Dashboard open in your browser.")
            print("  Press Ctrl+C to stop all services.\n")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    else:
        try:
            import webview

            window = webview.create_window(
                title="Agentop — Local AI Control Center",
                url="http://localhost:3007",
                width=1400,
                height=900,
                min_size=(900, 600),
                resizable=True,
                text_select=True,
                confirm_close=False,
            )

            # This blocks until the window is closed
            webview.start(
                debug=False,
                private_mode=False,
                gui="qt",
            )

        except ImportError:
            print("  pywebview not available, opening in browser instead...")
            import webbrowser
            webbrowser.open("http://localhost:3007")
            print("\n  Dashboard open in your browser.")
            print("  Press Ctrl+C to stop all services.\n")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        except Exception as e:
            # Fallback: if no display (headless), open in browser
            if "display" in str(e).lower() or "gtk" in str(e).lower() or "qt" in str(e).lower():
                print(f"  No display detected ({e}), opening in browser...")
                import webbrowser
                webbrowser.open("http://localhost:3007")
                print("\n  Dashboard open in your browser.")
                print("  Press Ctrl+C to stop all services.\n")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
            else:
                raise

    # When window closes, cleanup runs via atexit
    print("\n👋 Window closed.")


if __name__ == "__main__":
    main()
