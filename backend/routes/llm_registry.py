from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.llm.unified_registry import unified_model_router

router = APIRouter(prefix="/llm/registry", tags=["llm-registry"])


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    system: str = ""
    task: str = "general"
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024


@router.get("/models")
async def list_unified_models() -> dict:
    return {
        "models": unified_model_router.list_models(),
        "count": len(unified_model_router.list_models()),
    }


@router.post("/generate")
async def generate_with_registry(payload: GenerateRequest) -> dict:
    result = await unified_model_router.generate(
        prompt=payload.prompt,
        system=payload.system,
        task=payload.task,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return result
