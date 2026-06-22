"""Statement endpoints.

Routes (prefix ``/api/v1/statements``):
    GET /                       list statements (``q`` substring on claim/topic, paginated)
    GET /{id}                   one statement (404 if missing)
    GET /{id}/contradictions    paginated flagged statement<->evidence candidates

Objectivity note: a contradiction is a *flag* (status defaults to needs_review)
carrying both source links — never an assertion that the politician lied.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from knesset_osint.api.deps import Pagination, get_db
from knesset_osint.models import Contradiction, Statement
from knesset_osint.schemas.common import Page
from knesset_osint.schemas.statement import ContradictionRead, StatementRead

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


def _get_statement_or_404(db: Session, statement_id: int) -> Statement:
    obj = db.get(Statement, statement_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found",
        )
    return obj


@router.get("", response_model=Page[StatementRead], summary="List statements")
def list_statements(
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
    q: Annotated[
        str | None,
        Query(description="Case-insensitive substring match on claim or topic."),
    ] = None,
    politician_id: Annotated[
        int | None,
        Query(description="Optional filter: only statements by this politician."),
    ] = None,
) -> Page[StatementRead]:
    """List statements, optionally filtered by text and/or politician."""
    conditions = []
    if q:
        conditions.append(
            or_(Statement.claim.ilike(f"%{q}%"), Statement.topic.ilike(f"%{q}%"))
        )
    if politician_id is not None:
        conditions.append(Statement.politician_id == politician_id)

    total = db.scalar(
        select(func.count()).select_from(Statement).where(*conditions)
    ) or 0
    rows = db.scalars(
        select(Statement)
        .where(*conditions)
        .order_by(Statement.statement_date.desc().nullslast(), Statement.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[StatementRead](
        items=[StatementRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{statement_id}", response_model=StatementRead, summary="Get a statement")
def get_statement(
    statement_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> StatementRead:
    """Return one statement (404 if missing)."""
    return StatementRead.model_validate(_get_statement_or_404(db, statement_id))


@router.get(
    "/{statement_id}/contradictions",
    response_model=Page[ContradictionRead],
    summary="List a statement's flagged contradictions",
)
def list_contradictions(
    statement_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[ContradictionRead]:
    """Paginated contradiction candidates flagged for this statement.

    Each item carries both source links and a human-review status; the API never
    presents these as proven falsehoods.
    """
    _get_statement_or_404(db, statement_id)

    total = db.scalar(
        select(func.count())
        .select_from(Contradiction)
        .where(Contradiction.statement_id == statement_id)
    ) or 0
    rows = db.scalars(
        select(Contradiction)
        .where(Contradiction.statement_id == statement_id)
        .order_by(Contradiction.score.desc().nullslast(), Contradiction.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[ContradictionRead](
        items=[ContradictionRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
