"""
Port Guard — Collision Prevention System for Agentop
====================================================

Prevents and diagnoses port binding conflicts across the Agentop system.

Usage:
    # Check all port reservations
    python -m backend.port_guard status

    # Start server with port reservation
    python -m backend.port_guard serve backend.server:app --port 8000

    # Release a stuck port
    python -m backend.port_guard release 8000

    # Kill process using a port
    python -m backend.port_guard kill 8000
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT

# Port registry file location
PORT_REGISTRY_PATH = Path("/tmp/agentop-port-registry.json")

# Known Agentop ports with their purposes
KNOWN_PORTS = {
    3000: "Next.js Dashboard (dev)",
    3007: "Next.js Dashboard (alt)",
    8000: "FastAPI Backend (primary)",
    8811: "Docker MCP Gateway",
    11434: "Ollama LLM",
}

# Dynamic ranges
SANDBOX_BACKEND_RANGE = range(8100, 9000)
SANDBOX_FRONTEND_RANGE = range(3100, 4000)


@dataclass
class PortReservation:
    port: int
    pid: int
    command: str
    started_at: str
    last_heartbeat: str
    purpose: str
    cwd: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortReservation:
        return cls(**data)


class PortRegistry:
    """Thread-safe (process-safe via atomic writes) port reservation registry."""

    def __init__(self, path: Path = PORT_REGISTRY_PATH) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "reservations": {}, "updated_at": None}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, IOError):
            return {"version": 1, "reservations": {}, "updated_at": None}

    def _save(self, data: dict[str, Any]) -> None:
        """Atomic write with 0o600 permissions to prevent other-user reads."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(data, indent=2).encode()
        # Create temp file in same directory as the target for atomic rename
        dir_ = str(self.path.parent)
        fd, tmp_name = tempfile.mkstemp(dir=dir_, prefix="agentop-port-registry-", suffix=".tmp")
        try:
            os.chmod(tmp_name, 0o600)
            os.write(fd, payload)
        finally:
            os.close(fd)
        Path(tmp_name).replace(self.path)

    def claim(self, port: int, purpose: str, command: str, cwd: str) -> PortReservation:
        """Claim a port in the registry."""
        data = self._load()
        pid = os.getpid()
        reservation = PortReservation(
            port=port,
            pid=pid,
            command=command,
            started_at=datetime.now(timezone.utc).isoformat(),
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
            purpose=purpose,
            cwd=cwd,
        )
        data["reservations"][str(port)] = reservation.to_dict()
        self._save(data)
        return reservation

    def release(self, port: int) -> bool:
        """Release a port from the registry."""
        data = self._load()
        key = str(port)
        if key in data["reservations"]:
            del data["reservations"][key]
            self._save(data)
            return True
        return False

    def get(self, port: int) -> PortReservation | None:
        """Get reservation for a port."""
        data = self._load()
        key = str(port)
        if key in data["reservations"]:
            return PortReservation.from_dict(data["reservations"][key])
        return None

    def list_all(self) -> list[PortReservation]:
        """List all reservations."""
        data = self._load()
        return [PortReservation.from_dict(r) for r in data["reservations"].values()]

    def cleanup_stale(self) -> int:
        """Remove reservations for dead processes. Returns count cleaned."""
        data = self._load()
        to_remove = []
        for port, res in data["reservations"].items():
            pid = res.get("pid")
            if pid and not _is_process_alive(pid):
                to_remove.append(port)
        for port in to_remove:
            del data["reservations"][port]
        if to_remove:
            self._save(data)
        return len(to_remove)


