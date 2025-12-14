"""Helpers to manage Streamlit session state in one place."""
import base64
import copy
import json
from typing import Optional

import streamlit as st

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
    if "conversation_cache" not in st.session_state:
        # Per-user in-memory cache so chat history survives logout/login within the same browser session.
        st.session_state.conversation_cache = {}


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

    # Try to restore cached conversations for this user if present
    if st.session_state.user and not st.session_state.conversations:
        restored = restore_conversations_for_user(st.session_state.user["email"])
        if restored:
            return

    # If logged in and no conversation yet, create the first one
    if st.session_state.user and st.session_state.active_conv_id is None:
        create_new_conversation(initial=True)


def create_new_conversation(initial: bool = False):
    """
    Create a new blank conversation in local state.
    Later, this can call an API to create a new chat.
    """
    conversations = st.session_state.conversations

    new_id = (max([c["id"] for c in conversations]) + 1) if conversations else 1

    conv = {
        "id": new_id,
        "title": "New chat" if initial else f"Chat {new_id}",
        "file_id": None,
        "file_name": None,
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


def reset_conversation_state():
    """Clear chat-related state for a fresh start."""
    st.session_state.conversations = []
    st.session_state.active_conv_id = None
    st.session_state.messages = []
    st.session_state.file_id = None
    st.session_state.file_name = None


def stash_conversations_for_user(email: str):
    """Cache current conversations for a given user inside session_state."""
    if not email:
        return
    st.session_state.conversation_cache[email] = {
        "conversations": copy.deepcopy(st.session_state.get("conversations", [])),
        "active_conv_id": st.session_state.get("active_conv_id"),
    }


def restore_conversations_for_user(email: str) -> bool:
    """Restore cached conversations if available. Returns True on success."""
    if not email:
        return False
    cache = st.session_state.conversation_cache.get(email)
    if not cache:
        return False

    st.session_state.conversations = copy.deepcopy(cache.get("conversations", []))
    st.session_state.active_conv_id = cache.get("active_conv_id")

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
