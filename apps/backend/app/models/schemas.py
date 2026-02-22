
"""Pydantic models used for request and response bodies."""
from typing import List, Optional

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


class ChatCitation(BaseModel):
    file_id: int
    filename: str
    page_number: Optional[int] = None
    score: Optional[float] = None


class RetrievalSummary(BaseModel):
    top_score: Optional[float] = None
    avg_score: Optional[float] = None
    chunks_used: int = 0
    total_hits: int = 0
    low_confidence: bool = False
    confidence_label: str = "low"
    reason: Optional[str] = None


class ChatResponse(BaseModel):
    """
    Outgoing payload to Streamlit:
        {
            "reply": "... bot answer ...",
            "citations": [
                {
                    "file_id": 1,
                    "filename": "policy.pdf",
                    "page_number": 3
                }
            ]
        }
    """
    reply: str
    citations: List[ChatCitation] = Field(default_factory=list)
    retrieval: RetrievalSummary = Field(default_factory=RetrievalSummary)
