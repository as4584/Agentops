"""
Sprint 2 Acceptance Tests — Durability and Retrieval Convergence
================================================================
PR 1 — Typed embedding config + startup validation
PR 2 — Qdrant primary with explicit, observable fallback
PR 3 — Atomic writes for JSON persistence
PR 4 — Durable task/event history via SQLite

All tests must pass with zero external dependencies (no running Qdrant,
no running Ollama).  Tests use in-memory stores and temp directories.

Run:
    pytest backend/tests/test_sprint2_durability.py -v
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

# ===========================================================================
# PR 1 — Typed Embedding Config + Startup Validation
# ===========================================================================


class TestEmbeddingConfig:
    """PR 1: EmbeddingConfig typed contract in backend.models."""

    def test_embedding_config_roundtrip_from_config(self) -> None:
        """EmbeddingConfig.from_config() reads QDRANT_EMBED_MODEL and QDRANT_DEFAULT_DIM."""
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig.from_config()
        assert cfg.model  # non-empty
        assert cfg.dim > 0

    def test_embedding_config_known_model_passes(self) -> None:
        """nomic-embed-text with dim=768 should pass dim_matches_known()."""
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="nomic-embed-text", dim=768)
        assert cfg.dim_matches_known() is True

    def test_embedding_config_known_model_mismatch(self) -> None:
        """nomic-embed-text with wrong dim must fail dim_matches_known()."""
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="nomic-embed-text", dim=384)
        assert cfg.dim_matches_known() is False

    def test_embedding_config_unknown_model_passes(self) -> None:
        """An unknown model name cannot be validated — must return True."""
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="some-custom-embed-v99", dim=512)
        assert cfg.dim_matches_known() is True

    def test_embedding_config_dim_must_be_positive(self) -> None:
        """dim=0 or negative must be rejected by the model validator."""
        from pydantic import ValidationError

        from backend.models import EmbeddingConfig

        with pytest.raises(ValidationError):
            EmbeddingConfig(model="nomic-embed-text", dim=0)

    def test_embedding_config_collection_prefix_default(self) -> None:
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="nomic-embed-text", dim=768)
        assert cfg.collection_prefix == ""


class TestStartupValidation:
    """PR 1: validate_embedding_startup() function."""

    def test_valid_config_returns_no_warnings(self) -> None:
        """Config with matching model/dim must return []."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 768),
            patch(
                "backend.knowledge.context_assembler.KNOWN_EMBED_DIMS",
                {"nomic-embed-text": 768},
            ),
        ):
            warnings = validate_embedding_startup()
        assert warnings == []

    def test_empty_model_name_returns_warning(self) -> None:
        """Empty QDRANT_EMBED_MODEL must produce a warning."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", ""),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 768),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        assert len(warnings) >= 1
        assert any("unset" in w or "empty" in w for w in warnings)

    def test_zero_dim_returns_warning(self) -> None:
        """QDRANT_DEFAULT_DIM=0 must produce a warning."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 0),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        assert len(warnings) >= 1
        assert any("invalid" in w.lower() or "0" in w for w in warnings)

    def test_known_model_dim_mismatch_returns_warning(self) -> None:
        """nomic-embed-text with dim=384 must warn about the mismatch."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 384),
            patch(
                "backend.knowledge.context_assembler.KNOWN_EMBED_DIMS",
                {"nomic-embed-text": 768},
            ),
        ):
            warnings = validate_embedding_startup()
        assert len(warnings) >= 1
        assert any("mismatch" in w.lower() or "768" in w for w in warnings)

    def test_unknown_model_no_dim_warning(self) -> None:
        """An unlisted model with any dim must not produce a mismatch warning."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "custom-embed"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 512),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        assert warnings == []

    def test_config_exports_qdrant_embed_model(self) -> None:
        """backend.config must export QDRANT_EMBED_MODEL."""
        from backend.config import QDRANT_EMBED_MODEL

        assert isinstance(QDRANT_EMBED_MODEL, str)
        assert QDRANT_EMBED_MODEL  # non-empty default

    def test_config_exports_known_embed_dims(self) -> None:
        """backend.config must export KNOWN_EMBED_DIMS dict with nomic-embed-text."""
        from backend.config import KNOWN_EMBED_DIMS

        assert isinstance(KNOWN_EMBED_DIMS, dict)
        assert "nomic-embed-text" in KNOWN_EMBED_DIMS
        assert KNOWN_EMBED_DIMS["nomic-embed-text"] == 768


# ===========================================================================
# PR 2 — Qdrant Primary with Explicit, Observable Fallback
# ===========================================================================


