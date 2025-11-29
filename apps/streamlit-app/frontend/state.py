"""Helpers to manage Streamlit session state in one place."""
import streamlit as st


def ensure_base_state():
    """Ensure the base auth-related keys are present."""
    if "user" not in st.session_state:
        st.session_state.user = None  # {"id": ..., "email": ...}


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
