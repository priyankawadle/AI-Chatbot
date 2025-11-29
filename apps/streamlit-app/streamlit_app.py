import os
import httpx
import streamlit as st
from pydantic import BaseModel, EmailStr, ValidationError

# ---------- Config ----------
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

# ---------- Models ----------
class ChatResponse(BaseModel):
    reply: str


class User(BaseModel):
    id: int
    email: EmailStr


# ---------- Tiny API helpers ----------

def api_post(path: str, payload: dict):
    """
    Simple JSON POST helper for normal endpoints like /auth/login, /chat, etc.
    """
    url = f"{API_BASE}{path}"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


def api_upload_file(path: str, file):
    """
    Multipart file upload helper for /files/upload.
    """
    url = f"{API_BASE}{path}"

    file_bytes = file.getvalue()
    file_name = file.name
    file_type = file.type or "application/octet-stream"

    files = {
        "file": (file_name, file_bytes, file_type)
    }

    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, files=files)
        r.raise_for_status()
        return r.json()


# ---------- Conversation helpers (local only for now) ----------

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


# ---------- Auth page (shown when NOT logged in) ----------

def show_auth_page():
    """
    Full-page Login / Register, shown when there is no logged-in user.
    """
    st.title("🤖 AI Chatbot")
    st.caption("Streamlit + FastAPI · Secure, document-aware customer queries")

    tabs = st.tabs(["Login", "Register"])

    # ----- Login tab -----
    with tabs[0]:
        st.subheader("Sign in to your workspace")
        with st.form("login_form", clear_on_submit=False):
            login_email = st.text_input("Work email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            login_submitted = st.form_submit_button("Sign in")
        if login_submitted:
            try:
                data = api_post("/auth/login", {"email": login_email, "password": login_password})
                # backend returns: {"message": "...", "user": {"id": ..., "email": ...}}
                st.session_state.user = data["user"]
                # Reset all conversation-related state on fresh login
                st.session_state.conversations = []
                st.session_state.active_conv_id = None
                st.session_state.messages = []
                st.session_state.file_id = None
                st.session_state.file_name = None
                st.toast("Login successful", icon="✅")
                st.rerun()
            except ValidationError as ve:
                st.error(f"Invalid email: {ve}")
            except httpx.HTTPStatusError as he:
                try:
                    detail = he.response.json().get("detail", str(he))
                except Exception:
                    detail = str(he)
                st.error(f"Login failed: {detail}")
            except Exception as e:
                st.error(f"Login error: {e}")

    # ----- Register tab -----
    with tabs[1]:
        st.subheader("Create a new account")
        with st.form("register_form", clear_on_submit=False):
            reg_email = st.text_input("Work email", key="reg_email")
            reg_password = st.text_input("Password", type="password", key="reg_password")
            reg_confirm = st.text_input("Confirm password", type="password", key="reg_confirm")
            reg_submitted = st.form_submit_button("Create account")
        if reg_submitted:
            if reg_password != reg_confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    # backend 201 -> returns UserOut: {"id": ..., "email": ...}
                    user = api_post("/auth/register", {"email": reg_email, "password": reg_password})
                    st.success("Registration successful. You can log in now.")
                    st.session_state.user = user
                    # On fresh registration, also reset conversation state
                    st.session_state.conversations = []
                    st.session_state.active_conv_id = None
                    st.session_state.messages = []
                    st.session_state.file_id = None
                    st.session_state.file_name = None
                    st.rerun()
                except httpx.HTTPStatusError as he:
                    try:
                        detail = he.response.json().get("detail", str(he))
                    except Exception:
                        detail = str(he)
                    st.error(f"Registration failed: {detail}")
                except Exception as e:
                    st.error(f"Registration error: {e}")


# ---------- Layout + main app ----------

st.set_page_config(
    page_title="AI Support Bot",
    page_icon="🤖",
    layout="wide",
)

# Base session state for auth
if "user" not in st.session_state:
    st.session_state.user = None  # {"id": ..., "email": ...}

# If not logged in -> only show auth page (no sidebar history / chat yet)
if not st.session_state.user:
    show_auth_page()
    st.stop()

# From here on, user is logged in
ensure_conversation_state()

# ---------- Sidebar: Conversation history ----------
with st.sidebar:
    st.header("Chat history")

    # List conversations (local only for now)
    if st.session_state.conversations:
        for conv in st.session_state.conversations:
            label = conv["title"] or "Untitled chat"
            is_active = conv["id"] == st.session_state.active_conv_id
            button_label = f"👉 {label}" if is_active else label
            if st.button(button_label, key=f"conv_btn_{conv['id']}", type="secondary"):
                load_conversation(conv["id"])
                st.rerun()
    else:
        st.info("No chats yet. Start by uploading a document and asking a question.")

    st.markdown("---")
    if st.button("➕ New chat", use_container_width=True):
        create_new_conversation(initial=False)
        st.rerun()

# Ensure we have a valid active conversation loaded
active_conv = get_active_conversation()
if not active_conv:
    create_new_conversation(initial=True)
    active_conv = get_active_conversation()

# ---------- Top bar: Title + Account details ----------
top_col1, top_col2 = st.columns([4, 3])

with top_col1:
    st.title("🤖 AI ChatBot")

with top_col2:
    email = st.session_state.user["email"]
    info_col1, info_col2 = st.columns([3, 2])
    with info_col1:
        st.write("Logged in")
        st.write(f"**{email}**")
    with info_col2:
        if st.button("Logout", key="logout_btn"):
            # Clear all state on logout
            st.session_state.user = None
            st.session_state.conversations = []
            st.session_state.active_conv_id = None
            st.session_state.messages = []
            st.session_state.file_id = None
            st.session_state.file_name = None
            st.toast("Logged out", icon="✅")
            st.rerun()

# ---------- STEP 1: File upload (per conversation) ----------
st.subheader("Step 1 · Upload a document")

uploaded_file = st.file_uploader(
    "Upload a file",
    type=["txt", "pdf"],
)

upload_btn_disabled = uploaded_file is None
if st.button("📤 Upload file to server", disabled=upload_btn_disabled, use_container_width=True):
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
                f"✅ {resp.get('message', 'File uploaded successfully')} "
                f"(file_id={st.session_state.file_id}, chunks={resp.get('chunks_stored')})"
            )
        except httpx.HTTPStatusError as he:
            try:
                detail = he.response.json().get("detail", str(he))
            except Exception:
                detail = str(he)
            st.error(f"File upload failed: {detail}")
        except Exception as e:
            st.error(f"Unexpected error during upload: {e}")

if not st.session_state.file_id:
    st.info(
        "Please upload a file for this chat. Once it is processed, "
        "you can start asking questions about its content."
    )
    st.stop()

# ---------- STEP 2: Chat about the uploaded file ----------
st.subheader("Step 2 · Ask questions about this document")
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
    active_conv["messages"] = st.session_state.messages

    with st.chat_message("assistant"):
        st.markdown(bot_reply)
