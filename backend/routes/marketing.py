from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT
from backend.database.customer_store import customer_store
from backend.llm.unified_registry import unified_model_router

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

FAQS: list[dict[str, str]] = [
    {
        "question": "What is Agentop?",
        "answer": "Agentop is a multi-agent operating system for business growth workflows: customer ops, website generation, SEO/AEO, social workflows, and AI receptionist execution.",
    },
    {
        "question": "How does the AI receptionist help owners?",
        "answer": "It answers repetitive call intents like hours, booking, and service questions so teams can stay focused on service delivery.",
    },
    {
        "question": "How are services assigned?",
        "answer": "Customer services are mapped to subagents. When you click + and confirm, Agentop creates orchestration tasks and subagent child tasks with timeline events.",
    },
    {
        "question": "Can we track token usage per customer?",
        "answer": "Yes. The customer dashboard tracks monthly token budget and usage per customer with progress indicators.",
    },
    {
        "question": "What tiers can we sell?",
        "answer": "Foundation, Growth, and Domination tiers with setup + monthly pricing and optional add-ons like AI receptionist, chatbot, and CRM tracking.",
    },
]

DOC_SOURCES: list[Path] = [
    PROJECT_ROOT / "docs" / "IMPLEMENTATION_SPRINTS.md",
    PROJECT_ROOT / "docs" / "SOURCE_OF_TRUTH.md",
    PROJECT_ROOT / "to_do_list.md",
]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    customer_id: str | None = None


class DeployMarketingRequest(BaseModel):
    target: str = Field(default="frontend", pattern="^(frontend|marketing-static)$")


def _score_query(text: str, query_terms: list[str]) -> int:
    base = text.lower()
    return sum(base.count(term) for term in query_terms)


def _retrieve_context(question: str, limit: int = 3) -> list[str]:
    terms = [token for token in re.findall(r"[a-zA-Z0-9]+", question.lower()) if len(token) > 2]
    snippets: list[tuple[int, str]] = []

    for source in DOC_SOURCES:
        if not source.exists():
            continue
        content = source.read_text(encoding="utf-8", errors="ignore")
        chunks = re.split(r"\n\n+", content)
        for chunk in chunks:
            score = _score_query(chunk, terms)
            if score > 0:
                snippets.append((score, f"[{source.name}] {chunk[:1000]}"))

    snippets.sort(key=lambda item: item[0], reverse=True)
    return [snippet for _, snippet in snippets[:limit]]


def _faq_match(question: str) -> dict[str, str] | None:
    q = question.lower()
    best: tuple[int, dict[str, str] | None] = (0, None)
    for faq in FAQS:
        score = _score_query(faq["question"], [token for token in re.findall(r"[a-z0-9]+", q) if len(token) > 2])
        if score > best[0]:
            best = (score, faq)
    return best[1] if best[0] > 0 else None


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
    return matches[-1] if matches else None


def _build_customer_context(customer_id: str | None) -> str:
    if not customer_id:
        return "No customer selected."

    customer = customer_store.get_customer(customer_id)
    if customer is None:
        return f"Customer '{customer_id}' was requested but not found."

    services_summary = (
        ", ".join(
            f"{service.type.value}:{service.status.value}:{service.progress_percent}%" for service in customer.services
        )
        or "none"
    )

    social_summary = (
        ", ".join(f"{platform}={url}" for platform, url in customer.social_media_accounts.items()) or "none"
    )

    return (
        f"Customer ID: {customer.id}\n"
        f"Business Name: {customer.business_name}\n"
        f"Tier: {customer.tier}\n"
        f"Website: {customer.website_url or 'not_assigned'}\n"
        f"Token Usage: {customer.tokens_used_this_month}/{customer.monthly_token_budget}\n"
        f"Social Accounts: {social_summary}\n"
        f"Services: {services_summary}"
    )


@router.get("/faq")
async def marketing_faq() -> dict[str, Any]:
    return {"faqs": FAQS}


@router.post("/ask")
async def ask_marketing(payload: AskRequest) -> dict[str, Any]:
    matched = _faq_match(payload.question)
    context_snippets = _retrieve_context(payload.question)

    system = (
        "You are Agentop's business-facing assistant. "
        "Answer clearly for business owners, keep it practical, and be transparent. "
        "If information is unknown, say so clearly."
    )

    context_block = "\n\n".join(context_snippets) if context_snippets else "No indexed snippets found."
    faq_hint = json.dumps(matched) if matched else "none"
    customer_context = _build_customer_context(payload.customer_id)

    prompt = (
        f"Question: {payload.question}\n\n"
        f"Selected customer context:\n{customer_context}\n\n"
        f"FAQ hint: {faq_hint}\n\n"
        f"Docs context:\n{context_block}\n\n"
        "Respond in plain language for a business owner and include short action steps."
    )

    response = await unified_model_router.generate(
        prompt=prompt,
        system=system,
        task="general",
        model="llama3.2",
        temperature=0.3,
        max_tokens=500,
    )

    return {
        "answer": response["output"],
        "model_id": response["model_id"],
        "provider": response["provider"],
        "estimated_cost_usd": response["estimated_cost_usd"],
    }


@router.post("/deploy")
async def deploy_marketing(payload: DeployMarketingRequest) -> dict[str, Any]:
    vercel_bin = _require_vercel_cli()

    if payload.target == "frontend":
        deploy_dir = PROJECT_ROOT / "frontend"
    else:
        deploy_dir = PROJECT_ROOT / "output" / "marketing-static"
        deploy_dir.mkdir(parents=True, exist_ok=True)
        html = deploy_dir / "index.html"
        html.write_text(
            """
<!doctype html>
<html><head><meta charset='utf-8'/><title>Agentop Marketing</title></head>
<body style='font-family:system-ui;background:#0b1020;color:#f2f5ff;padding:24px'>
<h1>Agentop</h1>
<p>Business growth system with AI receptionist, website generation, and customer operations.</p>
<p>Use the dashboard for full functionality.</p>
</body></html>
""".strip(),
            encoding="utf-8",
        )

    result = subprocess.run(
        [vercel_bin, "--yes", "--prod"],
        cwd=str(deploy_dir),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    deployed_url = _extract_url(output)

    if result.returncode != 0 or not deployed_url:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Marketing deploy failed",
                "return_code": result.returncode,
                "output": output[-2000:],
            },
        )

    try:
        qrcode = import_module("qrcode")
    except ImportError as exc:
        raise HTTPException(status_code=412, detail="qrcode package missing.") from exc

    qr_dir = PROJECT_ROOT / "output" / "qr" / "marketing"
    qr_dir.mkdir(parents=True, exist_ok=True)
    qr_path = qr_dir / "marketing_qr.png"
    image = qrcode.make(deployed_url)
    image.save(str(qr_path))

    return {
        "target": payload.target,
        "deployed_url": deployed_url,
        "qr_path": str(qr_path.relative_to(PROJECT_ROOT)),
        "deployed_at": datetime.now(UTC).isoformat(),
    }
