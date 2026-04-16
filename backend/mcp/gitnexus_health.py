"""
GitNexus health inspection — Sprint 2 S2.2.

Reads .gitnexus/meta.json, derives staleness, and returns a GitNexusHealthState.
Completely side-effect-free: never modifies files, never contacts the network.
Callers should treat the returned state as a snapshot; re-call to refresh.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import (
    GITNEXUS_ENABLED,
    GITNEXUS_EXPECT_EMBEDDINGS,
    GITNEXUS_REPO_NAME,
    GITNEXUS_STALE_HOURS,
    PROJECT_ROOT,
)
from backend.models import GitNexusHealthState
from backend.utils import logger

# Canonical path to the GitNexus index metadata file.
_META_PATH: Path = PROJECT_ROOT / ".gitnexus" / "meta.json"


def _transport_available() -> bool:
    """Return True if the docker-mcp CLI binary is present on PATH."""
    return shutil.which("docker") is not None


def _read_meta() -> dict[str, Any] | None:
    """Read .gitnexus/meta.json and return parsed dict, or None on any failure."""
    try:
        raw = _META_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning("[GitNexus] meta.json is not a JSON object — treating as missing")
            return None
        return data
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        logger.warning(f"[GitNexus] meta.json parse error: {exc} — treating as missing")
        return None
    except OSError as exc:
        logger.warning(f"[GitNexus] meta.json read error: {exc}")
        return None


def _compute_stale(last_analyzed_at: str, stale_hours: int) -> bool:
    """Return True if the index was last analyzed more than stale_hours ago."""
    if stale_hours <= 0 or not last_analyzed_at:
        return False
    try:
        last = datetime.fromisoformat(last_analyzed_at.rstrip("Z")).replace(tzinfo=UTC)
        now = datetime.now(tz=UTC)
        age_hours = (now - last).total_seconds() / 3600
        return age_hours > stale_hours
    except (ValueError, OverflowError):
        return False


def get_gitnexus_health() -> GitNexusHealthState:
    """Return a snapshot of the current GitNexus health state.

    Always returns a valid GitNexusHealthState; never raises.
    """
    if not GITNEXUS_ENABLED:
        return GitNexusHealthState(
            enabled=False,
            repo_name=GITNEXUS_REPO_NAME,
            stale_hours=GITNEXUS_STALE_HOURS,
            reason="GitNexus is disabled (GITNEXUS_ENABLED=false).",
        )

    transport_ok = _transport_available()
    meta = _read_meta()

    if not meta:
        return GitNexusHealthState(
            enabled=True,
            transport_available=transport_ok,
            repo_name=GITNEXUS_REPO_NAME,
            index_exists=False,
            stale_hours=GITNEXUS_STALE_HOURS,
            reason="Index not found (.gitnexus/meta.json missing or unreadable). Run: npx gitnexus analyze",
        )

    stats: dict[str, Any] = meta.get("stats", {})
    symbol_count: int = int(stats.get("symbols", 0))
    relationship_count: int = int(stats.get("relationships", 0))
    embeddings_count: int = int(stats.get("embeddings", 0))
    embeddings_present: bool = embeddings_count > 0
    last_analyzed_at: str = meta.get("analyzedAt", meta.get("analyzed_at", ""))
    stale = _compute_stale(last_analyzed_at, GITNEXUS_STALE_HOURS)

    reasons: list[str] = []
    if not transport_ok:
        reasons.append("docker CLI not found on PATH.")
    if stale:
        reasons.append(
            f"Index is stale (last analyzed: {last_analyzed_at or 'unknown'}, "
            f"threshold: {GITNEXUS_STALE_HOURS}h). Run: npx gitnexus analyze"
        )
    if GITNEXUS_EXPECT_EMBEDDINGS and not embeddings_present:
        reasons.append(
            "Embeddings expected (GITNEXUS_EXPECT_EMBEDDINGS=true) but index has 0 embeddings. "
            "Run: npx gitnexus analyze --embeddings"
        )

    return GitNexusHealthState(
        enabled=True,
        transport_available=transport_ok,
        repo_name=GITNEXUS_REPO_NAME,
        index_exists=True,
        symbol_count=symbol_count,
        relationship_count=relationship_count,
        embeddings_present=embeddings_present,
        last_analyzed_at=last_analyzed_at,
        stale=stale,
        stale_hours=GITNEXUS_STALE_HOURS,
        reason="; ".join(reasons),
    )
