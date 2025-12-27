FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install dependencies for both backend and Streamlit frontend
COPY apps/backend/requirements.txt /tmp/requirements-backend.txt
COPY apps/streamlit-app/requirements.txt /tmp/requirements-streamlit.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r /tmp/requirements-backend.txt -r /tmp/requirements-streamlit.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . /app

# Default envs for Hugging Face Space (overridable in Space Secrets)
ENV API_BASE=http://127.0.0.1:8000 \
    DB_DRIVER=sqlite \
    SQLITE_PATH=/app/data/app.db \
    QDRANT_PATH=/app/data/qdrant \
    QDRANT_URL= \
    PYTHONPATH=/app/apps/backend

RUN mkdir -p /app/data && chmod +x /app/entrypoint.sh

EXPOSE 7860

CMD ["bash", "entrypoint.sh"]
