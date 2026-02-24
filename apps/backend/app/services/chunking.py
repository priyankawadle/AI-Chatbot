"""Structure-aware chunking helpers used during ingestion."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Literal, Sequence, Tuple

from app.config import MAX_CHARS_PER_CHUNK

ChunkType = Literal["heading", "paragraph", "list", "table"]

_PARAGRAPH_OVERLAP = 140
_LIST_OVERLAP = 80
_TABLE_OVERLAP = 40
_HEADING_MAX_CHARS = 120


@dataclass
class ChunkRecord:
    text: str
    chunk_type: ChunkType
    section_title: str | None = None


def _is_heading(line: str) -> bool:
    trimmed = line.strip()
    if not trimmed or len(trimmed) > _HEADING_MAX_CHARS:
        return False

    if re.match(r"^(\d+(\.\d+)*)\s+\S+", trimmed):
        return True
    if trimmed.endswith(":") and len(trimmed.split()) <= 12:
        return True
    words = trimmed.split()
    if 1 <= len(words) <= 10 and trimmed.upper() == trimmed and any(ch.isalpha() for ch in trimmed):
        return True
    return False


def _line_type(line: str) -> ChunkType:
    stripped = line.strip()
    if _is_heading(stripped):
        return "heading"
    if "\t" in line or "|" in line:
        return "table"
    if re.match(r"^(\*|-|•|\d+[\.\)])\s+", stripped):
        return "list"
    return "paragraph"


def _split_with_overlap(text: str, *, max_chars: int, overlap: int) -> List[str]:
    """Split long text while preserving trailing overlap for continuity."""
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    chunks: List[str] = []
    start = 0
    size = len(body)
    safe_overlap = max(0, min(overlap, max_chars // 2))

    while start < size:
        end = min(start + max_chars, size)
        if end < size:
            break_pos = body.rfind("\n", start + 1, end)
            if break_pos == -1:
                break_pos = body.rfind(" ", start + 1, end)
            if break_pos != -1 and break_pos > start:
                end = break_pos
        part = body[start:end].strip()
        if part:
            chunks.append(part)
        if end >= size:
            break
        start = max(end - safe_overlap, start + 1)
    return chunks


def _append_block_chunks(
    out: List[ChunkRecord],
    *,
    block_lines: Sequence[str],
    chunk_type: ChunkType,
    section_title: str | None,
    max_chars: int,
) -> None:
    text = "\n".join(block_lines).strip()
    if not text:
        return

    if chunk_type == "table":
        overlap = _TABLE_OVERLAP
    elif chunk_type == "list":
        overlap = _LIST_OVERLAP
    else:
        overlap = _PARAGRAPH_OVERLAP

    for piece in _split_with_overlap(text, max_chars=max_chars, overlap=overlap):
        out.append(ChunkRecord(text=piece, chunk_type=chunk_type, section_title=section_title))


def chunk_text_structured(
    text: str,
    *,
    max_chars: int = MAX_CHARS_PER_CHUNK,
    current_section: str | None = None,
) -> Tuple[List[ChunkRecord], str | None]:
    """
    Build structure-aware chunks and keep section continuity across pages.

    Returns:
        (chunks, last_section_title)
    """
    raw = (text or "").strip()
    if not raw:
        return [], current_section

    lines = [line.rstrip() for line in raw.splitlines()]
    chunks: List[ChunkRecord] = []
    buffer: List[str] = []
    buffer_type: ChunkType | None = None
    section_title = current_section

    def flush_buffer() -> None:
        nonlocal buffer, buffer_type
        if not buffer or buffer_type is None:
            buffer = []
            buffer_type = None
            return
        _append_block_chunks(
            chunks,
            block_lines=buffer,
            chunk_type=buffer_type,
            section_title=section_title,
            max_chars=max_chars,
        )
        buffer = []
        buffer_type = None

    for line in lines:
        if not line.strip():
            flush_buffer()
            continue

        ltype = _line_type(line)
        if ltype == "heading":
            flush_buffer()
            heading_text = line.strip()
            section_title = heading_text
            chunks.append(ChunkRecord(text=heading_text, chunk_type="heading", section_title=section_title))
            continue

        if buffer_type is None:
            buffer_type = ltype
            buffer = [line]
            continue

        if ltype == buffer_type:
            buffer.append(line)
        else:
            flush_buffer()
            buffer_type = ltype
            buffer = [line]

    flush_buffer()
    return chunks, section_title
