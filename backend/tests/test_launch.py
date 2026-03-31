"""
Agentop launch smoke test.
Starts backend + frontend via app.py helpers and verifies both are healthy.
Run: python -m pytest backend/tests/test_launch.py -v

NOTE: This is an integration test that requires live servers.
      Skipped in CI — run manually with: pytest backend/tests/test_launch.py -v
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LAUNCH_TEST"),
    reason="Integration test — set RUN_LAUNCH_TEST=1 to enable (requires live servers)",
)

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_TIMEOUT = 30  # seconds
FRONTEND_TIMEOUT = 60  # seconds


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_for_port(port: int, timeout: int) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _is_port_open(port):
            return True
        time.sleep(0.5)
    return False


def _http_get(url: str, timeout: int = 5) -> int:
    """Return HTTP status code or 0 on failure."""
    import urllib.error
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.status
    except Exception:
        return 0


@pytest.fixture(scope="module")
def agentop_stack():
    """Start backend + frontend, yield ports, then tear down."""
    procs = []
    backend_port = 18000  # Use non-standard ports to avoid conflicts
    frontend_port = 13007

    env = {**os.environ, "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{backend_port}"}

    # Start backend
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(backend_port)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        preexec_fn=os.setsid,
    )
    procs.append(backend)

    # Start frontend (dev mode for live reload)
    frontend = subprocess.Popen(
        ["npx", "next", "dev", "-p", str(frontend_port)],
        cwd=str(ROOT / "frontend"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        preexec_fn=os.setsid,
    )
    procs.append(frontend)

    yield {"backend_port": backend_port, "frontend_port": frontend_port, "procs": procs}

    # Teardown
    for proc in reversed(procs):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    time.sleep(1)
    for proc in reversed(procs):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


class TestLaunch:
    def test_backend_starts(self, agentop_stack):
        port = agentop_stack["backend_port"]
        assert _wait_for_port(port, BACKEND_TIMEOUT), f"Backend did not start on :{port}"

    def test_backend_health(self, agentop_stack):
        port = agentop_stack["backend_port"]
        _wait_for_port(port, BACKEND_TIMEOUT)
        status = _http_get(f"http://127.0.0.1:{port}/health")
        assert status == 200, f"Backend /health returned {status}"

    def test_frontend_starts(self, agentop_stack):
        port = agentop_stack["frontend_port"]
        assert _wait_for_port(port, FRONTEND_TIMEOUT), f"Frontend did not start on :{port}"

    def test_frontend_serves_page(self, agentop_stack):
        port = agentop_stack["frontend_port"]
        _wait_for_port(port, FRONTEND_TIMEOUT)
        # Next.js dev may return 200 or 500 initially while compiling; just check it responds
        status = _http_get(f"http://127.0.0.1:{port}/")
        assert status in (200, 500), f"Frontend / returned {status}"

    def test_electron_binary_exists(self):
        electron_bin = ROOT / "frontend" / "node_modules" / "electron" / "dist" / "electron"
        assert electron_bin.exists(), f"Electron binary not found at {electron_bin}"
