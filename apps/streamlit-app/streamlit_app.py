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


# ---------- Global styles ----------

def inject_global_styles():
    """
    Inject custom CSS to give a modern SaaS-style UI.
    """
    st.markdown(
        """
        <style>
        /* ---- Global layout ---- */
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #f9fafb 0%, #eef2ff 30%, #f9fafb 100%);
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        /* Center main content a bit and limit width */
        [data-testid="stMain"] > div {
            max-width: 1120px;
            margin: 0 auto;
            padding-top: 1rem;
        }

        /* ---- Sidebar styling ---- */
        [data-testid="stSidebar"] {
            background-color: #f7f8fa;
            border-right: 1px solid #e5e7eb;
        }

        [data-testid="stSidebar"] .sidebar-content {
            padding-top: 0.75rem;
        }

        [data-testid="stSidebar"] .css-1d391kg,  /* older streamlit */
        [data-testid="stSidebar"] section {
            padding-top: 0.75rem;
        }

        [data-testid="stSidebar"] h2, 
        [data-testid="stSidebar"] h3 {
            font-weight: 600;
            color: #111827;
        }

        /* Conversation buttons in sidebar */
        [data-testid="stSidebar"] button[kind="secondary"] {
            border-radius: 999px;
            border: 1px solid transparent;
            padding: 0.25rem 0.9rem;
            margin-bottom: 0.25rem;
            font-size: 0.9rem;
            text-align: left;
        }
        [data-testid="stSidebar"] button[kind="secondary"]:hover {
            border-color: #3b82f6;
            background: #eff6ff;
            color: #1d4ed8;
        }

        /* New chat button — make it stand out a bit */
        [data-testid="stSidebar"] button[kind="primary"] {
            border-radius: 999px;
            font-weight: 600;
        }


        .top-title {
            font-size: 1.55rem;
            font-weight: 700;
            color: #111827;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .top-title span.icon {
            font-size: 1.7rem;
        }

        .user-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.25rem 0.8rem;
            border-radius: 999px;
            background: #ecfdf3;
            border: 1px solid #bbf7d0;
            color: #166534;
            font-size: 0.85rem;
        }

        .user-pill-avatar {
            width: 26px;
            height: 26px;
            border-radius: 999px;
            background: #22c55e22;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.9rem;
        }

        /* Logout button next to pill */
        .logout-wrapper button {
            border-radius: 999px !important;
            padding: 0.25rem 0.9rem !important;
            font-size: 0.85rem !important;
        }

        /* ---- Step cards ---- */
        .step-card {
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.04);
            border: 1px solid #e5e7eb;
            margin-bottom: 1.2rem;
        }

        .step-header {
            font-weight: 600;
            font-size: 1.02rem;
            color: #111827;
            margin-bottom: 0.15rem;
        }

        .step-caption {
            font-size: 0.9rem;
            color: #6b7280;
            margin-bottom: 0.6rem;
        }

        /* ---- File uploader ---- */
        [data-testid="stFileUploader"] section {
            border-radius: 14px;
            border: 1px dashed #cbd5f5;
            background: #f9fafb;
        }

        [data-testid="stFileUploader"] section:hover {
            border-color: #3b82f6;
            background: #eff6ff;
        }

        [data-testid="stFileUploader"] label {
            font-size: 0.92rem;
        }

        /* Upload button full-width & pill-shaped */
        .upload-btn-wrapper button {
            width: 100%;
            border-radius: 999px !important;
            font-weight: 600;
        }

        /* Info strip under uploader */
        .info-strip {
            margin-top: 0.6rem;
            padding: 0.7rem 0.9rem;
            border-radius: 12px;
            background: #eff6ff;
            color: #1d4ed8;
            font-size: 0.88rem;
        }

        /* Active document success message */
        .active-doc {
            font-size: 0.9rem;
        }

        /* ---- Chat messages ---- */
        .element-container:has([data-testid="stChatMessage"]) {
            margin-bottom: 0.35rem;
        }

        /* Chat input area */
        [data-testid="stChatInput"] textarea {
            border-radius: 999px !important;
        }

        /* General buttons (outside sidebar) */
        button[kind="secondary"] {
            border-radius: 999px !important;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


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
        st.markdown("#### Sign in to your workspace")
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
        st.markdown("#### Create a new account")
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

# Inject custom CSS once
inject_global_styles()

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
    st.markdown("### Chat history")

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

# ---------- Top bar: Title + Account details (right corner) ----------
st.markdown('<div class="top-header-card">', unsafe_allow_html=True)
header_cols = st.columns([4, 3])

with header_cols[0]:
    st.markdown(
        '<div class="top-title"><span class="icon">🤖</span>'
        '<span>AI ChatBot</span></div>',
        unsafe_allow_html=True,
    )
with header_cols[1]:
    user_cols = st.columns([3, 2])
    with user_cols[0]:
        email = st.session_state.user["email"]
        st.markdown(
            f"""
            <div class="user-pill">
                <div class="user-pill-avatar">👤</div>
                <div>
                    <div style="font-weight:600;">Logged in</div>
                    <div style="font-size:0.8rem;">{email}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with user_cols[1]:
        st.markdown('<div class="logout-wrapper">', unsafe_allow_html=True)
        if st.button("Logout", key="logout_btn", type="secondary"):
            # Clear all state on logout
            st.session_state.user = None
            st.session_state.conversations = []
            st.session_state.active_conv_id = None
            st.session_state.messages = []
            st.session_state.file_id = None
            st.session_state.file_name = None
            st.toast("Logged out", icon="✅")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)  # end top-header-card

# ---------- STEP 1: File upload (per conversation) ----------
st.markdown('<div class="step-card">', unsafe_allow_html=True)
st.markdown('<div class="step-header">Step 1 · Upload a document</div>', unsafe_allow_html=True)


uploaded_file = st.file_uploader(
    "Drag & drop or browse a file",
    type=["txt", "pdf"],
    label_visibility="collapsed",
)

upload_btn_disabled = uploaded_file is None
st.markdown('<div class="upload-btn-wrapper">', unsafe_allow_html=True)
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
st.markdown("</div>", unsafe_allow_html=True)  # end upload-btn-wrapper

if not st.session_state.file_id:
    st.markdown(
        '<div class="info-strip">Please upload a file for this chat. Once it is processed, '
        "you can start asking questions about its content.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)  # end step-card
    st.stop()

# If we have a file_id, show active document info
st.markdown(
    '<div class="info-strip active-doc">'
    f'Active document: <strong>{st.session_state.file_name}</strong> '
    f'(file_id={st.session_state.file_id})'
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("</div>", unsafe_allow_html=True)  # end step-card

# ---------- STEP 2: Chat about the uploaded file ----------
st.markdown('<div class="step-card">', unsafe_allow_html=True)
st.markdown('<div class="step-header">Step 2 · Ask questions about this document</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="step-caption">Type your question in natural language. The assistant will answer based on the uploaded file.</div>',
    unsafe_allow_html=True,
)

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

st.markdown("</div>", unsafe_allow_html=True)  # end step-card
