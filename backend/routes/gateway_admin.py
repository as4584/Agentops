"""
Gateway Admin API — Key management and configuration endpoints.
===============================================================
All routes require X-Admin-Secret header OR an API key with admin scope.

POST   /admin/keys                  — Create new API key
GET    /admin/keys                  — List all keys
GET    /admin/keys/{id}             — Get key details
PUT    /admin/keys/{id}             — Update key (quotas, ACL, disable)
DELETE /admin/keys/{id}             — Revoke/delete key
GET    /admin/keys/{id}/usage       — Usage stats for a key
POST   /admin/keys/{id}/rotate      — Start key rotation (generate secondary)
POST   /admin/keys/{id}/promote     — Promote secondary to primary

GET    /admin/models                — List models with pricing
POST   /admin/secrets               — Set a provider API key in the vault
DELETE /admin/secrets/{provider}    — Remove a provider key from the vault

GET    /admin/audit                 — Recent audit log entries
GET    /admin/health                — Provider health + circuit breaker status
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.gateway.acl import TIER_MODELS, get_acl
from backend.gateway.audit import get_audit_logger
from backend.gateway.auth import (
    DEFAULT_SCOPES,
    APIKey,
    get_key_manager,
)
from backend.gateway.health import all_circuit_status, get_health_monitor
from backend.gateway.middleware import GatewayContext, require_admin_auth
from backend.gateway.secrets import (
    INFRA_DEVICES,
    get_vault,
    list_infra_devices,
    set_infra_credential,
)
from backend.gateway.usage import get_usage_tracker
from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY

router = APIRouter(prefix="/admin", tags=["Gateway Admin"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    owner: str = ""
    scopes: list[str] = list(DEFAULT_SCOPES)
    expires_in_days: int | None = Field(None, ge=1, le=3650)
    quota_rpm: int = Field(60, ge=0)
    quota_tpm: int = Field(100_000, ge=0)
    quota_tpd: int = Field(1_000_000, ge=0)
    quota_daily_usd: float = Field(5.0, ge=0)
    quota_monthly_usd: float = Field(50.0, ge=0)
    models: list[str] = []  # explicit model patterns
    tier: str | None = None  # "budget" | "standard" | "premium"
    metadata: dict[str, Any] = {}


class UpdateKeyRequest(BaseModel):
    name: str | None = None
    owner: str | None = None
    scopes: list[str] | None = None
    disabled: bool | None = None
    expires_in_days: int | None = Field(None, ge=0)  # 0 = remove expiry
    quota_rpm: int | None = Field(None, ge=0)
    quota_tpm: int | None = Field(None, ge=0)
    quota_tpd: int | None = Field(None, ge=0)
    quota_daily_usd: float | None = Field(None, ge=0)
    quota_monthly_usd: float | None = Field(None, ge=0)
    add_models: list[str] = []
    remove_models: list[str] = []
    add_tier: str | None = None
    metadata: dict[str, Any] | None = None


class SetSecretRequest(BaseModel):
    provider: str
    api_key: str = Field(..., min_length=1)


class SetInfraCredentialRequest(BaseModel):
    device: str = Field(..., min_length=1, max_length=50)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


def _key_to_dict(k: APIKey, include_hashes: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": k.key_id,
        "name": k.name,
        "owner": k.owner,
        "prefix": k.key_prefix,
        "created_at": k.created_at,
        "expires_at": k.expires_at or None,
        "disabled": k.disabled,
        "scopes": sorted(k.scopes),
        "quota_rpm": k.quota_rpm,
        "quota_tpm": k.quota_tpm,
        "quota_tpd": k.quota_tpd,
        "quota_daily_usd": k.quota_daily_usd,
        "quota_monthly_usd": k.quota_monthly_usd,
        "has_secondary_key": k.secondary_hash is not None,
        "metadata": k.metadata,
    }
    return d


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


@router.post("/keys")
async def create_key(
    body: CreateKeyRequest,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    mgr = get_key_manager()
    acl = get_acl()

    raw_key, api_key = mgr.create_key(
        name=body.name,
        owner=body.owner,
        scopes=set(body.scopes),
        expires_in_days=body.expires_in_days,
        quota_rpm=body.quota_rpm,
        quota_tpm=body.quota_tpm,
        quota_tpd=body.quota_tpd,
        quota_daily_usd=body.quota_daily_usd,
        quota_monthly_usd=body.quota_monthly_usd,
        metadata=body.metadata,
    )

    # Grant model access
    if body.tier:
        acl.grant_tier(api_key.key_id, body.tier)
    if body.models:
        acl.grant(api_key.key_id, body.models)

    return JSONResponse(
        {
            "key": raw_key,  # shown ONCE — never retrievable again
            "key_id": api_key.key_id,
            "prefix": api_key.key_prefix,
            "message": "Store this key securely — it will not be shown again.",
            **_key_to_dict(api_key),
        },
        status_code=201,
    )


@router.get("/keys")
async def list_keys(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    keys = get_key_manager().list_keys()
    return JSONResponse({"keys": [_key_to_dict(k) for k in keys]})


@router.get("/keys/{key_id}")
async def get_key(
    key_id: str,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    k = get_key_manager().get_by_id(key_id)
    if not k:
        raise HTTPException(status_code=404, detail="Key not found")
    acl = get_acl()
    d = _key_to_dict(k)
    d["allowed_models"] = acl.get_allowed_patterns(key_id)
    return JSONResponse(d)


@router.put("/keys/{key_id}")
async def update_key(
    key_id: str,
    body: UpdateKeyRequest,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    mgr = get_key_manager()
    acl = get_acl()

    k = mgr.get_by_id(key_id)
    if not k:
        raise HTTPException(status_code=404, detail="Key not found")

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.owner is not None:
        updates["owner"] = body.owner
    if body.scopes is not None:
        updates["scopes"] = set(body.scopes)
    if body.disabled is not None:
        updates["disabled"] = body.disabled
    if body.expires_in_days is not None:
        updates["expires_at"] = 0.0 if body.expires_in_days == 0 else time.time() + body.expires_in_days * 86400
    for q in ("quota_rpm", "quota_tpm", "quota_tpd", "quota_daily_usd", "quota_monthly_usd"):
        val = getattr(body, q)
        if val is not None:
            updates[q] = val
    if body.metadata is not None:
        updates["metadata"] = body.metadata

    mgr.update_key(key_id, **updates)

    # ACL changes
    if body.remove_models:
        acl.revoke(key_id, body.remove_models)
    if body.add_tier:
        acl.grant_tier(key_id, body.add_tier)
    if body.add_models:
        acl.grant(key_id, body.add_models)

    updated = mgr.get_by_id(key_id)
    return JSONResponse(_key_to_dict(updated))  # type: ignore[arg-type]


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: str,
    hard: bool = False,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    mgr = get_key_manager()
    acl = get_acl()
    if hard:
        deleted = mgr.delete_key(key_id)
    else:
        deleted = mgr.revoke_key(key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
    acl.revoke_all(key_id)
    return JSONResponse({"deleted": key_id, "hard": hard})


@router.post("/keys/{key_id}/rotate")
async def rotate_key(
    key_id: str,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    result = get_key_manager().rotate_key(key_id)
    if not result:
        raise HTTPException(status_code=404, detail="Key not found")
    new_raw, new_prefix = result
    return JSONResponse(
        {
            "new_key": new_raw,
            "new_prefix": new_prefix,
            "message": "New secondary key generated. Call /promote when ready to switch.",
        },
        status_code=201,
    )


@router.post("/keys/{key_id}/promote")
async def promote_rotation(
    key_id: str,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    ok = get_key_manager().promote_rotation(key_id)
    if not ok:
        raise HTTPException(status_code=400, detail="No secondary key to promote for this key_id")
    return JSONResponse({"promoted": True, "key_id": key_id})


@router.get("/keys/{key_id}/usage")
async def get_key_usage(
    key_id: str,
    days: int = 30,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    tracker = get_usage_tracker()
    summary = tracker.get_daily_usage(key_id, days=days)
    top = tracker.top_models(key_id, days=days)
    daily_cost = tracker.get_today_cost(key_id)
    monthly_cost = tracker.get_monthly_cost(key_id)
    return JSONResponse(
        {
            "key_id": key_id,
            "today_cost_usd": round(daily_cost, 6),
            "month_cost_usd": round(monthly_cost, 6),
            "top_models": top,
            "daily_breakdown": [
                {
                    "day": r.period,
                    "model": r.model,
                    "requests": r.requests,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "cost_usd": round(r.cost_usd, 6),
                }
                for r in summary
            ],
        }
    )


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------


@router.get("/models")
async def list_all_models(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    models = []
    for mid, spec in UNIFIED_MODEL_REGISTRY.items():
        models.append(
            {
                "id": mid,
                "provider": spec.provider.value,
                "display_name": spec.display_name,
                "context_window": spec.context_window,
                "input_cost_per_m": spec.input_cost_per_m,
                "output_cost_per_m": spec.output_cost_per_m,
                "supports_tools": spec.supports_tools,
                "best_for": spec.best_for,
            }
        )
    tiers = {tier: patterns for tier, patterns in TIER_MODELS.items()}
    return JSONResponse({"models": models, "tiers": tiers})


# ---------------------------------------------------------------------------
# Provider secrets vault
# ---------------------------------------------------------------------------


@router.post("/secrets")
async def set_provider_secret(
    body: SetSecretRequest,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    vault = get_vault()
    vault.set(f"provider:{body.provider}", body.api_key)
    return JSONResponse(
        {
            "stored": True,
            "provider": body.provider,
            "message": "Key encrypted and stored in vault.",
        }
    )


@router.delete("/secrets/{provider}")
async def delete_provider_secret(
    provider: str,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    vault = get_vault()
    deleted = vault.delete(f"provider:{provider}")
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No secret found for provider {provider!r}")
    return JSONResponse({"deleted": provider})


@router.get("/secrets")
async def list_secret_providers(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    vault = get_vault()
    providers = [k.removeprefix("provider:") for k in vault.list_keys() if k.startswith("provider:")]
    return JSONResponse({"providers": providers})


# ---------------------------------------------------------------------------
# Infrastructure credentials vault
# ---------------------------------------------------------------------------


@router.post("/infra-credentials")
async def set_infra_cred(
    body: SetInfraCredentialRequest,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    try:
        set_infra_credential(body.device, body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(
        {
            "stored": True,
            "device": body.device,
            "message": "Credential encrypted and stored in vault.",
        }
    )


@router.get("/infra-credentials")
async def list_infra_creds(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    return JSONResponse(
        {
            "devices_with_credentials": list_infra_devices(),
            "valid_devices": sorted(INFRA_DEVICES),
        }
    )


@router.delete("/infra-credentials/{device}")
async def delete_infra_cred(
    device: str,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    vault = get_vault()
    deleted = vault.delete(f"infra:{device}")
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No credential found for device {device!r}")
    return JSONResponse({"deleted": device})


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/audit")
async def get_audit_log(
    n: int = 100,
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    entries = get_audit_logger().tail(min(n, 1000))
    return JSONResponse({"entries": entries, "count": len(entries)})


# ---------------------------------------------------------------------------
# Health & circuit status
# ---------------------------------------------------------------------------


@router.get("/health")
async def admin_health(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    monitor = get_health_monitor()
    status = monitor.get_status()
    circuits = all_circuit_status()
    return JSONResponse({**status, "circuits": circuits})


@router.post("/health/check")
async def trigger_health_check(
    ctx: GatewayContext = Depends(require_admin_auth),
) -> Any:
    monitor = get_health_monitor()
    results = await monitor.check_all()
    return JSONResponse({"results": results})
