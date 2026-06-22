"""FastAPI application factory.

``create_app`` builds the app, configures logging, and mounts every router from
:data:`knesset_osint.api.routers.ALL_ROUTERS`. A module-level ``app`` is exposed
for ASGI servers, e.g.::

    uvicorn knesset_osint.main:app --reload

Extending: add a new resource by creating ``api/routers/<name>.py`` and
appending its ``router`` to ``ALL_ROUTERS`` — no change is needed here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from knesset_osint.api.deps import get_db
from knesset_osint.api.routers import ALL_ROUTERS
from knesset_osint.api.routers.health import health as health_handler
from knesset_osint.core.config import settings
from knesset_osint.core.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    configure_logging(settings.log_level)
    logger = get_logger("main")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Objective OSINT platform tracking Israeli politicians against hard "
            "public data. Every record carries source provenance; the system "
            "flags contradictions for human review and never asserts intent."
        ),
    )

    for router in ALL_ROUTERS:
        app.include_router(router)

    @app.get("/", tags=["root"], summary="API root summary")
    def root() -> dict:
        """Lightweight landing payload pointing at docs and key endpoints."""
        return {
            "name": settings.app_name,
            "version": app.version,
            "environment": settings.environment,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
            "endpoints": {
                "politicians": "/api/v1/politicians",
                "votes": "/api/v1/votes",
                "statements": "/api/v1/statements",
            },
            "pilot": {
                "person_id": settings.pilot_person_id,
                "party_he": settings.pilot_party_he,
                "party_en": settings.pilot_party_en,
            },
        }

    # Reuse the same health logic at the root level (mirrors /health) so simple
    # uptime probes can hit either path.
    @app.get("/healthz", tags=["health"], summary="Health check (alias of /health)")
    def healthz(db: Annotated[Session, Depends(get_db)]) -> dict:
        return health_handler(db)

    logger.info("App ready: %d routers mounted", len(ALL_ROUTERS))
    return app


# Module-level ASGI app for uvicorn / gunicorn.
app = create_app()
