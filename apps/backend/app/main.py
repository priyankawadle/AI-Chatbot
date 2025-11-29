"""Application entrypoint that ties together routes, DB, and services."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS, APP_TITLE
from app.db.database import close_pool, init_pool
from app.routes.auth_routes import router as auth_router
from app.routes.chat_routes import router as chat_router
from app.routes.file_routes import router as file_router
from app.routes.health_routes import router as health_router
from app.services.vector_store import ensure_qdrant_collection

app = FastAPI(title=APP_TITLE)

# Enable CORS for the Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    """Create a small connection pool on startup and ensure schema exists."""
    init_pool()
    ensure_qdrant_collection()
    print("DB pool initialized and Qdrant collection ensured.")


@app.on_event("shutdown")
def shutdown_event() -> None:
    """Close the pool on shutdown."""
    close_pool()
    print("DB pool closed.")

# Register routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(file_router)
app.include_router(chat_router)