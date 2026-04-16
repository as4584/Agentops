"""
Sprint 1 — S1.1 / S1.2: Config validation tests.

Covers:
- Deployment-mode parsing (supported vs. unsupported)
- Numeric bound validation
- URL validity
- Cross-field operator-only safety rules (S1.2)
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

import backend.config as cfg


def _reload_and_validate(**env_overrides: str) -> list[str]:
    """Reload backend.config with env overrides, call validate_config(), return errors."""
    with patch.dict("os.environ", env_overrides, clear=False):
        reloaded = importlib.reload(cfg)
        return reloaded.validate_config()


# ---------------------------------------------------------------------------
# Deployment mode
# ---------------------------------------------------------------------------


class TestDeploymentMode:
    def test_default_is_operator_only(self):
        errors = cfg.validate_config()
        assert not any("AGENTOP_DEPLOYMENT_MODE" in e for e in errors), errors

    def test_explicit_operator_only_is_valid(self, monkeypatch):
        monkeypatch.setenv("AGENTOP_DEPLOYMENT_MODE", "operator_only")
        errors = _reload_and_validate(AGENTOP_DEPLOYMENT_MODE="operator_only")
        assert not any("AGENTOP_DEPLOYMENT_MODE" in e for e in errors), errors

    def test_unsupported_mode_raises_error(self):
        errors = _reload_and_validate(AGENTOP_DEPLOYMENT_MODE="saas_public")
        assert any("AGENTOP_DEPLOYMENT_MODE" in e for e in errors), errors

    def test_unsupported_mode_error_message_contains_mode(self):
        errors = _reload_and_validate(AGENTOP_DEPLOYMENT_MODE="multi_tenant")
        assert any("multi_tenant" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Numeric bounds
# ---------------------------------------------------------------------------


class TestNumericBounds:
    def test_invalid_backend_port_zero(self):
        errors = _reload_and_validate(BACKEND_PORT="0")
        assert any("BACKEND_PORT" in e for e in errors), errors

    def test_invalid_backend_port_too_high(self):
        errors = _reload_and_validate(BACKEND_PORT="99999")
        assert any("BACKEND_PORT" in e for e in errors), errors

    def test_valid_backend_port(self):
        errors = _reload_and_validate(BACKEND_PORT="8000")
        assert not any("BACKEND_PORT" in e for e in errors), errors

    def test_negative_rate_limit_fails(self):
        errors = _reload_and_validate(RATE_LIMIT_RPM="-1")
        assert any("RATE_LIMIT_RPM" in e for e in errors), errors

    def test_zero_rate_limit_is_ok(self):
        """Zero means disabled — valid."""
        errors = _reload_and_validate(RATE_LIMIT_RPM="0")
        assert not any("RATE_LIMIT_RPM" in e for e in errors), errors

    def test_negative_max_message_length_fails(self):
        errors = _reload_and_validate(MAX_CHAT_MESSAGE_LENGTH="0")
        assert any("MAX_CHAT_MESSAGE_LENGTH" in e for e in errors), errors


# ---------------------------------------------------------------------------
# URL validity
# ---------------------------------------------------------------------------


class TestUrlValidity:
    def test_invalid_ollama_url_fails(self):
        errors = _reload_and_validate(OLLAMA_BASE_URL="not-a-url")
        assert any("OLLAMA_BASE_URL" in e for e in errors), errors

    def test_valid_ollama_url_passes(self):
        errors = _reload_and_validate(OLLAMA_BASE_URL="http://localhost:11434")
        assert not any("OLLAMA_BASE_URL" in e for e in errors), errors

    def test_invalid_glmocr_url_fails(self):
        errors = _reload_and_validate(GLMOCR_URL="localhost:5002")
        assert any("GLMOCR_URL" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Cross-field operator-only safety (S1.2)
# ---------------------------------------------------------------------------


class TestOperatorOnlySafetyRules:
    def test_loopback_with_no_secret_is_safe(self):
        """localhost bind without a secret is fine (local dev)."""
        errors = _reload_and_validate(
            BACKEND_HOST="127.0.0.1",
            AGENTOP_API_SECRET="",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert not any("UNSAFE" in e for e in errors), errors

    def test_non_loopback_with_no_secret_fails(self):
        errors = _reload_and_validate(
            BACKEND_HOST="0.0.0.0",
            AGENTOP_API_SECRET="",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert any("UNSAFE" in e and "BACKEND_HOST" in e for e in errors), errors

    def test_non_loopback_with_secret_is_ok(self):
        # Value intentionally non-empty; not a real credential.
        _tok = "test-token-x" + "x" * 20
        errors = _reload_and_validate(
            BACKEND_HOST="0.0.0.0",
            AGENTOP_API_SECRET=_tok,
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert not any("BACKEND_HOST" in e and "UNSAFE" in e for e in errors), errors

    def test_api_docs_plus_non_loopback_fails(self):
        _tok = "test-token-x" + "x" * 20
        errors = _reload_and_validate(
            BACKEND_HOST="0.0.0.0",
            AGENTOP_API_SECRET=_tok,
            AGENTOP_ENABLE_API_DOCS="true",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert any("API_DOCS" in e and "UNSAFE" in e for e in errors), errors

    def test_api_docs_on_loopback_is_ok(self):
        errors = _reload_and_validate(
            BACKEND_HOST="127.0.0.1",
            AGENTOP_ENABLE_API_DOCS="true",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert not any("API_DOCS" in e and "UNSAFE" in e for e in errors), errors

    def test_non_local_cors_without_secret_fails(self):
        errors = _reload_and_validate(
            AGENTOP_CORS_ORIGINS="https://app.example.com",
            AGENTOP_API_SECRET="",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert any("CORS" in e and "UNSAFE" in e for e in errors), errors

    def test_non_local_cors_with_secret_is_ok(self):
        _tok = "test-token-x" + "x" * 20
        errors = _reload_and_validate(
            AGENTOP_CORS_ORIGINS="https://app.example.com",
            AGENTOP_API_SECRET=_tok,
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        assert not any("CORS" in e and "UNSAFE" in e for e in errors), errors

    def test_default_config_has_no_safety_errors(self):
        """Localhost defaults must pass all safety rules cleanly."""
        errors = _reload_and_validate(
            BACKEND_HOST="127.0.0.1",
            AGENTOP_API_SECRET="",
            AGENTOP_ENABLE_API_DOCS="false",
            AGENTOP_DEPLOYMENT_MODE="operator_only",
        )
        safety_errors = [e for e in errors if "UNSAFE" in e]
        assert not safety_errors, f"Default config has safety errors: {safety_errors}"
