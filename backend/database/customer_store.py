from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.models.customer import Customer, CustomerService, ServiceStatus, ServiceType


class CustomerStore:
    """SQLite storage for customers and assigned services."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path("data/customers.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    business_name TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    website_url TEXT,
                    social_media_accounts TEXT,
                    monthly_token_budget INTEGER NOT NULL DEFAULT 100000,
                    tokens_used_this_month INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS customer_services (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    assigned_agents TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                );

                CREATE INDEX IF NOT EXISTS idx_customer_services_customer
                ON customer_services(customer_id);

                CREATE TABLE IF NOT EXISTS service_events (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY(customer_id) REFERENCES customers(id),
                    FOREIGN KEY(service_id) REFERENCES customer_services(id)
                );

                CREATE INDEX IF NOT EXISTS idx_service_events_service
                ON service_events(service_id, created_at);

                CREATE TABLE IF NOT EXISTS customer_deployments (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    project_slug TEXT,
                    deployed_url TEXT NOT NULL,
                    qr_path TEXT,
                    deployed_at TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                );

                CREATE INDEX IF NOT EXISTS idx_customer_deployments_customer
                ON customer_deployments(customer_id, deployed_at DESC);

                PRAGMA journal_mode=WAL;
                """
            )
            conn.commit()

    def create_customer(self, customer: Customer) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO customers
                (id, name, email, business_name, tier, website_url, social_media_accounts,
                 monthly_token_budget, tokens_used_this_month, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer.id,
                    customer.name,
                    customer.email,
                    customer.business_name,
                    customer.tier,
                    customer.website_url,
                    json.dumps(customer.social_media_accounts),
                    customer.monthly_token_budget,
                    customer.tokens_used_this_month,
                    1 if customer.active else 0,
                    customer.created_at.isoformat(),
                ),
            )
            conn.commit()

    def list_customers(self) -> list[Customer]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM customers WHERE active = 1 ORDER BY created_at DESC").fetchall()

        return [self._hydrate_customer(row) for row in rows]

    def get_customer(self, customer_id: str) -> Customer | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
        if row is None:
            return None
        return self._hydrate_customer(row)

    def add_service(self, customer_id: str, service: CustomerService) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO customer_services
                (id, customer_id, type, status, progress_percent, assigned_agents,
                 notes, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service.id,
                    customer_id,
                    service.type.value,
                    service.status.value,
                    service.progress_percent,
                    json.dumps(service.assigned_agents),
                    service.notes,
                    service.created_at.isoformat(),
                    service.completed_at.isoformat() if service.completed_at else None,
                ),
            )
            conn.commit()

    def add_service_event(
        self,
        customer_id: str,
        service_id: str,
        event_type: str,
        detail: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO service_events
                (id, customer_id, service_id, event_type, detail, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evt_{uuid4().hex[:16]}",
                    customer_id,
                    service_id,
                    event_type,
                    detail,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()

    def get_service_events(self, customer_id: str, service_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, detail, created_at, metadata_json
                FROM service_events
                WHERE customer_id = ? AND service_id = ?
                ORDER BY created_at ASC
                """,
                (customer_id, service_id),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "detail": row["detail"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]

    def add_customer_deployment(
        self,
        customer_id: str,
        project_id: str,
        project_slug: str,
        deployed_url: str,
        qr_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO customer_deployments
                (id, customer_id, project_id, project_slug, deployed_url, qr_path, deployed_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"dep_{uuid4().hex[:16]}",
                    customer_id,
                    project_id,
                    project_slug,
                    deployed_url,
                    qr_path,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()

    def list_customer_deployments(self, customer_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, customer_id, project_id, project_slug, deployed_url, qr_path, deployed_at, metadata_json
                FROM customer_deployments
                WHERE customer_id = ?
                ORDER BY deployed_at DESC
                """,
                (customer_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "customer_id": row["customer_id"],
                "project_id": row["project_id"],
                "project_slug": row["project_slug"],
                "deployed_url": row["deployed_url"],
                "qr_path": row["qr_path"],
                "deployed_at": row["deployed_at"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]

    def update_service_status(
        self, service_id: str, status: ServiceStatus, progress_percent: int | None = None
    ) -> None:
        with self.connection() as conn:
            if progress_percent is None:
                conn.execute(
                    "UPDATE customer_services SET status = ? WHERE id = ?",
                    (status.value, service_id),
                )
            else:
                conn.execute(
                    "UPDATE customer_services SET status = ?, progress_percent = ? WHERE id = ?",
                    (status.value, progress_percent, service_id),
                )
            if status == ServiceStatus.COMPLETED:
                conn.execute(
                    "UPDATE customer_services SET completed_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), service_id),
                )
            conn.commit()

    def update_customer_tokens(self, customer_id: str, delta_tokens: int) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE customers
                SET tokens_used_this_month = tokens_used_this_month + ?
                WHERE id = ?
                """,
                (delta_tokens, customer_id),
            )
            conn.commit()

    def dashboard_stats(self) -> dict[str, int]:
        with self.connection() as conn:
            total_customers = conn.execute("SELECT COUNT(*) AS count FROM customers WHERE active = 1").fetchone()[
                "count"
            ]
            total_tokens = conn.execute(
                "SELECT COALESCE(SUM(tokens_used_this_month), 0) AS total FROM customers WHERE active = 1"
            ).fetchone()["total"]
            active_services = conn.execute(
                "SELECT COUNT(*) AS count FROM customer_services WHERE status = ?",
                (ServiceStatus.IN_PROGRESS.value,),
            ).fetchone()["count"]

        return {
            "total_customers": total_customers,
            "active_services": active_services,
            "total_tokens_used": total_tokens,
        }

    def _hydrate_customer(self, row: sqlite3.Row) -> Customer:
        with self.connection() as conn:
            service_rows = conn.execute(
                "SELECT * FROM customer_services WHERE customer_id = ? ORDER BY created_at DESC",
                (row["id"],),
            ).fetchall()

        services: list[CustomerService] = []
        for service_row in service_rows:
            services.append(
                CustomerService(
                    id=service_row["id"],
                    type=ServiceType(service_row["type"]),
                    status=ServiceStatus(service_row["status"]),
                    progress_percent=service_row["progress_percent"],
                    assigned_agents=json.loads(service_row["assigned_agents"] or "[]"),
                    notes=service_row["notes"] or "",
                    created_at=datetime.fromisoformat(service_row["created_at"]),
                    completed_at=datetime.fromisoformat(service_row["completed_at"])
                    if service_row["completed_at"]
                    else None,
                )
            )

        return Customer(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            business_name=row["business_name"],
            tier=row["tier"],
            website_url=row["website_url"],
            social_media_accounts=json.loads(row["social_media_accounts"] or "{}"),
            monthly_token_budget=row["monthly_token_budget"],
            tokens_used_this_month=row["tokens_used_this_month"],
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            services=services,
        )


customer_store = CustomerStore()
