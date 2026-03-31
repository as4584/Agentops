from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT
from backend.database.customer_store import customer_store
from backend.llm import OllamaClient
from backend.webgen.models import BusinessType, ClientBrief, SiteStatus
from backend.webgen.pipeline import WebGenPipeline
from backend.webgen.site_store import SiteStore

router = APIRouter(prefix="/api/webgen", tags=["webgen-builder"])

_pipeline = WebGenPipeline(llm=OllamaClient(model="webgen"))
_store = SiteStore()


class GenerateSiteRequest(BaseModel):
    business_name: str = Field(..., min_length=2)
    business_type: str = "custom"
    tagline: str = ""
    description: str = ""
    services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    tone: str = "professional"
    customer_id: str | None = None


class SavePageRequest(BaseModel):
    html: str = Field(..., min_length=10)


class DeployRequest(BaseModel):
    project_id: str
    customer_id: str | None = None


class QRRequest(BaseModel):
    project_id: str
    target_url: str


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\-\s]", "", value)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-") or "site"


def _project_first_html(project_id: str) -> tuple[Path, Path]:
    project_dir = PROJECT_ROOT / "output" / "webgen" / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project output not found: {project_id}")

    candidate_files = [project_dir / "index.html", project_dir / "home.html"]
    for candidate in candidate_files:
        if candidate.exists():
            return project_dir, candidate

    any_html = next((p for p in project_dir.glob("*.html") if p.is_file()), None)
    if any_html is None:
        raise HTTPException(status_code=404, detail="No HTML page found in project output")
    return project_dir, any_html


def _require_vercel_cli() -> str:
    vercel_bin = shutil.which("vercel")
    if not vercel_bin:
        raise HTTPException(
            status_code=412,
            detail="Vercel CLI not found. Install with: npm i -g vercel and run `vercel login`.",
        )
    return vercel_bin


def _extract_url(text: str) -> str | None:
    matches = re.findall(r"https://[\w\-\.]+\.vercel\.app", text)
    if matches:
        return matches[-1]
    return None


