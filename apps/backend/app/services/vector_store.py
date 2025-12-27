"""Helpers for talking to Qdrant (vector search)."""
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME,
    QDRANT_PATH,
    QDRANT_URL,
)


def _build_client() -> QdrantClient:
    """
    Use remote Qdrant if QDRANT_URL is set; otherwise fall back to embedded mode
    (stores data under QDRANT_PATH).
    """
    if QDRANT_URL:
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    Path(QDRANT_PATH).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=QDRANT_PATH)


# Shared Qdrant client instance
qdrant_client = _build_client()


def ensure_qdrant_collection() -> None:
    """
    Creates the collection in Qdrant if it does not exist.
    Uses cosine distance and fixed vector size.
    """
    try:
        qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
        # If no exception, collection already exists.
        return
    except Exception:
        # Collection does not exist yet -> create
        qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
