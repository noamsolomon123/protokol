"""FastAPI routers, aggregated for the app factory.

Each module owns one resource group. ``create_app`` includes every router in
``ALL_ROUTERS``; to add a new resource, create ``routers/<name>.py`` exposing a
module-level ``router`` and append it here.
"""

from __future__ import annotations

from knesset_osint.api.routers import (
    health,
    politicians,
    statements,
    votes,
)

# Order is cosmetic (affects OpenAPI tag ordering only).
ALL_ROUTERS = [
    health.router,
    politicians.router,
    votes.router,
    statements.router,
]

__all__ = ["ALL_ROUTERS", "health", "politicians", "votes", "statements"]