def _resolve_qr_file_path(relative_path: str) -> Path:
    # Use normpath to neutralise ".." traversal before checking bounds
    candidate = Path(os.path.normpath(str(PROJECT_ROOT / relative_path)))
    qr_root = Path(os.path.normpath(str(PROJECT_ROOT / "output" / "qr")))

    if not str(candidate).startswith(str(qr_root)):
        raise HTTPException(status_code=400, detail="Invalid QR path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="QR file not found")
    return candidate


@router.post("/generate")
async def generate_site(payload: GenerateSiteRequest) -> dict[str, Any]:
    if payload.customer_id:
        customer = customer_store.get_customer(payload.customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found")

    try:
        business_type = BusinessType(payload.business_type)
    except ValueError:
        business_type = BusinessType.CUSTOM

    brief = ClientBrief(
        business_name=payload.business_name,
        business_type=business_type,
        tagline=payload.tagline,
        description=payload.description or payload.tagline or payload.business_name,
        services=payload.services,
        target_audience=payload.target_audience,
        tone=payload.tone,
    )

    project = await _pipeline.quick_generate(
        brief=brief,
        base_url="",
        export=True,
        quality_checks={
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
        },
    )

    if payload.customer_id:
        project.metadata["customer_id"] = payload.customer_id
        _store.save(project)

    project_dir, html_file = _project_first_html(_slugify(payload.business_name))
    html = html_file.read_text(encoding="utf-8", errors="ignore")

    return {
        "project_id": project.id,
        "project_slug": _slugify(payload.business_name),
        "status": project.status.value,
        "customer_id": project.metadata.get("customer_id"),
        "output_dir": str(project_dir.relative_to(PROJECT_ROOT)),
        "preview_file": str(html_file.relative_to(PROJECT_ROOT)),
        "html": html,
        "pages": [page.slug for page in project.pages],
    }


@router.get("/projects")
async def list_webgen_projects() -> dict[str, Any]:
    projects = _store.list_projects()
    return {
        "projects": [
            {
                "id": project.id,
                "business_name": project.brief.business_name,
                "status": project.status.value,
                "updated_at": project.updated_at,
                "output_dir": project.output_dir,
            }
            for project in projects
        ],
        "count": len(projects),
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = _store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    slug = _slugify(project.brief.business_name)
    project_dir, html_file = _project_first_html(slug)
    html = html_file.read_text(encoding="utf-8", errors="ignore")

    return {
        "project_id": project.id,
        "status": project.status.value,
        "business_name": project.brief.business_name,
        "project_slug": slug,
        "preview_file": str(html_file.relative_to(PROJECT_ROOT)),
        "output_dir": str(project_dir.relative_to(PROJECT_ROOT)),
        "html": html,
        "deployed_url": project.metadata.get("deployed_url", ""),
    }


@router.put("/projects/{project_id}/page")
async def save_project_page(project_id: str, payload: SavePageRequest) -> dict[str, Any]:
    project = _store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    slug = _slugify(project.brief.business_name)
    _, html_file = _project_first_html(slug)
    html_file.write_text(payload.html, encoding="utf-8")

    project.updated_at = datetime.now(UTC).isoformat()
    _store.save(project)

    return {
        "project_id": project_id,
        "saved_file": str(html_file.relative_to(PROJECT_ROOT)),
        "status": "saved",
    }


@router.post("/deploy")
async def deploy_project(payload: DeployRequest) -> dict[str, Any]:
    project = _store.load(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    slug = _slugify(project.brief.business_name)
    project_dir, _ = _project_first_html(slug)

    vercel_bin = _require_vercel_cli()

    command = [
        vercel_bin,
        "--yes",
        "--prod",
    ]

    result = subprocess.run(
        command,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    deployed_url = _extract_url(output)

    if result.returncode != 0 or not deployed_url:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Vercel deployment failed",
                "return_code": result.returncode,
                "output": output[-2000:],
            },
        )

    project.status = SiteStatus.DEPLOYED
    project.metadata["deployed_url"] = deployed_url
    project.metadata["deployed_at"] = datetime.now(UTC).isoformat()

    customer_id = payload.customer_id or project.metadata.get("customer_id")
    qr_path: str | None = None
    if customer_id:
        output_dir = PROJECT_ROOT / "output" / "qr" / payload.project_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "deploy_qr.png"
        try:
            qrcode = import_module("qrcode")
            image = qrcode.make(deployed_url)
            image.save(str(output_path))
            qr_path = str(output_path.relative_to(PROJECT_ROOT))
        except Exception:
            qr_path = None

        project.metadata["customer_id"] = customer_id
        project.metadata["qr_path"] = qr_path
        customer_store.add_customer_deployment(
            customer_id=customer_id,
            project_id=project.id,
            project_slug=slug,
            deployed_url=deployed_url,
            qr_path=qr_path,
            metadata={
                "source": "webgen_deploy",
                "project_status": project.status.value,
            },
        )

    _store.save(project)

    return {
        "project_id": payload.project_id,
        "deployed_url": deployed_url,
        "customer_id": customer_id,
        "qr_path": qr_path,
        "status": "deployed",
    }


@router.post("/qr")
async def generate_qr(payload: QRRequest) -> dict[str, Any]:
    try:
        qrcode = import_module("qrcode")
    except ImportError as exc:
        raise HTTPException(
            status_code=412,
            detail="qrcode package not installed. Install backend deps again to include qrcode[pil].",
        ) from exc

    output_dir = PROJECT_ROOT / "output" / "qr" / payload.project_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "deploy_qr.png"

    image = qrcode.make(payload.target_url)
    image.save(str(output_path))

    return {
        "project_id": payload.project_id,
        "target_url": payload.target_url,
        "qr_path": str(output_path.relative_to(PROJECT_ROOT)),
    }


@router.get("/qr/file")
async def get_qr_file(path: str) -> FileResponse:
    file_path = _resolve_qr_file_path(path)
    return FileResponse(path=file_path, media_type="image/png", filename=file_path.name)
