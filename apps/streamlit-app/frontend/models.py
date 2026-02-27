"""Pydantic models shared across the Streamlit app."""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


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
    reply: str
    citations: List[ChatCitation] = Field(default_factory=list)
    retrieval: RetrievalSummary = Field(default_factory=RetrievalSummary)


class User(BaseModel):
    id: int
    email: EmailStr
