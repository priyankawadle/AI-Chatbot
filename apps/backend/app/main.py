import os
import secrets
import hashlib
import hmac
import psycopg2

from typing import Generator, Optional,List
from fastapi import Depends, FastAPI, HTTPException,UploadFile, File, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from psycopg2 import OperationalError
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from openai import OpenAI

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from io import BytesIO

from pypdf import PdfReader
# ---------- Env & App ----------
load_dotenv()  # reads .env in project root

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mysecretpassword")


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "supportbot_documents")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small") 
EMBEDDING_DIM = 1536 

# Chat model config
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-nano")

# Qdrant search config
TOP_K = 5               # how many chunks to retrieve
MIN_SCORE = 0.35        # similarity threshold; tune this as needed

app = FastAPI(title="AI Chat Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI client (sync)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Qdrant client
qdrant_client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

# ---------- Models (request/response) ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    # Keep it simple: a single password field with minimal validation.
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr

class ChatRequest(BaseModel):
    """
    Incoming payload from Streamlit:
        {
            "message": "... user question ...",
            "file_id": 123
        }
    """
    message: str
    file_id: int

class ChatResponse(BaseModel):
    """
    Outgoing payload to Streamlit:
        {
            "reply": "... bot answer ..."
        }
    """
    reply: str

# ---------- Password hashing helpers (PBKDF2) ----------
# We store "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 150_000  # reasonable default, adjust per environment/hardware
SALT_BYTES = 16

MAX_CHARS_PER_CHUNK = 1000
MAX_CHUNKS_PER_FILE = 100_000
SUPPORTED_EXTENSIONS = (".txt", ".pdf")

def hash_password(password: str) -> str:
    """Derive a PBKDF2-HMAC-SHA256 hash for the password with a random salt."""
    if not isinstance(password, str) or password == "":
        raise ValueError("Password required")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"{PBKDF2_ALGO}${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored PBKDF2 record."""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != PBKDF2_ALGO:
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False

# ---------- DB Pool ----------
pool: Optional[SimpleConnectionPool] = None  # global handle

def _create_users_table_if_needed(conn) -> None:
    """Create a minimal users table if it doesn't exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

@app.on_event("startup")
def startup_event() -> None:
    """Create a small connection pool on startup and ensure schema exists."""
    global pool
    try:
        pool = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        )
        # quick sanity ping + create users table
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                _ = cur.fetchone()
            _create_users_table_if_needed(conn)
        finally:
            pool.putconn(conn)

        print("✅ DB pool initialized and schema verified.")
        ensure_qdrant_collection()
    except OperationalError as e:
        print(f"❌ Failed to initialize DB pool: {e}")
        raise

@app.on_event("shutdown")
def shutdown_event() -> None:
    """Close the pool on shutdown."""
    global pool
    if pool:
        pool.closeall()
        print("🔌 DB pool closed.")

def get_db_conn() -> Generator:
    """FastAPI dependency to get/return a pooled connection."""
    global pool
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

def ensure_qdrant_collection():
    """
    Creates the collection in Qdrant if it does not exist.
    Uses cosine distance and fixed vector size.
    """
    try:
        qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
        # If no exception, collection already exists.
        return
    except Exception:
        # Collection does not exist yet -> create
        qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )

# ---------- Utility DB functions ----------
def _email_exists(conn, email: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s LIMIT 1;", (email,))
        return cur.fetchone() is not None

def _insert_user(conn, email: str, password_hash: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id;",
            (email, password_hash),
        )
        user_id = cur.fetchone()[0]
    conn.commit()
    return user_id

def _get_user_by_email(conn, email: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "password_hash": row[2]}

# -------------------------
# Helper: text chunking
# -------------------------

def chunk_text(text: str, max_chars: int = 1000) -> List[str]:
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

# -------------------------
# Helper: embeddings
# -------------------------

def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Calls OpenAI embeddings for a list of texts.
    Returns a list of embedding vectors.
    """
    if not texts:
        return []

    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )

    # Map back to list of floats
    vectors: List[List[float]] = [d.embedding for d in response.data]
    return vectors

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

