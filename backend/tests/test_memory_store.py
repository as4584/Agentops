"""
Tests for backend.memory.MemoryStore — namespaced JSON persistence.

Covers:
- write + read round-trip
- default value when key missing
- read_all returns full namespace data
- delete removes a key
- delete returns False for missing key
- namespace isolation — agent A cannot see agent B's keys
- append_shared_event + get_shared_events
- get_shared_events honours the limit parameter
- get_namespace_size returns > 0 after write
- list_namespaces includes written namespaces
- _load_store recovers gracefully from corrupt JSON
"""

from __future__ import annotations

import json
import pytest

from backend.memory import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path, monkeypatch):
    """MemoryStore backed by a temp directory — no pollution between tests."""
    import backend.memory as mem_module
    import backend.config as cfg

    mem_dir = tmp_path / "memory"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    # Also patch the name in the memory module (imported at module level)
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    # Re-create the store so it picks up the patched MEMORY_DIR
    s = mem_module.MemoryStore()
    return s


# ---------------------------------------------------------------------------
# Basic read / write
# ---------------------------------------------------------------------------

def test_write_and_read_round_trip(store):
    store.write("soul_core", "goal", "achieve alignment")
    assert store.read("soul_core", "goal") == "achieve alignment"


def test_read_missing_key_returns_default(store):
    assert store.read("soul_core", "nonexistent") is None
    assert store.read("soul_core", "nonexistent", default="fallback") == "fallback"


def test_overwrite_updates_value(store):
    store.write("devops_agent", "last_deploy", "v1.0")
    store.write("devops_agent", "last_deploy", "v2.0")
    assert store.read("devops_agent", "last_deploy") == "v2.0"


def test_write_complex_value(store):
    payload = {"jobs": ["lint", "test", "build"], "passed": True}
    store.write("monitor_agent", "ci_status", payload)
    result = store.read("monitor_agent", "ci_status")
    assert result == payload


# ---------------------------------------------------------------------------
# read_all
# ---------------------------------------------------------------------------

def test_read_all_returns_all_keys(store):
    store.write("code_review_agent", "last_pr", 42)
    store.write("code_review_agent", "last_branch", "main")
    data = store.read_all("code_review_agent")
    assert data == {"last_pr": 42, "last_branch": "main"}


def test_read_all_empty_namespace(store):
    # Namespace doesn't exist yet — should return empty dict
    data = store.read_all("brand_new_agent")
    assert data == {}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_delete_removes_key(store):
    store.write("security_agent", "cve_flag", "CVE-1234")
    assert store.delete("security_agent", "cve_flag") is True
    assert store.read("security_agent", "cve_flag") is None


def test_delete_missing_key_returns_false(store):
    assert store.delete("security_agent", "does_not_exist") is False


# ---------------------------------------------------------------------------
# Namespace isolation (INV-4)
# ---------------------------------------------------------------------------

def test_namespace_isolation(store):
    store.write("agent_a", "secret", "for_a_only")
    store.write("agent_b", "secret", "for_b_only")

    assert store.read("agent_a", "secret") == "for_a_only"
    assert store.read("agent_b", "secret") == "for_b_only"

    # agent_a cannot see agent_b's key by name collision
    store.write("agent_a", "key_collision", "a_value")
    store.write("agent_b", "key_collision", "b_value")
    assert store.read("agent_a", "key_collision") == "a_value"
    assert store.read("agent_b", "key_collision") == "b_value"


# ---------------------------------------------------------------------------
# Shared events (append-only, INV-9)
# ---------------------------------------------------------------------------

def test_append_and_read_shared_event(store):
    store.append_shared_event({"type": "agent_started", "agent": "soul_core"})
    events = store.get_shared_events()
    assert len(events) == 1
    assert events[0]["type"] == "agent_started"
    assert "timestamp" in events[0]


def test_shared_events_are_ordered(store):
    for i in range(5):
        store.append_shared_event({"seq": i})
    events = store.get_shared_events()
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(5))


def test_shared_events_limit_is_respected(store):
    for i in range(20):
        store.append_shared_event({"seq": i})
    events = store.get_shared_events(limit=5)
    assert len(events) == 5
    # get_shared_events returns the LAST n events
    assert events[-1]["seq"] == 19


def test_empty_shared_events(store):
    events = store.get_shared_events()
    assert events == []


# ---------------------------------------------------------------------------
# Namespace metadata
# ---------------------------------------------------------------------------

def test_get_namespace_size_after_write(store):
    store.write("data_agent", "schema", {"table": "customers", "rows": 100})
    size = store.get_namespace_size("data_agent")
    assert size > 0


def test_get_namespace_size_missing_namespace(store):
    assert store.get_namespace_size("nonexistent_agent") == 0


def test_list_namespaces_includes_written(store):
    store.write("ns_alpha", "k", "v")
    store.write("ns_beta", "k", "v")
    namespaces = store.list_namespaces()
    assert "ns_alpha" in namespaces
    assert "ns_beta" in namespaces


def test_list_namespaces_excludes_shared(store):
    """The 'shared' directory should never appear as an agent namespace."""
    store.append_shared_event({"type": "test"})
    namespaces = store.list_namespaces()
    assert "shared" not in namespaces


# ---------------------------------------------------------------------------
# Resilience — corrupt JSON store
# ---------------------------------------------------------------------------

def test_corrupted_store_resets_gracefully(store, tmp_path, monkeypatch):
    import backend.config as cfg

    memory_dir = tmp_path / "memory"
    monkeypatch.setattr(cfg, "MEMORY_DIR", memory_dir)
    store2 = MemoryStore()

    # Write a valid entry first
    store2.write("corrupt_ns", "good_key", "good_value")

    # Corrupt the store file
    store_file = memory_dir / "corrupt_ns" / "store.json"
    store_file.write_text("{ this is NOT valid json !!!")

    # Should not raise — just reset to empty
    value = store2.read("corrupt_ns", "good_key")
    assert value is None  # reset; original value gone
