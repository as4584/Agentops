"""
Configuration — Central configuration for the Agentop system.
==============================================================
All configuration is local-first. No cloud dependencies.
Environment variables override defaults for deployment flexibility.
"""

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
MEMORY_DIR: Path = BACKEND_DIR / "memory"

# Governance documents
SOURCE_OF_TRUTH_PATH: Path = DOCS_DIR / "SOURCE_OF_TRUTH.md"
CHANGE_LOG_PATH: Path = DOCS_DIR / "CHANGE_LOG.md"
AGENT_REGISTRY_PATH: Path = DOCS_DIR / "AGENT_REGISTRY.md"
DRIFT_GUARD_PATH: Path = DOCS_DIR / "DRIFT_GUARD.md"

# ---------------------------------------------------------------------------
# Ollama LLM Configuration (local inference — no cloud)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Cloud LLM Configuration (OpenRouter — hybrid/cloud modes)
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
LLM_ROUTER_MODE: str = os.getenv("LLM_ROUTER_MODE", "hybrid")
LLM_MONTHLY_BUDGET: float = float(os.getenv("LLM_MONTHLY_BUDGET", "50.0"))

# ---------------------------------------------------------------------------
# Server Configuration
# ---------------------------------------------------------------------------
# NOTE: Default changed to 127.0.0.1 (localhost-only) for security.
# Set BACKEND_HOST=0.0.0.0 explicitly if you need network access.
BACKEND_HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

# ---------------------------------------------------------------------------
# Security Configuration
# ---------------------------------------------------------------------------
# API key for bearer-token authentication.  Set to "" to disable (dev only).
API_SECRET: str = os.getenv("AGENTOP_API_SECRET", "")
# Maximum chat message size (bytes)
MAX_CHAT_MESSAGE_LENGTH: int = int(os.getenv("MAX_CHAT_MESSAGE_LENGTH", "8192"))
# Rate limit: max requests per minute per IP (0 = disabled)
RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "120"))
# Internal-only URL prefixes that webhook_send / health_check must NOT contact
SSRF_BLOCKED_PREFIXES: list[str] = [
    "http://169.254.",       # cloud metadata
    "http://127.",           # loopback
    "http://localhost",      # loopback
    "http://0.0.0.0",       # wildcard loopback
    "http://[::1]",         # ipv6 loopback
    "http://10.",            # private RFC-1918
    "http://172.16.",        # private RFC-1918
    "http://192.168.",       # private RFC-1918
    "https://169.254.",
    "https://127.",
    "https://localhost",
    "https://0.0.0.0",
    "https://[::1]",
    "https://10.",
    "https://172.16.",
    "https://192.168.",
]

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_DIR: Path = BACKEND_DIR / "logs"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
MAX_LOG_ENTRIES: int = int(os.getenv("MAX_LOG_ENTRIES", "10000"))

# ---------------------------------------------------------------------------
# Tool Safety Configuration
# ---------------------------------------------------------------------------
# Whitelisted commands for safe_shell tool
SAFE_SHELL_WHITELIST: list[str] = [
    "ls", "cat", "head", "tail", "grep", "find", "wc",
    "df", "du", "free", "uptime", "whoami", "hostname",
    "date", "echo", "pwd", "env", "ps", "top",
    "uname", "id", "which", "file", "stat",
]

# Shell metacharacters that MUST NOT appear in commands (prevents chaining)
SHELL_DANGEROUS_CHARS: list[str] = [
    ";", "&&", "||", "|", "`", "$(", "${", "<(", ">(", "\n",
    ">>", ">", "<", "\\", "!",
]

# Prohibited patterns for safe_shell
SAFE_SHELL_BLACKLIST: list[str] = [
    "rm -rf", "rm -r", "rm -f", "rm ", "rmdir", "mkfs", "dd ",
    "pip install", "npm install", "apt install", "brew install",
    "curl", "wget", "ssh", "scp", "sudo", "su ",
    "> /dev/", "chmod", "chown", "chgrp",
    "mv ", "cp ", "mkdir ", "touch ",
    "kill ", "pkill", "killall",
    "eval ", "exec ", "source ",
    "python", "node ", "ruby ", "perl ",
    "/etc/", "/proc/", "/sys/", "/dev/",
    "../",  # directory traversal
]

# ---------------------------------------------------------------------------
# Drift Detection Configuration
# ---------------------------------------------------------------------------
DRIFT_CHECK_INTERVAL_SECONDS: int = int(os.getenv("DRIFT_CHECK_INTERVAL", "30"))

# ---------------------------------------------------------------------------
# Docker MCP Gateway Configuration
# ---------------------------------------------------------------------------
# Set DOCKER_MCP_IN_CONTAINER=1 when running without Docker Desktop
# (e.g. Docker CE, WSL2, or containerised environments)
MCP_GATEWAY_ENABLED: bool = os.getenv("MCP_GATEWAY_ENABLED", "true").lower() == "true"
MCP_GATEWAY_PORT: int = int(os.getenv("MCP_GATEWAY_PORT", "8811"))
MCP_GATEWAY_URL: str = os.getenv("MCP_GATEWAY_URL", f"http://localhost:{int(os.getenv('MCP_GATEWAY_PORT', '8811'))}")
MCP_TOOL_TIMEOUT: int = int(os.getenv("MCP_TOOL_TIMEOUT", "30"))
# Path to docker-mcp config directory (defaults to project mcp-gateway/ folder)
MCP_CONFIG_DIR: Path = Path(os.getenv("MCP_CONFIG_DIR", str(PROJECT_ROOT / "mcp-gateway")))

# Ensure required directories exist
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
