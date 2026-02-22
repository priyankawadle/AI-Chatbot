"""Pydantic models shared across the Streamlit app."""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class ChatCitation(BaseModel):
    file_id: int
    filename: str
    page_number: Optional[int] = None
    score: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    citations: List[ChatCitation] = Field(default_factory=list)


class User(BaseModel):
    id: int
    email: EmailStr
