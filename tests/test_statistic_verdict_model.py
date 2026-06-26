"""StatisticVerdict defaults: unpublished + pending until the gate/human rules."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models import (
    OfficialStatistic,
    Politician,
    Statement,
    StatisticVerdict,
)
from knesset_osint.models.enums import (
    SourceType,
    StatementType,
    VerdictOutcome,
    VerdictReviewStatus,
)


def _politician() -> Politician:
    return Politician(
        knesset_person_id=965,
        first_name="בנימין",
        last_name="נתניהו",
        full_name="בנימין נתניהו",
        is_current=True,
        source_type=SourceType.KNESSET_ODATA,
        source_url="https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )


def test_verdict_defaults_to_unpublished_pending(db_session: Session) -> None:
    pol = _politician()
    stmt = Statement(
        politician=pol,
        claim="תל אביב עם שיעור הגיוס הנמוך בארץ.",
        statement_type=StatementType.INTERVIEW,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/interview/1",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    db_session.add_all([pol, stmt])
    db_session.flush()

    verdict = StatisticVerdict(
        statement_id=stmt.id,
        official_statistic_id=None,
        statistic_ids=[1, 2, 3],
        outcome=VerdictOutcome.INCONSISTENT,
        confidence=0.92,
        numeric_gap=14.0,
        statement_url=stmt.source_url,
        statistic_url="https://example.org/idf/report-2022",
        rationale="לבדיקה: הטענה אינה תואמת את הדירוג בנתונים.",
        adjudicator_version="test-0.0",
        # published / auto_published / review_status deliberately NOT set.
    )
    db_session.add(verdict)
    db_session.commit()

    loaded = db_session.execute(select(StatisticVerdict)).scalar_one()
    assert loaded.published is False
    assert loaded.auto_published is False
    assert loaded.review_status == VerdictReviewStatus.PENDING
    assert loaded.reviewer is None
    assert loaded.outcome == VerdictOutcome.INCONSISTENT
    assert loaded.statement_url == "https://example.org/interview/1"
    assert loaded.statistic_ids == [1, 2, 3]
