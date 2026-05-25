"""
BM25 sparse index over the Agentop RAG corpus.
Runs entirely local — no external dependencies beyond rank_bm25.
Designed to sit alongside Qdrant dense retrieval, not replace it.
Merged with dense hits via Reciprocal Rank Fusion in retrieval_engine.py.
"""

import json
import logging
import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

BM25_INDEX_PATH = Path("data/bm25_index.pkl")
BM25_META_PATH = Path("data/bm25_meta.json")


class BM25Index:
    """
    Persistent BM25 index over corpus chunks.
    Rebuilt from Qdrant payload on first run or when
    force_rebuild=True. Incremental updates not supported —
    rebuild is fast enough (< 2s for 9000 chunks).
    """

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunks: list[dict] = []  # parallel to BM25 corpus
        self._built = False

    # ----------------------------------------------------------------
    # Build
    # ----------------------------------------------------------------

    def build(
        self,
        chunks: list[dict],
        force_rebuild: bool = False,
    ) -> None:
        """
        Build BM25 index from chunk list.
        Each chunk must have: chunk_id, text, source, section,
        agent_scope, last_indexed.
        """
        if self._built and not force_rebuild:
            return

        if not chunks:
            logger.warning("[BM25] build() called with empty chunk list")
            return

        logger.info(f"[BM25] Building index over {len(chunks)} chunks")

        self._chunks = chunks
        tokenized = [self._tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(tokenized)
        self._built = True

        self._persist()
        logger.info("[BM25] Index built and persisted")

    def _tokenize(self, text: str) -> list[str]:
        """
        Lowercase, split on whitespace and punctuation.
        Keeps numbers intact — critical for IP/port exact matching.
        """
        import re

        tokens = re.findall(r"[a-z0-9_\.\-\/]+", text.lower())
        return tokens if tokens else ["__empty__"]

    # ----------------------------------------------------------------
    # Search
    # ----------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 20,
        agent_scope: str | None = None,
        source_prefix: list[str] | None = None,
    ) -> list[dict]:
        """
        BM25 search with optional scope filtering.
        Returns list of chunk dicts with bm25_score appended.
        """
        if not self._built or self._bm25 is None:
            logger.warning("[BM25] search() called before index built")
            return []

        query_tokens = self._tokenize(query)
        scores = self._bm25.get_scores(query_tokens)

        # Pair chunks with scores
        scored = [{**self._chunks[i], "bm25_score": float(scores[i])} for i in range(len(self._chunks))]

        # Apply scope filter
        if agent_scope:
            scored = [c for c in scored if agent_scope in c.get("agent_scope", []) or "all" in c.get("agent_scope", [])]

        # Apply source prefix filter
        if source_prefix:
            scored = [c for c in scored if any(c["source"].startswith(p) for p in source_prefix)]

        # Sort by BM25 score, return top_k
        scored.sort(key=lambda x: x["bm25_score"], reverse=True)

        # Discard zero-score results — no signal
        nonzero = [c for c in scored if c["bm25_score"] > 0.0]

        return nonzero[:top_k]

    # ----------------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------------

    def _persist(self) -> None:
        BM25_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BM25_INDEX_PATH.open("wb") as f:
            pickle.dump(self._bm25, f)
        with BM25_META_PATH.open("w") as f:
            json.dump(
                {
                    "chunk_count": len(self._chunks),
                    "chunks": self._chunks,
                },
                f,
                indent=2,
            )
        logger.info(f"[BM25] Persisted {len(self._chunks)} chunks to {BM25_INDEX_PATH}")

    def load(self) -> bool:
        """
        Load persisted index. Returns True if successful.
        Falls back gracefully — dense retrieval continues if
        BM25 index is absent.
        """
        if not BM25_INDEX_PATH.exists() or not BM25_META_PATH.exists():
            logger.info("[BM25] No persisted index found — will rebuild")
            return False

        try:
            with BM25_INDEX_PATH.open("rb") as f:
                self._bm25 = pickle.load(f)
            with BM25_META_PATH.open() as f:
                meta = json.load(f)
                self._chunks = meta["chunks"]
            self._built = True
            logger.info(f"[BM25] Loaded {len(self._chunks)} chunks from {BM25_INDEX_PATH}")
            return True
        except Exception as e:
            logger.warning(f"[BM25] Load failed: {e} — will rebuild")
            self._built = False
            return False

    @property
    def available(self) -> bool:
        return self._built and self._bm25 is not None

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)
