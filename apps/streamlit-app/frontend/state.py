"""Helpers to manage Streamlit session state in one place."""
import base64
import json
from typing import Optional

import streamlit as st

from frontend.api import api_get, api_post, api_put

AUTH_QUERY_KEY = "auth"


def ensure_base_state():
    """Ensure the base auth-related keys are present."""
    if "user" not in st.session_state:
        st.session_state.user = None  # {"id": ..., "email": ...}
    if "tokens" not in st.session_state:
        st.session_state.tokens = None  # {"access_token": ..., "refresh_token": ...}
    if "uploads" not in st.session_state:
        st.session_state.uploads = []  # admin-only: [{"file_id": int, "file_name": str}]
    if "upload_history_loaded" not in st.session_state:
        st.session_state.upload_history_loaded = False
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0  # used to reset the file_uploader widget


def ensure_conversation_state():
    """
    Initialize conversation-related session state.
    In future, you can fetch history from a backend API here.
    """
    if "conversations" not in st.session_state:
        # List[dict]: each dict = one conversation
        st.session_state.conversations = []

    if "active_conv_id" not in st.session_state:
        st.session_state.active_conv_id = None

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "file_id" not in st.session_state:
        st.session_state.file_id = None

    if "file_name" not in st.session_state:
        st.session_state.file_name = None

    # Try to load persisted conversations from backend for this user
    if st.session_state.user and not st.session_state.conversations:
        loaded = load_conversations_from_backend()
        if loaded:
            return

    # If logged in and no conversation yet, create the first one
    if st.session_state.user and st.session_state.active_conv_id is None:
        create_new_conversation(initial=True)


def create_new_conversation(initial: bool = False):
    """
    Create a new blank conversation in local state.
    Later, this can call an API to create a new chat.
    """
    title = "New chat" if initial else "New chat"
    file_id = st.session_state.get("file_id")
    file_name = st.session_state.get("file_name")
    new_id = None
    if st.session_state.get("user"):
        try:
            data = api_post(
                "/chat/conversations",
                {"title": title, "file_id": file_id, "file_name": file_name},
            )
            new_id = data.get("id")
        except Exception as e:
            st.warning(f"Could not create conversation in DB: {e}")

    conversations = st.session_state.conversations
    if new_id is None:
        new_id = (max([c["id"] for c in conversations]) + 1) if conversations else 1

    conv = {
        "id": new_id,
        "title": title,
        "file_id": file_id,
        "file_name": file_name,
        "messages": [],  # we'll bind this to st.session_state.messages
    }

    conversations.append(conv)
    st.session_state.active_conv_id = new_id

    # Keep references aligned
    st.session_state.messages = conv["messages"]
    st.session_state.file_id = conv["file_id"]
    st.session_state.file_name = conv["file_name"]


def get_active_conversation():
    """
    Return the currently active conversation dict or None.
    """
    active_id = st.session_state.active_conv_id
    for conv in st.session_state.conversations:
        if conv["id"] == active_id:
            return conv
    return None


def load_conversation(conv_id: int):
    """
    Set a given conversation as active and sync its fields
    into the top-level session_state for easier access.
    """
    for conv in st.session_state.conversations:
        if conv["id"] == conv_id:
            st.session_state.active_conv_id = conv_id

            # Ensure messages list is shared
            st.session_state.messages = conv.get("messages", [])
            conv["messages"] = st.session_state.messages

            st.session_state.file_id = conv.get("file_id")
            st.session_state.file_name = conv.get("file_name")
            return


def update_active_conversation_metadata():
    """
    After changing file_id/file_name, sync to the active conversation.
    """
    conv = get_active_conversation()
    if conv:
        conv["file_id"] = st.session_state.file_id
        conv["file_name"] = st.session_state.file_name
        persist_active_conversation()


def maybe_update_conversation_title_from_prompt(prompt: str):
    """
    If conversation title is still generic, set it from the first user prompt.
    """
    conv = get_active_conversation()
    if not conv:
        return
    title = conv.get("title") or ""
    if title.startswith("New chat") or title.startswith("Chat "):
        trimmed = prompt.strip()
        if not trimmed:
            return
        max_len = 40
        conv["title"] = trimmed[:max_len] + ("..." if len(trimmed) > max_len else "")
        persist_active_conversation()


def reset_conversation_state():
    """Clear chat-related state for a fresh start."""
    st.session_state.conversations = []
    st.session_state.active_conv_id = None
    st.session_state.messages = []
    st.session_state.file_id = None
    st.session_state.file_name = None


