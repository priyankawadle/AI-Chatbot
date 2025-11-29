"""Auth page rendering (login + register)."""
import httpx
import streamlit as st
from pydantic import ValidationError

from frontend.api import api_post


def show_auth_page():
    """Full-page Login / Register, shown when there is no logged-in user."""
    st.title("AI Chatbot")
    st.caption("Streamlit + FastAPI - Secure, document-aware customer queries")

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
                st.toast("Login successful", icon="\U00002705")
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
