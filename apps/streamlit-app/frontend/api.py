"""Tiny HTTP helpers for talking to the FastAPI backend."""
import httpx

from frontend.config import API_BASE


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
