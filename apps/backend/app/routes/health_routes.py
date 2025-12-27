"""Lightweight health endpoint."""
from fastapi import APIRouter, Depends

from app.db.database import IS_SQLITE, db_cursor, get_db_conn

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db=Depends(get_db_conn)):
    """Health includes DB status + version."""
    try:
        version_sql = "SELECT sqlite_version();" if IS_SQLITE else "SELECT version();"
        with db_cursor(db) as cur:
            cur.execute(version_sql)
            version_row = cur.fetchone()
            version = version_row[0] if version_row else "unknown"
        return {"status": "ok", "db": "up", "db_version": version}
    except Exception as e:
        return {"status": "degraded", "db": "down", "error": str(e)}
