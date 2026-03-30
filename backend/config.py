"""
Configuration — Central configuration for the Agentop system.
==============================================================
All configuration is local-first. No cloud dependencies.
Environment variables override defaults for deployment flexibility.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (owner-only 600 file, never committed to git)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
MEMORY_DIR: Path = PROJECT_ROOT / "data" / "agents"
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
BROWSER_ALLOWED_AGENTS: list[str] = [
    a.strip()
    for a in os.getenv("BROWSER_ALLOWED_AGENTS", "").split(",")
    if a.strip()
]

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
LLM_CIRCUIT_FAILURE_THRESHOLD: int = int(os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "3"))
LLM_CIRCUIT_RESET_SECONDS: int = int(os.getenv("LLM_CIRCUIT_RESET_SECONDS", "300"))
AGENTOP_WEBHOOK_SECRET: str = os.getenv("AGENTOP_WEBHOOK_SECRET", "")
WEBHOOK_RATE_LIMIT_RPM: int = int(os.getenv("WEBHOOK_RATE_LIMIT_RPM", "60"))
A2A_MAX_DEPTH: int = int(os.getenv("A2A_MAX_DEPTH", "4"))

# ---------------------------------------------------------------------------
# TTS Configuration (Qwen CosyVoice — local open-source)
# ---------------------------------------------------------------------------
QWEN_TTS_MODEL: str = os.getenv("QWEN_TTS_MODEL", "iic/CosyVoice2-0.5B")
QWEN_TTS_VOICE: str = os.getenv("QWEN_TTS_VOICE", "中文女")

# ---------------------------------------------------------------------------
# ML Pipeline Configuration
# ---------------------------------------------------------------------------
ML_DIR: Path = PROJECT_ROOT / "backend" / "ml"
ML_EXPERIMENTS_DIR: Path = ML_DIR / "experiments"
ML_MODELS_DIR: Path = ML_DIR / "models"
ML_MONITORING_DIR: Path = ML_DIR / "monitoring"
TRAINING_DATA_DIR: Path = PROJECT_ROOT / ".training_data"
ML_DOC_PATH: Path = DOCS_DIR / "ML_CHANGELOG.md"
ML_MONITOR_INTERVAL_SECONDS: int = int(os.getenv("ML_MONITOR_INTERVAL_SECONDS", "300"))
ML_ACCURACY_THRESHOLD: float = float(os.getenv("ML_ACCURACY_THRESHOLD", "0.85"))
ML_LATENCY_THRESHOLD_MS: float = float(os.getenv("ML_LATENCY_THRESHOLD_MS", "2000"))
ML_DRIFT_THRESHOLD: float = float(os.getenv("ML_DRIFT_THRESHOLD", "0.1"))

# MLflow tracking (local file store by default)
MLFLOW_TRACKING_URI: str = os.getenv("MLFLOW_TRACKING_URI", str(ML_EXPERIMENTS_DIR / "mlruns"))
MLFLOW_EXPERIMENT_NAME: str = os.getenv("MLFLOW_EXPERIMENT_NAME", "agentop")

# Qdrant vector store
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_IN_MEMORY: bool = os.getenv("QDRANT_IN_MEMORY", "false").lower() == "true"
QDRANT_DEFAULT_DIM: int = int(os.getenv("QDRANT_DEFAULT_DIM", "384"))

# Eval thresholds
EVAL_PASS_SCORE: float = float(os.getenv("EVAL_PASS_SCORE", "0.7"))
EVAL_LATENCY_THRESHOLD_MS: float = float(os.getenv("EVAL_LATENCY_THRESHOLD_MS", "2000"))
EVAL_MAX_TOKENS: int = int(os.getenv("EVAL_MAX_TOKENS", "4096"))

# TurboQuant embedding quantization
TURBOQUANT_BITS: int = int(os.getenv("TURBOQUANT_BITS", "4"))

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
# Dashboard polls ~10 endpoints every 5s (~120/min) so keep headroom
RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "600"))
# Stricter rate limit for expensive LLM-backed endpoints (per-IP, per minute)
LLM_RATE_LIMIT_RPM: int = int(os.getenv("LLM_RATE_LIMIT_RPM", "30"))
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


# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------

def _parse_cors_origins() -> list[str]:
    """Parse allowed CORS origins from the environment.

    AGENTOP_CORS_ORIGINS accepts a comma-separated list of origins.
    Falls back to localhost:3007 (the default Next.js dashboard port) when
    the variable is unset so local development works out of the box.
    Wildcard '*' is explicitly rejected because we use allow_credentials=True.
    """
    raw = os.getenv("AGENTOP_CORS_ORIGINS", "")
    if not raw.strip():
        return ["http://localhost:3007", "http://127.0.0.1:3007"]
    origins: list[str] = []
    for origin in raw.split(","):
        origin = origin.strip()
        if origin == "*":
            # Wildcard is incompatible with credentials and is a security risk.
            # Silently skip it — callers must list origins explicitly.
            continue
        if origin:
            origins.append(origin)
    return origins or ["http://localhost:3007", "http://127.0.0.1:3007"]


CORS_ORIGINS: list[str] = _parse_cors_origins()

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
SCHEDULER_DB_PATH: Path = Path(os.getenv("SCHEDULER_DB_PATH", str(PROJECT_ROOT / "data" / "scheduler.db")))
WEBHOOKS_DB_PATH: Path = Path(os.getenv("WEBHOOKS_DB_PATH", str(PROJECT_ROOT / "data" / "webhooks.json")))

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

# ---------------------------------------------------------------------------
# Higgsfield MCP Server (headed Playwright browser on port 8812)
# ---------------------------------------------------------------------------
HF_MCP_PORT: int = int(os.getenv("HF_MCP_PORT", "8812"))

# ---------------------------------------------------------------------------
# Sandbox / Playbox Enforcement Configuration
# ---------------------------------------------------------------------------
SANDBOX_ENFORCEMENT_ENABLED: bool = os.getenv("SANDBOX_ENFORCEMENT_ENABLED", "true").lower() == "true"
SANDBOX_ROOT_DIR: Path = Path(os.getenv("SANDBOX_ROOT_DIR", "/tmp/ai-sandbox"))
PLAYBOX_DIR: Path = Path(os.getenv("PLAYBOX_DIR", str(PROJECT_ROOT / "data" / "playbox")))
LOCAL_LLM_REQUIRED_CHECKS: tuple[str, ...] = tuple(
    item.strip()
    for item in os.getenv(
        "LOCAL_LLM_REQUIRED_CHECKS",
        "tests_ok,playwright_ok,lighthouse_mobile_ok",
    ).split(",")
    if item.strip()
)
SANDBOX_FRONTEND_PORT_RANGE_START = int(os.getenv("SANDBOX_FRONTEND_PORT_RANGE_START", "3100"))
SANDBOX_FRONTEND_PORT_RANGE_END = int(os.getenv("SANDBOX_FRONTEND_PORT_RANGE_END", "3999"))
SANDBOX_BACKEND_PORT_RANGE_START = int(os.getenv("SANDBOX_BACKEND_PORT_RANGE_START", "8100"))
SANDBOX_BACKEND_PORT_RANGE_END = int(os.getenv("SANDBOX_BACKEND_PORT_RANGE_END", "8999"))
SANDBOX_DOCKER_ENABLED: bool = os.getenv("SANDBOX_DOCKER_ENABLED", "false").lower() == "true"
SANDBOX_DOCKER_IMAGE: str = os.getenv("SANDBOX_DOCKER_IMAGE", "agentop/sandbox:latest")
SANDBOX_DOCKER_NETWORK: str = os.getenv("SANDBOX_DOCKER_NETWORK", "none")
SANDBOX_DOCKER_MEM_LIMIT: str = os.getenv("SANDBOX_DOCKER_MEM_LIMIT", "1g")
SANDBOX_DOCKER_CPU_LIMIT: str = os.getenv("SANDBOX_DOCKER_CPU_LIMIT", "1.0")
SANDBOX_DOCKER_PIDS_LIMIT: int = int(os.getenv("SANDBOX_DOCKER_PIDS_LIMIT", "256"))
SANDBOX_DOCKER_READONLY_ROOTFS: bool = os.getenv("SANDBOX_DOCKER_READONLY_ROOTFS", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Canvas + A2UI (Feature 5)
# ---------------------------------------------------------------------------
# Maximum canvas events (render/replace/append/clear) per session lifetime
A2UI_MAX_EVENTS_PER_SESSION: int = int(os.getenv("A2UI_MAX_EVENTS_PER_SESSION", "200"))
# Maximum widgets per canvas target per session (prevents DOM flooding)
A2UI_MAX_WIDGETS_PER_TARGET: int = int(os.getenv("A2UI_MAX_WIDGETS_PER_TARGET", "50"))
# Agents allowed to emit A2UI events (empty = all agents)
A2UI_ALLOWED_AGENTS: list[str] = [
    a.strip()
    for a in os.getenv("A2UI_ALLOWED_AGENTS", "").split(",")
    if a.strip()
]

# Ensure required directories exist
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_ROOT_DIR.mkdir(parents=True, exist_ok=True)
PLAYBOX_DIR.mkdir(parents=True, exist_ok=True)
SCHEDULER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
WEBHOOKS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
