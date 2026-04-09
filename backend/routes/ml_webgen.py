"""
ML WebGen routes — gallery browser, site file serving, generation trigger, human preference recording.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.config import PROJECT_ROOT
from backend.utils import logger
from backend.webgen.gallery import list_gallery, save_iteration
from backend.webgen.models import ClientBrief
from backend.webgen.pipeline import WebGenPipeline

router = APIRouter(prefix="/ml/webgen", tags=["ml-webgen"])

GALLERY_ROOT = PROJECT_ROOT / "output" / "webgen" / "gallery"
DPO_DIR = PROJECT_ROOT / "data" / "dpo"


# ── Models ──────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    business_name: str
    business_type: str = "general"
    design_style: str = "premium"


class PreferenceRequest(BaseModel):
    winner_entry: str  # gallery folder name, e.g. "apex-fitness-studio__v2__llama3.2"
    loser_entry: str
    business_slug: str
    judge: str = "human"


class GradeRequest(BaseModel):
    project_id: str  # folder slug from /projects (output/webgen/<slug>)
    overall: int  # 1-10
    visual_quality: int  # 1-10
    clarity: int  # 1-10
    conversion: int  # 1-10
    mobile: int  # 1-10
    pass_fail: bool
    notes: str = ""
    reviewer: str = "human"


class ReviewRequest(BaseModel):
    project_id: str
    business_slug: str
    overall_score: int  # 1-10
    visual_quality: int  # 1-10
    clarity: int  # 1-10
    conversion_strength: int  # 1-10
    mobile_confidence: int  # 1-10
    pass_fail: bool
    notes: str = ""
    reviewer: str = "human"


# ── Gallery ──────────────────────────────────────────────────────────────────


@router.get("/gallery")
async def get_gallery() -> list[dict]:
    """List all gallery iterations sorted by newest first."""
    return list_gallery()


# ── Static file serving (iframes) ────────────────────────────────────────────


@router.get("/site/{entry_name}/{filepath:path}")
async def serve_site_file(entry_name: str, filepath: str) -> Response:
    """Serve a file from a gallery entry so iframes can load HTML/CSS/JS."""
    # Security: ensure we stay inside GALLERY_ROOT
    safe_entry = Path(entry_name).name  # strip any path traversal
    target = (GALLERY_ROOT / safe_entry / filepath).resolve()

    try:
        target.relative_to(GALLERY_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")

    content_type, _ = mimetypes.guess_type(str(target))
    content_type = content_type or "application/octet-stream"

    return Response(content=target.read_bytes(), media_type=content_type)


# ── Generate ─────────────────────────────────────────────────────────────────


@router.post("/generate")
async def generate_site(req: GenerateRequest) -> dict:
    """
    Trigger a full WebGen pipeline run for the given business.
    Runs synchronously (~60s) and returns the gallery manifest on completion.
    """
    logger.info(f"[ml_webgen] Generating site for: {req.business_name}")

    brief = ClientBrief(
        business_name=req.business_name,
        business_type=req.business_type,  # type: ignore[arg-type]
        design_style=req.design_style,  # type: ignore[call-arg]
    )

    pipeline = WebGenPipeline()
    project = await pipeline.quick_generate(brief)

    if not project.output_dir:
        raise HTTPException(status_code=500, detail="Pipeline did not produce an output directory")

    ux_scores = {page.slug: page.ux_score for page in project.pages if page.ux_score is not None}  # type: ignore[attr-defined]

    gallery_dir = save_iteration(
        output_dir=project.output_dir,
        business_slug=project.slug,  # type: ignore[attr-defined]
        model_name=pipeline.llm.model if pipeline.llm else "unknown",
        ux_scores=ux_scores,
        design_style=req.design_style,
    )

    # Return the fresh manifest
    manifest_path = gallery_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest["gallery_dir"] = str(gallery_dir)
    manifest["entry_name"] = gallery_dir.name

    return manifest


# ── Human preference ─────────────────────────────────────────────────────────


@router.post("/preference")
async def record_preference(req: PreferenceRequest) -> dict:
    """
    Record a human preference judgment as a DPO training pair.
    winner_entry is the site the user judged as better.
    loser_entry is the version it beat (or was worse than).
    """
    DPO_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    dpo_file = DPO_DIR / f"human_pref_{ts}.jsonl"

    pair = {
        "category": "webgen_human_preference",
        "business_slug": req.business_slug,
        "winner_entry": req.winner_entry,
        "loser_entry": req.loser_entry,
        "judge": req.judge,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "why_winner": "human visual judgment — thumbs up",
        "why_loser": "human visual judgment — thumbs down",
    }

    dpo_file.write_text(json.dumps(pair) + "\n")
    logger.info(f"[ml_webgen] DPO preference recorded: {dpo_file.name}")

    return {"status": "recorded", "file": dpo_file.name}


# ── Single-project human grade ────────────────────────────────────────────────

REVIEWS_DIR = PROJECT_ROOT / "data" / "reviews"


@router.post("/grade")
async def grade_project(req: GradeRequest) -> dict:
    """
    Record a human quality grade for a single WebGen project.
    Persisted to data/reviews/ as JSONL — reusable for eval and training.
    """
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    review_file = REVIEWS_DIR / f"webgen_review_{req.project_id}_{ts}.jsonl"

    record = {
        "project_id": req.project_id,
        "overall": req.overall,
        "visual_quality": req.visual_quality,
        "clarity": req.clarity,
        "conversion": req.conversion,
        "mobile": req.mobile,
        "pass_fail": req.pass_fail,
        "notes": req.notes,
        "reviewer": req.reviewer,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }

    review_file.write_text(json.dumps(record) + "\n")
    logger.info(f"[ml_webgen] Grade recorded for {req.project_id}: {req.overall}/10")

    return {"status": "recorded", "file": review_file.name, "grade": record}


@router.get("/grade/{project_id}")
async def get_project_grades(project_id: str) -> dict:
    """Fetch all human grades for a given project_id."""
    grades: list[dict] = []
    if REVIEWS_DIR.exists():
        for f in sorted(REVIEWS_DIR.glob(f"webgen_review_{project_id}_*.jsonl")):
            try:
                grades.append(json.loads(f.read_text().strip()))
            except Exception:
                pass
    return {"project_id": project_id, "grades": grades, "count": len(grades)}


# ── Single-project human review ───────────────────────────────────────────────

_REVIEWS_DIR = PROJECT_ROOT / "data" / "reviews"


@router.post("/review")
async def record_review(req: ReviewRequest) -> dict:
    """
    Record a single-project human review as structured evaluation data.
    Fields feed into the eval pipeline and can be converted to DPO pairs later.
    """
    _REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    review_file = _REVIEWS_DIR / f"webgen_review_{req.project_id}_{ts}.json"

    review = {
        "project_id": req.project_id,
        "business_slug": req.business_slug,
        "overall_score": req.overall_score,
        "visual_quality": req.visual_quality,
        "clarity": req.clarity,
        "conversion_strength": req.conversion_strength,
        "mobile_confidence": req.mobile_confidence,
        "pass_fail": req.pass_fail,
        "notes": req.notes,
        "reviewer": req.reviewer,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }

    review_file.write_text(json.dumps(review, indent=2))
    logger.info(f"[ml_webgen] Review recorded: {review_file.name}")

    return {"status": "recorded", "file": review_file.name}
