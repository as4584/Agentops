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

from backend.port_guard import _get_process_using_port

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


def _is_healthy(port: int, path: str = "/", expect_status: int = 200) -> bool:
    """HTTP health check — verifies the service returns the expected status."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        resp = urllib.request.urlopen(req, timeout=3)
        return resp.status == expect_status
    except Exception:
        return False


def _kill_port(port: int) -> None:
    """Kill any process listening on a port (cleanup zombies/stale procs)."""
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], stderr=subprocess.DEVNULL).decode().strip()
        if out:
            for pid in out.split("\n"):
                pid = pid.strip()
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        print(f"  → Killed stale PID {pid} on :{port}")
                    except (ProcessLookupError, PermissionError):
                        pass
            time.sleep(0.5)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass


def _find_available_port(preferred: int, fallback_start: int, fallback_end: int, host: str = "127.0.0.1") -> int:
    if not _is_port_open(preferred, host=host):
        return preferred
    for port in range(fallback_start, fallback_end + 1):
        if not _is_port_open(port, host=host):
            return port
    raise RuntimeError(f"No available port in range {fallback_start}-{fallback_end} (preferred {preferred} occupied)")


def _is_agentop_owned_process(command: str) -> bool:
    cmd = command.lower()
    return (
        "backend.server:app" in cmd or "next dev" in cmd or "agentop" in cmd or "frontend/node_modules/electron" in cmd
    )


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


def _wait_for_healthy(port: int, path: str = "/", timeout: int = 60, label: str = "") -> bool:
    """Block until an HTTP endpoint returns 200 or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if _is_healthy(port, path):
            print(f"  ✓ {label or f'Port {port}'} healthy")
            return True
        time.sleep(1)
    print(f"  ✗ {label or f'Port {port}'} health check timed out after {timeout}s")
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
    # Remove port file
    port_file = ROOT / ".dashboard_port"
    port_file.unlink(missing_ok=True)
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
    backend_port = 8000
    if _is_port_open(backend_port) and _is_healthy(backend_port, "/health"):
        print(f"  ✓ Backend already running and healthy on :{backend_port}")
    else:
        if _is_port_open(backend_port):
            owner = _get_process_using_port(backend_port)
            owner_cmd = owner.get("command", "") if owner else ""
            if owner and _is_agentop_owned_process(owner_cmd):
                print(f"  ⚠ Port {backend_port} occupied by stale Agentop process — killing")
                _kill_port(backend_port)
            else:
                print(f"  ⚠ Port {backend_port} occupied by non-Agentop process; selecting fallback port")
                backend_port = _find_available_port(backend_port, 8765, 8799)
                print(f"  → Backend fallback port: :{backend_port}")
        _start_process(
            [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            cwd=ROOT,
            label="backend",
        )
        _wait_for_healthy(backend_port, "/health", timeout=90, label=f"Backend :{backend_port}")

    # ---- Start Frontend ----
    print("\n🎨 Starting dashboard...")
    dashboard_port = 3007
    if _is_port_open(dashboard_port) and _is_healthy(dashboard_port):
        print(f"  ✓ Dashboard already running and healthy on :{dashboard_port}")
    else:
        if _is_port_open(dashboard_port):
            owner = _get_process_using_port(dashboard_port)
            owner_cmd = owner.get("command", "") if owner else ""
            if owner and _is_agentop_owned_process(owner_cmd):
                print(f"  ⚠ Port {dashboard_port} occupied by stale Agentop process — killing")
                _kill_port(dashboard_port)
            else:
                print(f"  ⚠ Port {dashboard_port} occupied by non-Agentop process; selecting fallback port")
                dashboard_port = _find_available_port(dashboard_port, 3008, 3099)
                print(f"  → Dashboard fallback port: :{dashboard_port}")
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
            ["npx", "next", "dev", "-p", str(dashboard_port)],
            cwd=FRONTEND_DIR,
            label="dashboard",
            env={"NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{backend_port}"},
        )
        # Wait for Next.js to be fully compiled and serving pages
        _wait_for_healthy(dashboard_port, "/", timeout=60, label=f"Dashboard :{dashboard_port}")

    # ---- Open Native Window ----
    print("\n🖥️  Opening Agentop window...\n")

    # Write port file so Electron picks it up even without env var
    port_file = ROOT / ".dashboard_port"
    port_file.write_text(str(dashboard_port))

    # Detect WSL — Electron works natively on Windows display, pywebview doesn't
    is_wsl = "microsoft" in (Path("/proc/version").read_text().lower() if Path("/proc/version").exists() else "")

    if is_wsl or os.environ.get("AGENTOP_USE_ELECTRON"):
        print("  WSL detected → launching Electron native window...")
        try:
            electron_proc = _start_process(
                ["npx", "electron", ".", "--no-sandbox", "--disable-gpu"],
                cwd=FRONTEND_DIR,
                label="electron",
                env={"AGENTOP_DASHBOARD_PORT": str(dashboard_port)},
            )
            # Block until Electron exits
            electron_proc.wait()
        except (FileNotFoundError, OSError) as e:
            print(f"  ✗ Electron failed ({e}), opening in browser...")
            import webbrowser

            webbrowser.open(f"http://localhost:{dashboard_port}")
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

            webview.create_window(
                title="Agentop — Local AI Control Center",
                url=f"http://localhost:{dashboard_port}",
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

                webbrowser.open(f"http://localhost:{dashboard_port}")
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
