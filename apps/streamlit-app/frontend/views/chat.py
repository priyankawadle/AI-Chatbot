"""Main chat + upload workflow rendering."""
import streamlit as st

from frontend.api import api_post, api_upload_file
from frontend.models import ChatResponse
from frontend.state import (
    fetch_upload_history,
    get_active_conversation,
    maybe_update_conversation_title_from_prompt,
    update_active_conversation_metadata,
)


def render_upload_step(active_conv):
    """Render upload UI and sync file metadata into conversation state."""
    role = (st.session_state.user or {}).get("role", "user")
    if role != "admin":
        st.info("Only admins can upload documents. Please ask an admin to upload files.")
        return

    # Show last upload success message after a rerun
    if st.session_state.get("last_upload_success"):
        st.success(st.session_state.pop("last_upload_success"))

    st.subheader("Step 1 - Upload a document")
    st.caption("Upload a new file, then pick it from the history list to make it active.")

    uploaded_file = st.file_uploader(
        "Upload a file",
        type=["txt", "pdf"],
        key=f"admin_uploader_{st.session_state.get('uploader_key', 0)}",
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

                # Track uploads for admin sidebar history (newest first)
                st.session_state.uploads.insert(
                    0,
                    {
                        "id": st.session_state.file_id,
                        "filename": st.session_state.file_name,
                        "chunk_count": resp.get("chunks_stored"),
                        "size_bytes": uploaded_file.size,
                    },
                )
                st.session_state.upload_history_loaded = True

                # Refresh cached history from backend so sidebars get DB-backed data
                try:
                    fetch_upload_history(force_refresh=True)
                except Exception:
                    # Non-fatal: we already added the upload locally
                    pass

                # Sync metadata to active conversation
                update_active_conversation_metadata()

                # Persist success notice across rerun so sidebar refresh picks it up
                st.session_state.last_upload_success = (
                    f"{resp.get('message', 'File uploaded successfully')} "
                    f"(file_id={st.session_state.file_id}, chunks={resp.get('chunks_stored')})"
                )

                # Force a rerun so the sidebar picks up the refreshed upload history
                st.rerun()
            except Exception as e:
                st.error(f"File upload failed: {e}")

    if not st.session_state.file_id:
        st.info(
            "Please upload a file for this chat. Once it is processed, "
            "you can start asking questions about its content."
        )


def render_chat_step():
    """Render chat UI for the uploaded file."""
    role = (st.session_state.user or {}).get("role", "user")
    if role == "admin":
        st.info("Chat is available only to users. Switch to a user account to ask questions.")
        return

    st.subheader("Step 2 - Ask questions about this document")
    st.caption("Type your question in natural language. The assistant will answer based on the uploaded file.")

    # Fetch upload history so users can pick a document
    try:
        uploads = fetch_upload_history()
    except Exception as e:
        uploads = st.session_state.get("uploads", [])
        st.warning(f"Could not load uploaded files: {e}")

    active_conv = get_active_conversation()

    def set_active_file(file_id, file_name):
        """Update the active conversation's target file and clear chat if it changed."""
        if file_id != st.session_state.file_id:
            st.session_state.messages = []
            if active_conv:
                active_conv["messages"] = st.session_state.messages
        st.session_state.file_id = file_id
        st.session_state.file_name = file_name
        update_active_conversation_metadata()

    # Document selector
    if uploads:
        options = ["All documents"]
        option_map = {"All documents": None}
        for upload in uploads:
            file_id = upload.get("id") or upload.get("file_id")
            name = upload.get("filename") or upload.get("file_name") or f"File #{file_id}"
            label = f"{name} (#{file_id})"
            options.append(label)
            option_map[label] = upload

        default_label = "All documents"
        if st.session_state.file_id:
            for label, upload in option_map.items():
                if upload and (upload.get("id") == st.session_state.file_id or upload.get("file_id") == st.session_state.file_id):
                    default_label = label
                    break

        selection = st.selectbox(
            "Choose which uploaded file to chat about",
            options,
            index=options.index(default_label),
            help="Pick a specific upload to focus answers, or search across everything.",
        )

        chosen_upload = option_map.get(selection)
        if chosen_upload:
            target_id = chosen_upload.get("id") or chosen_upload.get("file_id")
            set_active_file(target_id, chosen_upload.get("filename") or chosen_upload.get("file_name"))
            chunk_info = ""
            if chosen_upload.get("chunk_count") is not None:
                chunk_info = f"({chosen_upload.get('chunk_count')} chunks indexed)"
            st.caption(f"Answering using: {chosen_upload.get('filename') or chosen_upload.get('file_name')} {chunk_info}")
        else:
            set_active_file(None, None)
            st.caption("No file pinned. I'll search across all admin-uploaded documents.")
    else:
        st.info("No uploaded documents found. Ask an admin to upload one.")

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
            payload = {"message": prompt}
            # If a specific file was chosen in this session, include it; otherwise backend searches all files.
            if st.session_state.file_id:
                payload["file_id"] = st.session_state.file_id
            # optionally: "user_id": st.session_state.user["id"]
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
