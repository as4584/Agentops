"""
Studio Routes — Agentop
========================
Video editing pipeline: upload → transcribe → edit captions → export.

Endpoints:
    POST /studio/upload          — upload a video file
    POST /studio/transcribe      — run Whisper on an uploaded video
    GET  /studio/jobs            — list all studio jobs
    GET  /studio/jobs/{job_id}   — get job status + transcript
    POST /studio/export          — burn captions and export final video
    GET  /studio/exports/{name}  — download an exported video
    DELETE /studio/jobs/{job_id} — delete a job and its files
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.config import PROJECT_ROOT

logger = logging.getLogger("agentop.studio")

router = APIRouter(prefix="/studio", tags=["studio"])

UPLOAD_DIR = PROJECT_ROOT / "data" / "studio" / "uploads"
EXPORT_DIR = PROJECT_ROOT / "data" / "studio" / "exports"
JOBS_DIR = PROJECT_ROOT / "data" / "studio" / "jobs"

for _d in (UPLOAD_DIR, EXPORT_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Job store (file-backed JSON)
# ---------------------------------------------------------------------------


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _save_job(job: dict) -> None:
    _job_path(job["id"]).write_text(json.dumps(job, indent=2))


def _load_job(job_id: str) -> dict:
    p = _job_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return json.loads(p.read_text())


def _list_jobs() -> list[dict]:
    jobs = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            jobs.append(json.loads(p.read_text()))
        except Exception:
            pass
    return jobs


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
    "video/x-matroska",
}
MAX_UPLOAD_MB = 500


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)) -> dict:
    """Upload a video file and create a studio job."""
    if file.content_type and file.content_type not in ALLOWED_VIDEO_TYPES:
        # Be lenient — browsers sometimes send wrong content types
        logger.warning(f"[Studio] Unexpected content_type={file.content_type}, allowing anyway")

    job_id = uuid.uuid4().hex[:12]
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_path = UPLOAD_DIR / f"{job_id}{suffix}"

    # Stream to disk
    size = 0
    with open(video_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                video_path.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")
            f.write(chunk)

    job = {
        "id": job_id,
        "status": "uploaded",
        "filename": file.filename,
        "video_path": str(video_path),
        "transcript": None,
        "export_path": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
    }
    _save_job(job)
    logger.info(f"[Studio] Uploaded {file.filename} → job={job_id} ({size // 1024}KB)")
    return {"job_id": job_id, "status": "uploaded", "size_bytes": size}


# ---------------------------------------------------------------------------
# Transcribe
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    job_id: str
    model: str = "base"  # tiny | base | small | medium


def _run_transcribe(job_id: str, model: str) -> None:
    """Background task: run Whisper transcription."""
    job = _load_job(job_id)
    job["status"] = "transcribing"
    job["updated_at"] = time.time()
    _save_job(job)

    try:
        import os

        os.environ.setdefault("WHISPER_MODEL", model)
        from backend.video.transcriber import transcribe

        transcript = transcribe(job["video_path"])
        job["transcript"] = transcript
        job["status"] = "transcribed"
        logger.info(f"[Studio] Transcribed job={job_id} — {len(transcript['segments'])} segments")
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        logger.exception(f"[Studio] Transcription failed for job={job_id}")

    job["updated_at"] = time.time()
    _save_job(job)


@router.post("/transcribe")
async def transcribe_video(req: TranscribeRequest, bg: BackgroundTasks) -> dict:
    """Start Whisper transcription for an uploaded video."""
    job = _load_job(req.job_id)
    if job["status"] not in ("uploaded", "transcribed", "error"):
        raise HTTPException(400, f"Job is {job['status']}, cannot re-transcribe now")

    bg.add_task(_run_transcribe, req.job_id, req.model)
    return {"job_id": req.job_id, "status": "transcribing"}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs() -> dict:
    return {"jobs": _list_jobs()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    return _load_job(job_id)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    job = _load_job(job_id)
    for key in ("video_path", "export_path"):
        p = job.get(key)
        if p:
            Path(p).unlink(missing_ok=True)
    _job_path(job_id).unlink(missing_ok=True)
    return {"deleted": job_id}


# ---------------------------------------------------------------------------
# Transcript edit (save edited captions back to job)
# ---------------------------------------------------------------------------


class SaveTranscriptRequest(BaseModel):
    job_id: str
    transcript: dict  # full transcript object with segments + words


@router.post("/transcript/save")
async def save_transcript(req: SaveTranscriptRequest) -> dict:
    """Save edited transcript back to the job (user can fix words before export)."""
    job = _load_job(req.job_id)
    job["transcript"] = req.transcript
    job["updated_at"] = time.time()
    _save_job(job)
    return {"job_id": req.job_id, "saved": True}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class ExportRequest(BaseModel):
    job_id: str
    crop_to_vertical: bool = True  # 9:16 for Reels
    words_per_chunk: int = 3
    font_size: int = 22
    highlight_color: str = "&H0000CFFF"  # ASS hex — default yellow
    font_name: str = "Arial"


def _run_export(job_id: str, req_dict: dict) -> None:
    """Background task: burn captions into video."""
    job = _load_job(job_id)
    job["status"] = "exporting"
    job["updated_at"] = time.time()
    _save_job(job)

    try:
        from backend.video.caption_burner import DEFAULT_STYLE, burn_captions

        style = {
            **DEFAULT_STYLE,
            "words_per_chunk": req_dict["words_per_chunk"],
            "font_size": req_dict["font_size"],
            "highlight_color": req_dict["highlight_color"],
            "font_name": req_dict["font_name"],
        }

        output_name = f"{job_id}_captioned.mp4"
        output_path = EXPORT_DIR / output_name

        burn_captions(
            video_path=job["video_path"],
            transcript=job["transcript"],
            output_path=output_path,
            style=style,
            crop_to_vertical=req_dict["crop_to_vertical"],
        )

        job["export_path"] = str(output_path)
        job["export_filename"] = output_name
        job["status"] = "done"
        logger.info(f"[Studio] Export done → {output_path}")
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        logger.exception(f"[Studio] Export failed for job={job_id}")

    job["updated_at"] = time.time()
    _save_job(job)


@router.post("/export")
async def export_video(req: ExportRequest, bg: BackgroundTasks) -> dict:
    """Burn captions into video and export."""
    job = _load_job(req.job_id)
    if job["status"] not in ("transcribed", "done", "error"):
        raise HTTPException(400, f"Job must be transcribed before export (status={job['status']})")
    if not job.get("transcript"):
        raise HTTPException(400, "No transcript found — transcribe the video first")

    bg.add_task(_run_export, req.job_id, req.model_dump())
    return {"job_id": req.job_id, "status": "exporting"}


# ---------------------------------------------------------------------------
# Download export
# ---------------------------------------------------------------------------


@router.get("/exports/{filename}")
async def download_export(filename: str) -> FileResponse:
    path = EXPORT_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Export not found")
    # Safety: prevent path traversal
    if EXPORT_DIR not in path.parents and path.parent != EXPORT_DIR:
        raise HTTPException(403, "Forbidden")
    return FileResponse(str(path), media_type="video/mp4", filename=filename)