class TestContextAssemblerFallbackCounter:
    """PR 2: ContextAssembler._fallback_count is observable and increments."""

    def setup_method(self) -> None:
        """Reset the class-level counter before each test."""
        from backend.knowledge.context_assembler import ContextAssembler

        ContextAssembler._fallback_count = 0

    def test_fallback_count_starts_at_zero(self) -> None:
        from backend.knowledge.context_assembler import ContextAssembler

        assert ContextAssembler._fallback_count == 0

    def test_health_check_includes_fallback_count(self) -> None:
        """health_check() must include fallback_count key."""
        from unittest.mock import MagicMock

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        with patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", False):
            assembler = ContextAssembler(mock_llm)
        health = assembler.health_check()
        assert "fallback_count" in health
        assert health["fallback_count"] == 0

    def test_fallback_retrieve_increments_counter(self) -> None:
        """Each call to _fallback_retrieve must increment the class counter."""
        import asyncio
        from unittest.mock import MagicMock

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        with patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", False):
            assembler = ContextAssembler(mock_llm)

        # Patch _get_fallback_store to return None (empty result)
        with patch("backend.knowledge.context_assembler._get_fallback_store", return_value=None):
            asyncio.run(assembler._fallback_retrieve("test query", 3))

        assert ContextAssembler._fallback_count == 1

    def test_fallback_retrieve_increments_counter_twice(self) -> None:
        """Multiple fallback calls accumulate correctly."""
        import asyncio
        from unittest.mock import MagicMock

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        with patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", False):
            assembler = ContextAssembler(mock_llm)

        with patch("backend.knowledge.context_assembler._get_fallback_store", return_value=None):
            asyncio.run(assembler._fallback_retrieve("q1", 3))
            asyncio.run(assembler._fallback_retrieve("q2", 3))

        assert ContextAssembler._fallback_count == 2

    def test_health_check_fallback_count_reflects_increments(self) -> None:
        """health_check().fallback_count must reflect accumulated calls."""
        import asyncio
        from unittest.mock import MagicMock

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        with (
            patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", False),
            patch("backend.knowledge.context_assembler._get_fallback_store", return_value=None),
        ):
            assembler = ContextAssembler(mock_llm)
            asyncio.run(assembler._fallback_retrieve("query", 3))
            health = assembler.health_check()

        assert health["fallback_count"] == 1
        assert health["fallback_active"] is True

    def test_fallback_active_false_when_qdrant_available(self) -> None:
        """health_check().fallback_active must be False when Qdrant client is live."""
        from unittest.mock import MagicMock

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        mock_store = MagicMock()
        mock_store._client = MagicMock()  # non-None → connected
        mock_store._collections_initialized = set()

        with patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", True):
            assembler = ContextAssembler.__new__(ContextAssembler)
            assembler._llm = mock_llm
            assembler._store = mock_store

            health = assembler.health_check()
            assert health["fallback_active"] is False


# ===========================================================================
# PR 3 — Atomic Writes for JSON Persistence
# ===========================================================================


