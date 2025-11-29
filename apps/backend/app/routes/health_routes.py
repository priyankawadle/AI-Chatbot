"""Lightweight health endpoint."""
from fastapi import APIRouter, Depends

from app.db.database import get_db_conn

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db=Depends(get_db_conn)):
    """Health includes DB status + version."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
        return {"status": "ok", "db": "up", "db_version": version}
    except Exception as e:
        return {"status": "degraded", "db": "down", "error": str(e)}