# ---------- Routes (existing) ----------
@app.get("/health")
def health(db=Depends(get_db_conn)):
    """Health includes DB status + version."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
        return {"status": "ok", "db": "up", "db_version": version}
    except Exception as e:
        return {"status": "degraded", "db": "down", "error": str(e)}

# ---------- Auth Routes (simple & clear) ----------
@app.post("/auth/register", response_model=UserOut, status_code=201)
def register_user(payload: RegisterRequest, db=Depends(get_db_conn)):
    """
    Register a new user with email + password.

    - Enforces unique email.
    - Stores a PBKDF2 password hash (not the raw password).
    - Returns the minimal user profile.
    """
    # Basic existence check to give a clean 409
    if _email_exists(db, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    pwd_hash = hash_password(payload.password)
    try:
        user_id = _insert_user(db, payload.email, pwd_hash)
    except Exception as e:
        # Rollback on generic DB errors
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

    return UserOut(id=user_id, email=payload.email)

@app.post("/auth/login")
def login_user(payload: LoginRequest, db=Depends(get_db_conn)):
    """
    Validate user credentials.

    - Verifies email exists and password matches the stored PBKDF2 hash.
    - Keeps it simple: returns a success message + user profile (no JWT/session here).
      You can add JWT later if needed.
    """
    user = _get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        # Avoid leaking which field failed
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "message": "Login successful",
        "user": {"id": user["id"], "email": user["email"]},
    }

# -------------------------
# File upload endpoint
# -------------------------


@app.post("/files/upload")
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
        chunks = chunk_text(text_content, max_chars=MAX_CHARS_PER_CHUNK)
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
        file_id = None
        try:
            with conn:
                with conn.cursor() as cur:
                    # Insert file metadata
                    cur.execute(
                        """
                        INSERT INTO uploaded_files (filename, content_type, size_bytes)
                        VALUES (%s, %s, %s)
                        RETURNING id;
                        """,
                        (file.filename, file.content_type or "application/octet-stream", size_bytes),
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
            # exiting `with conn:` commits the transaction

        finally:
            # Always close the connection we got from Depends
            conn.close()

        if file_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="File ID is missing after insert.",
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
    
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
    """
    Chat over a single uploaded file.

    Flow:
      1. Embed the user question.
      2. Search Qdrant in the given file's chunks (filter by file_id).
      3. If no relevant chunk found -> return a friendly "no match" message.
      4. Otherwise, send top chunks + question to OpenAI and return the answer.
    """
    question = payload.message.strip()
    file_id = payload.file_id

    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question must not be empty.",
        )

    # 1) Embed the question using the same embedding model as for documents
    try:
        question_embedding = embed_texts([question])[0]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to embed question: {exc}",
        )

    # 2) Search Qdrant for most similar chunks for this file_id
    try:
        search_results = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=question_embedding,
            limit=TOP_K,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="file_id",
                        match=qmodels.MatchValue(value=file_id),
                    )
                ]
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {exc}",
        )

    # No chunks at all
    if not search_results:
        return ChatResponse(
            reply=(
                "I couldn't find any relevant information in the uploaded document "
                "for your question."
            )
        )

    # Check best score against threshold for relevance
    best_score = search_results[0].score
    if best_score is None or best_score < MIN_SCORE:
        return ChatResponse(
            reply=(
                "I searched your uploaded document but couldn't find a strong match "
                "for your question. Please try rephrasing or ask about another part "
                "of the document."
            )
        )

    # 3) Build context from top-k chunks
    context_snippets: List[str] = []
    for hit in search_results:
        payload = hit.payload or {}
        text = payload.get("text", "")
        chunk_index = payload.get("chunk_index", "?")
        if text:
            context_snippets.append(f"[Chunk {chunk_index}] {text}")

    if not context_snippets:
        return ChatResponse(
            reply=(
                "I tried to read relevant parts of the document, but couldn't extract "
                "any usable text for your question."
            )
        )

    context_block = "\n\n".join(context_snippets)

    # 4) Ask OpenAI to answer based ONLY on this context
    #    The instructions explicitly tell it not to hallucinate beyond context.
    try:
        prompt_for_model = (
            "You are an AI assistant that answers questions using ONLY the provided document context.\n"
            "If the answer is not clearly contained in the context, say that you cannot find it "
            "in the document. Do NOT invent facts.\n\n"
            f"Document context:\n{context_block}\n\n"
            f"User question: {question}\n\n"
            "Answer:"
        )

        completion = openai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful support assistant that only uses the given context.",
                },
                {
                    "role": "user",
                    "content": prompt_for_model,
                },
            ],
            temperature=0.2,
        )

        answer = completion.choices[0].message.content.strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM call failed: {exc}",
        )

    # 5) Return the final answer to Streamlit
    if not answer:
        answer = (
            "I tried to answer from the document, but couldn't generate a useful response. "
            "Please try rephrasing your question."
        )

    return ChatResponse(reply=answer)

