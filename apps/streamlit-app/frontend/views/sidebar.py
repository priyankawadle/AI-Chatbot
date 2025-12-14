"""Sidebar rendering for conversation history."""
import streamlit as st

from frontend.state import (
    create_new_conversation,
    fetch_upload_history,
    load_conversation,
    update_active_conversation_metadata,
)


def render_sidebar_history():
    """Show conversation list for users or uploads list for admins."""
    role = (st.session_state.user or {}).get("role", "user")
    if role == "admin":
        st.header("Uploaded files")
        if st.button("+ Upload new file", key="new_upload_btn", use_container_width=True, type="primary"):
            # Clear current selection so the main uploader is ready for a new file
            st.session_state.file_id = None
            st.session_state.file_name = None
            st.session_state.messages = []
            update_active_conversation_metadata()
            # Bump uploader_key to force Streamlit to render a fresh file_uploader widget
            st.session_state.uploader_key = st.session_state.get("uploader_key", 0) + 1
            st.rerun()
        st.caption("Pick a file to make it active.")

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
    else:
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
