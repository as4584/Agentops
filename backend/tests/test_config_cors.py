from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "localhost:3007",
        "http://localhost:3007/path",
        "https://localhost:3007?x=1",
        "https://localhost:3007#frag",
    ],
)
def test_cors_invalid_values_fail_fast(monkeypatch, value: str):
    monkeypatch.setenv("AGENTOP_CORS_ORIGINS", value)

    with pytest.raises(ValueError):
        import backend.config as cfg

        importlib.reload(cfg)


def test_cors_valid_values_are_normalized_and_deduped(monkeypatch):
    monkeypatch.setenv(
        "AGENTOP_CORS_ORIGINS",
        "http://localhost:3007/, https://127.0.0.1:3007, http://localhost:3007",
    )

    import backend.config as cfg

    reloaded = importlib.reload(cfg)
    assert reloaded.CORS_ORIGINS == ["http://localhost:3007", "https://127.0.0.1:3007"]
