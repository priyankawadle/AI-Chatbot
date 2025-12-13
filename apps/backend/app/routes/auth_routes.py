
"""Authentication endpoints split out for clarity."""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException

from app.config import REFRESH_TOKEN_EXPIRE_DAYS
from app.db.database import get_db_conn
from app.db.user_repository import (
    email_exists,
    get_user_by_email,
    get_user_by_id,
    insert_user,
    is_refresh_token_valid,
    revoke_refresh_token,
    save_refresh_token,
)
from app.models.schemas import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(db, user: dict) -> TokenPair:
    role = user.get("role", "user")
    user_id = user["id"]
    access_token = create_access_token(user_id, role)
    refresh_token = create_refresh_token(user_id, role)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    save_refresh_token(db, user_id, refresh_token, expires_at)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", response_model=AuthResponse, status_code=201)
def register_user(payload: RegisterRequest, db=Depends(get_db_conn)):
    """
    Register a new user with email + password.

    - Enforces unique email.
    - Stores a PBKDF2 password hash (not the raw password).
    - Returns the minimal user profile plus an access+refresh token pair.
    """
    # Basic existence check to give a clean 409
    if email_exists(db, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    role = (payload.role or "user").lower()
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Invalid role")

    pwd_hash = hash_password(payload.password)
    try:
        user_id = insert_user(db, payload.email, pwd_hash, role=role)
    except Exception as e:
        # Rollback on generic DB errors
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

    user = {"id": user_id, "email": payload.email, "role": role}
    tokens = _issue_tokens(db, user)
    return AuthResponse(user=UserOut(**user), tokens=tokens)


@router.post("/login", response_model=AuthResponse)
def login_user(payload: LoginRequest, db=Depends(get_db_conn)):
    """
    Validate user credentials.

    - Verifies email exists and password matches the stored PBKDF2 hash.
    - Issues access and refresh tokens on success.
    """
    user = get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        # Avoid leaking which field failed
        raise HTTPException(status_code=401, detail="Invalid email or password")

    tokens = _issue_tokens(db, user)
    return AuthResponse(user=UserOut(id=user["id"], email=user["email"], role=user.get("role", "user")), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(payload: RefreshRequest, db=Depends(get_db_conn)):
    """Exchange a valid refresh token for a new access/refresh pair (rotation)."""
    try:
        decoded = decode_token(payload.refresh_token, expected_type="refresh")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = decoded.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token payload")

    if not is_refresh_token_valid(db, payload.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found")

    # Rotate: revoke the presented refresh token and issue a new pair
    revoke_refresh_token(db, payload.refresh_token)
    user = get_user_by_id(db, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _issue_tokens(db, user)
