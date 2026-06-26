"""Tests for the structured-claim contract and the statistic matcher."""

from __future__ import annotations

from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim
from knesset_osint.models.enums import SourceType


def _claim(**over) -> StructuredClaim:
    base = dict(
        politician_id=1,
        statement_id=None,
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value="תל אביב",
        assertion=ClaimAssertion.SUPERLATIVE_MIN,
        claimed_value=None,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/interview/1",
        exact_quote="לתל אביב שיעור הגיוס הנמוך בארץ",
    )
    base.update(over)
    return StructuredClaim(**base)


def test_structured_claim_holds_fields() -> None:
    c = _claim()
    assert c.metric == "idf_enlistment_rate"
    assert c.assertion is ClaimAssertion.SUPERLATIVE_MIN
    assert c.dimension_value == "תל אביב"
    assert c.source_type is SourceType.MANUAL


from datetime import datetime, timezone

from sqlalchemy.orm import Session

from knesset_osint.models import OfficialStatistic
from knesset_osint.verification.matching import DimensionStatisticMatcher


def _stat(dim_value: str, value: float) -> OfficialStatistic:
    return OfficialStatistic(
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value=dim_value,
        value=value,
        unit="percent",
        period="2022",
        source_type=SourceType.IDF_SPOKESPERSON,
        source_url=f"https://example.org/idf/{dim_value}",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )


def test_matcher_returns_same_metric_and_dimension_type(db_session: Session) -> None:
    db_session.add_all([_stat("עיר-א", 50.0), _stat("עיר-ב", 70.0)])
    # A different metric that must NOT be matched:
    other = _stat("עיר-א", 1.0)
    other.metric = "crime_rate"
    db_session.add(other)
    db_session.commit()

    matcher = DimensionStatisticMatcher()
    matches = matcher.match(db_session, _claim(dimension_value="עיר-א"))

    metrics = {m.metric for m in matches}
    assert metrics == {"idf_enlistment_rate"}
    assert len(matches) == 2  # both cities of the same metric+dimension_type


def test_matcher_empty_when_no_metric(db_session: Session) -> None:
    matcher = DimensionStatisticMatcher()
    matches = matcher.match(db_session, _claim(metric="unknown_metric"))
    assert matches == []
