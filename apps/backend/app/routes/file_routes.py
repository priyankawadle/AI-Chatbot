"""Routes for uploading and chunking documents."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from qdrant_client.http import models as qmodels

from app.config import (
    MAX_CHUNKS_PER_FILE,
    SUPPORTED_EXTENSIONS,
    QDRANT_COLLECTION_NAME,
)
from app.db.database import get_db_conn
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.pdf_processing import extract_text_from_pdf
from app.services.vector_store import qdrant_client

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    conn=Depends(get_db_conn),
):
    """
    Upload a file (.txt or .pdf), create text chunks, embed them,
    store metadata & chunks in Postgres, and embeddings in Qdrant.

    Returns:
        {
            "message": "File uploaded successfully",
            "file_id": <int>,
            "chunks_stored": <int>
        }
    """
    # 1) Basic validation
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
        # 2) Read file content into memory
        raw_bytes = await file.read()
        size_bytes = len(raw_bytes)

        if size_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # 3) Decode / extract text based on file type
        if filename_lower.endswith(".txt"):
            text_content = raw_bytes.decode("utf-8", errors="ignore").strip()
        else:  # .pdf
            text_content = extract_text_from_pdf(raw_bytes)

        if not text_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No readable text found in the uploaded file.",
            )

        # 4) Chunk text
        chunks = chunk_text(text_content)
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty or could not be parsed into chunks.",
            )

        # 5) Generate embeddings
        embeddings = embed_texts(chunks)
        if len(embeddings) != len(chunks):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate embeddings for all chunks.",
            )

        # 6) Store file metadata + chunks in Postgres
        try:
            with conn.cursor() as cur:
                # Insert file metadata
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
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to persist file metadata.",
                    )
                file_id = row[0]

                # Insert chunks; if you need chunk_ids, collect them here
                for idx, chunk in enumerate(chunks):
                    cur.execute(
                        """
                        INSERT INTO file_chunks (file_id, chunk_index, content)
                        VALUES (%s, %s, %s);
                        """,
                        (file_id, idx, chunk),
                    )
            conn.commit()
        except HTTPException:
            raise
        except Exception as db_exc:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to store file or chunks: {db_exc}",
            )

        # 7) Store embeddings in Qdrant
        points = []
        for idx, (chunk_text_value, vector) in enumerate(zip(chunks, embeddings)):
            point_id = file_id * MAX_CHUNKS_PER_FILE + idx
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "file_id": file_id,
                        "chunk_index": idx,
                        "filename": file.filename,
                        "text": chunk_text_value,
                    },
                )
            )

        qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=points,
        )

        # 8) Success response
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "message": "File uploaded successfully",
                "file_id": file_id,
                "chunks_stored": len(chunks),
            },
        )

    except HTTPException:
        # Re-raise FastAPI-controlled errors
        raise
    except Exception as exc:
        # Generic failure path
        # TODO: Optionally delete partial DB rows / Qdrant points to keep things consistent.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {exc}",
        )


@router.get("/history")
async def list_uploaded_files(conn=Depends(get_db_conn)):
    """
    Return a list of previously uploaded files with basic metadata + chunk counts.
    Used by the Streamlit sidebar history to populate file pickers.
    """
    try:
        with conn.cursor() as cur:
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
        files.append(
            {
                "id": row[0],
                "filename": row[1],
                "content_type": row[2],
                "size_bytes": row[3],
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "chunk_count": row[5],
            }
        )

    return {"files": files}
