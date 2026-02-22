"""Utility for extracting text from PDF uploads."""
from io import BytesIO
from typing import List, Tuple

from fastapi import HTTPException, status
from pypdf import PdfReader
import pdfplumber 


def extract_text_pages_from_pdf(pdf_bytes: bytes) -> List[Tuple[int, str]]:
    """
    Extract text from a PDF byte stream and return (page_number, text) tuples.
    Page numbers are 1-based.
    """
    try:
        text_pages: List[Tuple[int, str]] = []

        # Primary: pdfplumber (handles table layout better)
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                txt = page.extract_text() or ""
                tables = page.extract_tables() or []
                for table in tables:
                    rows = ["\t".join((cell or "").strip() for cell in row) for row in table]
                    txt += "\n" + "\n".join(rows)
                cleaned = txt.strip()
                if cleaned:
                    text_pages.append((idx, cleaned))

        # Secondary fallback: pypdf
        if not text_pages:
            with BytesIO(pdf_bytes) as pdf_stream:
                reader = PdfReader(pdf_stream)
                for idx, page in enumerate(reader.pages, start=1):
                    txt = (page.extract_text() or "").strip()
                    if txt:
                        text_pages.append((idx, txt))

        if not text_pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No readable text found in the uploaded PDF (may be scanned).",
            )

        return text_pages

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from PDF: {exc}",
        )


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Backward-compatible helper: return all extracted pages as one string.
    """
    text_pages = extract_text_pages_from_pdf(pdf_bytes)
    return "\n\n".join(text for _, text in text_pages).strip()
