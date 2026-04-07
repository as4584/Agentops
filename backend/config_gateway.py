"""
Gateway Configuration — Settings for the Agentop AI Gateway.
=============================================================
All gateway settings with secure defaults.
Environment variables override defaults for deployment flexibility.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.config import BACKEND_DIR

# ---------------------------------------------------------------------------
# Feature Flag
# ---------------------------------------------------------------------------
GATEWAY_ENABLED: bool = os.getenv("GATEWAY_ENABLED", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Master Key — used to encrypt provider secrets at rest.
# MUST be set via AGENTOP_GATEWAY_MASTER_KEY env var.  No fallback.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
# ---------------------------------------------------------------------------
_master_key_raw: str = os.getenv("AGENTOP_GATEWAY_MASTER_KEY", "")
if not _master_key_raw:
    import warnings

    warnings.warn(
        "AGENTOP_GATEWAY_MASTER_KEY is not set. Gateway encryption disabled. "
        'Generate one: python -c "import secrets; print(secrets.token_hex(32))"',
        stacklevel=2,
    )

GATEWAY_MASTER_KEY: str = _master_key_raw

# ---------------------------------------------------------------------------
# Admin Secret — protects /admin/* endpoints.
# MUST be set via AGENTOP_ADMIN_SECRET env var when gateway is enabled.
# ---------------------------------------------------------------------------
GATEWAY_ADMIN_SECRET: str = os.getenv("AGENTOP_ADMIN_SECRET", "")
if GATEWAY_ENABLED and not GATEWAY_ADMIN_SECRET:
    import warnings

    warnings.warn(
        "AGENTOP_ADMIN_SECRET is not set. Gateway admin endpoints are unprotected. "
        "Set this env var before enabling the gateway in production.",
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Rate Limiting Backend
# ---------------------------------------------------------------------------
# "memory" — single-process in-memory (default, no infra required)
# "redis"  — Redis-backed (multi-process / distributed)
GATEWAY_RATE_LIMIT_BACKEND: str = os.getenv("GATEWAY_RATE_LIMIT_BACKEND", "memory")
GATEWAY_REDIS_URL: str = os.getenv("GATEWAY_REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Per-Key Default Quotas
# ---------------------------------------------------------------------------
GATEWAY_DEFAULT_QUOTA_RPM: int = int(os.getenv("GATEWAY_DEFAULT_QUOTA_RPM", "60"))
GATEWAY_DEFAULT_QUOTA_TPM: int = int(os.getenv("GATEWAY_DEFAULT_QUOTA_TPM", "100000"))
GATEWAY_DEFAULT_QUOTA_TPD: int = int(os.getenv("GATEWAY_DEFAULT_QUOTA_TPD", "1000000"))
GATEWAY_DEFAULT_QUOTA_DAILY_USD: float = float(os.getenv("GATEWAY_DEFAULT_QUOTA_DAILY_USD", "5.0"))
GATEWAY_DEFAULT_QUOTA_MONTHLY_USD: float = float(os.getenv("GATEWAY_DEFAULT_QUOTA_MONTHLY_USD", "50.0"))

# ---------------------------------------------------------------------------
# Request Validation
# ---------------------------------------------------------------------------
GATEWAY_MAX_PROMPT_LENGTH: int = int(os.getenv("GATEWAY_MAX_PROMPT_LENGTH", "32768"))
GATEWAY_MAX_MESSAGES: int = int(os.getenv("GATEWAY_MAX_MESSAGES", "100"))
GATEWAY_MAX_RESPONSE_TOKENS: int = int(os.getenv("GATEWAY_MAX_RESPONSE_TOKENS", "16384"))

# ---------------------------------------------------------------------------
# Audit / Logging
# ---------------------------------------------------------------------------
GATEWAY_AUDIT_LOG_PATH: Path = Path(os.getenv("GATEWAY_AUDIT_LOG_PATH", str(BACKEND_DIR / "logs" / "gateway.jsonl")))
GATEWAY_AUDIT_RETENTION_DAYS: int = int(os.getenv("GATEWAY_AUDIT_RETENTION_DAYS", "90"))
# Set to "1" to emit prompts/completions in debug stream (NEVER in production!)
GATEWAY_DEBUG_LOG_CONTENT: bool = os.getenv("GATEWAY_DEBUG_LOG_CONTENT", "0") == "1"

# ---------------------------------------------------------------------------
# Provider Secrets Storage
# ---------------------------------------------------------------------------
GATEWAY_SECRETS_PATH: Path = Path(
    os.getenv("GATEWAY_SECRETS_PATH", str(BACKEND_DIR / "memory" / "gateway_secrets.enc"))
)

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
GATEWAY_CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("GATEWAY_CIRCUIT_BREAKER_THRESHOLD", "5"))
GATEWAY_CIRCUIT_BREAKER_TIMEOUT: int = int(os.getenv("GATEWAY_CIRCUIT_BREAKER_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# Provider Fallback Order
# ---------------------------------------------------------------------------
# Providers tried in order when primary is unavailable
GATEWAY_FALLBACK_ORDER: list[str] = [
    p.strip() for p in os.getenv("GATEWAY_FALLBACK_ORDER", "openrouter,openai,anthropic,ollama").split(",") if p.strip()
]

# Ensure log directory exists
GATEWAY_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
GATEWAY_SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
