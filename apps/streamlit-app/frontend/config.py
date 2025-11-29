"""App-level configuration."""
import os

# Backend FastAPI base URL
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
