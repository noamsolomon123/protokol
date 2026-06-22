"""Reusable FastAPI dependencies.

* ``get_db`` is re-exported from :mod:`knesset_osint.db.session` so routers
  import their DB dependency from one place (``from ...api.deps import get_db``).
* ``PaginationParams`` + ``pagination`` provide a validated ``limit``/``offset``
  window shared by every list endpoint (limit <= 200, default 50; offset >= 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

# Re-export the canonical DB dependency. Routers should import it from here.
from knesset_osint.db.session import get_db  # noqa: F401  (re-exported on purpose)

__all__ = ["get_db", "PaginationParams", "pagination", "Pagination"]

# Pagination bounds. Centralized so the whole API stays consistent and a single
# change scales the limits everywhere (e.g. when serving all 120 MKs).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(slots=True)
class PaginationParams:
    """A validated pagination window (a page of ``limit`` rows from ``offset``)."""

    limit: int
    offset: int


def pagination(
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIMIT, description=f"Max rows to return (<= {MAX_LIMIT})."),
    ] = DEFAULT_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of rows to skip."),
    ] = 0,
) -> PaginationParams:
    """FastAPI dependency producing validated pagination params.

    FastAPI enforces the bounds (``ge``/``le``) and returns a 422 on violation,
    so handlers can trust the values without re-checking them.
    """
    return PaginationParams(limit=limit, offset=offset)


# Convenience annotated alias so routers can write ``page: Pagination``.
Pagination = Annotated[PaginationParams, Depends(pagination)]
