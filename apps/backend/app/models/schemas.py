"""Pydantic models used for request and response bodies."""
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    # Keep it simple: a single password field with minimal validation.
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr


class ChatRequest(BaseModel):
    """
    Incoming payload from Streamlit:
        {
            "message": "... user question ...",
            "file_id": 123
        }
    """
    message: str
    file_id: int


class ChatResponse(BaseModel):
    """
    Outgoing payload to Streamlit:
        {
            "reply": "... bot answer ..."
        }
    """
    reply: str
