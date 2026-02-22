"""Repository helpers for persistent per-user chat history."""

from typing import Any

from app.db.database import db_cursor


def create_conversation(
    conn,
    *,
    user_id: int,
    title: str,
    file_id: int | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    with db_cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO chat_conversations (user_id, title, file_id, file_name)
            VALUES (%s, %s, %s, %s)
            RETURNING id, title, file_id, file_name;
            """,
            (user_id, title, file_id, file_name),
        )
        row = cur.fetchone()
    conn.commit()
    return {
        "id": row[0],
        "title": row[1],
        "file_id": row[2],
        "file_name": row[3],
        "messages": [],
    }


def get_conversations_for_user(conn, *, user_id: int) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    with db_cursor(conn) as cur:
        cur.execute(
            """
            SELECT id, title, file_id, file_name
            FROM chat_conversations
            WHERE user_id = %s
            ORDER BY updated_at DESC, id DESC;
            """,
            (user_id,),
        )
        conv_rows = cur.fetchall()

        if not conv_rows:
            return conversations

        conv_ids = [row[0] for row in conv_rows]
        messages_by_conv: dict[int, list[dict[str, str]]] = {conv_id: [] for conv_id in conv_ids}

        cur.execute(
            """
            SELECT conversation_id, role, content
            FROM chat_messages
            WHERE conversation_id = ANY(%s)
            ORDER BY id ASC;
            """,
            (conv_ids,),
        )
        for conversation_id, role, content in cur.fetchall():
            messages_by_conv[conversation_id].append({"role": role, "content": content})

    for row in conv_rows:
        conv_id = row[0]
        conversations.append(
            {
                "id": conv_id,
                "title": row[1],
                "file_id": row[2],
                "file_name": row[3],
                "messages": messages_by_conv.get(conv_id, []),
            }
        )

    return conversations


def upsert_conversation_state(
    conn,
    *,
    user_id: int,
    conversation_id: int,
    title: str,
    file_id: int | None,
    file_name: str | None,
    messages: list[dict[str, str]],
) -> None:
    with db_cursor(conn) as cur:
        cur.execute(
            """
            UPDATE chat_conversations
            SET title = %s,
                file_id = %s,
                file_name = %s,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s;
            """,
            (title, file_id, file_name, conversation_id, user_id),
        )

        if cur.rowcount == 0:
            raise ValueError("Conversation not found for this user.")

        cur.execute(
            "DELETE FROM chat_messages WHERE conversation_id = %s;",
            (conversation_id,),
        )

        for msg in messages:
            role = msg.get("role", "").strip()
            content = msg.get("content", "")
            if not role:
                continue
            cur.execute(
                """
                INSERT INTO chat_messages (conversation_id, role, content)
                VALUES (%s, %s, %s);
                """,
                (conversation_id, role, content),
            )

    conn.commit()
