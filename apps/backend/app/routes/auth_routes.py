"""Authentication endpoints split out for clarity."""
from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db_conn
from app.db.user_repository import email_exists, get_user_by_email, insert_user
from app.models.schemas import LoginRequest, RegisterRequest, UserOut
from app.services.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register_user(payload: RegisterRequest, db=Depends(get_db_conn)):
    """
    Register a new user with email + password.

    - Enforces unique email.
    - Stores a PBKDF2 password hash (not the raw password).
    - Returns the minimal user profile.
    """
    # Basic existence check to give a clean 409
    if email_exists(db, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    pwd_hash = hash_password(payload.password)
    try:
        user_id = insert_user(db, payload.email, pwd_hash)
    except Exception as e:
        # Rollback on generic DB errors
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

    return UserOut(id=user_id, email=payload.email)


@router.post("/login")
def login_user(payload: LoginRequest, db=Depends(get_db_conn)):
    """
    Validate user credentials.

    - Verifies email exists and password matches the stored PBKDF2 hash.
    - Keeps it simple: returns a success message + user profile (no JWT/session here).
      You can add JWT later if needed.
    """
    user = get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        # Avoid leaking which field failed
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "message": "Login successful",
        "user": {"id": user["id"], "email": user["email"]},
    }