def _normalize_message_item(message_item) -> tuple[str, str]:
    if isinstance(message_item, dict):
        return str(message_item.get("role", "")), str(message_item.get("content", ""))
    if isinstance(message_item, (tuple, list)) and len(message_item) == 2:
        return str(message_item[0]), str(message_item[1])
    return "", ""


def _conversation_payload(conv: dict) -> dict:
    messages = []
    for item in conv.get("messages", []):
        role, content = _normalize_message_item(item)
        if not role:
            continue
        messages.append({"role": role, "content": content})
    return {
        "title": conv.get("title") or "New chat",
        "file_id": conv.get("file_id"),
        "file_name": conv.get("file_name"),
        "messages": messages,
    }


def persist_active_conversation():
    """Persist active conversation to backend, including full message list."""
    conv = get_active_conversation()
    if not conv or not st.session_state.get("user"):
        return

    conv["messages"] = st.session_state.get("messages", conv.get("messages", []))
    payload = _conversation_payload(conv)

    try:
        api_put(f"/chat/conversations/{conv['id']}", payload)
    except Exception as e:
        st.warning(f"Could not save chat history: {e}")


def load_conversations_from_backend() -> bool:
    """Load this user's persisted conversation history from backend."""
    if not st.session_state.get("user"):
        return False

    try:
        data = api_get("/chat/conversations")
    except Exception as e:
        st.warning(f"Could not load previous chats: {e}")
        return False

    fetched_conversations = []
    for raw_conv in data.get("conversations", []):
        raw_messages = raw_conv.get("messages", [])
        conv_messages = []
        for item in raw_messages:
            role, content = _normalize_message_item(item)
            if role:
                conv_messages.append((role, content))
        fetched_conversations.append(
            {
                "id": raw_conv.get("id"),
                "title": raw_conv.get("title") or "New chat",
                "file_id": raw_conv.get("file_id"),
                "file_name": raw_conv.get("file_name"),
                "messages": conv_messages,
            }
        )

    st.session_state.conversations = fetched_conversations
    st.session_state.active_conv_id = (
        fetched_conversations[0]["id"] if fetched_conversations else None
    )

    # Align top-level convenience fields with the active conversation
    active = get_active_conversation()
    if active:
        st.session_state.messages = active.get("messages", [])
        active["messages"] = st.session_state.messages  # keep shared reference
        st.session_state.file_id = active.get("file_id")
        st.session_state.file_name = active.get("file_name")
    else:
        reset_conversation_state()
    return True


# ---- File upload history helpers ----


def fetch_upload_history(force_refresh: bool = False):
    """
    Fetch uploaded file history from the backend and cache it in session_state.
    Set force_refresh=True to ignore the cached list.
    """
    if (
        st.session_state.upload_history_loaded
        and st.session_state.get("uploads")
        and not force_refresh
    ):
        return st.session_state.uploads

    # Import locally to avoid circular imports at module load time
    from frontend.api import api_get

    try:
        resp = api_get("/files/history")
        st.session_state.uploads = resp.get("files", [])
        st.session_state.upload_history_loaded = True
    except Exception:
        st.session_state.upload_history_loaded = False
        raise

    return st.session_state.uploads


# ---- Lightweight auth persistence across refresh ----


def _encode_auth_payload(user: dict, tokens: Optional[dict]) -> str:
    payload = {"user": user, "tokens": tokens}
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_auth_payload(value: str) -> Optional[dict]:
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        return json.loads(raw)
    except Exception:
        return None


def hydrate_auth_from_query_params():
    """
    If session_state is empty (new session) but we have auth data encoded
    in the URL query params, restore it so a browser refresh doesn't log out.
    """
    if st.session_state.get("user"):
        return
    params = st.query_params
    encoded = params.get(AUTH_QUERY_KEY)
    if not encoded:
        return
    payload = _decode_auth_payload(encoded[0] if isinstance(encoded, list) else encoded)
    if payload and payload.get("user"):
        st.session_state.user = payload["user"]
        st.session_state.tokens = payload.get("tokens")


def persist_auth_to_query_params():
    """Store current auth (user + tokens) in URL query params for reload resilience."""
    user = st.session_state.get("user")
    if not user:
        return
    encoded = _encode_auth_payload(user, st.session_state.get("tokens"))
    st.query_params = {AUTH_QUERY_KEY: encoded}


def clear_auth_query_params():
    """Remove auth payload from query params, used on logout."""
    st.query_params = {}
