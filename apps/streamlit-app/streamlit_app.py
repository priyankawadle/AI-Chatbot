import streamlit as st

from frontend.state import (
    create_new_conversation,
    ensure_base_state,
    ensure_conversation_state,
    get_active_conversation,
    clear_auth_query_params,
    hydrate_auth_from_query_params,
    stash_conversations_for_user,
)
from frontend.views.auth import show_auth_page
from frontend.views.chat import render_chat_step, render_upload_step
from frontend.views.sidebar import render_sidebar_history

# ---------- Layout + main app ----------

st.set_page_config(
    page_title="AI Support Bot",
    page_icon=":robot_face:",
    layout="wide",
)

# Base session state for auth
ensure_base_state()
hydrate_auth_from_query_params()

# If not logged in -> only show auth page (no sidebar history / chat yet)
if not st.session_state.user:
    show_auth_page()
    st.stop()

# From here on, user is logged in
ensure_conversation_state()

# ---------- Sidebar: Conversation history ----------
with st.sidebar:
    render_sidebar_history()

# Ensure we have a valid active conversation loaded
active_conv = get_active_conversation()
if not active_conv:
    create_new_conversation(initial=True)
    active_conv = get_active_conversation()

# ---------- Top bar: Title + Account details ----------
top_col1, top_col2 = st.columns([5, 2])

with top_col1:
    st.markdown("""
    <div style="margin-bottom: 15px;">
    <h1 style="margin: 0; color: #ffffff;">🤖 AI Document Assistant</h1>
    <p style="margin: 5px 0 0 0; color: #a0a0a0; font-size: 14px;">Smart document search and Q&A</p>
    </div>
    """, unsafe_allow_html=True)

with top_col2:
    email = st.session_state.user["email"]
    role = st.session_state.user.get("role", "user")
    
    st.markdown(f"""
    <div style="text-align: right; font-size: 13px; line-height: 1.6;">
    <p style="margin: 0; color: #808080;">Logged in</p>
    <p style="margin: 3px 0; color: #ffffff; font-weight: 500;">{email}</p>
    <p style="margin: 5px 0 0 0; color: #a0a0a0; font-size: 12px;">{'Admin' if role == 'admin' else 'User'}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Logout", key="logout_btn", use_container_width=True):
        # Save this user's conversations in the session cache so a later login can restore them
        stash_conversations_for_user(email)
        # Clear all state on logout
        st.session_state.user = None
        st.session_state.tokens = None
        st.session_state.conversations = []
        st.session_state.active_conv_id = None
        st.session_state.messages = []
        st.session_state.file_id = None
        st.session_state.file_name = None
        st.session_state.uploads = []
        st.session_state.upload_history_loaded = False
        clear_auth_query_params()
        st.toast("Logged out", icon="\u2705")
        st.rerun()

# ---------- Main Content ----------


# Create tabs for Upload and Chat
if role == "admin":
    # Admins see both upload and chat tabs
    upload_tab, chat_tab = st.tabs(["📁 Upload Documents", "💬 Chat"])
    
    with upload_tab:
        st.markdown("")
        render_upload_step(active_conv)
    
    with chat_tab:
        st.markdown("")
        render_chat_step()
else:
    # Users only see chat tab
    st.markdown("")
    render_chat_step()
