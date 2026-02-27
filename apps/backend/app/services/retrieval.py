"""Hybrid retrieval helpers: vector + BM25 lexical search with score fusion."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

try:
    from rank_bm25 import BM25Okapi
except ModuleNotFoundError:  # pragma: no cover - fallback for uninstalled dependency
    BM25Okapi = None  # type: ignore[assignment]

from app.db.database import db_cursor


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\\-\\.]+")
_RRF_K = 60.0


@dataclass
class LexicalHit:
    file_id: int
    chunk_index: int
    page_number: int | None
    filename: str
    text: str
    bm25_score: float


@dataclass
class HybridHit:
    file_id: int
    chunk_index: int
    page_number: int | None
    filename: str
    text: str
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0


def _tokenize(text: str) -> List[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


def _fallback_keyword_scores(
    query_tokens: List[str],
    docs_tokens: List[List[str]],
) -> List[float]:
    """
    Lightweight lexical fallback when rank_bm25 is unavailable.

    Uses token overlap ratio so retrieval still functions until dependencies
    are installed from requirements.txt.
    """
    query_set = set(query_tokens)
    if not query_set:
        return [0.0 for _ in docs_tokens]
    scores: List[float] = []
    for doc_tokens in docs_tokens:
        if not doc_tokens:
            scores.append(0.0)
            continue
        doc_set = set(doc_tokens)
        overlap = len(query_set.intersection(doc_set))
        scores.append(float(overlap) / float(len(query_set)))
    return scores


def bm25_search_chunks(
    conn,
    *,
    question: str,
    file_id: int | None,
    limit: int,
) -> List[LexicalHit]:
    """Retrieve top lexical matches from stored chunks using BM25."""
    query_tokens = _tokenize(question)
    if not query_tokens:
        return []

    sql = (
        """
        SELECT c.file_id, c.chunk_index, c.page_number, c.content, f.filename
        FROM file_chunks c
        JOIN uploaded_files f ON f.id = c.file_id
        """
    )
    params: tuple[Any, ...] = ()
    if file_id is not None:
        sql += " WHERE c.file_id = %s"
        params = (file_id,)
    sql += " ORDER BY c.file_id ASC, c.chunk_index ASC;"

    with db_cursor(conn) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        return []

    docs_tokens: List[List[str]] = []
    for row in rows:
        docs_tokens.append(_tokenize(str(row[3])))

    if BM25Okapi is not None:
        bm25 = BM25Okapi(docs_tokens)
        raw_scores = bm25.get_scores(query_tokens)
    else:
        raw_scores = _fallback_keyword_scores(query_tokens, docs_tokens)

    ranked: List[Tuple[float, tuple[Any, ...]]] = sorted(
        ((float(score), row) for score, row in zip(raw_scores, rows) if float(score) > 0.0),
        key=lambda item: item[0],
        reverse=True,
    )

    hits: List[LexicalHit] = []
    for score, row in ranked[:limit]:
        hits.append(
            LexicalHit(
                file_id=int(row[0]),
                chunk_index=int(row[1]),
                page_number=(int(row[2]) if row[2] is not None else None),
                text=str(row[3]),
                filename=str(row[4] or f"file_{int(row[0])}"),
                bm25_score=score,
            )
        )
    return hits


def _normalize_scores(values: Iterable[float]) -> Dict[float, float]:
    values_list = list(values)
    if not values_list:
        return {}
    min_v = min(values_list)
    max_v = max(values_list)
    if max_v - min_v <= 1e-9:
        return {v: 1.0 for v in values_list}
    return {v: (v - min_v) / (max_v - min_v) for v in values_list}


def _extract_what_is_target(question: str | None) -> str | None:
    if not question:
        return None
    m = re.match(r"^\s*what\s+is\s+(.+?)\s*\??\s*$", question.strip(), flags=re.IGNORECASE)
    if not m:
        return None
    target = m.group(1).strip().strip('"').strip("'")
    return target.lower() if target else None


def _definition_boost(text: str, target: str | None) -> float:
    if not target:
        return 0.0
    body = (text or "").lower()
    boost = 0.0
    if f"what is {target}" in body:
        boost += 0.20
    if re.search(rf"\b{re.escape(target)}\b\s+(is|are|refers to|means|returns)\b", body):
        boost += 0.20
    if target in body:
        boost += 0.05
    return boost


def fuse_and_rank_hits(
    *,
    vector_hits: List[Any],
    lexical_hits: List[LexicalHit],
    top_k: int,
    question: str | None = None,
) -> List[HybridHit]:
    """
    Merge vector and lexical candidates, then rank using a blended score.

    Final score blend:
      - normalized vector score
      - normalized BM25 score
      - Reciprocal rank fusion bonus from both rankings
    """
    merged: Dict[tuple[int, int], HybridHit] = {}

    vector_scores: List[float] = []
    for item in vector_hits:
        if item.score is None:
            continue
        vector_scores.append(float(item.score))
    vector_norm = _normalize_scores(vector_scores)

    lexical_scores = [float(item.bm25_score) for item in lexical_hits]
    lexical_norm = _normalize_scores(lexical_scores)

    for rank, item in enumerate(vector_hits, start=1):
        payload = item.payload or {}
        raw_file_id = payload.get("file_id")
        raw_chunk_index = payload.get("chunk_index")
        text = str(payload.get("text") or "")
        if raw_file_id is None or raw_chunk_index is None or not text:
            continue
        try:
            file_id = int(raw_file_id)
            chunk_index = int(raw_chunk_index)
            page_number = int(payload.get("page_number")) if payload.get("page_number") is not None else None
        except (TypeError, ValueError):
            continue

        key = (file_id, chunk_index)
        vec_score = float(item.score) if item.score is not None else 0.0
        rrf = 1.0 / (_RRF_K + rank)
        merged[key] = HybridHit(
            file_id=file_id,
            chunk_index=chunk_index,
            page_number=page_number,
            filename=str(payload.get("filename") or f"file_{file_id}"),
            text=text,
            score=0.0,
            vector_score=vector_norm.get(vec_score, 0.0) + rrf,
            bm25_score=0.0,
        )

    for rank, item in enumerate(lexical_hits, start=1):
        key = (item.file_id, item.chunk_index)
        rrf = 1.0 / (_RRF_K + rank)
        lex_score = lexical_norm.get(float(item.bm25_score), 0.0) + rrf
        if key in merged:
            merged[key].bm25_score = lex_score
            if not merged[key].text:
                merged[key].text = item.text
            if not merged[key].filename:
                merged[key].filename = item.filename
            if merged[key].page_number is None:
                merged[key].page_number = item.page_number
        else:
            merged[key] = HybridHit(
                file_id=item.file_id,
                chunk_index=item.chunk_index,
                page_number=item.page_number,
                filename=item.filename,
                text=item.text,
                score=0.0,
                vector_score=0.0,
                bm25_score=lex_score,
            )

    ranked_hits = list(merged.values())
    question_tokens = set(_tokenize(question or ""))
    target = _extract_what_is_target(question)

    for item in ranked_hits:
        doc_tokens = set(_tokenize(item.text))
        overlap = (
            float(len(question_tokens.intersection(doc_tokens))) / float(len(question_tokens))
            if question_tokens
            else 0.0
        )
        def_boost = _definition_boost(item.text, target)

        # Keep score in [0, 1] so existing thresholds remain meaningful.
        final = (
            (0.50 * item.vector_score)
            + (0.30 * item.bm25_score)
            + (0.15 * overlap)
            + def_boost
        )
        item.score = max(0.0, min(final, 1.0))

    ranked_hits.sort(key=lambda hit: hit.score, reverse=True)
    return ranked_hits[:top_k]
