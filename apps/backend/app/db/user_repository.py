"""Small helpers for working with the `users` table."""
from typing import Optional


def email_exists(conn, email: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s LIMIT 1;", (email,))
        return cur.fetchone() is not None


def insert_user(conn, email: str, password_hash: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id;",
            (email, password_hash),
        )
        user_id = cur.fetchone()[0]
    conn.commit()
    return user_id


def get_user_by_email(conn, email: str) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "password_hash": row[2]}
