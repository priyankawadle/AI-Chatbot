"""Tiny HTTP helpers for talking to the FastAPI backend."""
import httpx
import streamlit as st

from frontend.config import API_BASE


def _get_auth_header():
    """Get the Authorization header with the current user's access token."""
    tokens = st.session_state.get("tokens")
    if tokens and tokens.get("access_token"):
        return {"Authorization": f"Bearer {tokens['access_token']}"}
    return {}


def api_get(path: str):
    """
    Simple GET helper for list-style endpoints.
    """
    url = f"{API_BASE}{path}"
    headers = _get_auth_header()
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


def api_post(path: str, payload: dict):
    """
    Simple JSON POST helper for normal endpoints like /auth/login, /chat, etc.
    """
    url = f"{API_BASE}{path}"
    headers = _get_auth_header()
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


def api_upload_file(path: str, file):
    """
    Multipart file upload helper for /files/upload.
    Includes Authorization header for authenticated requests.
    """
    url = f"{API_BASE}{path}"

    file_bytes = file.getvalue()
    file_name = file.name
    file_type = file.type or "application/octet-stream"

    files = {
        "file": (file_name, file_bytes, file_type)
    }

    headers = _get_auth_header()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, files=files, headers=headers)
        r.raise_for_status()
        return r.json()
