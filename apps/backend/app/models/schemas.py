
"""Pydantic models used for request and response bodies."""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    # Keep it simple: a single password field with minimal validation.
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str = "user"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    user: UserOut
    tokens: TokenPair


class RefreshRequest(BaseModel):
    refresh_token: str


class ChatRequest(BaseModel):
    """
    Incoming payload from Streamlit:
        {
            "message": "... user question ...",
            "file_id": 123 (optional; will default to most recent uploaded file)
        }
    """
    message: str
    file_id: Optional[int] = None


class ChatResponse(BaseModel):
    """
    Outgoing payload to Streamlit:
        {
            "reply": "... bot answer ..."
        }
    """
    reply: str
