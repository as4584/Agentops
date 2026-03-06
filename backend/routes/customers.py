from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.database.customer_store import customer_store
from backend.models.customer import AddServiceRequest, Customer, CustomerCreate, CustomerService, ServiceStatus
from backend.tasks import task_tracker

router = APIRouter(prefix="/api/customers", tags=["customers"])

SERVICE_AGENT_MAP: dict[str, list[str]] = {
    "website": ["it_agent", "code_review_agent", "knowledge_agent"],
    "seo": ["knowledge_agent", "data_agent"],
    "ai_receptionist": ["cs_agent", "it_agent"],
    "social_media": ["comms_agent", "knowledge_agent"],
}


def _fanout_service_tasks(customer_id: str, service_id: str, service_type: str, agents: list[str]) -> dict[str, str]:
    parent_task_id = task_tracker.create_task(
        agent_id="soul_core",
        action="service_orchestration_started",
        detail=f"customer={customer_id} service={service_id} type={service_type}",
    )
    task_tracker.start_task(parent_task_id)

    child_tasks: dict[str, str] = {}
    for agent_id in agents:
        child_id = task_tracker.create_task(
            agent_id=agent_id,
            action="service_subtask_assigned",
            detail=f"customer={customer_id} service={service_id} type={service_type}",
        )
        child_tasks[agent_id] = child_id

    task_tracker.complete_task(
        parent_task_id,
        detail=f"fanout_complete child_tasks={len(child_tasks)}",
    )
    return child_tasks


@router.get("/")
async def list_customers() -> list[Customer]:
    return customer_store.list_customers()


@router.get("/dashboard/stats")
async def dashboard_stats() -> dict[str, Any]:
    return customer_store.dashboard_stats()


@router.get("/{customer_id}")
async def get_customer(customer_id: str) -> Customer:
    customer = customer_store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("/", status_code=201)
async def create_customer(payload: CustomerCreate) -> Customer:
    customer = Customer(
        id=f"cust_{uuid4().hex[:10]}",
        name=payload.name,
        email=payload.email,
        business_name=payload.business_name,
        tier=payload.tier,
    )
    customer_store.create_customer(customer)
    task_tracker.create_task(
        agent_id="soul_core",
        action="customer_created",
        detail=f"Created customer {customer.id} ({customer.business_name})",
    )
    return customer


@router.post("/{customer_id}/services", status_code=201)
async def add_service(customer_id: str, payload: AddServiceRequest) -> dict[str, Any]:
    customer = customer_store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    service_id = f"srv_{uuid4().hex[:10]}"
    assigned_agents = SERVICE_AGENT_MAP.get(payload.service_type.value, ["knowledge_agent"])
    service = CustomerService(
        id=service_id,
        type=payload.service_type,
        status=ServiceStatus.IN_PROGRESS,
        progress_percent=5,
        assigned_agents=assigned_agents,
        notes=payload.notes,
        created_at=datetime.now(timezone.utc),
    )
    customer_store.add_service(customer_id, service)
    customer_store.add_service_event(
        customer_id=customer_id,
        service_id=service_id,
        event_type="service_created",
        detail=f"Service '{payload.service_type.value}' created and queued for execution",
        metadata={"assigned_agents": assigned_agents},
    )

    child_tasks = _fanout_service_tasks(
        customer_id=customer_id,
        service_id=service_id,
        service_type=payload.service_type.value,
        agents=assigned_agents,
    )

    customer_store.add_service_event(
        customer_id=customer_id,
        service_id=service_id,
        event_type="subagents_assigned",
        detail=f"Subagents assigned: {', '.join(assigned_agents)}",
        metadata={"child_tasks": child_tasks},
    )

    customer_store.update_service_status(
        service_id=service_id,
        status=ServiceStatus.IN_PROGRESS,
        progress_percent=20,
    )

    task_tracker.create_task(
        agent_id="soul_core",
        action="service_assigned",
        detail=(
            f"Customer={customer_id} Service={payload.service_type.value} "
            f"Agents={','.join(assigned_agents)}"
        ),
    )

    return {
        "service_id": service_id,
        "status": ServiceStatus.IN_PROGRESS.value,
        "assigned_agents": assigned_agents,
        "child_tasks": child_tasks,
    }


@router.get("/{customer_id}/services/{service_id}/timeline")
async def service_timeline(customer_id: str, service_id: str) -> dict[str, Any]:
    customer = customer_store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    service_exists = any(service.id == service_id for service in customer.services)
    if not service_exists:
        raise HTTPException(status_code=404, detail="Service not found for customer")

    events = customer_store.get_service_events(customer_id=customer_id, service_id=service_id)
    return {
        "customer_id": customer_id,
        "service_id": service_id,
        "events": events,
    }


@router.get("/{customer_id}/deployments")
async def customer_deployments(customer_id: str) -> dict[str, Any]:
    customer = customer_store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    deployments = customer_store.list_customer_deployments(customer_id)
    return {
        "customer_id": customer_id,
        "deployments": deployments,
        "count": len(deployments),
    }


@router.patch("/{customer_id}/usage")
async def increment_usage(customer_id: str, tokens: int) -> dict[str, Any]:
    if tokens <= 0:
        raise HTTPException(status_code=400, detail="tokens must be > 0")

    customer = customer_store.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer_store.update_customer_tokens(customer_id, tokens)
    updated = customer_store.get_customer(customer_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Customer state unavailable after update")

    return {
        "customer_id": customer_id,
        "tokens_used_this_month": updated.tokens_used_this_month,
        "monthly_token_budget": updated.monthly_token_budget,
        "remaining_tokens": max(updated.monthly_token_budget - updated.tokens_used_this_month, 0),
    }
