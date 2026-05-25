"""End-to-end tests for the Week 2 ticket A1 ingestion CLI.

Covers:
  * ``python -m cli.ingest_cli <path>`` ingests .md / .txt / .rst.
  * Idempotency: a second run re-uses the manifest and reports
    ``skipped_unchanged > 0`` with zero new upserts.
  * Editing a file invalidates only that file's manifest entry and re-embeds.
  * ``--reindex`` drops the collection and clears the manifest.
  * Output is valid JSON for downstream tooling.

The Qdrant client is replaced with an in-process fake so the test does not
require a running Qdrant / Ollama. Embeddings are mocked to a small fixed
vector — vector contents do not matter for these structural assertions.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# In-process Qdrant fake — patterned after backend/tests/test_sprint7_convergence.py
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self) -> None:
        self._points: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._client = MagicMock()
        self._client.get_collections.return_value = MagicMock(collections=[])
        self._collections_initialized: set[str] = set()
        self.upsert_calls: int = 0

    # backend.knowledge.doc_seed force_rebuild path -------------------------
    def _drop_collection(self, name: str) -> None:
        self._points.pop(name, None)
        self._collections_initialized.discard(name)

    # Mirror VectorStore surface --------------------------------------------
    def ensure_collection(self, name: str) -> None:
        self._collections_initialized.add(name)

    def upsert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str],
        collection: str = "",
        agent_namespace: str = "",
    ) -> int:
        del vectors, agent_namespace
        coll = collection or "knowledge_agent"
        self.ensure_collection(coll)
        for idx, payload in enumerate(payloads):
            point_id = ids[idx] if ids else str(idx)
            self._points[coll][point_id] = payload
        self.upsert_calls += 1
        return len(payloads)

    def count(self, collection: str = "") -> int:
        coll = collection or "knowledge_agent"
        return len(self._points.get(coll, {}))


def _patch_force_rebuild_drop(store: _FakeStore) -> None:
    """Wire fake store.get_collections so force_rebuild path drops cleanly."""

    def _drop_side_effect(collection_name: str) -> None:
        store._drop_collection(collection_name)

    store._client.delete_collection.side_effect = _drop_side_effect
    store._client.get_collections.return_value = MagicMock(
        collections=[MagicMock(name=name) for name in list(store._points.keys())]
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_store() -> _FakeStore:
    return _FakeStore()


@pytest.fixture()
def docs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "MVP_SCOPE.md").write_text(
        "# MVP Scope\n\nThe MVP includes a knowledge agent backed by Qdrant.\n" + "alpha " * 200,
        encoding="utf-8",
    )
    (d / "notes.txt").write_text("Plain text note describing operator workflow.\n" + "beta " * 200, encoding="utf-8")
    (d / "spec.rst").write_text("Spec\n====\n\nReStructuredText body.\n" + "gamma " * 200, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str], fake_store: _FakeStore, manifest_dir: Path) -> tuple[int, dict[str, Any]]:
    """Invoke ``cli.ingest_cli.main`` with all I/O patched out, capture JSON."""
    from cli import ingest_cli

    mock_llm = MagicMock()
    mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
    mock_llm.close = AsyncMock()

    _patch_force_rebuild_drop(fake_store)

    buf = io.StringIO()
    with (
        patch("backend.knowledge.doc_seed.get_vector_store", return_value=fake_store),
        patch("backend.knowledge.doc_seed.QDRANT_AVAILABLE", True),
        patch("backend.knowledge.doc_seed.INGEST_MANIFEST_DIR", manifest_dir),
        patch("backend.llm.OllamaClient", return_value=mock_llm),
        patch("cli.ingest_cli.OllamaClient", return_value=mock_llm),
        redirect_stdout(buf),
    ):
        rc = ingest_cli.main(argv)

    out = buf.getvalue().strip()
    summary = json.loads(out) if out else {}
    return rc, summary


def test_ingest_cli_seeds_md_txt_rst(fake_store: _FakeStore, docs_dir: Path, tmp_path: Path) -> None:
    rc, summary = _run_cli(
        [str(docs_dir), "--collection", "knowledge_agent", "--skip-bm25"],
        fake_store,
        tmp_path / "manifests",
    )

    assert rc == 0, summary
    assert summary["seeded"] is True
    # All 3 files (md + txt + rst) were ingested
    assert summary["source_documents"] == 3
    assert summary["processed_documents"] == 3
    assert summary["skipped_unchanged"] == 0
    assert summary["chunks"] >= 3
    assert fake_store.count("knowledge_agent") >= 3

    # Sources captured per-payload include all three relative paths
    sources = {p["source"] for p in fake_store._points["knowledge_agent"].values()}
    assert any(s.endswith("MVP_SCOPE.md") for s in sources)
    assert any(s.endswith("notes.txt") for s in sources)
    assert any(s.endswith("spec.rst") for s in sources)


def test_ingest_cli_is_idempotent_via_hash_manifest(fake_store: _FakeStore, docs_dir: Path, tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"

    rc1, first = _run_cli([str(docs_dir), "--skip-bm25"], fake_store, manifests)
    assert rc1 == 0
    first_upsert_calls = fake_store.upsert_calls
    assert first["processed_documents"] == 3
    assert first["skipped_unchanged"] == 0
    assert first_upsert_calls > 0

    # Manifest file was persisted
    manifest_file = manifests / "ingest_manifest_knowledge_agent.json"
    assert manifest_file.is_file(), "ingest manifest should be persisted on disk"
    manifest_data = json.loads(manifest_file.read_text())
    assert len(manifest_data) == 3

    # Second run — every file is unchanged ⇒ zero embed/upsert work
    rc2, second = _run_cli([str(docs_dir), "--skip-bm25"], fake_store, manifests)
    assert rc2 == 0
    assert second["processed_documents"] == 0
    assert second["skipped_unchanged"] == 3
    assert fake_store.upsert_calls == first_upsert_calls, "no new upserts should occur for unchanged corpus"


def test_ingest_cli_reembeds_only_modified_file(fake_store: _FakeStore, docs_dir: Path, tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    _run_cli([str(docs_dir), "--skip-bm25"], fake_store, manifests)
    baseline_upserts = fake_store.upsert_calls

    # Mutate one file → its hash changes, the other two stay cached
    (docs_dir / "notes.txt").write_text(
        "Plain text note - REVISED operator workflow.\n" + "delta " * 200, encoding="utf-8"
    )

    rc, summary = _run_cli([str(docs_dir), "--skip-bm25"], fake_store, manifests)
    assert rc == 0
    assert summary["processed_documents"] == 1
    assert summary["skipped_unchanged"] == 2
    assert fake_store.upsert_calls > baseline_upserts


def test_ingest_cli_reindex_drops_manifest(fake_store: _FakeStore, docs_dir: Path, tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    _run_cli([str(docs_dir), "--skip-bm25"], fake_store, manifests)
    baseline_upserts = fake_store.upsert_calls

    rc, summary = _run_cli(
        [str(docs_dir), "--skip-bm25", "--reindex"],
        fake_store,
        manifests,
    )
    assert rc == 0
    # force_rebuild wipes the manifest → every file is re-processed
    assert summary["processed_documents"] == 3
    assert summary["skipped_unchanged"] == 0
    assert fake_store.upsert_calls > baseline_upserts


def test_ingest_cli_rejects_non_directory(tmp_path: Path, fake_store: _FakeStore) -> None:
    bogus = tmp_path / "does_not_exist"
    rc, summary = _run_cli([str(bogus), "--skip-bm25"], fake_store, tmp_path / "manifests")
    assert rc == 2
    assert summary == {}
