"""
Repository functions for the `users` and `refresh_tokens` tables.

All queries target PostgreSQL and use the standard %s parameterized placeholder.
Each function accepts an open psycopg connection (injected via Depends(get_db_conn))
and commits its own transaction where data is modified.
"""

import hashlib
from datetime import datetime
from typing import Optional

from app.db.database import db_cursor


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def email_exists(conn, email: str) -> bool:
    """Return True if the given email address is already registered."""
    with db_cursor(conn) as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE email = %s LIMIT 1;",
            (email,),
        )
        return cur.fetchone() is not None


def insert_user(conn, email: str, password_hash: str, role: str = "user") -> int:
    """
    Insert a new user row and return the generated primary-key id.

    Uses RETURNING id so the new id is retrieved in the same round-trip
    without needing a separate SELECT.
    """
    with db_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id;",
            (email, password_hash, role),
        )
        user_id: int = cur.fetchone()[0]
    conn.commit()
    return user_id


def get_user_by_email(conn, email: str) -> Optional[dict]:
    """
    Fetch a user row by email address.

    Returns a dict with keys {id, email, password_hash, role}, or None if
    no matching user exists.
    """
    with db_cursor(conn) as cur:
        cur.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = %s LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2], "role": row[3]}


def get_user_by_id(conn, user_id: int) -> Optional[dict]:
    """
    Fetch a user row by primary key.

    Returns a dict with keys {id, email, password_hash, role}, or None if
    no matching user exists.
    """
    with db_cursor(conn) as cur:
        cur.execute(
            "SELECT id, email, password_hash, role FROM users WHERE id = %s LIMIT 1;",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2], "role": row[3]}


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------

def _hash_refresh_token(token: str) -> str:
    """SHA-256 hash the raw token before storing it (never store plaintext tokens)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def save_refresh_token(conn, user_id: int, token: str, expires_at: datetime) -> None:
    """
    Persist a new refresh token for the given user.

    The raw token is hashed before storage. ON CONFLICT DO NOTHING handles the
    unlikely case of a hash collision without raising an error.
    """
    token_hash = _hash_refresh_token(token)
    with db_cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token_hash) DO NOTHING;
            """,
            (user_id, token_hash, expires_at),
        )
    conn.commit()


def revoke_refresh_token(conn, token: str) -> None:
    """
    Mark a refresh token as revoked so it can no longer be used to obtain
    new access tokens (e.g. on explicit logout).
    """
    token_hash = _hash_refresh_token(token)
    with db_cursor(conn) as cur:
        cur.execute(
            "UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = %s;",
            (token_hash,),
        )
    conn.commit()


def is_refresh_token_valid(conn, token: str) -> bool:
    """
    Return True only if the token exists, has not been revoked, and has not expired.

    Used by the token-refresh endpoint to validate incoming refresh tokens.
    """
    token_hash = _hash_refresh_token(token)
    with db_cursor(conn) as cur:
        cur.execute(
            """
            SELECT 1 FROM refresh_tokens
            WHERE token_hash = %s
              AND revoked    = FALSE
              AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1;
            """,
            (token_hash,),
        )
        return cur.fetchone() is not None
