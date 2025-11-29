"""Utility for extracting text from PDF uploads."""
from io import BytesIO

from fastapi import HTTPException, status
from pypdf import PdfReader


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract text from a PDF byte stream using pypdf.
    Returns a single string with text from all pages.
    """
    try:
        with BytesIO(pdf_bytes) as pdf_stream:
            reader = PdfReader(pdf_stream)
            pages_text = []

            for page in reader.pages:
                text = page.extract_text() or ""
                if text:
                    pages_text.append(text.strip())

        full_text = "\n\n".join(pages_text).strip()
        return full_text
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from PDF: {exc}",
        )
