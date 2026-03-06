from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.memory import memory_store

router = APIRouter(tags=["memory-management"])


@router.get("/memory")
async def get_memory_overview() -> dict[str, Any]:
    namespaces = memory_store.list_namespaces()
    namespace_summary: dict[str, dict[str, float]] = {}
    for namespace in namespaces:
        size_bytes = memory_store.get_namespace_size(namespace)
        namespace_summary[namespace] = {
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 4),
        }
    return {
        "namespaces": namespace_summary,
        "shared_events_count": len(memory_store.get_shared_events(limit=500)),
    }


@router.get("/memory/{namespace}")
async def get_memory_namespace(namespace: str) -> dict[str, Any]:
    if namespace not in memory_store.list_namespaces():
        raise HTTPException(status_code=404, detail=f"Namespace '{namespace}' not found")
    data = memory_store.read_all(namespace)
    size_bytes = memory_store.get_namespace_size(namespace)
    return {
        "namespace": namespace,
        "data": data,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 4),
    }
