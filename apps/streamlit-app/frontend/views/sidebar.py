"""Sidebar rendering for conversation history."""
import streamlit as st

from frontend.state import (
    create_new_conversation,
    fetch_upload_history,
    load_conversation,
    update_active_conversation_metadata,
)


def _render_upload_sidebar():
    st.header("Uploaded files")
    uploads = st.session_state.get("uploads", [])
    if not uploads:
        try:
            uploads = fetch_upload_history()
        except Exception as e:
            st.warning(f"Could not load uploads: {e}")

    if uploads:
        for upload in uploads:
            file_id = upload.get("id") or upload.get("file_id")
            if not file_id:
                continue
            label = upload.get("filename") or upload.get("file_name") or f"File #{file_id}"
            meta = []
            if upload.get("chunk_count") is not None:
                meta.append(f"{upload.get('chunk_count')} chunks")
            if upload.get("size_bytes") is not None:
                meta.append(f"{upload.get('size_bytes')} bytes")
            meta_text = " | ".join(meta)
            button_label = f"{label} (#{file_id})"
            if st.button(button_label, key=f"upload_{file_id}", type="secondary", help=meta_text or None):
                st.session_state.file_id = file_id
                st.session_state.file_name = upload.get("filename") or upload.get("file_name")
                st.session_state.messages = []
                update_active_conversation_metadata()
                st.rerun()
    else:
        st.info("No uploads yet. Add a file to see it listed here.")


def _render_chat_history_sidebar():
    st.header("Chat history")

    # List conversations (local only for now)
    if st.session_state.conversations:
        for conv in st.session_state.conversations:
            label = conv["title"] or "Untitled chat"
            is_active = conv["id"] == st.session_state.active_conv_id
            button_label = f"-> {label}" if is_active else label
            if st.button(button_label, key=f"conv_btn_{conv['id']}", type="secondary"):
                load_conversation(conv["id"])
                st.rerun()
    else:
        st.info("No chats yet. Start by uploading a document and asking a question.")

    st.markdown("---")
    if st.button("+ New chat", use_container_width=True):
        create_new_conversation(initial=False)
        st.rerun()


def render_sidebar_history(admin_view: str = "chat"):
    """Show uploads or chat history depending on role and current view."""
    role = (st.session_state.user or {}).get("role", "user")
    if role == "admin":
        if admin_view == "upload":
            _render_upload_sidebar()
        else:
            _render_chat_history_sidebar()
    else:
        _render_chat_history_sidebar()
