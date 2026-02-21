# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.10-slim

# ── System dependencies ────────────────────────────────────────────────────────
# libpq-dev  : required by psycopg[binary] to link against PostgreSQL client libs
# build-essential : C compiler for any packages that build native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ──────────────────────────────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ────────────────────────────────────────────────
# Copy only requirements first so Docker can cache this layer independently of
# source code changes (faster rebuilds when only code changes).
COPY apps/backend/requirements.txt       /app/requirements-backend.txt
COPY apps/streamlit-app/requirements.txt /app/requirements-streamlit.txt

RUN pip install --no-cache-dir \
        -r /app/requirements-backend.txt \
        -r /app/requirements-streamlit.txt

# ── Copy application source ────────────────────────────────────────────────────
COPY apps/ /app/apps/
COPY entrypoint.sh /app/entrypoint.sh

# ── Runtime setup ─────────────────────────────────────────────────────────────
# Create directories for local data (Qdrant embedded mode, etc.)
RUN mkdir -p /app/data /app/data/qdrant

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# HF Spaces only exposes port 7860 externally.
# Streamlit runs on 7860 (public), FastAPI runs on 8000 (internal only).
EXPOSE 7860

# ── Entrypoint ─────────────────────────────────────────────────────────────────
CMD ["/app/entrypoint.sh"]
