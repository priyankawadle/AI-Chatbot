import os
import secrets
import hashlib
import hmac
from typing import Generator, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from psycopg2 import OperationalError
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

# ---------- Env & App ----------
load_dotenv()  # reads .env in project root

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mysecretpassword")

app = FastAPI(title="AI Support Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# ---------- Password hashing helpers (PBKDF2) ----------
# We store "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 150_000  # reasonable default, adjust per environment/hardware
SALT_BYTES = 16

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

@app.get("/db/ping")
def db_ping(db=Depends(get_db_conn)):
    """Lightweight DB ping endpoint."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1;")
            _ = cur.fetchone()
        return {"db": "up"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {e}")

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
