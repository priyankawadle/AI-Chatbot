"""
Qdrant vector store helpers.

Connects to a running Qdrant instance via URL (local Docker or remote cloud).
QDRANT_URL defaults to http://localhost:6333 if not set in the environment,
so a local Docker Qdrant works out of the box with no extra config.
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME,
    QDRANT_URL,
)

print("EMBEDDING_DIM",EMBEDDING_DIM,"QDRANT_API_KEY",QDRANT_API_KEY,
"QDRANT_COLLECTION_NAME",QDRANT_COLLECTION_NAME,"QDRANT_URL",QDRANT_URL)
# Fall back to local Docker Qdrant if QDRANT_URL is not explicitly set
_qdrant_url = QDRANT_URL 

# Shared Qdrant client – created once at import time and reused across requests
qdrant_client = QdrantClient(url=_qdrant_url, api_key=QDRANT_API_KEY or None)


def ensure_qdrant_collection() -> None:
    """
    Create the vector collection in Qdrant if it does not already exist.

    Called once at application startup (main.py @app.on_event("startup")).
    Uses cosine distance and the embedding dimension defined in config.
    """
    try:
        qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
        # Collection already exists – nothing to do
    except Exception:
        # Collection missing – create it now
        qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
