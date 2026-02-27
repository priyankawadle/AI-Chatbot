# AI Chatbot (FastAPI + Streamlit + RAG)

An AI document assistant that lets users upload `.txt`/`.pdf` files and ask questions grounded in those documents using hybrid retrieval (Qdrant vector search + BM25) and OpenAI responses.

## Purpose

- Build a customer-support style chatbot that answers from uploaded documents.
- Support role-based access:
- `admin`: upload/delete files + chat.
- `user`: chat with indexed content.
- Persist conversations and authentication in PostgreSQL.

## Features

- JWT auth with access/refresh token rotation.
- Admin-only document upload and chat.
- Structured chunking for text and PDF pages.
- Hybrid retrieval:
 1. semantic search in Qdrant.
 2. lexical BM25 search in PostgreSQL.
- Inline citations with `page` + `filename + confidence`
- Duplicate upload protection using SHA-256 file hash (prevents re-uploading same document).
- Multi-file query support when file_id is not provided in /chat (searches across available files).
- Retrieval confidence summary in responses (top_score, avg_score, confidence_label, low_confidence, reason).
- Streamlit chat UI with conversation history.
- FastAPI docs via Swagger.

## Tech Stack

- Python 3.10
- FastAPI + Uvicorn
- Streamlit
- PostgreSQL (psycopg3 + connection pool)
- Qdrant
- OpenAI API

## Prerequisites (Exact)

- Python `3.10.x`
- PostgreSQL `14+` (local or managed)
- Qdrant `1.7+` (local Docker or Qdrant Cloud)
- OpenAI API key

## Project Structure

- `apps/backend`: FastAPI API, DB, retrieval, embeddings
- `apps/streamlit-app`: Streamlit frontend
- `Dockerfile`: single container running backend + UI

## Environment Setup

Create env files from examples:

```powershell
Copy-Items from apps\backend\.env.example into apps\backend\.env
Copy-Items from apps\streamlit-app\.env.example into apps\streamlit-app\.env
```

### Backend variables (`apps/backend/.env`)

- `DB_HOST`: PostgreSQL host
- `DB_PORT`: PostgreSQL port
- `DB_NAME`: database name
- `DB_USER`: database user
- `DB_PASSWORD`: database password
- `QDRANT_URL`: Qdrant HTTP URL (example: `http://localhost:6333`)
- `QDRANT_API_KEY`: Qdrant Cloud key (blank for local)
- `QDRANT_COLLECTION_NAME`: collection name for chunk vectors
- `OPENAI_API_KEY`: OpenAI secret key
- `OPENAI_CHAT_MODEL`: chat model (example: `gpt-4.1-nano`)
- `EMBEDDING_MODEL`: embedding model (example: `text-embedding-3-small`)
- `MIN_SCORE_ANSWER`: minimum score threshold for answer confidence
- `LOW_CONFIDENCE_SCORE`: threshold for low-confidence warning
- `ALLOWED_ORIGINS`: comma-separated CORS origins (or `*`)
- `JWT_SECRET`: signing secret for tokens
- `JWT_ALGO`: JWT algorithm (`HS256`)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: access token lifetime
- `REFRESH_TOKEN_EXPIRE_DAYS`: refresh token lifetime

### Frontend variables (`apps/streamlit-app/.env`)

- `API_BASE`: backend base URL (example: `http://127.0.0.1:8000`)

## Run Locally (Step by Step)

1. Create and activate virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r apps\backend\requirements.txt -r apps\streamlit-app\requirements.txt
```

3. Start PostgreSQL :
- install pgadmin+postgres 
- create local db in pgadmin and add your db secrets in .env

4. Start Qdrant (example with Docker):

```powershell
docker run --name ai-chatbot-qdrant -p 6333:6333 -d qdrant/qdrant
```

5. Configure `.env` files from examples and update credentials.

6. Execute these commands:
```powershell
$env:OPENAI_API_KEY ="sk-"
$env:API_BASE = http://127.0.0.1:8000"
```
7. Start backend:

```powershell
uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000 --reload
```

8. In a new terminal, start Streamlit:

```powershell
streamlit run apps/streamlit-app/streamlit_app.py --server.address 127.0.0.1 --server.port 7860
```

## URLs (UI + Docs)

- Streamlit UI: `http://127.0.0.1:7860`
- FastAPI base: `http://127.0.0.1:8000`
- Swagger docs: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health endpoint: `http://127.0.0.1:8000/health`
- Qdrant dashboard (local): `http://127.0.0.1:6333/dashboard`

