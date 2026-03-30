"""Tests for CustomerStore — SQLite persistence layer for CS agent."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from backend.database.customer_store import CustomerStore
from backend.models.customer import Customer, CustomerService, ServiceStatus, ServiceType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_customer(email: str = "test@example.com") -> Customer:
    return Customer(
        id=uuid4().hex,
        name="Alice Test",
        email=email,
        business_name="ACME Ltd",
        tier="foundation",
    )


def _make_service(
    stype: ServiceType = ServiceType.WEBSITE,
    status: ServiceStatus = ServiceStatus.PENDING,
) -> CustomerService:
    return CustomerService(
        id=f"svc_{uuid4().hex[:12]}",
        type=stype,
        status=status,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> CustomerStore:
    """Isolated CustomerStore backed by a temp SQLite file."""
    return CustomerStore(db_path=tmp_path / "test_customers.db")


# ---------------------------------------------------------------------------
# Schema / init
# ---------------------------------------------------------------------------

class TestInit:
    def test_db_file_created(self, tmp_path: Path) -> None:
        db = tmp_path / "cs.db"
        CustomerStore(db_path=db)
        assert db.exists()

    def test_all_tables_present(self, tmp_path: Path) -> None:
        store = CustomerStore(db_path=tmp_path / "schema.db")
        with store.connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"customers", "customer_services", "service_events", "customer_deployments"} <= tables

    def test_double_init_idempotent(self, tmp_path: Path) -> None:
        """Calling _init_schema twice must not raise (CREATE TABLE IF NOT EXISTS)."""
        db = tmp_path / "idem.db"
        CustomerStore(db_path=db)
        CustomerStore(db_path=db)  # should not raise


# ---------------------------------------------------------------------------
# create_customer / get_customer
# ---------------------------------------------------------------------------

class TestCreateAndGet:
    def test_create_and_retrieve(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        result = store.get_customer(c.id)
        assert result is not None
        assert result.id == c.id
        assert result.name == c.name
        assert result.email == c.email
        assert result.business_name == c.business_name

    def test_get_unknown_returns_none(self, store: CustomerStore) -> None:
        assert store.get_customer("nonexistent_id") is None

    def test_duplicate_email_raises(self, store: CustomerStore) -> None:
        c1 = _make_customer("dup@example.com")
        c2 = _make_customer("dup@example.com")
        c2 = c2.model_copy(update={"id": uuid4().hex})  # different id, same email
        store.create_customer(c1)
        with pytest.raises(sqlite3.IntegrityError):
            store.create_customer(c2)

    def test_default_tier_stored(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        result = store.get_customer(c.id)
        assert result is not None
        assert result.tier == "foundation"

    def test_optional_fields_nullable(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        result = store.get_customer(c.id)
        assert result is not None
        assert result.website_url is None


# ---------------------------------------------------------------------------
# list_customers
# ---------------------------------------------------------------------------

class TestListCustomers:
    def test_empty_store(self, store: CustomerStore) -> None:
        assert store.list_customers() == []

    def test_lists_active_customers(self, store: CustomerStore) -> None:
        c1 = _make_customer("a@example.com")
        c2 = _make_customer("b@example.com")
        store.create_customer(c1)
        store.create_customer(c2)
        result = store.list_customers()
        assert len(result) == 2

    def test_inactive_excluded(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        # Directly deactivate via SQL
        with store.connection() as conn:
            conn.execute("UPDATE customers SET active = 0 WHERE id = ?", (c.id,))
            conn.commit()
        assert store.list_customers() == []


# ---------------------------------------------------------------------------
# add_service / update_service_status
# ---------------------------------------------------------------------------

class TestServices:
    def test_add_and_retrieve_service(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        # Confirm via direct SQL since there's no get_service helper
        with store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM customer_services WHERE id = ?", (svc.id,)
            ).fetchone()
        assert row is not None
        assert row["customer_id"] == c.id
        assert row["type"] == ServiceType.WEBSITE.value
        assert row["status"] == ServiceStatus.PENDING.value

    def test_update_service_status_no_progress(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        store.update_service_status(svc.id, ServiceStatus.IN_PROGRESS)
        with store.connection() as conn:
            row = conn.execute(
                "SELECT status, progress_percent FROM customer_services WHERE id = ?", (svc.id,)
            ).fetchone()
        assert row["status"] == ServiceStatus.IN_PROGRESS.value
        assert row["progress_percent"] == 0  # unchanged

    def test_update_service_status_with_progress(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        store.update_service_status(svc.id, ServiceStatus.IN_PROGRESS, progress_percent=55)
        with store.connection() as conn:
            row = conn.execute(
                "SELECT progress_percent FROM customer_services WHERE id = ?", (svc.id,)
            ).fetchone()
        assert row["progress_percent"] == 55

    def test_complete_service_sets_completed_at(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        store.update_service_status(svc.id, ServiceStatus.COMPLETED)
        with store.connection() as conn:
            row = conn.execute(
                "SELECT completed_at FROM customer_services WHERE id = ?", (svc.id,)
            ).fetchone()
        assert row["completed_at"] is not None


# ---------------------------------------------------------------------------
# add_service_event / get_service_events
# ---------------------------------------------------------------------------

class TestServiceEvents:
    def test_log_and_retrieve_event(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        store.add_service_event(c.id, svc.id, "progress_update", "50% done")
        events = store.get_service_events(c.id, svc.id)
        assert len(events) == 1
        assert events[0]["event_type"] == "progress_update"
        assert events[0]["detail"] == "50% done"

    def test_multiple_events_ordered_asc(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        for msg in ["first", "second", "third"]:
            store.add_service_event(c.id, svc.id, "note", msg)

        events = store.get_service_events(c.id, svc.id)
        assert [e["detail"] for e in events] == ["first", "second", "third"]

    def test_event_metadata_stored(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)

        store.add_service_event(c.id, svc.id, "deploy", "live", metadata={"url": "https://x.com"})
        events = store.get_service_events(c.id, svc.id)
        assert events[0]["metadata"]["url"] == "https://x.com"

    def test_empty_events_for_new_service(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        svc = _make_service()
        store.add_service(c.id, svc)
        assert store.get_service_events(c.id, svc.id) == []


# ---------------------------------------------------------------------------
# add_customer_deployment / list_customer_deployments
# ---------------------------------------------------------------------------

class TestDeployments:
    def test_record_and_list_deployment(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        store.add_customer_deployment(
            customer_id=c.id,
            project_id="proj_abc",
            project_slug="my-site",
            deployed_url="https://my-site.vercel.app",
        )
        deployments = store.list_customer_deployments(c.id)
        assert len(deployments) == 1
        assert deployments[0]["deployed_url"] == "https://my-site.vercel.app"
        assert deployments[0]["project_slug"] == "my-site"

    def test_deployment_metadata_stored(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        store.add_customer_deployment(
            customer_id=c.id,
            project_id="proj_xyz",
            project_slug="brand-site",
            deployed_url="https://brand.vercel.app",
            metadata={"framework": "next"},
        )
        deployments = store.list_customer_deployments(c.id)
        assert deployments[0]["metadata"]["framework"] == "next"

    def test_no_deployments_returns_empty(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        assert store.list_customer_deployments(c.id) == []


# ---------------------------------------------------------------------------
# update_customer_tokens
# ---------------------------------------------------------------------------

class TestTokenTracking:
    def test_increment_tokens(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        store.update_customer_tokens(c.id, 500)
        result = store.get_customer(c.id)
        assert result is not None
        assert result.tokens_used_this_month == 500

    def test_increment_tokens_accumulates(self, store: CustomerStore) -> None:
        c = _make_customer()
        store.create_customer(c)
        store.update_customer_tokens(c.id, 300)
        store.update_customer_tokens(c.id, 700)
        result = store.get_customer(c.id)
        assert result is not None
        assert result.tokens_used_this_month == 1000

    def test_tokens_isolated_between_customers(self, store: CustomerStore) -> None:
        c1 = _make_customer("x@example.com")
        c2 = _make_customer("y@example.com")
        store.create_customer(c1)
        store.create_customer(c2)
        store.update_customer_tokens(c1.id, 999)
        result2 = store.get_customer(c2.id)
        assert result2 is not None
        assert result2.tokens_used_this_month == 0
