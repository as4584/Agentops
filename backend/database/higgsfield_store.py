"""
Higgsfield Store — SQLite persistence for character registry, generation runs, and RAG corpus.
==============================================================================================
Tables:
  characters       — locked character identities (Xpel, MrWilly, ...)
  generation_runs  — every video generation attempt (success or failure)
  rag_entries      — structured evidence for the RAG improvement loop
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


# ---------------------------------------------------------------------------
# Default DB path — relative to project root
# ---------------------------------------------------------------------------
_DEFAULT_DB = Path("data/higgsfield/higgsfield.db")


class HighgsfieldStore:
    """CRUD layer for all Higgsfield data."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                -- Characters: locked identity registry
                CREATE TABLE IF NOT EXISTS characters (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL UNIQUE,
                    character_type TEXT NOT NULL DEFAULT 'human_character',
                    soul_id_url   TEXT,
                    soul_id_status TEXT NOT NULL DEFAULT 'pending',
                    anchor_image_path TEXT NOT NULL,
                    positive_prefix TEXT,
                    negative_prefix TEXT,
                    profile_json  TEXT,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                );

                -- Generation runs: every attempt logged (success + failure)
                CREATE TABLE IF NOT EXISTS generation_runs (
                    id              TEXT PRIMARY KEY,
                    character_id    TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    prompt          TEXT NOT NULL,
                    anchor_image    TEXT,
                    outcome         TEXT NOT NULL DEFAULT 'pending',
                    failure_reason  TEXT,
                    result_url      TEXT,
                    evidence_path   TEXT,
                    duration_s      REAL,
                    cost_usd        REAL,
                    campaign        TEXT,
                    tags_json       TEXT,
                    created_at      TEXT NOT NULL,
                    completed_at    TEXT,
                    FOREIGN KEY(character_id) REFERENCES characters(id)
                );

                CREATE INDEX IF NOT EXISTS idx_runs_character
                ON generation_runs(character_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_runs_outcome
                ON generation_runs(outcome, created_at DESC);

                -- RAG corpus: structured evidence for improvement loop
                CREATE TABLE IF NOT EXISTS rag_entries (
                    id              TEXT PRIMARY KEY,
                    run_id          TEXT NOT NULL,
                    character_id    TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    prompt          TEXT NOT NULL,
                    outcome         TEXT NOT NULL,
                    failure_reason  TEXT,
                    evidence_screenshot TEXT,
                    result_url      TEXT,
                    tags_json       TEXT,
                    lesson          TEXT,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES generation_runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_rag_character
                ON rag_entries(character_id, outcome);

                PRAGMA journal_mode=WAL;
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------

    def upsert_character(
        self,
        *,
        name: str,
        character_type: str = "human_character",
        anchor_image_path: str,
        positive_prefix: str = "",
        negative_prefix: str = "",
        profile_json: dict[str, Any] | None = None,
        soul_id_url: str | None = None,
        soul_id_status: str = "pending",
    ) -> str:
        """Insert or update a character record. Returns the character ID."""
        now = datetime.now(timezone.utc).isoformat()
        char_id = f"char_{name.lower().replace(' ', '_')}"
        profile_str = json.dumps(profile_json) if profile_json else None

        with self.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM characters WHERE name = ?", (name,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE characters SET
                        character_type=?, soul_id_url=?, soul_id_status=?,
                        anchor_image_path=?, positive_prefix=?, negative_prefix=?,
                        profile_json=?, updated_at=?
                    WHERE name=?
                    """,
                    (
                        character_type, soul_id_url, soul_id_status,
                        anchor_image_path, positive_prefix, negative_prefix,
                        profile_str, now, name,
                    ),
                )
                conn.commit()
                return str(existing["id"])

            conn.execute(
                """
                INSERT INTO characters
                    (id, name, character_type, soul_id_url, soul_id_status,
                     anchor_image_path, positive_prefix, negative_prefix,
                     profile_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    char_id, name, character_type, soul_id_url, soul_id_status,
                    anchor_image_path, positive_prefix, negative_prefix,
                    profile_str, now, now,
                ),
            )
            conn.commit()
        return char_id

    def get_character(self, character_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE id=?", (character_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_character_by_name(self, name: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE name=?", (name,)
            ).fetchone()
        return dict(row) if row else None

    def list_characters(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM characters ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_soul_id(self, character_id: str, soul_id_url: str, status: str = "locked") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "UPDATE characters SET soul_id_url=?, soul_id_status=?, updated_at=? WHERE id=?",
                (soul_id_url, status, now, character_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Generation Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        character_id: str,
        model: str,
        prompt: str,
        anchor_image: str | None = None,
        campaign: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        run_id = f"run_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        tags_str = json.dumps(tags or [])
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO generation_runs
                    (id, character_id, model, prompt, anchor_image,
                     outcome, campaign, tags_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (run_id, character_id, model, prompt, anchor_image,
                 "pending", campaign, tags_str, now),
            )
            conn.commit()
        return run_id

    def complete_run(
        self,
        run_id: str,
        *,
        outcome: str,  # "success" | "failure" | "partial"
        result_url: str | None = None,
        evidence_path: str | None = None,
        failure_reason: str | None = None,
        duration_s: float | None = None,
        cost_usd: float | None = None,
        tags: list[str] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            # Get current tags to merge
            row = conn.execute(
                "SELECT tags_json FROM generation_runs WHERE id=?", (run_id,)
            ).fetchone()
            prev_tags: list[str] = json.loads(row["tags_json"] or "[]") if row else []
            merged_tags = list(set(prev_tags + (tags or [])))

            conn.execute(
                """
                UPDATE generation_runs SET
                    outcome=?, result_url=?, evidence_path=?,
                    failure_reason=?, duration_s=?, cost_usd=?,
                    tags_json=?, completed_at=?
                WHERE id=?
                """,
                (
                    outcome, result_url, evidence_path,
                    failure_reason, duration_s, cost_usd,
                    json.dumps(merged_tags), now, run_id,
                ),
            )
            conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM generation_runs WHERE id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self,
        character_id: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if character_id and outcome:
                rows = conn.execute(
                    "SELECT * FROM generation_runs WHERE character_id=? AND outcome=? ORDER BY created_at DESC LIMIT ?",
                    (character_id, outcome, limit),
                ).fetchall()
            elif character_id:
                rows = conn.execute(
                    "SELECT * FROM generation_runs WHERE character_id=? ORDER BY created_at DESC LIMIT ?",
                    (character_id, limit),
                ).fetchall()
            elif outcome:
                rows = conn.execute(
                    "SELECT * FROM generation_runs WHERE outcome=? ORDER BY created_at DESC LIMIT ?",
                    (outcome, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM generation_runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def count_consecutive_failures(self, character_id: str, model: str) -> int:
        """Count consecutive failures for a character+model combo (for research trigger)."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT outcome FROM generation_runs
                WHERE character_id=? AND model=?
                ORDER BY created_at DESC LIMIT 10
                """,
                (character_id, model),
            ).fetchall()
        count = 0
        for r in rows:
            if r["outcome"] == "failure":
                count += 1
            else:
                break
        return count

    # ------------------------------------------------------------------
    # RAG Corpus
    # ------------------------------------------------------------------

    def add_rag_entry(
        self,
        *,
        run_id: str,
        character_id: str,
        model: str,
        prompt: str,
        outcome: str,
        failure_reason: str | None = None,
        evidence_screenshot: str | None = None,
        result_url: str | None = None,
        tags: list[str] | None = None,
        lesson: str | None = None,
    ) -> str:
        entry_id = f"rag_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO rag_entries
                    (id, run_id, character_id, model, prompt, outcome,
                     failure_reason, evidence_screenshot, result_url,
                     tags_json, lesson, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry_id, run_id, character_id, model, prompt, outcome,
                    failure_reason, evidence_screenshot, result_url,
                    json.dumps(tags or []), lesson, now,
                ),
            )
            conn.commit()
        return entry_id

    def get_rag_entries(
        self,
        character_id: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if character_id and outcome:
                rows = conn.execute(
                    "SELECT * FROM rag_entries WHERE character_id=? AND outcome=? ORDER BY created_at DESC LIMIT ?",
                    (character_id, outcome, limit),
                ).fetchall()
            elif character_id:
                rows = conn.execute(
                    "SELECT * FROM rag_entries WHERE character_id=? ORDER BY created_at DESC LIMIT ?",
                    (character_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rag_entries ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_failure_patterns(self, character_id: str | None = None) -> list[dict[str, Any]]:
        """Aggregate failure reasons for RAG analysis."""
        with self.connection() as conn:
            if character_id:
                rows = conn.execute(
                    """
                    SELECT failure_reason, COUNT(*) as count, model
                    FROM rag_entries
                    WHERE outcome='failure' AND character_id=?
                    GROUP BY failure_reason, model
                    ORDER BY count DESC
                    """,
                    (character_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT failure_reason, COUNT(*) as count, model
                    FROM rag_entries
                    WHERE outcome='failure'
                    GROUP BY failure_reason, model
                    ORDER BY count DESC
                    """
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            total_runs = conn.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0]
            successes = conn.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE outcome='success'"
            ).fetchone()[0]
            failures = conn.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE outcome='failure'"
            ).fetchone()[0]
            total_cost = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM generation_runs"
            ).fetchone()[0]
            soul_id_locked = conn.execute(
                "SELECT COUNT(*) FROM characters WHERE soul_id_status='locked'"
            ).fetchone()[0]
        return {
            "total_runs": total_runs,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total_runs, 3) if total_runs else 0.0,
            "total_cost_usd": round(total_cost, 4),
            "soul_id_locked": soul_id_locked,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
higgsfield_store = HighgsfieldStore()
