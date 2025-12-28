# AI-Powered Customer Support Bot (RAG + Intent)

## Objective
- Provide a retrieval-augmented chatbot that answers customer/support questions grounded in your docs.
- Combine a FastAPI backend (ingestion, intent, retrieval, chat endpoints) with a Streamlit chat UI.
- Ship as a single Docker image ready for local use or Hugging Face Spaces.

## Project structure
- apps/backend/app/main.py: FastAPI application entrypoint and router wiring.
- apps/backend/app/services/: ingestion, chunking, embedding, and Qdrant helpers.
- apps/backend/app/db/: schema + connection helpers (SQLite by default; Postgres supported).
- apps/backend/data/app.db: default SQLite database path for local/Space runs.
- apps/streamlit-app/streamlit_app.py: Streamlit UI entrypoint.
- apps/streamlit-app/frontend/: shared UI state, models, and API helpers.
- Dockerfile: builds backend + Streamlit in one image (used locally and on Spaces).
- entrypoint.sh: starts uvicorn on 8000 and Streamlit on 7860 inside the container.

## Tech stack
- Backend: Python 3.10, FastAPI, Pydantic, psycopg2/SQLite, Qdrant client.
- Retrieval: OpenAI chat + embeddings (pluggable), hybrid chunking, embedded or remote Qdrant vector store.
- Frontend: Streamlit chat UI with history and file upload hooks.
- Infra: Docker-based build; environment-driven config via `.env` files or Space secrets.

## Run locally (no Docker)
1) Prereqs: Python 3.10+, optional Docker if you prefer Postgres/Qdrant containers. For quickest start, set `DB_DRIVER=sqlite` to use the bundled file DB and embedded Qdrant.
2) Install deps:
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r apps/backend/requirements.txt -r apps/streamlit-app/requirements.txt
```
3) Configure envs (do not commit secrets):
   - `apps/backend/.env`: `DB_DRIVER=sqlite`, `SQLITE_PATH=./apps/backend/data/app.db`, `QDRANT_PATH=./apps/backend/data/qdrant`, `OPENAI_API_KEY=<your key>`, optional `QDRANT_URL`/Postgres settings.
   - `apps/streamlit-app/.env`: `API_BASE=http://127.0.0.1:8000`, `OPENAI_API_KEY=<your key>`, `OPENAI_MODEL=<chat model>`, `OPENAI_EMBED_MODEL=<embed model>`, optional `QDRANT_*` overrides.
4) (Optional) Remote Qdrant instead of embedded:
```bash
docker run -p 6333:6333 qdrant/qdrant
# set QDRANT_URL=http://localhost:6333 in both env files
```
5) Start the backend:
```bash
uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000 --reload
```
6) Start the Streamlit UI:
```bash
API_BASE=http://127.0.0.1:8000 streamlit run apps/streamlit-app/streamlit_app.py --server.address 127.0.0.1 --server.port 7860
```
Visit http://127.0.0.1:7860 to chat.

## Docker (local) run
```bash
docker build -t ai-chatbot .
docker run -p 8000:8000 -p 7860:7860 \
  -e OPENAI_API_KEY=<your key> \
  ai-chatbot
```
Add `-v "$(pwd)/data:/app/data"` to persist SQLite/Qdrant data across runs.

## Deploy to Hugging Face Spaces (Docker)
1) Create a new Space and choose SDK **Docker**.
2) Push this repo to the Space (keep `Dockerfile` and `entrypoint.sh`).
 - git clone https://github.com/<username>/<repo-name>.git
 - cd <repo-name>
 - git remote add hf https://huggingface.co/spaces/<username>/<space-name>
 - git remote -v
 - git add .
 - git commit -m "Update app"
 - git push origin main  
 - git push hf main       

3) In Space **Secrets**, set at minimum `OPENAI_API_KEY`. Optional overrides: `JWT_SECRET`, `ALLOWED_ORIGINS`, `DB_DRIVER`/   `DB_*` (for Postgres), `QDRANT_URL` (for managed Qdrant), `API_BASE` (if you front the API differently).
4) Build/launch: Spaces builds the Docker image, then `entrypoint.sh` starts FastAPI on `0.0.0.0:8000` and Streamlit on `0.0.0.0:7860`. With no overrides, it uses SQLite at `/app/data/app.db` and embedded Qdrant at `/app/data/qdrant`.

Defaults for Spaces:
* DB: SQLite at `/app/data/app.db` (set `DB_DRIVER=postgres` plus connection envs if you prefer Postgres).
* Vectors: embedded Qdrant at `/app/data/qdrant` (set `QDRANT_URL` to point at a managed Qdrant instead).
* CORS: `ALLOWED_ORIGINS="*"` unless you override via env.
