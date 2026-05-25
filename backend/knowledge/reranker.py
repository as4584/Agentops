# backend/knowledge/reranker.py
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_TOP_K = 5
_CANDIDATE_POOL = 20  # RRF sends at most 20 into the reranker


class Reranker:
    """
    Local cross-encoder reranker. ONNX-accelerated via
    sentence-transformers. Never calls an external API (INV-16).

    Failure contract:
        Any error in load or score returns the input list unchanged.
        Callers receive Sprint 2 RRF ordering — not an exception.
    """

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: Any | None = None
        self._load()

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            self._model = CrossEncoder(
                self._model_name,
                max_length=512,
                device="cpu",
            )
            logger.info("Reranker loaded: %s", self._model_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Reranker failed to load (%s). "
                "Falling back to RRF ordering on every call.",
                exc,
            )
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = _TOP_K,
        text_field: str = "text",
    ) -> list[dict]:
        """
        Score each candidate against the query.
        Returns top_k results sorted by reranker score (descending).

        Falls back to input[:top_k] if the model is unavailable
        or scoring raises.

        Args:
            query:       The user/agent query string.
            candidates:  List of chunk dicts (must contain text_field key).
            top_k:       How many to return. Default 5.
            text_field:  Dict key that holds the passage text.

        Returns:
            Reranked list of chunk dicts, each annotated with
            "_reranker_score" for downstream observability.
        """
        if not candidates:
            return []

        if not self.available:
            logger.debug("Reranker unavailable — returning RRF top-%d", top_k)
            return candidates[:top_k]

        pool = candidates[:_CANDIDATE_POOL]

        try:
            pairs = [[query, c.get(text_field, "")] for c in pool]
            scores: list[float] = self._model.predict(pairs).tolist()

            scored = [
                {**chunk, "_reranker_score": score}
                for chunk, score in zip(pool, scores)
            ]
            scored.sort(key=lambda x: x["_reranker_score"], reverse=True)
            return scored[:top_k]

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Reranker scoring failed (%s). "
                "Returning RRF top-%d unchanged.",
                exc,
                top_k,
            )
            return candidates[:top_k]
