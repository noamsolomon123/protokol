"""Liveness / readiness endpoint.

``GET /health`` verifies the platform can actually serve requests: it pings the
database with ``SELECT 1`` and reports whether the Neo4j graph layer is enabled.
A failing DB check downgrades ``status`` to ``degraded`` (still HTTP 200 so load
balancers get a body to inspect; flip to 503 if you want hard failure).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from knesset_osint.api.deps import get_db
from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger

logger = get_logger("api.health")

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health check")
def health(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Report overall status plus DB connectivity and graph-layer config."""
    database_ok = False
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        # Never leak connection strings/credentials in the response or logs.
        logger.warning("Health DB check failed: %s", type(exc).__name__)

    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "error",
        "neo4j": {"enabled": settings.neo4j_enabled},
    }
