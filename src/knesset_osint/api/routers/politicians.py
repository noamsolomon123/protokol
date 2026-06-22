"""Politician endpoints: the core entity and its sub-resources.

Routes (prefix ``/api/v1/politicians``):
    GET  /                      list politicians (``q`` substring on full_name, paginated)
    GET  /{id}                  one politician with related-record counts (404 if missing)
    GET  /{id}/roles            paginated roles
    GET  /{id}/bills            paginated bill sponsorships (bill nested)
    GET  /{id}/votes            paginated votes (vote event nested)
    GET  /{id}/statements       paginated statements
    GET  /{id}/actions          paginated actions

``{id}`` is always our INTERNAL primary key (``Politician.id``), not the
ParliamentInfo ``KNS_Person.Id`` — keep clients on stable internal ids.

Scaling note: nothing here is pilot-specific. The same handlers serve 1 MK or
all 120; growth is purely a matter of ingesting more rows.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from knesset_osint.api.deps import Pagination, get_db
from knesset_osint.models import (
    Action,
    Bill,
    BillSponsorship,
    Politician,
    Role,
    Statement,
    Vote,
)
from knesset_osint.schemas.common import Page
from knesset_osint.schemas.politician import (
    ActionRead,
    BillSponsorshipRead,
    PoliticianDetail,
    PoliticianRead,
    RoleRead,
)
from knesset_osint.schemas.statement import StatementRead
from knesset_osint.schemas.vote import VoteRead

router = APIRouter(prefix="/api/v1/politicians", tags=["politicians"])


def _get_politician_or_404(db: Session, politician_id: int) -> Politician:
    """Load a politician by internal id or raise 404. Shared by sub-resources."""
    obj = db.get(Politician, politician_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Politician {politician_id} not found",
        )
    return obj


@router.get("", response_model=Page[PoliticianRead], summary="List politicians")
def list_politicians(
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
    q: Annotated[
        str | None,
        Query(description="Case-insensitive substring match on full_name."),
    ] = None,
) -> Page[PoliticianRead]:
    """List politicians, optionally filtered by a ``full_name`` substring."""
    conditions = []
    if q:
        # ilike for case-insensitivity; works on Postgres and SQLite alike.
        conditions.append(Politician.full_name.ilike(f"%{q}%"))

    total = db.scalar(
        select(func.count()).select_from(Politician).where(*conditions)
    ) or 0

    rows = db.scalars(
        select(Politician)
        .where(*conditions)
        .order_by(Politician.full_name)
        .limit(page.limit)
        .offset(page.offset)
    ).all()

    return Page[PoliticianRead](
        items=[PoliticianRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{politician_id}", response_model=PoliticianDetail, summary="Get a politician")
def get_politician(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> PoliticianDetail:
    """Return one politician plus counts of their related records (404 if missing)."""
    obj = _get_politician_or_404(db, politician_id)

    # Cheap COUNT(*) per relation — avoids loading collections just to size them.
    def _count(model: type, fk: object) -> int:
        return db.scalar(
            select(func.count()).select_from(model).where(fk == politician_id)
        ) or 0

    detail = PoliticianDetail.model_validate(obj)
    detail.role_count = _count(Role, Role.politician_id)
    detail.bill_count = _count(BillSponsorship, BillSponsorship.politician_id)
    detail.vote_count = _count(Vote, Vote.politician_id)
    detail.statement_count = _count(Statement, Statement.politician_id)
    detail.action_count = _count(Action, Action.politician_id)
    return detail


@router.get(
    "/{politician_id}/roles",
    response_model=Page[RoleRead],
    summary="List a politician's roles",
)
def list_roles(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[RoleRead]:
    """Paginated official positions held by the politician."""
    _get_politician_or_404(db, politician_id)

    total = db.scalar(
        select(func.count()).select_from(Role).where(Role.politician_id == politician_id)
    ) or 0
    rows = db.scalars(
        select(Role)
        .where(Role.politician_id == politician_id)
        .order_by(Role.start_date.desc().nullslast(), Role.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[RoleRead](
        items=[RoleRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{politician_id}/bills",
    response_model=Page[BillSponsorshipRead],
    summary="List a politician's bill sponsorships",
)
def list_bills(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[BillSponsorshipRead]:
    """Paginated bill sponsorships, with each bill nested inline."""
    _get_politician_or_404(db, politician_id)

    total = db.scalar(
        select(func.count())
        .select_from(BillSponsorship)
        .where(BillSponsorship.politician_id == politician_id)
    ) or 0
    rows = db.scalars(
        select(BillSponsorship)
        .where(BillSponsorship.politician_id == politician_id)
        # Eager-load the bill so the nested BillRead is populated in one query.
        .options(joinedload(BillSponsorship.bill))
        .order_by(BillSponsorship.ordinal.asc().nullslast(), BillSponsorship.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[BillSponsorshipRead](
        items=[BillSponsorshipRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{politician_id}/votes",
    response_model=Page[VoteRead],
    summary="List a politician's votes",
)
def list_votes(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[VoteRead]:
    """Paginated votes, each with the vote event (title + date) nested inline."""
    _get_politician_or_404(db, politician_id)

    total = db.scalar(
        select(func.count()).select_from(Vote).where(Vote.politician_id == politician_id)
    ) or 0
    rows = db.scalars(
        select(Vote)
        .where(Vote.politician_id == politician_id)
        # Eager-load the event so VoteRead.event / event_title / event_date fill.
        .options(joinedload(Vote.event))
        .order_by(Vote.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[VoteRead](
        items=[VoteRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{politician_id}/statements",
    response_model=Page[StatementRead],
    summary="List a politician's statements",
)
def list_statements(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[StatementRead]:
    """Paginated public statements made by the politician."""
    _get_politician_or_404(db, politician_id)

    total = db.scalar(
        select(func.count())
        .select_from(Statement)
        .where(Statement.politician_id == politician_id)
    ) or 0
    rows = db.scalars(
        select(Statement)
        .where(Statement.politician_id == politician_id)
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


@router.get(
    "/{politician_id}/actions",
    response_model=Page[ActionRead],
    summary="List a politician's actions",
)
def list_actions(
    politician_id: int,
    db: Annotated[Session, Depends(get_db)],
    page: Pagination,
) -> Page[ActionRead]:
    """Paginated concrete actions / achievements attributed to the politician."""
    _get_politician_or_404(db, politician_id)

    total = db.scalar(
        select(func.count()).select_from(Action).where(Action.politician_id == politician_id)
    ) or 0
    rows = db.scalars(
        select(Action)
        .where(Action.politician_id == politician_id)
        .order_by(Action.action_date.desc().nullslast(), Action.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page[ActionRead](
        items=[ActionRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
