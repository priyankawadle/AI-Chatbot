"""Routes that handle chat over uploaded documents."""
import re
from typing import List, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from qdrant_client.http import models as qmodels

from app.config import (
    CHAT_MODEL,
    LOW_CONFIDENCE_SCORE,
    MIN_SCORE_ANSWER,
    QDRANT_COLLECTION_NAME,
    TOP_K,
)
from app.models.schemas import (
    ChatCitation,
    ChatConversationCreateRequest,
    ChatConversationListResponse,
    ChatConversationOut,
    ChatConversationUpsertRequest,
    ChatRequest,
    ChatResponse,
    RetrievalSummary,
)
from app.services.embeddings import embed_texts, openai_client
from app.services.retrieval import bm25_search_chunks, fuse_and_rank_hits
from app.services.security import get_current_user
from app.services.vector_store import qdrant_client
from app.db.database import db_cursor, get_db_conn
from app.db.chat_repository import (
    create_conversation,
    get_conversations_for_user,
    upsert_conversation_state,
)

router = APIRouter(tags=["chat"])


def _extract_what_is_target(question: str) -> str | None:
    m = re.match(r"^\s*what\s+is\s+(.+?)\s*\??\s*$", question.strip(), flags=re.IGNORECASE)
    if not m:
        return None
    target = m.group(1).strip().strip('"').strip("'")
    return target if target else None


def _extract_definition_from_context(question: str, context_snippets: List[str]) -> str | None:
    target = _extract_what_is_target(question)
    if not target:
        return None

    target_l = target.lower()
    definition_patterns = [
        re.compile(rf"\b{re.escape(target_l)}\b\s+(is|are|refers to|means|returns)\b.+?[\.!?]", re.IGNORECASE),
        re.compile(rf"\bwhat\s+is\s+{re.escape(target_l)}\b.+?[\.!?]", re.IGNORECASE),
    ]

    for snippet in context_snippets:
        text = snippet.strip()
        text_l = text.lower()
        if target_l not in text_l:
            continue
        for pattern in definition_patterns:
            m = pattern.search(text_l)
            if not m:
                continue
            start, end = m.span()
            # Return text from original snippet preserving casing.
            return text[start:end].strip()
    return None


def _tokenize_simple(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_\\-\\.]+", text or "")]


def _extract_topic_from_question(question: str) -> str | None:
    q = (question or "").strip()
    if not q:
        return None
    patterns = [
        r"^\s*what\s+is\s+(.+?)\s*\??\s*$",
        r"^\s*explain\s+me\s+(.+?)\s*\??\s*$",
        r"^\s*explain\s+(.+?)\s*\??\s*$",
        r"^\s*describe\s+(.+?)\s*\??\s*$",
        r"^\s*tell\s+me\s+about\s+(.+?)\s*\??\s*$",
    ]
    for pat in patterns:
        m = re.match(pat, q, flags=re.IGNORECASE)
        if m:
            topic = m.group(1).strip().strip('"').strip("'")
            if topic:
                return topic
    return None


def _hit_focus_score(question: str, text: str) -> float:
    q_tokens = set(_tokenize_simple(question))
    d_tokens = set(_tokenize_simple(text))
    overlap = (len(q_tokens.intersection(d_tokens)) / len(q_tokens)) if q_tokens else 0.0

    topic = _extract_topic_from_question(question)
    topic_l = topic.lower() if topic else None
    body = (text or "").lower()
    topic_boost = 0.0
    if topic_l and topic_l in body:
        topic_boost += 0.30
    if topic_l and f"what is {topic_l}" in body:
        topic_boost += 0.20
    if topic_l and re.search(rf"\b{re.escape(topic_l)}\b\s+(is|are|includes|covers|reports|refers to|means)\b", body):
        topic_boost += 0.20

    return (0.50 * overlap) + topic_boost


def _looks_like_refusal(answer: str) -> bool:
    low = (answer or "").lower()
    markers = [
        "cannot find it in the document",
        "does not provide specific information",
        "not provided in the document",
        "not enough information in the document",
    ]
    return any(m in low for m in markers)


