
"""Small helpers for working with the `users` table and refresh tokens."""
import hashlib
from datetime import datetime
from typing import Optional

from app.db.database import DB_PLACEHOLDER, IS_SQLITE, db_cursor


def _ph(count: int) -> str:
    """Return a comma-separated placeholder string matching the active DB driver."""
    return ", ".join([DB_PLACEHOLDER] * count)


def email_exists(conn, email: str) -> bool:
    with db_cursor(conn) as cur:
        cur.execute(f"SELECT 1 FROM users WHERE email = {DB_PLACEHOLDER} LIMIT 1;", (email,))
        return cur.fetchone() is not None


def insert_user(conn, email: str, password_hash: str, role: str = "user") -> int:
    with db_cursor(conn) as cur:
        query = f"INSERT INTO users (email, password_hash, role) VALUES ({_ph(3)})"
        if not IS_SQLITE:
            query += " RETURNING id;"
        else:
            query += ";"
        cur.execute(query, (email, password_hash, role))
        user_id = cur.lastrowid if IS_SQLITE else cur.fetchone()[0]
    conn.commit()
    return user_id


def get_user_by_email(conn, email: str) -> Optional[dict]:
    with db_cursor(conn) as cur:
        cur.execute(
            f"SELECT id, email, password_hash, role FROM users WHERE email = {DB_PLACEHOLDER} LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()
        if not row:
            return None
        role = row[3] if len(row) > 3 else "user"
        return {"id": row[0], "email": row[1], "password_hash": row[2], "role": role}


def get_user_by_id(conn, user_id: int) -> Optional[dict]:
    with db_cursor(conn) as cur:
        cur.execute(
            f"SELECT id, email, password_hash, role FROM users WHERE id = {DB_PLACEHOLDER} LIMIT 1;",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        role = row[3] if len(row) > 3 else "user"
        return {"id": row[0], "email": row[1], "password_hash": row[2], "role": role}


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def save_refresh_token(conn, user_id: int, token: str, expires_at: datetime) -> None:
    token_hash = _hash_refresh_token(token)
    expires_value = expires_at.strftime("%Y-%m-%d %H:%M:%S") if IS_SQLITE else expires_at
    with db_cursor(conn) as cur:
        cur.execute(
            f"""
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ({_ph(3)})
            ON CONFLICT (token_hash) DO NOTHING;
            """,
            (user_id, token_hash, expires_value),
        )
    conn.commit()


def revoke_refresh_token(conn, token: str) -> None:
    token_hash = _hash_refresh_token(token)
    with db_cursor(conn) as cur:
        cur.execute(f"UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = {DB_PLACEHOLDER};", (token_hash,))
    conn.commit()


def is_refresh_token_valid(conn, token: str) -> bool:
    token_hash = _hash_refresh_token(token)
    with db_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT 1 FROM refresh_tokens
            WHERE token_hash = {DB_PLACEHOLDER} AND revoked = FALSE AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1;
            """,
            (token_hash,),
        )
        return cur.fetchone() is not None
