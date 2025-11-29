"""Pydantic models shared across the Streamlit app."""
from pydantic import BaseModel, EmailStr


class ChatResponse(BaseModel):
    reply: str


class User(BaseModel):
    id: int
    email: EmailStr
