"""
Memory Store — Namespaced JSON persistence for agents.
======================================================
Each agent gets an isolated namespace (directory + JSON file).
Cross-namespace access is PROHIBITED (INV-4).

Governance Note:
- Memory namespaces must not overlap (INV-4).
- Shared memory is append-only via orchestrator (INV-9).
- Schema changes require documentation update per DRIFT_GUARD.md §6.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import MEMORY_DIR
from backend.utils import logger


class MemoryStore:
    """
    Namespaced JSON memory store with strict isolation.

    Each agent receives a unique namespace that maps to a directory.
    The store enforces that agents can only access their own namespace.
    """

    def __init__(self) -> None:
        self._locks: dict[str, Lock] = {}
        self._global_lock = Lock()
        self._ensure_shared_store()
        logger.info("MemoryStore initialized")

    def _ensure_shared_store(self) -> None:
        """Create the shared events store if it doesn't exist."""
        shared_dir = MEMORY_DIR / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        events_file = shared_dir / "events.json"
        if not events_file.exists():
            events_file.write_text(json.dumps({"events": []}, indent=2))

    def _get_lock(self, namespace: str) -> Lock:
        """Get or create a lock for a namespace."""
        with self._global_lock:
            if namespace not in self._locks:
                self._locks[namespace] = Lock()
            return self._locks[namespace]

    def _namespace_path(self, namespace: str) -> Path:
        """
        Resolve the directory path for a namespace.
        Creates the directory if it doesn't exist.
        """
        ns_dir = MEMORY_DIR / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir

    def _store_file(self, namespace: str) -> Path:
        """Get the JSON store file for a namespace."""
        return self._namespace_path(namespace) / "store.json"

    # ----- Read Operations -----

    def read(self, namespace: str, key: str, default: Any = None) -> Any:
        """
        Read a value from an agent's namespace.

        Args:
            namespace: The agent's memory namespace.
            key: The key to read.
            default: Default value if key not found.

        Returns:
            The stored value or default.
        """
        lock = self._get_lock(namespace)
        with lock:
            store = self._load_store(namespace)
            value = store.get("data", {}).get(key, default)
            logger.info(f"Memory READ: ns={namespace}, key={key}")
            return value

    def read_all(self, namespace: str) -> dict[str, Any]:
        """Read all data from an agent's namespace."""
        lock = self._get_lock(namespace)
        with lock:
            store = self._load_store(namespace)
            return store.get("data", {})

    # ----- Write Operations -----

    def write(self, namespace: str, key: str, value: Any) -> None:
        """
        Write a value to an agent's namespace.

        Args:
            namespace: The agent's memory namespace.
            key: The key to write.
            value: The value to store.
        """
        lock = self._get_lock(namespace)
        with lock:
            store = self._load_store(namespace)
            if "data" not in store:
                store["data"] = {}
            store["data"][key] = value
            store["last_modified"] = datetime.utcnow().isoformat()
            self._save_store(namespace, store)
            logger.info(f"Memory WRITE: ns={namespace}, key={key}")

    def delete(self, namespace: str, key: str) -> bool:
        """Delete a key from an agent's namespace."""
        lock = self._get_lock(namespace)
        with lock:
            store = self._load_store(namespace)
            if key in store.get("data", {}):
                del store["data"][key]
                store["last_modified"] = datetime.utcnow().isoformat()
                self._save_store(namespace, store)
                logger.info(f"Memory DELETE: ns={namespace}, key={key}")
                return True
            return False

    # ----- Shared Events (append-only via orchestrator — INV-9) -----

    def append_shared_event(self, event: dict[str, Any]) -> None:
        """
        Append an event to the shared event store.
        This is append-only and should only be called by the orchestrator.
        """
        lock = self._get_lock("shared")
        with lock:
            events_file = MEMORY_DIR / "shared" / "events.json"
            try:
                data = json.loads(events_file.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                data = {"events": []}
            event["timestamp"] = datetime.utcnow().isoformat()
            data["events"].append(event)
            events_file.write_text(json.dumps(data, indent=2))
            logger.info(f"Shared event appended: {event.get('type', 'unknown')}")

    def get_shared_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read recent shared events."""
        lock = self._get_lock("shared")
        with lock:
            events_file = MEMORY_DIR / "shared" / "events.json"
            try:
                data = json.loads(events_file.read_text())
                return data.get("events", [])[-limit:]
            except (json.JSONDecodeError, FileNotFoundError):
                return []

    # ----- Namespace Info -----

    def get_namespace_size(self, namespace: str) -> int:
        """Get the size in bytes of a namespace's store file."""
        store_file = self._store_file(namespace)
        if store_file.exists():
            return store_file.stat().st_size
        return 0

    def list_namespaces(self) -> list[str]:
        """List all existing memory namespaces."""
        if not MEMORY_DIR.exists():
            return []
        return [d.name for d in MEMORY_DIR.iterdir() if d.is_dir() and d.name != "shared"]

    # ----- Handoff Memory (temporary inter-agent context) -----

    def write_handoff(
        self,
        from_agent: str,
        to_agent: str,
        payload: dict[str, Any],
        ttl_seconds: int = 300,
    ) -> str:
        """
        Write a temporary handoff message from one agent to another.

        The handoff is stored in a shared handoff directory and auto-expires
        after ``ttl_seconds`` (default 5 minutes). The receiving agent can
        read it once with ``read_handoffs()``, which also prunes expired entries.

        Returns the handoff ID.
        """
        import uuid

        handoff_dir = MEMORY_DIR / "handoffs"
        handoff_dir.mkdir(parents=True, exist_ok=True)
        handoff_file = handoff_dir / "pending.json"

        lock = self._get_lock("handoffs")
        with lock:
            try:
                data = json.loads(handoff_file.read_text()) if handoff_file.exists() else {"handoffs": []}
            except (json.JSONDecodeError, FileNotFoundError):
                data = {"handoffs": []}

            handoff_id = uuid.uuid4().hex[:12]
            entry = {
                "id": handoff_id,
                "from_agent": from_agent,
                "to_agent": to_agent,
                "payload": payload,
                "created": datetime.utcnow().isoformat(),
                "ttl_seconds": ttl_seconds,
            }
            data["handoffs"].append(entry)
            handoff_file.write_text(json.dumps(data, indent=2, default=str))
            logger.info(f"Handoff WRITE: {from_agent} → {to_agent} (id={handoff_id}, ttl={ttl_seconds}s)")
            return handoff_id

    def read_handoffs(self, agent_id: str, consume: bool = True) -> list[dict[str, Any]]:
        """
        Read all pending handoff messages for an agent.

        Prunes expired entries. If ``consume=True``, the read entries
        are removed from the store (consume-once semantics).
        """
        handoff_dir = MEMORY_DIR / "handoffs"
        handoff_file = handoff_dir / "pending.json"
        if not handoff_file.exists():
            return []

        lock = self._get_lock("handoffs")
        with lock:
            try:
                data = json.loads(handoff_file.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                return []

            now = datetime.utcnow()
            alive: list[dict[str, Any]] = []
            matched: list[dict[str, Any]] = []

            for entry in data.get("handoffs", []):
                created = datetime.fromisoformat(entry["created"])
                age = (now - created).total_seconds()
                if age > entry.get("ttl_seconds", 300):
                    continue  # expired — prune
                if entry["to_agent"] == agent_id:
                    matched.append(entry)
                    if not consume:
                        alive.append(entry)
                else:
                    alive.append(entry)

            data["handoffs"] = alive
            handoff_file.write_text(json.dumps(data, indent=2, default=str))

            if matched:
                logger.info(f"Handoff READ: {agent_id} consumed {len(matched)} handoff(s)")
            return matched

    # ----- Internal -----

    def _load_store(self, namespace: str) -> dict[str, Any]:
        """Load the JSON store for a namespace."""
        store_file = self._store_file(namespace)
        if store_file.exists():
            try:
                return json.loads(store_file.read_text())
            except json.JSONDecodeError:
                logger.warning(f"Corrupted store for namespace {namespace}, resetting")
                return {"data": {}, "created": datetime.utcnow().isoformat()}
        return {"data": {}, "created": datetime.utcnow().isoformat()}

    def _save_store(self, namespace: str, store: dict[str, Any]) -> None:
        """Save the JSON store for a namespace."""
        store_file = self._store_file(namespace)
        store_file.write_text(json.dumps(store, indent=2, default=str))


# Module-level singleton
memory_store = MemoryStore()