## API Examples

### Register

`POST /auth/register`

Request:

```json
{
  "email": "admin@example.com",
  "password": "StrongPass123!",
  "role": "admin"
}
```

Response (201):

```json
{
  "user": {
    "id": 1,
    "email": "admin@example.com",
    "role": "admin"
  },
  "tokens": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "bearer"
  }
}
```

### Login

`POST /auth/login`

Request:

```json
{
  "email": "admin@example.com",
  "password": "StrongPass123!"
}
```

Response:

```json
{
  "user": {
    "id": 1,
    "email": "admin@example.com",
    "role": "admin"
  },
  "tokens": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "bearer"
  }
}
```

### Upload File (admin only)

`POST /files/upload` with `multipart/form-data`

Example curl:

```bash
curl -X POST "http://127.0.0.1:8000/files/upload" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@sample.pdf"
```

Response (201):

```json
{
  "message": "File uploaded successfully",
  "file_id": 12,
  "chunks_stored": 84
}
```

### Chat

`POST /chat`

Request:

```json
{
  "message": "What is the refund policy?",
  "file_id": 12
}
```

Response:

```json
{
  "reply": "The refund policy allows returns within 30 days...",
  "citations": [
    {
      "file_id": 12,
      "filename": "sample.pdf",
      "page_number": 3,
      "score": 0.82
    }
  ],
  "retrieval": {
    "top_score": 0.82,
    "avg_score": 0.66,
    "chunks_used": 5,
    "total_hits": 15,
    "low_confidence": false,
    "confidence_label": "high",
    "reason": "Hybrid retrieval used semantic and BM25 candidates."
  }
}
```

## Troubleshooting

- `Database pool is not initialized`:
- Backend failed at startup; check PostgreSQL host/port/credentials in `apps/backend/.env`.
- `Vector search failed` or Qdrant errors:
- Verify `QDRANT_URL` and that Qdrant is running.
- `Failed to embed question` / OpenAI errors:
- Check `OPENAI_API_KEY`, model names, and API quota.
- `401 Invalid authentication credentials`:
- Access token expired or missing; login again or call `/auth/refresh`.
- `403 Admin privileges required`:
- Upload/delete/reindex endpoints require a user with role `admin`.
- CORS issues in browser:
- Set `ALLOWED_ORIGINS` correctly or use `*` during local development.

## Deployment Notes

### Hugging Face Spaces (Docker)

1. Create a new Space with SDK `Docker`.
2. Push this repository to the Space.
3. Add Secrets:
- required: `OPENAI_API_KEY`
- recommended: `DB_*`, `QDRANT_URL`, `QDRANT_API_KEY`, `JWT_SECRET`, `ALLOWED_ORIGINS`
4. Build and run. The container starts:
- FastAPI on `0.0.0.0:8000` (internal)
- Streamlit on `0.0.0.0:7860` (public)

### Render (How We Deploy)

Use one Web Service with the existing Docker image pattern (backend + Streamlit in one container).

1. Push this repo to GitHub.
2. In Render, click `New` -> `Web Service` -> connect the repo.
3. Runtime:
- preferred: `Docker`
4. Instance config:
- Region close to your users
- Set health check path to `/health`
5. Environment variables:
- required: `OPENAI_API_KEY`
- required: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- required: `QDRANT_URL` (and `QDRANT_API_KEY` if cloud)
- recommended: `JWT_SECRET`, `ALLOWED_ORIGINS`


7. Deploy and open the Render URL.
8. Validate:
- `/health` returns status JSON
- UI loads and can login/upload/chat
