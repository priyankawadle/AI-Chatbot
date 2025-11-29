"""
Basic settings used across the API.
The values are loaded from environment variables so they can be changed
without touching the code (handy for local dev vs. production).
"""
import os

from dotenv import load_dotenv

# Load values from a .env file sitting in the project root
load_dotenv()

# Database settings
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mysecretpassword")

# Qdrant (vector database) settings
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "supportbot_documents")

# OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-nano")

# Search and chunking defaults
TOP_K = 5
MIN_SCORE = 0.35
MAX_CHARS_PER_CHUNK = 1000
MAX_CHUNKS_PER_FILE = 100_000
SUPPORTED_EXTENSIONS = (".txt", ".pdf")

# FastAPI app metadata and CORS
APP_TITLE = "AI Chat Bot API"
ALLOWED_ORIGINS = ["http://localhost:8501", "http://127.0.0.1:8501"]
