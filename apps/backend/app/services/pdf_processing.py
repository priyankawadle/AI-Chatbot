"""Utility for extracting text from PDF uploads."""
from io import BytesIO

from fastapi import HTTPException, status
from pypdf import PdfReader
import pdfplumber 


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract text from a PDF byte stream using pypdf.
    Returns a single string with text from all pages.
    """
    try:
        text_parts = []

        # Primary: pdfplumber (handles table layout better)
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                tables = page.extract_tables() or []
                for table in tables:
                    rows = ["\t".join((cell or "").strip() for cell in row) for row in table]
                    txt += "\n" + "\n".join(rows)
                if txt.strip():
                    text_parts.append(txt.strip())

        # Secondary fallback: pypdf
        if not text_parts:
            with BytesIO(pdf_bytes) as pdf_stream:
                reader = PdfReader(pdf_stream)
                for page in reader.pages:
                    txt = page.extract_text() or ""
                    if txt.strip():
                        text_parts.append(txt.strip())

        full_text = "\n\n".join(text_parts).strip()
        if not full_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No readable text found in the uploaded PDF (may be scanned).",
            )
        return full_text

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from PDF: {exc}",
        )
