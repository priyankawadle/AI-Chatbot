"""Tiny helper for breaking text into smaller pieces."""
from typing import List

from app.config import MAX_CHARS_PER_CHUNK


def chunk_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> List[str]:
    """
    Very simple character-based chunker.
    You can replace with token-based chunking later.
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # Try to break at a newline or space for nicer chunks
        break_pos = text.rfind("\n", start, end)
        if break_pos == -1:
            break_pos = text.rfind(" ", start, end)
        if break_pos == -1 or break_pos <= start:
            break_pos = end
        chunks.append(text[start:break_pos].strip())
        start = break_pos
    return [c for c in chunks if c]
