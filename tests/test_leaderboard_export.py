"""Leaderboard aggregation: counts PUBLISHED inconsistent verdicts per politician."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from knesset_osint.models import Politician, Statement, StatisticVerdict
from knesset_osint.models.enums import (
    SourceType,
    StatementType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from scripts.export_leaderboard import build_leaderboard


def _pol(session: Session, pid: int, name: str) -> Politician:
    p = Politician(
        knesset_person_id=pid,
        full_name=name,
        is_current=True,
        source_type=SourceType.KNESSET_ODATA,
        source_url=f"https://knesset.gov.il/p/{pid}",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


def _verdict(session: Session, pol: Politician, *, outcome, published) -> None:
    stmt = Statement(
        politician_id=pol.id,
        claim="טענה לבדיקה",
        statement_type=StatementType.PLENUM,
        source_type=SourceType.KNESSET_ODATA,
        source_url="https://knesset.gov.il/t/1",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    session.add(stmt)
    session.flush()
    session.add(
        StatisticVerdict(
            statement_id=stmt.id,
            outcome=outcome,
            confidence=0.9,
            statement_url=stmt.source_url,
            statistic_url="https://example.org/s",
            published=published,
            review_status=(
                VerdictReviewStatus.APPROVED if published else VerdictReviewStatus.PENDING
            ),
        )
    )
    session.flush()


def test_leaderboard_counts_only_published_inconsistent(db_session: Session) -> None:
    a = _pol(db_session, 1, "פוליטיקאי א")
    b = _pol(db_session, 2, "פוליטיקאי ב")
    # a: 2 published inconsistent + 1 unpublished inconsistent (must not count)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=True)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=True)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=False)
    # a: 1 published CONSISTENT (must not count toward contradictions)
    _verdict(db_session, a, outcome=VerdictOutcome.CONSISTENT, published=True)
    # b: 1 published inconsistent
    _verdict(db_session, b, outcome=VerdictOutcome.INCONSISTENT, published=True)
    db_session.commit()

    board = build_leaderboard(db_session)

    assert [r["full_name"] for r in board] == ["פוליטיקאי א", "פוליטיקאי ב"]  # sorted desc
    assert board[0]["contradicted_count"] == 2
    assert board[1]["contradicted_count"] == 1
