"""Main chat + upload workflow rendering."""
import streamlit as st

from frontend.api import api_post, api_upload_file
from frontend.models import ChatResponse
from frontend.state import (
    get_active_conversation,
    maybe_update_conversation_title_from_prompt,
    update_active_conversation_metadata,
)


def render_upload_step(active_conv):
    """Render upload UI and sync file metadata into conversation state."""
    st.subheader("Step 1 - Upload a document")

    uploaded_file = st.file_uploader(
        "Upload a file",
        type=["txt", "pdf"],
    )

    upload_btn_disabled = uploaded_file is None
    if st.button("Upload file to server", disabled=upload_btn_disabled, use_container_width=True):
        if uploaded_file is None:
            st.warning("Please select a file first.")
        else:
            try:
                with st.spinner("Uploading and processing file..."):
                    resp = api_upload_file("/files/upload", uploaded_file)

                # Expected response: { "message": "...", "file_id": <int>, "chunks_stored": <int> }
                st.session_state.file_id = resp.get("file_id")
                st.session_state.file_name = uploaded_file.name

                # Reset chat when new file is uploaded for this conversation
                st.session_state.messages = []
                active_conv["messages"] = st.session_state.messages

                # Sync metadata to active conversation
                update_active_conversation_metadata()

                st.success(
                    f"{resp.get('message', 'File uploaded successfully')} "
                    f"(file_id={st.session_state.file_id}, chunks={resp.get('chunks_stored')})"
                )
            except Exception as e:
                st.error(f"File upload failed: {e}")

    if not st.session_state.file_id:
        st.info(
            "Please upload a file for this chat. Once it is processed, "
            "you can start asking questions about its content."
        )
        st.stop()


def render_chat_step():
    """Render chat UI for the uploaded file."""
    st.subheader("Step 2 - Ask questions about this document")
    st.caption("Type your question in natural language. The assistant will answer based on the uploaded file.")

    # Render chat history for this conversation
    for role, content in st.session_state.messages:
        with st.chat_message(role):
            st.markdown(content)

    # Chat input
    if prompt := st.chat_input("Ask a question about the uploaded file..."):
        # Update conversation title from first prompt if needed
        maybe_update_conversation_title_from_prompt(prompt)

        # Store user message
        st.session_state.messages.append(("user", prompt))
        active_conv = get_active_conversation()
        if active_conv:
            active_conv["messages"] = st.session_state.messages  # keep reference in sync

        with st.chat_message("user"):
            st.markdown(prompt)

        # Call backend chat API
        try:
            payload = {
                "message": prompt,
                "file_id": st.session_state.file_id,
                # optionally: "user_id": st.session_state.user["id"]
            }
            data = api_post("/chat", payload)
            bot_reply = ChatResponse(**data).reply
        except Exception as e:
            bot_reply = f"Error contacting API: {e}"

        # Store assistant message
        st.session_state.messages.append(("assistant", bot_reply))
        if active_conv:
            active_conv["messages"] = st.session_state.messages

        with st.chat_message("assistant"):
            st.markdown(bot_reply)
