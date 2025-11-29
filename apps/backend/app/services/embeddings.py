"""Wrapper around the OpenAI client for embedding text."""
from typing import List

from openai import OpenAI

from app.config import EMBEDDING_MODEL, OPENAI_API_KEY

# Single shared client instance
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Calls OpenAI embeddings for a list of texts.
    Returns a list of embedding vectors.
    """
    if not texts:
        return []

    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )

    # Map back to list of floats
    vectors: List[List[float]] = [d.embedding for d in response.data]
    return vectors
