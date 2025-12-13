
"""Small helpers for working with the `users` table and refresh tokens."""
import hashlib
from datetime import datetime
from typing import Optional


def email_exists(conn, email: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s LIMIT 1;", (email,))
        return cur.fetchone() is not None


def insert_user(conn, email: str, password_hash: str, role: str = "user") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id;",
            (email, password_hash, role),
        )
        user_id = cur.fetchone()[0]
    conn.commit()
    return user_id


def get_user_by_email(conn, email: str) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = %s LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()
        if not row:
            return None
        role = row[3] if len(row) > 3 else "user"
        return {"id": row[0], "email": row[1], "password_hash": row[2], "role": role}


def get_user_by_id(conn, user_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, password_hash, role FROM users WHERE id = %s LIMIT 1;",
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
    with conn.cursor() as cur:
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
    token_hash = _hash_refresh_token(token)
    with conn.cursor() as cur:
        cur.execute("UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = %s;", (token_hash,))
    conn.commit()


def is_refresh_token_valid(conn, token: str) -> bool:
    token_hash = _hash_refresh_token(token)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM refresh_tokens
            WHERE token_hash = %s AND revoked = FALSE AND expires_at > NOW()
            LIMIT 1;
            """,
            (token_hash,),
        )
        return cur.fetchone() is not None
