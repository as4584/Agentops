"""
WebGen Gallery — Versioned archive of generated websites.
==========================================================
Stores iterations by (business_slug, version, model) so we can compare
quality over time and identify the "art" worth keeping.

Each gallery entry is a copy of the output directory + a manifest.json:
  output/webgen/gallery/{slug}__v{N}__{model}/
    manifest.json     ← scores, model, timestamp, notes
    index.html, ...   ← copy of generated site
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from backend.config import PROJECT_ROOT

GALLERY_ROOT = PROJECT_ROOT / "output" / "webgen" / "gallery"


def _model_safe(model_name: str) -> str:
    """Convert model name to filesystem-safe string."""
    return model_name.replace(":", "_").replace("/", "_").replace(" ", "-")


def save_iteration(
    output_dir: str | Path,
    business_slug: str,
    model_name: str,
    ux_scores: dict[str, int],
    design_style: str = "",
    notes: str = "",
) -> Path:
    """
    Copy a generated site to the gallery with version metadata.

    Versions are auto-incremented per (business_slug, model) pair.
    Returns the gallery directory path.
    """
    GALLERY_ROOT.mkdir(parents=True, exist_ok=True)

    model_safe = _model_safe(model_name)
    pattern = f"{business_slug}__v*__{model_safe}"
    existing = list(GALLERY_ROOT.glob(pattern))
    version = len(existing) + 1

    dest_name = f"{business_slug}__v{version}__{model_safe}"
    dest = GALLERY_ROOT / dest_name

    src = Path(output_dir)
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=False)
    else:
        dest.mkdir(parents=True, exist_ok=True)

    avg_score = sum(ux_scores.values()) // len(ux_scores) if ux_scores else 0

    manifest = {
        "business_slug": business_slug,
        "version": version,
        "model": model_name,
        "design_style": design_style,
        "ux_scores": ux_scores,
        "avg_ux_score": avg_score,
        "notes": notes,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "source_dir": str(output_dir),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return dest


def list_gallery() -> list[dict]:
    """List all gallery iterations sorted by timestamp descending."""
    if not GALLERY_ROOT.exists():
        return []

    manifests = []
    for manifest_path in GALLERY_ROOT.glob("*/manifest.json"):
        try:
            data = json.loads(manifest_path.read_text())
            data["gallery_dir"] = str(manifest_path.parent)
            manifests.append(data)
        except Exception:
            pass

    return sorted(manifests, key=lambda d: d.get("timestamp", ""), reverse=True)


def get_best_iteration(business_slug: str) -> dict | None:
    """Return the gallery entry with the highest avg UX score for a given business."""
    items = [d for d in list_gallery() if d.get("business_slug") == business_slug]
    if not items:
        return None
    return max(items, key=lambda d: d.get("avg_ux_score", 0))
