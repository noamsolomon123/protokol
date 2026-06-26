"""Tests for the verdict enums and the official-statistics catalog model."""

from __future__ import annotations

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)


def test_verdict_outcome_values() -> None:
    assert VerdictOutcome.CONSISTENT.value == "consistent"
    assert VerdictOutcome.INCONSISTENT.value == "inconsistent"
    assert VerdictOutcome.UNVERIFIABLE.value == "unverifiable"


def test_verdict_review_status_values() -> None:
    assert VerdictReviewStatus.PENDING.value == "pending"
    assert VerdictReviewStatus.APPROVED.value == "approved"
    assert VerdictReviewStatus.REJECTED.value == "rejected"


def test_new_official_source_types() -> None:
    assert SourceType.CBS.value == "cbs"
    assert SourceType.IDF_SPOKESPERSON.value == "idf_spokesperson"


from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models import OfficialStatistic


def test_official_statistic_round_trips(db_session: Session) -> None:
    stat = OfficialStatistic(
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value="עיר-א",
        value=72.5,
        unit="percent",
        period="2022",
        notes="נתון סינתטי לבדיקה בלבד",
        source_type=SourceType.IDF_SPOKESPERSON,
        source_name=SourceType.IDF_SPOKESPERSON.value,
        source_url="https://example.org/idf/report-2022",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    db_session.add(stat)
    db_session.commit()

    loaded = db_session.execute(select(OfficialStatistic)).scalar_one()
    assert loaded.metric == "idf_enlistment_rate"
    assert loaded.dimension_value == "עיר-א"
    assert loaded.value == 72.5
    assert loaded.source_url == "https://example.org/idf/report-2022"
    assert loaded.created_at is not None
