"""
Connection pooling helpers that FastAPI dependencies can share.
Keeping this here keeps `main.py` light and makes it clear where DB
setup lives.
"""
from typing import Generator, Optional

from fastapi import HTTPException
from psycopg2 import OperationalError
from psycopg2.pool import SimpleConnectionPool

from app.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)

pool: Optional[SimpleConnectionPool] = None  # created at startup


def _create_users_table_if_needed(conn) -> None:
    """Create a minimal users table if it doesn't exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def init_pool() -> None:
    """Bootstrap a small connection pool and sanity check connectivity."""
    global pool
    if pool:
        return

    pool = SimpleConnectionPool(
        minconn=1,
        maxconn=5,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
    )

    # Quick ping + ensure basic schema
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        _create_users_table_if_needed(conn)
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """Close all pooled connections when the app stops."""
    global pool
    if pool:
        pool.closeall()
        pool = None


def get_db_conn() -> Generator:
    """
    FastAPI dependency that hands out a pooled connection.
    The `yield` makes FastAPI return the connection to the pool
    after the request finishes.
    """
    global pool
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)
