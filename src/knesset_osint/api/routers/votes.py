"""Vote endpoints.

Routes (prefix ``/api/v1/votes``):
    GET /{id}   one Vote (per-MK stance) with its VoteEvent nested (404 if missing)

``{id}`` is the internal ``Vote.id``. The response surfaces the politician's
``stance`` plus the full event (what was voted on, when, outcome) and the
``source_url`` provenance on both sides.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from knesset_osint.api.deps import get_db
from knesset_osint.models import Vote
from knesset_osint.schemas.vote import VoteRead

router = APIRouter(prefix="/api/v1/votes", tags=["votes"])


@router.get("/{vote_id}", response_model=VoteRead, summary="Get a vote with its event")
def get_vote(
    vote_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> VoteRead:
    """Return one per-MK vote and its event (404 if missing)."""
    vote = db.scalar(
        select(Vote).where(Vote.id == vote_id).options(joinedload(Vote.event))
    )
    if vote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vote {vote_id} not found",
        )
    return VoteRead.model_validate(vote)
