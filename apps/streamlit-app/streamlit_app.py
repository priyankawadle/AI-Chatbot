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
    NEW: Multipart file upload helper for /files/upload.
    Expects the backend FastAPI endpoint:
        @app.post("/files/upload")
        async def upload_file(file: UploadFile = File(...)):
            ...
    """
    url = f"{API_BASE}{path}"

    # Streamlit's UploadedFile object -> bytes + metadata
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

# ---------- Streamlit UI ----------
st.set_page_config(page_title="AI Support Bot", page_icon="🤖")
st.title("🤖 AI Customer Support (Streamlit + FastAPI)")

# ---------- Session bootstrap ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "user" not in st.session_state:
    st.session_state.user = None  # will hold {"id": ..., "email": ...}

# NEW: Track uploaded file in session
if "file_id" not in st.session_state:
    st.session_state.file_id = None     # backend file id returned by /files/upload
if "file_name" not in st.session_state:
    st.session_state.file_name = None   # original filename

# ---------- Sidebar: Auth controls ----------
with st.sidebar:
    st.subheader("Account")

    if st.session_state.user:
        st.success(f"Logged in as **{st.session_state.user['email']}**")

        # NEW: Show upload status in sidebar
        if st.session_state.file_id:
            st.info(
                f"Active document:\n\n**{st.session_state.file_name}** "
                f"(file_id={st.session_state.file_id})"
            )

        if st.button("🔒 Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.messages = []
            st.session_state.file_id = None
            st.session_state.file_name = None
            st.toast("Logged out", icon="✅")
            st.rerun()
    else:
        tabs = st.tabs(["Login", "Register"])

        # ----- Login tab -----
        with tabs[0]:
            with st.form("login_form", clear_on_submit=False):
                login_email = st.text_input("Email", key="login_email")
                login_password = st.text_input("Password", type="password", key="login_password")
                login_submitted = st.form_submit_button("Sign in")
            if login_submitted:
                try:
                    data = api_post("/auth/login", {"email": login_email, "password": login_password})
                    # backend returns: {"message": "...", "user": {"id": ..., "email": ...}}
                    st.session_state.user = data["user"]
                    st.session_state.messages = []
                    st.session_state.file_id = None
                    st.session_state.file_name = None
                    st.toast("Login successful", icon="✅")
                    st.rerun()
                except ValidationError as ve:
                    st.error(f"Invalid email: {ve}")
                except httpx.HTTPStatusError as he:
                    detail = he.response.json().get("detail", str(he))
                    st.error(f"Login failed: {detail}")
                except Exception as e:
                    st.error(f"Login error: {e}")

        # ----- Register tab -----
        with tabs[1]:
            with st.form("register_form", clear_on_submit=False):
                reg_email = st.text_input("Email", key="reg_email")
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
                        st.session_state.messages = []
                        st.session_state.file_id = None
                        st.session_state.file_name = None
                        st.rerun()
                    except httpx.HTTPStatusError as he:
                        detail = he.response.json().get("detail", str(he))
                        st.error(f"Registration failed: {detail}")
                    except Exception as e:
                        st.error(f"Registration error: {e}")

st.divider()

# ---------- Main area requires login ----------
if not st.session_state.user:
    st.info("Please log in to start using the bot.")
    st.stop()

st.caption(f"Signed in as **{st.session_state.user['email']}**")

# ---------- STEP 1: File upload (MANDATORY before chat) ----------
st.subheader("Step 1: Upload a document")

# File uploader (txt / pdf)
uploaded_file = st.file_uploader(
    "Upload a .txt or .pdf file",
    type=["txt", "pdf"],
    help="The bot will answer questions based only on this file's content."
)

# Upload button (separate from file selection)
upload_btn_disabled = uploaded_file is None
if st.button("📤 Upload file to server", disabled=upload_btn_disabled):
    if uploaded_file is None:
        st.warning("Please select a file first.")
    else:
        try:
            with st.spinner("Uploading and processing file..."):
                resp = api_upload_file("/files/upload", uploaded_file)
            # Expected response from backend:
            # { "message": "File uploaded successfully", "file_id": <int>, "chunks_stored": <int> }
            st.session_state.file_id = resp.get("file_id")
            st.session_state.file_name = uploaded_file.name
            # Optional: reset chat when new file is uploaded
            st.session_state.messages = []

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

# If no file has been successfully uploaded yet, stop here.
if not st.session_state.file_id:
    st.info("Please upload a file first. Once the file is processed, you can start asking questions about it.")
    st.stop()

st.success(f"Active document: **{st.session_state.file_name}** (file_id={st.session_state.file_id})")

st.divider()

# ---------- STEP 2: Chat about the uploaded file ----------
st.subheader("Step 2: Ask questions about this document")

# Render chat history
for role, content in st.session_state.messages:
    with st.chat_message(role):
        st.markdown(content)

# Chat input (only enabled after file is uploaded)
if prompt := st.chat_input("Ask a question about the uploaded file..."):
    # Store user message
    st.session_state.messages.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call backend chat API
    try:
        # IMPORTANT:
        # We send file_id so backend can restrict search/answers to this file.
        payload = {
            "message": prompt,
            "file_id": st.session_state.file_id,
            # optionally: "user_id": st.session_state.user["id"]
        }
        data = api_post("/chat", payload)
        bot_reply = ChatResponse(**data).reply
    except Exception as e:
        bot_reply = f"Error contacting API: {e}"

    # Store and render assistant message
    st.session_state.messages.append(("assistant", bot_reply))
    with st.chat_message("assistant"):
        st.markdown(bot_reply)
