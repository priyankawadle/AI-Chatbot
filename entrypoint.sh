#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/data /app/data/qdrant

# Start FastAPI backend
uvicorn app.main:app --app-dir /app/apps/backend --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Streamlit frontend
API_BASE=${API_BASE:-http://127.0.0.1:8000} streamlit run /app/apps/streamlit-app/streamlit_app.py \
    --server.address 0.0.0.0 \
    --server.port 7860 \
    --server.headless true

# If Streamlit exits, stop backend
kill $BACKEND_PID 2>/dev/null || true
