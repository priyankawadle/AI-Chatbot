"""Main chat + upload workflow rendering."""
from collections import defaultdict

import streamlit as st

from frontend.api import api_post, api_upload_file
from frontend.models import ChatCitation, ChatResponse, RetrievalSummary
from frontend.state import (
    fetch_upload_history,
    get_active_conversation,
    maybe_update_conversation_title_from_prompt,
    persist_active_conversation,
    update_active_conversation_metadata,
)


def _format_citation(citation: ChatCitation) -> str:
    page_label = citation.page_number if citation.page_number is not None else "Unknown"
    return f"[File: {citation.filename}, Page {page_label}]"


def _format_grouped_citations(citations: list[ChatCitation]) -> str:
    pages_by_file = defaultdict(set)
    unknown_by_file = defaultdict(bool)

    for citation in citations:
        if citation.page_number is None:
            unknown_by_file[citation.filename] = True
            continue
        pages_by_file[citation.filename].add(citation.page_number)

    ordered_files = []
    for citation in citations:
        if citation.filename not in ordered_files:
            ordered_files.append(citation.filename)

    parts = []
    for filename in ordered_files:
        page_values = sorted(pages_by_file.get(filename, set()))
        if page_values:
            page_csv = ",".join(str(p) for p in page_values)
            parts.append(f"[File: {filename}, Page {page_csv}]")
        elif unknown_by_file.get(filename):
            parts.append(f"[File: {filename}, Page Unknown]")

    return " ".join(parts)


def _format_retrieval_summary(retrieval: RetrievalSummary) -> str:
    def _fmt_score(value: float | None) -> str:
        return f"{value:.3f}" if value is not None else "N/A"

    return (
        f"top={_fmt_score(retrieval.top_score)} | "
        f"avg={_fmt_score(retrieval.avg_score)} | "
        f"chunks used={retrieval.chunks_used}/{retrieval.total_hits} | "
        f"confidence={retrieval.confidence_label}"
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

    st.markdown("### Upload Your Documents")
    
    uploaded_file = st.file_uploader(
        "Select a file (PDF or TXT, max 50 MB)",
        type=["txt", "pdf"],
        key=f"admin_uploader_{st.session_state.get('uploader_key', 0)}",
        help="Supported: PDF and Text files. Maximum size: 50 MB"
    )

    
    upload_btn_disabled = uploaded_file is None
    if st.button("Upload & Process File", disabled=upload_btn_disabled, use_container_width=True, key="upload_btn"):
        if uploaded_file is None:
            st.warning("Please select a file first.")
        else:
            # Validate file size (50 MB limit)
            max_size_mb = 50
            max_size_bytes = max_size_mb * 1024 * 1024
            if uploaded_file.size > max_size_bytes:
                st.error(f"File size exceeds {max_size_mb}MB limit. Your file is {uploaded_file.size / (1024*1024):.2f}MB.")
                return
            
            try:
                with st.spinner("Processing your file..."):
                    resp = api_upload_file("/files/upload", uploaded_file)

                # Expected response: { "message": "...", "file_id": <int>, "chunks_stored": <int> }
                file_id = resp.get("file_id")
                file_name = uploaded_file.name

                # Track uploads for sidebar history (newest first)
                st.session_state.uploads.insert(
                    0,
                    {
                        "id": file_id,
                        "filename": file_name,
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
                    f"File uploaded successfully\nFile ID: {file_id} | Chunks: {resp.get('chunks_stored')}"
                )

                # Force a rerun so the sidebar picks up the refreshed upload history
                st.rerun()
            except Exception as e:
                st.error(f"Upload failed: {e}")



def render_chat_step():
    """Render chat UI. Always searches across all uploaded files."""
    st.markdown("### Chat with Your Documents")

    # Fetch upload history to check if documents are available
    try:
        uploads = fetch_upload_history()
    except Exception as e:
        uploads = st.session_state.get("uploads", [])
        st.warning(f"Could not load uploaded files: {e}")

    active_conv = get_active_conversation()

    if not uploads:
        st.info("No uploaded documents yet. Ask an admin to upload files to get started.")
        return

    # Show summary of available documents
    doc_count = len(uploads)
    st.caption(f"Searching across {doc_count} document{'s' if doc_count != 1 else ''}...")
    st.markdown("---")

    # Keep all chat messages in a dedicated container above the input.
    chat_container = st.container()
    with chat_container:
        # Render chat history for this conversation
        for role, content in st.session_state.messages:
            with st.chat_message(role):
                st.markdown(content)

    # Chat input
    if prompt := st.chat_input("Ask a question..."):
        # Update conversation title from first prompt if needed
        maybe_update_conversation_title_from_prompt(prompt)

        # Store user message
        st.session_state.messages.append(("user", prompt))
        active_conv = get_active_conversation()
        if active_conv:
            active_conv["messages"] = st.session_state.messages  # keep reference in sync
        persist_active_conversation()

        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        # Call backend chat API - always search all files (no file_id)
        try:
            payload = {"message": prompt}
            # No file_id specified -> backend searches all files
            data = api_post("/chat", payload)
            chat_response = ChatResponse(**data)
            bot_reply = chat_response.reply

            if chat_response.retrieval.low_confidence:
                reason = (
                    chat_response.retrieval.reason
                    or "Matches were weak. Try rephrasing with specific terms from the document."
                )
                bot_reply = (
                    f"**Low confidence warning:** {reason}\n"
                    "Try adding exact keywords, section names, dates, or policy names.\n\n"
                    f"{bot_reply}"
                )

            if chat_response.citations:
                citation_text = _format_grouped_citations(chat_response.citations)
                bot_reply = f"{bot_reply}\n\n**Citations:** {citation_text}"

            retrieval_text = _format_retrieval_summary(chat_response.retrieval)
            bot_reply = f"{bot_reply}\n\n**Retrieval:** {retrieval_text}"
        except Exception as e:
            bot_reply = f"Error: {e}"

        # Store assistant message
        st.session_state.messages.append(("assistant", bot_reply))
        if active_conv:
            active_conv["messages"] = st.session_state.messages
        persist_active_conversation()

        with chat_container:
            with st.chat_message("assistant"):
                st.markdown(bot_reply)
