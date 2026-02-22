"""
Schema management for PostgreSQL.

On every application startup, ensure_tables() is called to create all required
tables if they do not already exist. The raw SQL lives in table.sql (same
directory) so it can be inspected or run manually in pgAdmin / psql without
touching Python code.

All SQL statements use IF NOT EXISTS, so repeated calls are safe (idempotent).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Path to the SQL file that defines the full schema
# ---------------------------------------------------------------------------
SCHEMA_FILE = Path(__file__).resolve().parent / "table.sql"

# ---------------------------------------------------------------------------
# Fallback SQL – used only if table.sql is missing at runtime.
# Kept in sync with table.sql so the app can still boot in that edge case.
# ---------------------------------------------------------------------------
_FALLBACK_SQL = """
-- Users: stores account credentials and roles
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL    PRIMARY KEY,
    email         TEXT         NOT NULL UNIQUE,
    password_hash TEXT         NOT NULL,
    role          TEXT         NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Refresh tokens: long-lived JWT tokens that can be individually revoked
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         BIGSERIAL    PRIMARY KEY,
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT         NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ  NOT NULL,
    revoked    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);

-- Uploaded files: one row per file the user uploads
CREATE TABLE IF NOT EXISTS uploaded_files (
    id           BIGSERIAL   PRIMARY KEY,
    filename     TEXT        NOT NULL,
    content_type TEXT        NOT NULL,
    size_bytes   BIGINT      NOT NULL,
    file_hash       TEXT UNIQUE,
    usage_count     BIGINT      NOT NULL DEFAULT 0,
    last_queried_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- File chunks: text segments extracted from uploaded files for vector embedding
CREATE TABLE IF NOT EXISTS file_chunks (
    id          BIGSERIAL PRIMARY KEY,
    file_id     BIGINT    NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    chunk_index INT       NOT NULL,
    page_number INT,
    content     TEXT      NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_conversations (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT        NOT NULL DEFAULT 'New chat',
    file_id     BIGINT,
    file_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_user_id
    ON chat_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id               BIGSERIAL   PRIMARY KEY,
    conversation_id  BIGINT      NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role             TEXT        NOT NULL,
    content          TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id
    ON chat_messages(conversation_id, id ASC);
"""


def ensure_tables(conn) -> None:
    """
    Create all schema tables in PostgreSQL if they do not already exist.

    Reads SQL from table.sql (next to this file). Falls back to the inline
    _FALLBACK_SQL if the file cannot be read (e.g. during certain deployments).

    Safe to call on every startup – all statements use IF NOT EXISTS.

    Args:
        conn: An open psycopg connection (borrowed from the pool).
    """
    # Prefer the external file so the schema can be changed without editing Python
    try:
        sql_text = SCHEMA_FILE.read_text(encoding="utf-8")
    except OSError:
        # table.sql missing – fall back to the inline definition above
        sql_text = _FALLBACK_SQL

    with conn.cursor() as cur:
        # Run the full schema in one round-trip
        cur.execute(sql_text)

        # Backfill: safely add the `role` column for databases that were
        # created before roles were introduced. IF NOT EXISTS prevents errors
        # on fresh installs where the column already exists from the schema.
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';"
        )
        # Backfill: add page_number on older DBs where file_chunks predate page citations.
        cur.execute("ALTER TABLE file_chunks ADD COLUMN IF NOT EXISTS page_number INT;")
        # Backfill: file upload dedupe + lifecycle stats.
        cur.execute("ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_hash TEXT;")
        cur.execute(
            "ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS usage_count BIGINT NOT NULL DEFAULT 0;"
        )
        cur.execute("ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS last_queried_at TIMESTAMPTZ;")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_uploaded_files_file_hash_unique ON uploaded_files(file_hash);"
        )

    conn.commit()
