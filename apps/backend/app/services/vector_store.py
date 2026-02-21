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
    Creates payload indexes for filtering.
    """
    try:
        collection = qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
        # Collection already exists – check if we need to create indexes
        print(f"✓ Collection '{QDRANT_COLLECTION_NAME}' exists")
    except Exception:
        # Collection missing – create it now
        print(f"Creating collection '{QDRANT_COLLECTION_NAME}'...")
        qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
    
    # Create payload index on file_id for filtering
    try:
        qdrant_client.create_payload_index(
            collection_name=QDRANT_COLLECTION_NAME,
            field_name="file_id",
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )
        print(f"✓ Payload index created on 'file_id'")
    except Exception as e:
        # Index might already exist
        if "already exists" in str(e).lower():
            print(f"✓ Payload index for 'file_id' already exists")
        else:
            print(f"Note: Could not create payload index on 'file_id': {e}")
