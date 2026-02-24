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

import hashlib

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
from app.services.chunking import chunk_text_structured
from app.services.embeddings import embed_texts
from app.services.pdf_processing import extract_text_pages_from_pdf
from app.services.security import get_current_user, require_admin
from app.services.vector_store import qdrant_client

router = APIRouter(prefix="/files", tags=["files"])


def _file_filter(file_id: int) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="file_id",
                match=qmodels.MatchValue(value=file_id),
            )
        ]
    )


def _delete_file_points_from_qdrant(file_id: int) -> None:
    qdrant_client.delete(
        collection_name=QDRANT_COLLECTION_NAME,
        points_selector=_file_filter(file_id),
        wait=True,
    )


def _upsert_file_points_to_qdrant(
    *,
    file_id: int,
    filename: str,
    chunk_rows: list[tuple[int, int | None, str, str | None, str | None]],
    embeddings: list[list[float]],
) -> None:
    points: list[qmodels.PointStruct] = []
    for (chunk_index, page_number, chunk_text, chunk_type, section_title), vector in zip(chunk_rows, embeddings):
        point_id = file_id * MAX_CHUNKS_PER_FILE + int(chunk_index)
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "file_id": file_id,
                    "chunk_index": int(chunk_index),
                    "page_number": page_number,
                    "filename": filename,
                    "text": chunk_text,
                    "chunk_type": chunk_type,
                    "section_title": section_title,
                },
            )
        )

    qdrant_client.upsert(
        collection_name=QDRANT_COLLECTION_NAME,
        points=points,
    )


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

        file_hash = hashlib.sha256(raw_bytes).hexdigest()

        with db_cursor(conn) as cur:
            cur.execute(
                """
                SELECT id, filename
                FROM uploaded_files
                WHERE file_hash = %s
                LIMIT 1;
                """,
                (file_hash,),
            )
            duplicate = cur.fetchone()

        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This file already exists in the corpus. "
                    f"Existing file: #{duplicate[0]} ({duplicate[1]})."
                ),
            )

        # 3) Extract text and keep optional page numbers for citations
        chunk_records = []
        if filename_lower.endswith(".txt"):
            text_content = raw_bytes.decode("utf-8", errors="ignore").strip()
            structured_chunks, _ = chunk_text_structured(text_content)
            for chunk in structured_chunks:
                chunk_records.append(
                    {
                        "text": chunk.text,
                        "page_number": 1,
                        "chunk_type": chunk.chunk_type,
                        "section_title": chunk.section_title,
                    }
                )
        else:  # .pdf
            text_pages = extract_text_pages_from_pdf(raw_bytes)
            current_section = None
            for page_number, page_text in text_pages:
                structured_chunks, current_section = chunk_text_structured(
                    page_text,
                    current_section=current_section,
                )
                for chunk in structured_chunks:
                    chunk_records.append(
                        {
                            "text": chunk.text,
                            "page_number": page_number,
                            "chunk_type": chunk.chunk_type,
                            "section_title": chunk.section_title,
                        }
                    )

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
                    INSERT INTO uploaded_files (filename, content_type, size_bytes, file_hash)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        file.filename,
                        file.content_type or "application/octet-stream",
                        size_bytes,
                        file_hash,
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
                        INSERT INTO file_chunks (
                            file_id,
                            chunk_index,
                            page_number,
                            content,
                            chunk_type,
                            section_title
                        )
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (
                            file_id,
                            idx,
                            record["page_number"],
                            record["text"],
                            record["chunk_type"],
                            record["section_title"],
                        ),
                    )

            conn.commit()

        except HTTPException:
            raise  # Let FastAPI-controlled errors propagate as-is
        except Exception as db_exc:
            conn.rollback()
            if "duplicate key value" in str(db_exc).lower() and "file_hash" in str(db_exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This file already exists in the corpus.",
                )
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
                        "chunk_type": record["chunk_type"],
                        "section_title": record["section_title"],
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
                    f.usage_count,
                    f.last_queried_at,
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
                "usage_count": row[5],
                "last_queried_at": (row[6].isoformat() if row[6] else None),
                "chunk_count": row[7],
            }
        )

    return {"files": files}


@router.delete("/{file_id}")
async def delete_uploaded_file(
    file_id: int,
    conn=Depends(get_db_conn),
    current_user: dict = Depends(require_admin),
):
    """Delete a file and its chunks from PostgreSQL and Qdrant."""
    try:
        with db_cursor(conn) as cur:
            cur.execute("SELECT filename FROM uploaded_files WHERE id = %s;", (file_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found.",
                )
            filename = row[0]

            cur.execute("DELETE FROM uploaded_files WHERE id = %s;", (file_id,))
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found.",
                )
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file from database: {exc}",
        )

    try:
        _delete_file_points_from_qdrant(file_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "File was deleted from PostgreSQL, but failed to remove vectors from Qdrant: "
                f"{exc}"
            ),
        )

    return {
        "message": "File deleted successfully.",
        "file_id": file_id,
        "filename": filename,
    }


@router.post("/{file_id}/reindex")
async def reindex_uploaded_file(
    file_id: int,
    conn=Depends(get_db_conn),
    current_user: dict = Depends(require_admin),
):
    """Rebuild embeddings and Qdrant points for an existing file."""
    try:
        with db_cursor(conn) as cur:
            cur.execute(
                """
                SELECT filename
                FROM uploaded_files
                WHERE id = %s;
                """,
                (file_id,),
            )
            file_row = cur.fetchone()
            if not file_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found.",
                )
            filename = file_row[0]

            cur.execute(
                """
                SELECT chunk_index, page_number, content, chunk_type, section_title
                FROM file_chunks
                WHERE file_id = %s
                ORDER BY chunk_index ASC;
                """,
                (file_id,),
            )
            chunk_rows = cur.fetchall()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load file chunks for reindex: {exc}",
        )

    if not chunk_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No chunks found for this file; cannot re-index.",
        )

    chunk_texts = [str(row[2]) for row in chunk_rows]
    try:
        embeddings = embed_texts(chunk_texts)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate embeddings during re-index: {exc}",
        )

    if len(embeddings) != len(chunk_rows):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Embedding count mismatch during re-index.",
        )

    try:
        _delete_file_points_from_qdrant(file_id)
        _upsert_file_points_to_qdrant(
            file_id=file_id,
            filename=filename,
            chunk_rows=chunk_rows,
            embeddings=embeddings,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update vectors in Qdrant during re-index: {exc}",
        )

    return {
        "message": "File re-indexed successfully.",
        "file_id": file_id,
        "filename": filename,
        "chunks_reindexed": len(chunk_rows),
    }


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
                SELECT f.filename, c.page_number, c.content, c.chunk_type, c.section_title
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
        "chunk_type": row[3],
        "section_title": row[4],
    }
