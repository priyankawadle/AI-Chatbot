"""
Database connection management using psycopg (psycopg3) and a connection pool.

This module is the single place responsible for:
  - Building the PostgreSQL connection string from environment config.
  - Creating and tearing down a ConnectionPool (shared across the app).
  - Providing a FastAPI dependency (get_db_conn) that hands a connection to
    each request and returns it to the pool when the request finishes.

All queries use the standard PostgreSQL parameterized placeholder: %s
"""

from contextlib import contextmanager
from typing import Generator, Optional

import psycopg                          # psycopg3 – PostgreSQL driver
from psycopg_pool import ConnectionPool  # psycopg3 async-compatible pool

from fastapi import HTTPException

from app.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)
from app.db.schema import ensure_tables

# ---------------------------------------------------------------------------
# Parameterized query placeholder for PostgreSQL
# Referenced in user_repository.py so both files stay in sync automatically.
# ---------------------------------------------------------------------------
DB_PLACEHOLDER = "%s"

# ---------------------------------------------------------------------------
# PostgreSQL connection string assembled from .env values
# ---------------------------------------------------------------------------
_CONNINFO = (
    f"host={DB_HOST} "
    f"port={DB_PORT} "
    f"dbname={DB_NAME} "
    f"user={DB_USER} "
    f"password={DB_PASSWORD} "
    f"connect_timeout=5"
)

# Global pool – None until init_pool() is called on application startup
pool: Optional[ConnectionPool] = None


# ---------------------------------------------------------------------------
# Cursor context manager
# ---------------------------------------------------------------------------

@contextmanager
def db_cursor(conn):
    """
    Thin context manager that opens a psycopg cursor and closes it on exit.

    Usage:
        with db_cursor(conn) as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
    """
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Pool lifecycle – hooked into FastAPI startup / shutdown events in main.py
# ---------------------------------------------------------------------------

def init_pool() -> None:
    """
    Create the PostgreSQL connection pool and verify connectivity.

    Called once at application startup (main.py @app.on_event("startup")).
    Passes open=True so the pool opens real connections immediately; this
    surfaces misconfigured credentials / unreachable host at boot time rather
    than silently failing on the first request.

    Also runs ensure_tables() to create schema objects that do not yet exist.
    """
    global pool

    if pool is not None:
        return  # Already initialized – idempotent

    pool = ConnectionPool(
        conninfo=_CONNINFO,
        min_size=1,   # Keep at least one connection alive at all times
        max_size=5,   # Cap concurrent connections to avoid overloading Postgres
        open=True,    # Open connections eagerly so startup fails fast on errors
    )

    # Ping the database and bootstrap the schema in a single borrowed connection
    with pool.connection() as conn:
        conn.execute("SELECT 1;")   # Lightweight liveness check
        ensure_tables(conn)          # CREATE TABLE IF NOT EXISTS for all tables


def close_pool() -> None:
    """
    Close all pooled connections gracefully.

    Called once at application shutdown (main.py @app.on_event("shutdown")).
    """
    global pool

    if pool is not None:
        pool.close()
        pool = None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db_conn() -> Generator:
    """
    FastAPI dependency that yields a pooled PostgreSQL connection per request.

    The connection is borrowed from the pool at the start of the request and
    automatically returned (with commit or rollback) when the request ends.

    Inject it into a route handler like this:
        @router.get("/example")
        def example(conn = Depends(get_db_conn)):
            with db_cursor(conn) as cur:
                cur.execute("SELECT 1;")
    """
    if pool is None:
        raise HTTPException(status_code=500, detail="Database pool is not initialized")

    # pool.connection() is a context manager:
    #   __enter__  → checks out a connection from the pool
    #   __exit__   → commits on success, rolls back on exception, returns conn
    with pool.connection() as conn:
        yield conn
