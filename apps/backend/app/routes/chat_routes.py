"""Routes that handle chat over uploaded documents."""
from typing import List, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from qdrant_client.http import models as qmodels

from app.config import CHAT_MODEL, MIN_SCORE, QDRANT_COLLECTION_NAME, TOP_K
from app.models.schemas import ChatCitation, ChatRequest, ChatResponse
from app.services.embeddings import embed_texts, openai_client
from app.services.security import get_current_user
from app.services.vector_store import qdrant_client
from app.db.database import db_cursor, get_db_conn

router = APIRouter(tags=["chat"])


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

    # 2) Search Qdrant for most similar chunks
    try:
        response = qdrant_client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            query=question_embedding,
            limit=TOP_K,
            query_filter=query_filter,
        )
        search_results = response.points
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {exc}",
        )

    # No chunks at all
    if not search_results:
        return ChatResponse(
            reply=(
                "I couldn't find any relevant information in the uploaded document "
                "for your question."
            )
        )

    # Check best score against threshold for relevance
    best_score = search_results[0].score
    if best_score is None or best_score < MIN_SCORE:
        return ChatResponse(
            reply=(
                "I searched your uploaded document but couldn't find a strong match "
                "for your question. Please try rephrasing or ask about another part "
                "of the document."
            )
        )

    # 3) Build context from top-k chunks
    context_snippets: List[str] = []
    citations: List[ChatCitation] = []
    seen_citations: Set[Tuple[int, int]] = set()
    for hit in search_results:
        payload = hit.payload or {}
        text = payload.get("text", "")
        file_id = payload.get("file_id")
        page_number = payload.get("page_number")
        filename = payload.get("filename")

        if text:
            page_label = page_number if page_number is not None else "Unknown"
            context_snippets.append(f"[File: {filename or 'Unknown'}, Page {page_label}] {text}")

        if file_id is None:
            continue

        try:
            file_id_int = int(file_id)
            page_number_int = int(page_number) if page_number is not None else -1
        except (TypeError, ValueError):
            continue

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
        return ChatResponse(
            reply=(
                "I tried to read relevant parts of the document, but couldn't extract "
                "any usable text for your question."
            )
        )

    context_block = "\n\n".join(context_snippets)

    # 4) Ask OpenAI to answer based ONLY on this context
    #    The instructions explicitly tell it not to hallucinate beyond context.
    try:
        prompt_for_model = (
            "You are an AI assistant that answers questions using ONLY the provided document context.\n"
            "If the answer is not clearly contained in the context, say that you cannot find it "
            "in the document. Do NOT invent facts.\n\n"
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

    return ChatResponse(reply=answer, citations=citations)
