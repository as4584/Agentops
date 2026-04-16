"""
Configuration — Central configuration for the Agentop system.
==============================================================
All configuration is local-first. No cloud dependencies.
Environment variables override defaults for deployment flexibility.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

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
BROWSER_ALLOWED_AGENTS: list[str] = [a.strip() for a in os.getenv("BROWSER_ALLOWED_AGENTS", "").split(",") if a.strip()]

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
# GLM-OCR Configuration (local document/image → Markdown extraction)
# Run: python -m glmocr.server   (starts on GLMOCR_URL, default port 5002)
# ---------------------------------------------------------------------------
GLMOCR_URL: str = os.getenv("GLMOCR_URL", "http://localhost:5002")
GLMOCR_ENABLED: bool = os.getenv("GLMOCR_ENABLED", "true").lower() == "true"
GLMOCR_TIMEOUT: int = int(os.getenv("GLMOCR_TIMEOUT", "60"))

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
# Sprint 4: standardised on nomic-embed-text (768 dims) across all collections.
# The old default was 384 (all-MiniLM-L6-v2). If you switch embed models,
# update BOTH values AND recreate all Qdrant collections.
QDRANT_DEFAULT_DIM: int = int(os.getenv("QDRANT_DEFAULT_DIM", "768"))
# Sprint 2: explicit embedding model name — must be consistent with QDRANT_DEFAULT_DIM.
# Known pairings: nomic-embed-text → 768, all-MiniLM-L6-v2 → 384.
# Validated at startup via backend.knowledge.context_assembler.validate_embedding_startup().
QDRANT_EMBED_MODEL: str = os.getenv("QDRANT_EMBED_MODEL", "nomic-embed-text")
# Known dimension for common embedding models — used for startup dimension validation.
KNOWN_EMBED_DIMS: dict[str, int] = {
    "nomic-embed-text": 768,
    "all-minilm-l6-v2": 384,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
}

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
API_DOCS_ENABLED: bool = os.getenv("AGENTOP_ENABLE_API_DOCS", "false").lower() == "true"
# Maximum chat message size (bytes)
MAX_CHAT_MESSAGE_LENGTH: int = int(os.getenv("MAX_CHAT_MESSAGE_LENGTH", "8192"))
# Rate limit: max requests per minute per IP (0 = disabled)
# Dashboard polls ~10 endpoints every 5s (~120/min) so keep headroom
RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "600"))
# Stricter rate limit for expensive LLM-backed endpoints (per-IP, per minute)
LLM_RATE_LIMIT_RPM: int = int(os.getenv("LLM_RATE_LIMIT_RPM", "30"))
# Internal-only URL prefixes that webhook_send / health_check must NOT contact
SSRF_BLOCKED_PREFIXES: list[str] = [
    "http://169.254.",  # cloud metadata (AWS/GCP/Azure IMDS)
    "http://127.",  # loopback
    "http://localhost",  # loopback
    "http://0.0.0.0",  # wildcard loopback
    "http://[::1]",  # ipv6 loopback
    "http://10.",  # private RFC-1918 class A
    "http://172.16.",  # private RFC-1918 class B (172.16.0.0/12 — covers 172.16–172.31)
    "http://172.17.",  # Docker bridge default range
    "http://172.18.",
    "http://172.19.",
    "http://172.20.",
    "http://172.21.",
    "http://172.22.",
    "http://172.23.",
    "http://172.24.",
    "http://172.25.",
    "http://172.26.",
    "http://172.27.",
    "http://172.28.",
    "http://172.29.",
    "http://172.30.",
    "http://172.31.",
    "http://192.168.",  # private RFC-1918 class C
    "https://169.254.",
    "https://127.",
    "https://localhost",
    "https://0.0.0.0",
    "https://[::1]",
    "https://10.",
    "https://172.16.",
    "https://172.17.",
    "https://172.18.",
    "https://172.19.",
    "https://172.20.",
    "https://172.21.",
    "https://172.22.",
    "https://172.23.",
    "https://172.24.",
    "https://172.25.",
    "https://172.26.",
    "https://172.27.",
    "https://172.28.",
    "https://172.29.",
    "https://172.30.",
    "https://172.31.",
    "https://192.168.",
]

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_DIR: Path = BACKEND_DIR / "logs"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
MAX_LOG_ENTRIES: int = int(os.getenv("MAX_LOG_ENTRIES", "10000"))

# ---------------------------------------------------------------------------
# Sprint 2: ReAct runtime feature flags
# ---------------------------------------------------------------------------
# Set AGENT_RUNTIME_V2=true to enable the bounded ReAct loop for all agents.
# Leave unset (default false) to keep legacy single-pass behaviour as rollback.
AGENT_RUNTIME_V2: bool = os.getenv("AGENT_RUNTIME_V2", "true").lower() == "true"
# Maximum think/act/observe iterations per message in the v2 ReAct loop.
AGENT_MAX_STEPS: int = int(os.getenv("AGENT_MAX_STEPS", "8"))

# ---------------------------------------------------------------------------
# Sprint 3: Planner/executor/validator feature flags
# ---------------------------------------------------------------------------
# Enable the planner role (generates ExecutionPlan before executor loop) and
# validator role (produces ValidationReport after executor loop).
# Requires AGENT_RUNTIME_V2=true to have any effect.
AGENT_PLANNER_ENABLED: bool = os.getenv("AGENT_PLANNER_ENABLED", "false").lower() == "true"
# Risk threshold above which the high-risk validator model is used instead of routine.
# Values: LOW, MEDIUM, HIGH, CRITICAL
AGENT_VALIDATOR_HIGH_RISK_THRESHOLD: str = os.getenv("AGENT_VALIDATOR_HIGH_RISK_THRESHOLD", "HIGH")
# Per-step LLM timeout in seconds for each ReAct executor turn.
# Set to 0 to disable timeout enforcement.
AGENT_STEP_TIMEOUT_SECONDS: float = float(os.getenv("AGENT_STEP_TIMEOUT_SECONDS", "60"))

# ---------------------------------------------------------------------------
# GitNexus Code Intelligence (Sprint 5)
# ---------------------------------------------------------------------------
# Enable GitNexus MCP tools for code_review_agent, security_agent, devops_agent.
GITNEXUS_ENABLED: bool = os.getenv("GITNEXUS_ENABLED", "false").lower() == "true"
# Default indexed repo name (used by planner hints and tools when no repo is specified).
GITNEXUS_REPO_NAME: str = os.getenv("GITNEXUS_REPO_NAME", "Agentop")
# Hours after which the GitNexus index is considered stale (0 = never stale).
GITNEXUS_STALE_HOURS: int = int(os.getenv("GITNEXUS_STALE_HOURS", "24"))
# Whether the operator expects embeddings to be present in the index.
GITNEXUS_EXPECT_EMBEDDINGS: bool = os.getenv("GITNEXUS_EXPECT_EMBEDDINGS", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Tool Safety Configuration
# ---------------------------------------------------------------------------
# Whitelisted commands for safe_shell tool
SAFE_SHELL_WHITELIST: list[str] = [
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "df",
    "du",
    "free",
    "uptime",
    "whoami",
    "hostname",
    "date",
    "echo",
    "pwd",
    "env",
    "ps",
    "top",
    "uname",
    "id",
    "which",
    "file",
    "stat",
]

# Shell metacharacters that MUST NOT appear in commands (prevents chaining)
SHELL_DANGEROUS_CHARS: list[str] = [
    ";",
    "&&",
    "||",
    "|",
    "`",
    "$(",
    "${",
    "<(",
    ">(",
    "\n",
    ">>",
    ">",
    "<",
    "\\",
    "!",
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
        return [
            "http://localhost:3007",
            "http://127.0.0.1:3007",
            "http://localhost:3009",
            "http://127.0.0.1:3009",
        ]
    origins: list[str] = []
    for origin in raw.split(","):
        origin = origin.strip()
        if not origin:
            continue
        if origin == "*":
            raise ValueError(
                "AGENTOP_CORS_ORIGINS cannot contain '*'. Explicit origins are required when allow_credentials=True."
            )

        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Invalid origin '{origin}' in AGENTOP_CORS_ORIGINS. Expected absolute URL like http://localhost:3007"
            )
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                f"Invalid origin '{origin}' in AGENTOP_CORS_ORIGINS. Origins must not include paths, query, or fragments."
            )

        # Normalize trailing slash and de-duplicate while preserving order.
        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in origins:
            origins.append(normalized)
    return origins or [
        "http://localhost:3007",
        "http://127.0.0.1:3007",
        "http://localhost:3009",
        "http://127.0.0.1:3009",
    ]


CORS_ORIGINS: list[str] = _parse_cors_origins()

# Optional startup prewarm for the local knowledge vector index.
KNOWLEDGE_SEED_ON_STARTUP: bool = os.getenv("KNOWLEDGE_SEED_ON_STARTUP", "true").lower() == "true"
KNOWLEDGE_SEED_FORCE_REBUILD: bool = os.getenv("KNOWLEDGE_SEED_FORCE_REBUILD", "false").lower() == "true"

# Prohibited patterns for safe_shell
SAFE_SHELL_BLACKLIST: list[str] = [
    "rm -rf",
    "rm -r",
    "rm -f",
    "rm ",
    "rmdir",
    "mkfs",
    "dd ",
    "pip install",
    "npm install",
    "apt install",
    "brew install",
    "curl",
    "wget",
    "ssh",
    "scp",
    "sudo",
    "su ",
    "> /dev/",
    "chmod",
    "chown",
    "chgrp",
    "mv ",
    "cp ",
    "mkdir ",
    "touch ",
    "kill ",
    "pkill",
    "killall",
    "eval ",
    "exec ",
    "source ",
    "python",
    "node ",
    "ruby ",
    "perl ",
    "/etc/",
    "/proc/",
    "/sys/",
    "/dev/",
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
A2UI_ALLOWED_AGENTS: list[str] = [a.strip() for a in os.getenv("A2UI_ALLOWED_AGENTS", "").split(",") if a.strip()]

# Ensure required directories exist
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_ROOT_DIR.mkdir(parents=True, exist_ok=True)
PLAYBOX_DIR.mkdir(parents=True, exist_ok=True)
SCHEDULER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
WEBHOOKS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Deployment Mode (Sprint 1 — S1.1)
# ---------------------------------------------------------------------------
# The ONLY supported deployment mode for this program is "operator_only".
# No multi-user, no public SaaS, no RBAC is implemented or planned here.
# Setting any other value will cause validate_config() to raise.
AGENTOP_DEPLOYMENT_MODE: str = os.getenv("AGENTOP_DEPLOYMENT_MODE", "operator_only")

_SUPPORTED_DEPLOYMENT_MODES: frozenset[str] = frozenset({"operator_only"})


# ---------------------------------------------------------------------------
# Typed parse helpers (Sprint 1 — S1.1)
# ---------------------------------------------------------------------------


def _parse_positive_int(name: str, raw: str, min_val: int = 0) -> int:
    """Parse an integer env var and raise a clear ValueError on bad input."""
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"Config error: {name}={raw!r} is not a valid integer."
        ) from None
    if value < min_val:
        raise ValueError(
            f"Config error: {name}={value} must be >= {min_val}."
        )
    return value


def _parse_url(name: str, raw: str) -> str:
    """Parse a URL env var and raise a clear ValueError on bad input."""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"Config error: {name}={raw!r} is not a valid absolute URL (expected http:// or https://)."
        )
    return raw


def _is_loopback(host: str) -> bool:
    """Return True if the host string resolves to a loopback address."""
    return host in {"127.0.0.1", "::1", "localhost"}


# ---------------------------------------------------------------------------
# Configuration Validation (Sprint 1 — S1.1 / S1.2)
# ---------------------------------------------------------------------------


def validate_config() -> list[str]:
    """Validate the current configuration and return a list of error strings.

    Returns an empty list when the configuration is valid.
    Collects all errors rather than raising on the first one so the operator
    gets a complete picture on a single invocation.
    """
    errors: list[str] = []

    # --- Deployment mode -------------------------------------------------------
    if AGENTOP_DEPLOYMENT_MODE not in _SUPPORTED_DEPLOYMENT_MODES:
        errors.append(
            f"AGENTOP_DEPLOYMENT_MODE={AGENTOP_DEPLOYMENT_MODE!r} is not supported. "
            f"Supported values: {sorted(_SUPPORTED_DEPLOYMENT_MODES)}"
        )

    # --- Numeric bounds --------------------------------------------------------
    if BACKEND_PORT < 1 or BACKEND_PORT > 65535:
        errors.append(f"BACKEND_PORT={BACKEND_PORT} is outside the valid range 1–65535.")
    if RATE_LIMIT_RPM < 0:
        errors.append(f"RATE_LIMIT_RPM={RATE_LIMIT_RPM} must be >= 0.")
    if LLM_RATE_LIMIT_RPM < 0:
        errors.append(f"LLM_RATE_LIMIT_RPM={LLM_RATE_LIMIT_RPM} must be >= 0.")
    if MAX_CHAT_MESSAGE_LENGTH < 1:
        errors.append(f"MAX_CHAT_MESSAGE_LENGTH={MAX_CHAT_MESSAGE_LENGTH} must be >= 1.")

    # --- URL sanity ------------------------------------------------------------
    for name, url in [
        ("OLLAMA_BASE_URL", OLLAMA_BASE_URL),
        ("GLMOCR_URL", GLMOCR_URL),
        ("MCP_GATEWAY_URL", MCP_GATEWAY_URL),
    ]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{name}={url!r} is not a valid absolute URL.")

    # --- Cross-field operator-only safety (Sprint 1 — S1.2) -------------------
    if AGENTOP_DEPLOYMENT_MODE == "operator_only":
        # Non-loopback bind + no API secret is an unsafe combination.
        if not _is_loopback(BACKEND_HOST) and not API_SECRET:
            errors.append(
                "UNSAFE: BACKEND_HOST is non-loopback but AGENTOP_API_SECRET is empty. "
                "Set a strong secret before exposing the server on a network interface."
            )

        # API docs + non-loopback bind leaks internals.
        if API_DOCS_ENABLED and not _is_loopback(BACKEND_HOST):
            errors.append(
                "UNSAFE: AGENTOP_ENABLE_API_DOCS=true while BACKEND_HOST is non-loopback. "
                "Disable API docs or restrict binding to loopback before deploying."
            )

        # Non-local CORS origins require an explicit secret.
        non_local_cors = [
            o for o in CORS_ORIGINS
            if not any(o.startswith(p) for p in ("http://localhost", "https://localhost",
                                                   "http://127.", "https://127."))
        ]
        if non_local_cors and not API_SECRET:
            errors.append(
                f"UNSAFE: Non-local CORS origins {non_local_cors} are configured but "
                "AGENTOP_API_SECRET is empty. Set a secret to protect the API."
            )

    return errors


if __name__ == "__main__":
    import sys

    _args = sys.argv[1:]
    if _args and _args[0] == "validate":
        _errs = validate_config()
        if _errs:
            print("Config validation FAILED:")
            for _e in _errs:
                print(f"  [ERROR] {_e}")
            sys.exit(1)
        else:
            print("Config validation OK — operator_only defaults are safe.")
            sys.exit(0)