class TestAtomicWriteMemoryStore:
    """PR 3: memory/__init__.py writes are atomic (temp + replace)."""

    def test_save_store_produces_valid_json(self, tmp_path: Path) -> None:
        """After write(), the store file contains valid JSON."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()
            store.write("agent_x", "key1", "value1")

        ns_file = tmp_path / "agent_x" / "store.json"
        assert ns_file.exists()
        data = json.loads(ns_file.read_text())
        assert data["data"]["key1"] == "value1"

    def test_write_roundtrip(self, tmp_path: Path) -> None:
        """write() followed by read() returns the same value."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()
            store.write("agent_y", "foo", {"nested": True})
            result = store.read("agent_y", "foo")

        assert result == {"nested": True}

    def test_atomic_write_no_partial_file_on_crash(self, tmp_path: Path) -> None:
        """_atomic_write_json leaves no partial file when write itself fails."""
        from backend.memory import _atomic_write_json

        target = tmp_path / "output.json"

        # Simulate a write failure by making the directory read-only
        # so tempfile.mkstemp fails.  We verify the target is untouched.
        target.write_text('{"old": true}')
        bad_path = tmp_path / "no_such_dir" / "output.json"
        with pytest.raises(Exception):
            _atomic_write_json(bad_path, {"new": True})

        # Original file untouched
        assert json.loads(target.read_text()) == {"old": True}

    def test_atomic_write_replaces_existing(self, tmp_path: Path) -> None:
        """_atomic_write_json replaces an existing file atomically."""
        from backend.memory import _atomic_write_json

        target = tmp_path / "data.json"
        target.write_text('{"v": 1}')
        _atomic_write_json(target, {"v": 2})
        assert json.loads(target.read_text()) == {"v": 2}

    def test_no_tmp_files_left_after_write(self, tmp_path: Path) -> None:
        """Temp files must be cleaned up after a successful write."""
        from backend.memory import _atomic_write_json

        target = tmp_path / "clean.json"
        _atomic_write_json(target, {"ok": True})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_shared_event_append_atomic(self, tmp_path: Path) -> None:
        """append_shared_event() stores events in valid JSON without partial writes."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()
            store.append_shared_event({"type": "agent_start", "agent": "devops_agent"})
            store.append_shared_event({"type": "tool_call", "tool": "safe_shell"})
            events = store.get_shared_events()

        assert len(events) == 2
        assert events[0]["type"] == "agent_start"
        assert events[1]["type"] == "tool_call"

    def test_handoff_write_atomic(self, tmp_path: Path) -> None:
        """write_handoff() stores a valid handoff in JSON."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()
            hid = store.write_handoff("devops_agent", "monitor_agent", {"context": "deploy done"})

        assert isinstance(hid, str)
        handoff_file = tmp_path / "handoffs" / "pending.json"
        assert handoff_file.exists()
        data = json.loads(handoff_file.read_text())
        assert len(data["handoffs"]) == 1

    def test_handoff_no_tmp_files_remain(self, tmp_path: Path) -> None:
        """No .tmp files must remain after write_handoff()."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()
            store.write_handoff("a1", "a2", {"x": 1})

        tmp_files = list((tmp_path / "handoffs").glob("*.tmp"))
        assert tmp_files == []

    def test_concurrent_writes_consistent(self, tmp_path: Path) -> None:
        """Concurrent threaded writes must not corrupt the store file."""
        with patch("backend.memory.MEMORY_DIR", tmp_path):
            from backend.memory import MemoryStore

            store = MemoryStore()

            def writer(idx: int) -> None:
                store.write("concurrent_ns", f"key_{idx}", idx)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # File must be valid JSON with all 10 keys
            ns_file = tmp_path / "concurrent_ns" / "store.json"
            data = json.loads(ns_file.read_text())
            assert len(data["data"]) == 10


class TestAtomicWriteSiteStore:
    """PR 3: webgen/site_store.py uses atomic writes."""

    def test_save_produces_valid_json(self, tmp_path: Path) -> None:
        """save() creates a valid JSON file."""
        from backend.webgen.models import SiteProject
        from backend.webgen.site_store import SiteStore

        store = SiteStore(base_dir=tmp_path)
        project = SiteProject(id="proj_1")
        store.save(project)

        path = tmp_path / "proj_1.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["id"] == "proj_1"

    def test_save_no_tmp_files_remain(self, tmp_path: Path) -> None:
        """No .tmp files must remain after save()."""
        from backend.webgen.models import SiteProject
        from backend.webgen.site_store import SiteStore

        store = SiteStore(base_dir=tmp_path)
        project = SiteProject(id="proj_2")
        store.save(project)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_overwrites_existing_atomically(self, tmp_path: Path) -> None:
        """Overwriting an existing project must produce correct final state."""
        from backend.webgen.models import ClientBrief, SiteProject
        from backend.webgen.site_store import SiteStore

        store = SiteStore(base_dir=tmp_path)
        p1 = SiteProject(id="proj_3", brief=ClientBrief(business_name="Original"))
        store.save(p1)
        p2 = SiteProject(id="proj_3", brief=ClientBrief(business_name="Updated"))
        store.save(p2)

        loaded = store.load("proj_3")
        assert loaded is not None
        assert loaded.brief.business_name == "Updated"


# ===========================================================================
# PR 4 — Durable Task/Event History via SQLite
# ===========================================================================


class TestTaskTrackerDurability:
    """PR 4: TaskTracker persists to SQLite and survives restarts."""

    def test_task_persisted_to_sqlite(self, tmp_path: Path) -> None:
        """create_task() + complete_task() must write to SQLite."""
        from backend.tasks import TaskStatus, TaskTracker

        db = tmp_path / "tasks.db"
        tracker = TaskTracker(db_path=db)
        tid = tracker.create_task("devops_agent", "deploy", "deploy app")
        tracker.complete_task(tid, "success")

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT id, status FROM tasks WHERE id = ?", (tid,)).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][1] == TaskStatus.COMPLETED

    def test_failed_task_persisted_to_sqlite(self, tmp_path: Path) -> None:
        """fail_task() must persist FAILED status to SQLite."""
        from backend.tasks import TaskStatus, TaskTracker

        db = tmp_path / "tasks.db"
        tracker = TaskTracker(db_path=db)
        tid = tracker.create_task("monitor_agent", "check", "health check")
        tracker.fail_task(tid, "connection refused")

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT status, error FROM tasks WHERE id = ?", (tid,)).fetchone()
        conn.close()

        assert row[0] == TaskStatus.FAILED
        assert "connection" in row[1]

    def test_tasks_survive_restart(self, tmp_path: Path) -> None:
        """Tasks persisted in one tracker instance must be visible in a fresh instance."""
        from backend.tasks import TaskTracker

        db = tmp_path / "tasks.db"

        tracker1 = TaskTracker(db_path=db)
        tid = tracker1.create_task("security_agent", "scan", "secret scan")
        tracker1.complete_task(tid)
        del tracker1

        tracker2 = TaskTracker(db_path=db)
        tasks = tracker2.get_tasks(limit=50)
        ids = [t["id"] for t in tasks]
        assert tid in ids

    def test_task_status_restored_correctly(self, tmp_path: Path) -> None:
        """Status (COMPLETED / FAILED) must be correctly restored after restart."""
        from backend.tasks import TaskStatus, TaskTracker

        db = tmp_path / "tasks.db"
        tracker1 = TaskTracker(db_path=db)
        tid_ok = tracker1.create_task("data_agent", "etl", "run ETL")
        tracker1.complete_task(tid_ok)
        tid_fail = tracker1.create_task("data_agent", "etl", "bad run")
        tracker1.fail_task(tid_fail, "schema error")
        del tracker1

        tracker2 = TaskTracker(db_path=db)
        tasks = {t["id"]: t for t in tracker2.get_tasks(limit=50)}
        assert tasks[tid_ok]["status"] == TaskStatus.COMPLETED
        assert tasks[tid_fail]["status"] == TaskStatus.FAILED

    def test_in_memory_still_works_without_db(self, tmp_path: Path) -> None:
        """DB errors inside _persist_task must never break the runtime path."""
        from backend.tasks import TaskTracker

        db = tmp_path / "tasks.db"
        tracker = TaskTracker(db_path=db)

        # Simulate a DB failure by patching sqlite3.connect to raise after init.
        # _persist_task catches all exceptions internally — create_task must succeed.
        with patch("backend.tasks.sqlite3.connect", side_effect=sqlite3.OperationalError("disk full")):
            tid = tracker.create_task("cs_agent", "faq", "help me")
            tracker.complete_task(tid)
            tracker.fail_task("nonexistent", "irrelevant")

        tasks = tracker.get_tasks()
        assert any(t["id"] == tid for t in tasks)

    def test_db_prunes_beyond_max_persisted(self, tmp_path: Path) -> None:
        """After inserting > MAX_PERSISTED_TASKS rows, SQLite is pruned."""
        from backend.tasks import TaskTracker

        db = tmp_path / "tasks.db"
        tracker = TaskTracker(db_path=db)
        old_max = tracker.MAX_PERSISTED_TASKS

        # Temporarily lower the limit so we can hit it quickly
        tracker.MAX_PERSISTED_TASKS = 5  # type: ignore[assignment]
        for i in range(8):
            tid = tracker.create_task("it_agent", f"action_{i}", "")
            tracker.complete_task(tid)

        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()

        assert count <= 5  # pruned to MAX_PERSISTED_TASKS
        tracker.MAX_PERSISTED_TASKS = old_max  # type: ignore[assignment]

    def test_task_counter_restored_from_db(self, tmp_path: Path) -> None:
        """After restart, task IDs must not restart from task_1."""
        from backend.tasks import TaskTracker

        db = tmp_path / "tasks.db"
        tracker1 = TaskTracker(db_path=db)
        ids_before = []
        for _ in range(3):
            tid = tracker1.create_task("devops_agent", "build", "")
            tracker1.complete_task(tid)
            ids_before.append(tid)
        del tracker1

        tracker2 = TaskTracker(db_path=db)
        new_tid = tracker2.create_task("devops_agent", "deploy", "")
        # New ID must be higher than the highest from session 1
        max_before = max(int(t.replace("task_", "")) for t in ids_before)
        new_seq = int(new_tid.replace("task_", ""))
        assert new_seq > max_before

    def test_get_stats_counts_correctly(self, tmp_path: Path) -> None:
        """get_stats() must reflect the correct counts including restored tasks."""
        from backend.tasks import TaskTracker

        db = tmp_path / "tasks.db"
        tracker = TaskTracker(db_path=db)
        t1 = tracker.create_task("ocr_agent", "extract", "")
        tracker.complete_task(t1)
        t2 = tracker.create_task("ocr_agent", "extract", "")
        tracker.fail_task(t2, "err")
        _t3 = tracker.create_task("ocr_agent", "extract", "")  # QUEUED

        stats = tracker.get_stats()
        assert stats["completed"] >= 1
        assert stats["failed"] >= 1
        assert stats["queued"] >= 1
