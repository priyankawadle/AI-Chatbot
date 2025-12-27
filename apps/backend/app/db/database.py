"""
Connection helpers shared by FastAPI dependencies.
Supports both Postgres (via psycopg2 pool) and SQLite (single-file, good for Spaces).
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from fastapi import HTTPException

from app.config import (
    DB_DRIVER,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    SQLITE_PATH,
)
from app.db.schema import ensure_tables

try:
    from psycopg2 import OperationalError
    from psycopg2.pool import SimpleConnectionPool
except Exception:  # pragma: no cover - psycopg2 may be absent in SQLite-only mode
    OperationalError = Exception  # type: ignore
    SimpleConnectionPool = None  # type: ignore


IS_SQLITE = DB_DRIVER == "sqlite"
DB_PLACEHOLDER = "?" if IS_SQLITE else "%s"

pool: Optional[SimpleConnectionPool] = None  # Postgres pool
sqlite_db_path = Path(SQLITE_PATH)


@contextmanager
def db_cursor(conn):
    """
    Context manager that works for both psycopg2 and sqlite3 cursors.
    """
    cur = conn.cursor()
    try:
        yield cur
    finally:
        try:
            cur.close()
        except Exception:
            pass


def _init_sqlite() -> None:
    """
    Ensure SQLite database file exists and schema is created.
    A new connection is opened per request (see get_db_conn).
    """
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_db_path, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        ensure_tables(conn, dialect="sqlite")
    finally:
        conn.close()


def init_pool() -> None:
    """Bootstrap DB connectivity (pool for Postgres, file for SQLite)."""
    global pool
    if IS_SQLITE:
        _init_sqlite()
        return

    if pool:
        return
    if SimpleConnectionPool is None:
        raise HTTPException(status_code=500, detail="psycopg2 not installed for Postgres mode")

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

    # Quick ping + ensure base schema
    conn = pool.getconn()
    try:
        with db_cursor(conn) as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        ensure_tables(conn, dialect="postgres")
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """Close pooled connections when the app stops."""
    global pool
    if IS_SQLITE:
        return
    if pool:
        pool.closeall()
        pool = None


def get_db_conn() -> Generator:
    """
    FastAPI dependency that hands out a connection.
    For SQLite we open/close per request; for Postgres we borrow from the pool.
    """
    global pool
    if IS_SQLITE:
        conn = sqlite3.connect(sqlite_db_path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return

    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)