def _touch_file_usage_stats(conn, file_ids: set[int]) -> None:
    if not file_ids:
        return
    try:
        with db_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE uploaded_files
                SET usage_count = usage_count + 1,
                    last_queried_at = NOW()
                WHERE id = ANY(%s);
                """,
                (list(file_ids),),
            )
        conn.commit()
    except Exception:
        conn.rollback()


@router.get("/chat/conversations", response_model=ChatConversationListResponse)
async def list_chat_conversations(
    conn=Depends(get_db_conn),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    items = get_conversations_for_user(conn, user_id=user_id)
    return ChatConversationListResponse(
        conversations=[ChatConversationOut(**item) for item in items]
    )


@router.post("/chat/conversations", response_model=ChatConversationOut, status_code=status.HTTP_201_CREATED)
async def create_chat_conversation(
    payload: ChatConversationCreateRequest,
    conn=Depends(get_db_conn),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    item = create_conversation(
        conn,
        user_id=user_id,
        title=(payload.title or "New chat").strip() or "New chat",
        file_id=payload.file_id,
        file_name=payload.file_name,
    )
    return ChatConversationOut(**item)


@router.put("/chat/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def save_chat_conversation(
    conversation_id: int,
    payload: ChatConversationUpsertRequest,
    conn=Depends(get_db_conn),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    try:
        upsert_conversation_state(
            conn,
            user_id=user_id,
            conversation_id=conversation_id,
            title=(payload.title or "New chat").strip() or "New chat",
            file_id=payload.file_id,
            file_name=payload.file_name,
            messages=[{"role": msg.role, "content": msg.content} for msg in payload.messages],
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found for this user.",
        )


def _build_retrieval_summary(
    *,
    scores: List[float],
    total_hits: int,
    chunks_used: int = 0,
    reason: str | None = None,
) -> RetrievalSummary:
    top_score = max(scores) if scores else None
    avg_score = (sum(scores) / len(scores)) if scores else None

    if top_score is None:
        confidence_label = "low"
        low_confidence = True
        fallback_reason = "No retrieval scores were available."
    elif top_score < MIN_SCORE_ANSWER:
        confidence_label = "low"
        low_confidence = True
        fallback_reason = "Top retrieval score is below the answer threshold."
    elif top_score < LOW_CONFIDENCE_SCORE:
        confidence_label = "medium"
        low_confidence = True
        fallback_reason = "Matches were weak; answer may be incomplete."
    else:
        confidence_label = "high"
        low_confidence = False
        fallback_reason = "Strong retrieval match."

    return RetrievalSummary(
        top_score=top_score,
        avg_score=avg_score,
        chunks_used=chunks_used,
        total_hits=total_hits,
        low_confidence=low_confidence,
        confidence_label=confidence_label,
        reason=reason or fallback_reason,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, conn=Depends(get_db_conn), current_user: dict = Depends(get_current_user)):
    """
    Chat over a single uploaded file.

    Flow:
      1. Embed the user question.
      2. Search Qdrant in the given file's chunks (filter by file_id).
      3. If no relevant chunk found -> return a friendly "no match" message.
      4. Otherwise, send top chunks + question to OpenAI and return the answer.
    """
    question = payload.message.strip()
    file_id = payload.file_id

    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question must not be empty.",
        )

    # 1) Embed the question using the same embedding model as for documents
    try:
        question_embedding = embed_texts([question])[0]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to embed question: {exc}",
        )

    # Resolve file_id if not provided: default to searching across all uploaded files
    query_filter = None
    if file_id is None:
        with db_cursor(conn) as cur:
            cur.execute("SELECT 1 FROM uploaded_files LIMIT 1;")
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No uploaded files available yet. Please ask an admin to upload one.",
                )
    else:
        query_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="file_id",
                    match=qmodels.MatchValue(value=file_id),
                )
            ]
        )

    candidate_limit = TOP_K * 3

    # 2a) Search Qdrant for semantic candidates
    try:
        response = qdrant_client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            query=question_embedding,
            limit=candidate_limit,
            query_filter=query_filter,
        )
        vector_results = response.points
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {exc}",
        )

    # 2b) Search PostgreSQL chunks with BM25 for lexical candidates
    try:
        lexical_results = bm25_search_chunks(
            conn,
            question=question,
            file_id=file_id,
            limit=candidate_limit,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"BM25 search failed: {exc}",
        )

    # 2c) Merge and rank hybrid candidates
    search_results = fuse_and_rank_hits(
        vector_hits=vector_results,
        lexical_hits=lexical_results,
        top_k=candidate_limit,
        question=question,
    )
    search_results = search_results[:TOP_K]

    # No chunks at all after hybrid retrieval
    if not search_results:
        return ChatResponse(
            reply=(
                "I couldn't find any relevant information in the uploaded document "
                "for your question."
            ),
            retrieval=_build_retrieval_summary(
                scores=[],
                total_hits=0,
                reason="No chunks were retrieved for this query.",
            ),
        )

    touched_file_ids: set[int] = set()
    for hit in search_results:
        touched_file_ids.add(hit.file_id)
    _touch_file_usage_stats(conn, touched_file_ids)

    scores = [float(hit.score) for hit in search_results if hit.score is not None]
    retrieval_summary = _build_retrieval_summary(
        scores=scores,
        total_hits=len(search_results),
        reason=(
            f"Hybrid retrieval used {len(vector_results)} semantic candidates and "
            f"{len(lexical_results)} BM25 candidates."
        ),
    )
    # Check best score against threshold for relevance
    if retrieval_summary.top_score is None or retrieval_summary.top_score < MIN_SCORE_ANSWER:
        return ChatResponse(
            reply=(
                "I searched your uploaded document but couldn't find a strong match "
                "for your question. Please try rephrasing or ask about another part "
                "of the document."
            ),
            retrieval=retrieval_summary,
        )

    # 3) Build context from top-k chunks (focus chunks most aligned to the question)
    focused_hits = sorted(
        search_results,
        key=lambda h: (_hit_focus_score(question, h.text), float(h.score or 0.0)),
        reverse=True,
    )

    context_snippets: List[str] = []
    citations: List[ChatCitation] = []
    seen_citations: Set[Tuple[int, int]] = set()
    for hit in focused_hits[:TOP_K]:
        text = hit.text
        chunk_file_id = hit.file_id
        page_number = hit.page_number
        filename = hit.filename

        if text:
            page_label = page_number if page_number is not None else "Unknown"
            context_snippets.append(f"[File: {filename or 'Unknown'}, Page {page_label}] {text}")

        file_id_int = int(chunk_file_id)
        page_number_int = int(page_number) if page_number is not None else -1

        citation_key = (file_id_int, page_number_int)
        if citation_key in seen_citations:
            continue

        seen_citations.add(citation_key)
        citations.append(
            ChatCitation(
                file_id=file_id_int,
                filename=str(filename or f"file_{file_id_int}"),
                page_number=(page_number_int if page_number_int >= 1 else None),
                score=float(hit.score) if hit.score is not None else None,
            )
        )

    if not context_snippets:
        retrieval_summary.chunks_used = 0
        retrieval_summary.reason = "Retrieved chunks did not contain usable text."
        return ChatResponse(
            reply=(
                "I tried to read relevant parts of the document, but couldn't extract "
                "any usable text for your question."
            ),
            retrieval=retrieval_summary,
        )

    retrieval_summary.chunks_used = len(context_snippets)

    context_block = "\n\n".join(context_snippets)

    # 4) Ask OpenAI to answer from this context only.
    try:
        prompt_for_model = (
            "You are an AI assistant that answers questions using ONLY the provided document context.\n"
            "If the context contains relevant information, provide a direct answer in simple language.\n"
            "If the user asks to explain in detail, include all relevant details from the context.\n"
            "Only say you cannot find it in the document when the context is genuinely unrelated.\n"
            "Do NOT invent facts.\n\n"
            f"Document context:\n{context_block}\n\n"
            f"User question: {question}\n\n"
            "Answer:"
        )

        completion = openai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful support assistant that only uses the given context.",
                },
                {
                    "role": "user",
                    "content": prompt_for_model,
                },
            ],
            temperature=0.2,
        )

        answer = completion.choices[0].message.content.strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM call failed: {exc}",
        )

    # 5) Return the final answer to Streamlit
    if not answer:
        answer = (
            "I tried to answer from the document, but couldn't generate a useful response. "
            "Please try rephrasing your question."
        )
    else:
        lower_answer = answer.lower()
        if _looks_like_refusal(answer):
            extracted = _extract_definition_from_context(question, context_snippets)
            if extracted:
                answer = extracted
            elif retrieval_summary.confidence_label in {"medium", "high"}:
                retry_prompt = (
                    "Answer using only this context. Do not refuse if relevant facts exist.\n"
                    "Return a concise factual answer and include key details explicitly present.\n\n"
                    f"Document context:\n{context_block}\n\n"
                    f"User question: {question}\n\n"
                    "Answer:"
                )
                retry = openai_client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a careful assistant that extracts facts from provided context.",
                        },
                        {
                            "role": "user",
                            "content": retry_prompt,
                        },
                    ],
                    temperature=0.0,
                )
                retry_answer = (retry.choices[0].message.content or "").strip()
                if retry_answer and not _looks_like_refusal(retry_answer):
                    answer = retry_answer

    return ChatResponse(reply=answer, citations=citations, retrieval=retrieval_summary)
