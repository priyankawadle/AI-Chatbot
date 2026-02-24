"""
Health check endpoint.

Returns the application status and the PostgreSQL server version so that
monitoring tools can verify both the API process and its database connection
are alive.
"""

from fastapi import APIRouter

from app.db.database import db_cursor, pool

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """
    Lightweight liveness + readiness probe.

    Runs a single cheap query against PostgreSQL and returns:
      - status: "ok" when the DB is reachable, "degraded" otherwise.
      - db:     "up" / "down"
      - db_version: PostgreSQL server version string (e.g. "PostgreSQL 16.2 ...").
    """
    try:
        if pool is None:
            return {"status": "degraded", "db": "down", "error": "Database pool is not initialized"}

        # Probe DB through the existing pool.
        with pool.connection() as db:
            with db_cursor(db) as cur:
                # SELECT version() returns the full PostgreSQL version string
                cur.execute("SELECT version();")
                version_row = cur.fetchone()
                version = version_row[0] if version_row else "unknown"

        return {"status": "ok", "db": "up", "db_version": version}

    except Exception as e:
        return {"status": "degraded", "db": "down", "error": str(e)}
