"""Schema helpers for creating base tables.

We keep the raw SQL in `apps/backend/table.sql` so it is easy to edit
or inspect outside of Python. On startup we read and execute that file.
"""
from pathlib import Path

# Path to the shared SQL file (now kept alongside this module)
SCHEMA_FILE = Path(__file__).resolve().parent / "table.sql"

# Fallback SQL in case the file is missing at runtime
FALLBACK_SQL = """
-- users table
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- file metadata
CREATE TABLE IF NOT EXISTS uploaded_files (
    id              BIGSERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- file chunks (what we embed)
CREATE TABLE IF NOT EXISTS file_chunks (
    id          BIGSERIAL PRIMARY KEY,
    file_id     BIGINT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL
);
"""


def load_schema_sql() -> str:
    """Load SQL text from the shared schema file, falling back to the embedded string."""
    try:
        return SCHEMA_FILE.read_text(encoding="utf-8")
    except OSError:
        # File missing? Use the built-in SQL so the app still boots.
        return FALLBACK_SQL


def ensure_tables(conn) -> None:
    """
    Execute the schema SQL against the provided connection.
    Safe to run repeatedly thanks to IF NOT EXISTS in the statements.
    """
    sql_text = load_schema_sql()
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()
