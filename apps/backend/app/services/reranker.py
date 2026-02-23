"""Cross-encoder reranker helpers for post-retrieval candidate ordering."""
from __future__ import annotations

import time
import math
from typing import List, Tuple

from app.config import (
    RERANK_ENABLED,
    RERANK_MODEL,
    RERANK_TIMEOUT_MS,
)
from app.services.retrieval import HybridHit

try:
    from sentence_transformers import CrossEncoder
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    CrossEncoder = None  # type: ignore[assignment]


_cross_encoder: CrossEncoder | None = None  # type: ignore[valid-type]
_load_failed = False


def _get_cross_encoder() -> CrossEncoder | None:  # type: ignore[valid-type]
    global _cross_encoder, _load_failed
    if _cross_encoder is not None:
        return _cross_encoder
    if _load_failed or CrossEncoder is None:
        return None
    try:
        _cross_encoder = CrossEncoder(RERANK_MODEL)
        return _cross_encoder
    except Exception:
        _load_failed = True
        return None


def rerank_hybrid_hits(
    *,
    question: str,
    hits: List[HybridHit],
    top_k: int,
    max_candidates: int,
) -> Tuple[List[HybridHit], bool, str | None]:
    """
    Apply cross-encoder reranking over hybrid candidates.

    Returns:
        (reranked_hits, used_reranker, reason_if_skipped)
    """
    if not hits:
        return [], False, "No candidates to rerank."
    if not RERANK_ENABLED:
        return hits[:top_k], False, "Reranker disabled by config."

    model = _get_cross_encoder()
    if model is None:
        if CrossEncoder is None:
            return hits[:top_k], False, "sentence-transformers is not installed."
        return hits[:top_k], False, "Cross-encoder model could not be loaded."

    candidate_hits = hits[:max(1, max_candidates)]
    model_inputs = [(question, hit.text) for hit in candidate_hits]

    start = time.perf_counter()
    try:
        scores = model.predict(model_inputs, show_progress_bar=False)
    except Exception:
        return hits[:top_k], False, "Cross-encoder inference failed."

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if elapsed_ms > float(RERANK_TIMEOUT_MS):
        return hits[:top_k], False, "Reranker timed out; using hybrid ordering."

    for hit, score in zip(candidate_hits, scores):
        # Convert cross-encoder logits to [0, 1] so existing confidence
        # thresholds remain comparable with previous retrieval scoring.
        logit = float(score)
        if logit >= 0:
            z = math.exp(-logit)
            hit.score = 1.0 / (1.0 + z)
        else:
            z = math.exp(logit)
            hit.score = z / (1.0 + z)

    candidate_hits.sort(key=lambda hit: hit.score, reverse=True)
    return candidate_hits[:top_k], True, None
