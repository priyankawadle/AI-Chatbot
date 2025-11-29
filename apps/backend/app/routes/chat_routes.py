"""Routes that handle chat over uploaded documents."""
from typing import List

from fastapi import APIRouter, HTTPException, status
from qdrant_client.http import models as qmodels

from app.config import CHAT_MODEL, MIN_SCORE, QDRANT_COLLECTION_NAME, TOP_K
from app.models.schemas import ChatRequest, ChatResponse
from app.services.embeddings import embed_texts, openai_client
from app.services.vector_store import qdrant_client

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
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

    # 2) Search Qdrant for most similar chunks for this file_id
    try:
        search_results = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=question_embedding,
            limit=TOP_K,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="file_id",
                        match=qmodels.MatchValue(value=file_id),
                    )
                ]
            ),
        )
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
    for hit in search_results:
        payload = hit.payload or {}
        text = payload.get("text", "")
        chunk_index = payload.get("chunk_index", "?")
        if text:
            context_snippets.append(f"[Chunk {chunk_index}] {text}")

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

    return ChatResponse(reply=answer)
