
"""Password hashing helpers (PBKDF2) and JWT token utilities."""
import hashlib
import hmac
import secrets
from typing import Optional
from datetime import datetime, timedelta, timezone

import jwt

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGO,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
)

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 150_000  # reasonable default, adjust per environment/hardware
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Derive a PBKDF2-HMAC-SHA256 hash for the password with a random salt."""
    if not isinstance(password, str) or password == "":
        raise ValueError("Password required")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"{PBKDF2_ALGO}${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored PBKDF2 record."""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != PBKDF2_ALGO:
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _build_token(sub: int, role: str, expires_delta: timedelta, token_type: str) -> str:
    """Create a signed JWT with a subject, expiry, and token type."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_access_token(user_id: int, role: str) -> str:
    return _build_token(user_id, role, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: int, role: str) -> str:
    return _build_token(user_id, role, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    """Decode and optionally validate the token type. Raises PyJWT errors on failure."""
    data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    if expected_type and data.get("type") != expected_type:
        raise jwt.InvalidTokenError("Incorrect token type")
    return data
