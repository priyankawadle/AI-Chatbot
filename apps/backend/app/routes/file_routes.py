"""
Routes for uploading and chunking documents.

Files are:
  1. Validated (type + size).
  2. Text-extracted (plain text or PDF).
  3. Chunked into smaller segments.
  4. Embedded via OpenAI.
  5. Stored as metadata + chunks in PostgreSQL.
  6. Indexed as vectors in Qdrant for semantic search.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from qdrant_client.http import models as qmodels

from app.config import (
    MAX_CHUNKS_PER_FILE,
    MAX_FILE_SIZE_MB,
    SUPPORTED_EXTENSIONS,
    QDRANT_COLLECTION_NAME,
)
from app.db.database import db_cursor, get_db_conn
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.pdf_processing import extract_text_pages_from_pdf
from app.services.security import get_current_user, require_admin
from app.services.vector_store import qdrant_client

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    conn=Depends(get_db_conn),
    current_user: dict = Depends(require_admin),
):
    """
    Upload a .txt or .pdf file, extract text, embed chunks, and store everything.

    Returns:
        {
            "message": "File uploaded successfully",
            "file_id": <int>,
            "chunks_stored": <int>
        }
    """
    # 1) Basic validation – ensure a filename was provided
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    filename_lower = file.filename.lower()
    if not filename_lower.endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .txt and .pdf files are supported right now.",
        )

    try:
        # 2) Read the entire file into memory
        raw_bytes = await file.read()
        size_bytes = len(raw_bytes)

        if size_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # Check file size limit
        max_size_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        if size_bytes > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds {MAX_FILE_SIZE_MB}MB limit.",
            )

        # 3) Extract text and keep optional page numbers for citations
        chunk_records = []
        if filename_lower.endswith(".txt"):
            text_content = raw_bytes.decode("utf-8", errors="ignore").strip()
            for chunk in chunk_text(text_content):
                chunk_records.append({"text": chunk, "page_number": 1})
        else:  # .pdf
            text_pages = extract_text_pages_from_pdf(raw_bytes)
            for page_number, page_text in text_pages:
                for chunk in chunk_text(page_text):
                    chunk_records.append({"text": chunk, "page_number": page_number})

        if not chunk_records:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No readable text found in the uploaded file.",
            )

        # 5) Generate vector embeddings for every chunk via OpenAI
        chunks = [record["text"] for record in chunk_records]
        embeddings = embed_texts(chunks)
        if len(embeddings) != len(chunk_records):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate embeddings for all chunks.",
            )

        # 6) Persist file metadata and chunks in PostgreSQL
        try:
            with db_cursor(conn) as cur:
                # Insert file metadata and retrieve the generated id in one step
                cur.execute(
                    """
                    INSERT INTO uploaded_files (filename, content_type, size_bytes)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        file.filename,
                        file.content_type or "application/octet-stream",
                        size_bytes,
                    ),
                )
                row = cur.fetchone()
                file_id = row[0] if row else None

                if not file_id:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to persist file metadata.",
                    )

                # Insert every text chunk linked to the file
                for idx, record in enumerate(chunk_records):
                    cur.execute(
                        """
                        INSERT INTO file_chunks (file_id, chunk_index, page_number, content)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (file_id, idx, record["page_number"], record["text"]),
                    )

            conn.commit()

        except HTTPException:
            raise  # Let FastAPI-controlled errors propagate as-is
        except Exception as db_exc:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to store file or chunks: {db_exc}",
            )

        # 7) Index the chunk embeddings in Qdrant for semantic search
        points = []
        for idx, (record, vector) in enumerate(zip(chunk_records, embeddings)):
            # Deterministic point id: file_id * large_offset + chunk_index
            point_id = file_id * MAX_CHUNKS_PER_FILE + idx
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "file_id": file_id,
                        "chunk_index": idx,
                        "page_number": record["page_number"],
                        "filename": file.filename,
                        "text": record["text"],
                    },
                )
            )

        qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=points,
        )

        # 8) Return a success summary
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "message": "File uploaded successfully",
                "file_id": file_id,
                "chunks_stored": len(chunks),
            },
        )

    except HTTPException:
        raise  # Re-raise FastAPI errors unchanged
    except Exception as exc:
        # Catch-all for unexpected failures
        # TODO: delete partial DB rows / Qdrant points to keep state consistent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {exc}",
        )


@router.get("/history")
async def list_uploaded_files(conn=Depends(get_db_conn)):
    """
    Return a list of previously uploaded files with metadata and chunk counts.

    Used by the Streamlit sidebar to populate the file-history picker.
    """
    try:
        with db_cursor(conn) as cur:
            cur.execute(
                """
                SELECT
                    f.id,
                    f.filename,
                    f.content_type,
                    f.size_bytes,
                    f.created_at,
                    COUNT(c.id) AS chunk_count
                FROM uploaded_files f
                LEFT JOIN file_chunks c ON c.file_id = f.id
                GROUP BY f.id
                ORDER BY f.created_at DESC;
                """
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load uploaded file history: {exc}",
        )

    files = []
    for row in rows:
        created_at = row[4]
        # PostgreSQL returns a datetime object; convert to ISO string for JSON
        created_at_str = (
            created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
        )
        files.append(
            {
                "id": row[0],
                "filename": row[1],
                "content_type": row[2],
                "size_bytes": row[3],
                "created_at": created_at_str,
                "chunk_count": row[5],
            }
        )

    return {"files": files}


@router.get("/{file_id}/chunks/{chunk_index}")
async def get_chunk_content(
    file_id: int,
    chunk_index: int,
    conn=Depends(get_db_conn),
    current_user: dict = Depends(get_current_user),
):
    """
    Return a specific stored chunk by file id and chunk index.
    Used by citation links in the Streamlit chat UI.
    """
    try:
        with db_cursor(conn) as cur:
            cur.execute(
                """
                SELECT f.filename, c.page_number, c.content
                FROM file_chunks c
                JOIN uploaded_files f ON f.id = c.file_id
                WHERE c.file_id = %s AND c.chunk_index = %s
                LIMIT 1;
                """,
                (file_id, chunk_index),
            )
            row = cur.fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load chunk: {exc}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found for the requested file.",
        )

    return {
        "file_id": file_id,
        "filename": row[0],
        "page_number": row[1],
        "chunk_index": chunk_index,
        "content": row[2],
    }
