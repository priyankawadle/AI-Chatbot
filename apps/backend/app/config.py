
"""
Basic settings used across the API.
The values are loaded from environment variables so they can be changed
without touching the code (handy for local dev vs. production).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load values from a .env file in the backend directory
backend_dir = Path(__file__).parent.parent  # apps/backend/
env_file = backend_dir / ".env"
load_dotenv(env_file)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# PostgreSQL connection settings (loaded from .env)
#TODO: after removing static text like localhost etc , getting error check later
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "ai-chatbot-db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Postgres@123")

# Qdrant (vector database) settings
QDRANT_URL = os.getenv("QDRANT_URL") 
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "supportbot_documents")


# OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-nano")

# Search and chunking defaults
TOP_K = 5
MIN_SCORE_ANSWER = float(os.getenv("MIN_SCORE_ANSWER", "0.35"))
LOW_CONFIDENCE_SCORE = float(os.getenv("LOW_CONFIDENCE_SCORE", "0.50"))
RERANK_ENABLED = _env_bool("RERANK_ENABLED", True)
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "20"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", str(TOP_K)))
RERANK_TIMEOUT_MS = int(os.getenv("RERANK_TIMEOUT_MS", "5000"))
# Backward-compatible alias for existing code paths that still import MIN_SCORE.
MIN_SCORE = MIN_SCORE_ANSWER
MAX_CHARS_PER_CHUNK = 1000
MAX_CHUNKS_PER_FILE = 100_000
MAX_FILE_SIZE_MB = 50  # Maximum file size in MB
SUPPORTED_EXTENSIONS = (".txt", ".pdf")

# FastAPI app metadata and CORS
APP_TITLE = "AI Chat Bot API"
raw_origins = os.getenv("ALLOWED_ORIGINS")
if raw_origins:
    ALLOWED_ORIGINS = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
else:
    # Default to permissive for co-located Streamlit/Backend deployments (e.g., Hugging Face Space)
    ALLOWED_ORIGINS = ["*"]

# JWT settings
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
