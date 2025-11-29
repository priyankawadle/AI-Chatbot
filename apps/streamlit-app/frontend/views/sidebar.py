"""Sidebar rendering for conversation history."""
import streamlit as st

from frontend.state import create_new_conversation, load_conversation


def render_sidebar_history():
    """Show conversation list and new chat button."""
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
