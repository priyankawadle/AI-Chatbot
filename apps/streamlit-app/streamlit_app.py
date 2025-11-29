import streamlit as st

from frontend.state import (
    create_new_conversation,
    ensure_base_state,
    ensure_conversation_state,
    get_active_conversation,
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
top_col1, top_col2 = st.columns([4, 3])

with top_col1:
    st.title("AI ChatBot")

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
            st.toast("Logged out", icon=":white_check_mark:")
            st.rerun()

# ---------- Steps ----------
render_upload_step(active_conv)
render_chat_step()