def _is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_process_using_port(port: int) -> dict[str, Any] | None:
    """Find which process is using a port using lsof or ss."""
    # Try lsof first
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip().split("\n")[0])
            # Get process details
            cmd_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm=,args="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return {
                "pid": pid,
                "command": cmd_result.stdout.strip() if cmd_result.returncode == 0 else "unknown",
                "found_via": "lsof",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Try ss
    try:
        result = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse ss output for pid
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "users:" in line:
                    # Extract pid from users:(("name",pid=1234,fd=...))
                    import re
                    match = re.search(r"pid=(\d+)", line)
                    if match:
                        pid = int(match.group(1))
                        return {
                            "pid": pid,
                            "command": line.strip(),
                            "found_via": "ss",
                        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def cmd_status() -> int:
    """Show status of all ports."""
    registry = PortRegistry()
    registry.cleanup_stale()

    print("=" * 70)
    print("AGENTOP PORT REGISTRY STATUS")
    print("=" * 70)

    reservations = registry.list_all()

    if not reservations:
        print("\nNo active port reservations.")
    else:
        print(f"\nActive Reservations: {len(reservations)}")
        print("-" * 70)
        for res in sorted(reservations, key=lambda r: r.port):
            alive = "✓ alive" if _is_process_alive(res.pid) else "✗ dead"
            print(f"Port {res.port:5d} | PID {res.pid:6d} ({alive})")
            print(f"  Purpose: {res.purpose}")
            print(f"  Command: {res.command[:60]}...")
            print(f"  Started: {res.started_at}")
            print()

    print("-" * 70)
    print("\nChecking known ports...")
    print("-" * 70)

    for port, purpose in KNOWN_PORTS.items():
        available = _is_port_available(port)
        status = "✓ AVAILABLE" if available else "✗ IN USE"
        print(f"{port:5d} | {status:12s} | {purpose}")

        if not available:
            proc = _get_process_using_port(port)
            if proc:
                print(f"       └─ PID {proc['pid']} via {proc['found_via']}")
                print(f"          {proc['command'][:70]}")

    return 0


def cmd_claim(port_str: str, purpose: str = "unknown") -> int:
    """Claim a port for the current process."""
    try:
        port = int(port_str)
    except ValueError:
        print(f"Error: Invalid port number: {port_str}", file=sys.stderr)
        return 1

    if not _is_port_available(port):
        proc = _get_process_using_port(port)
        if proc:
            print(f"Error: Port {port} is in use by PID {proc['pid']}")
            print(f"       {proc['command'][:70]}")
        else:
            print(f"Error: Port {port} is not available")
        return 1

    registry = PortRegistry()
    registry.claim(
        port=port,
        purpose=purpose,
        command=" ".join(sys.argv),
        cwd=str(Path.cwd()),
    )
    print(f"Claimed port {port} for {purpose}")
    return 0


def cmd_release(port_str: str) -> int:
    """Release a port from the registry."""
    try:
        port = int(port_str)
    except ValueError:
        print(f"Error: Invalid port number: {port_str}", file=sys.stderr)
        return 1

    registry = PortRegistry()
    reservation = registry.get(port)

    if not reservation:
        print(f"Port {port} is not in registry")
        return 0

    # Only allow releasing if process is dead or it's us
    if _is_process_alive(reservation.pid) and reservation.pid != os.getpid():
        print(f"Warning: Port {port} is held by alive PID {reservation.pid}")
        print(f"         Use 'kill {port}' to force release")
        return 1

    registry.release(port)
    print(f"Released port {port}")
    return 0


def cmd_kill(port_str: str) -> int:
    """Kill the process using a port."""
    try:
        port = int(port_str)
    except ValueError:
        print(f"Error: Invalid port number: {port_str}", file=sys.stderr)
        return 1

    proc = _get_process_using_port(port)
    if not proc:
        print(f"No process found using port {port}")
        # Still try to release from registry
        registry = PortRegistry()
        registry.release(port)
        return 0

    pid = proc["pid"]
    print(f"Killing PID {pid} using port {port}")
    print(f"  Command: {proc['command'][:70]}")

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to die
        for _ in range(10):
            if not _is_process_alive(pid):
                break
            time.sleep(0.1)
        else:
            # Force kill
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.1)
    except (OSError, ProcessLookupError) as e:
        print(f"Error killing process: {e}", file=sys.stderr)
        return 1

    # Release from registry
    registry = PortRegistry()
    registry.release(port)

    print(f"Killed process using port {port}")
    return 0


def cmd_serve() -> int:
    """Start uvicorn with port reservation."""
    # Parse uvicorn-style args
    args = sys.argv[2:]  # Skip 'port_guard.py' and 'serve'

    # Extract port from args
    port = 8000
    for i, arg in enumerate(args):
        if arg in ("--port", "-p") and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    # Check if port is available
    if not _is_port_available(port):
        proc = _get_process_using_port(port)
        print(f"ERROR: Port {port} is already in use!")
        if proc:
            print(f"       Process: PID {proc['pid']}")
            print(f"       Command: {proc['command'][:70]}")
        print()
        print("To resolve:")
        print(f"  1. Kill existing: python -m backend.port_guard kill {port}")
        print(f"  2. Use different port: --port {port + 1}")
        print(f"  3. Check status: python -m backend.port_guard status")
        return 1

    # Claim the port
    registry = PortRegistry()
    app_module = next((a for a in args if ":" in a and not a.startswith("-")), "unknown")
    registry.claim(
        port=port,
        purpose=f"uvicorn {app_module}",
        command=" ".join(["uvicorn"] + args),
        cwd=str(Path.cwd()),
    )

    # Set up cleanup on exit
    def cleanup(signum=None, frame=None):
        registry.release(port)
        if signum:
            sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        # Start uvicorn
        import uvicorn
        # Parse args for uvicorn
        sys.argv = ["uvicorn"] + args
        uvicorn.main()
    finally:
        cleanup()

    return 0


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Port Guard — Agentop Port Collision Prevention")
        print()
        print("Usage:")
        print("  python -m backend.port_guard status")
        print("  python -m backend.port_guard serve <app> [--port N]")
        print("  python -m backend.port_guard claim <port> [purpose]")
        print("  python -m backend.port_guard release <port>")
        print("  python -m backend.port_guard kill <port>")
        print()
        print("Examples:")
        print("  python -m backend.port_guard serve backend.server:app --port 8000")
        print("  python -m backend.port_guard status")
        print("  python -m backend.port_guard kill 8000")
        return 0

    cmd = sys.argv[1]
    commands = {
        "status": cmd_status,
        "serve": cmd_serve,
        "claim": lambda: cmd_claim(sys.argv[2]) if len(sys.argv) > 2 else (print("Usage: claim <port> [purpose]") or 1),
        "release": lambda: cmd_release(sys.argv[2]) if len(sys.argv) > 2 else (print("Usage: release <port>") or 1),
        "kill": lambda: cmd_kill(sys.argv[2]) if len(sys.argv) > 2 else (print("Usage: kill <port>") or 1),
    }

    if cmd in commands:
        return commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Known commands: {', '.join(commands.keys())}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
