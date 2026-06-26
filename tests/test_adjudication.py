"""Adjudicator: turns (claim, statistics) into a VerdictDraft. Pure, no DB."""

from __future__ import annotations

from dataclasses import dataclass

from knesset_osint.models.enums import SourceType, VerdictOutcome
from knesset_osint.verification.adjudication import Adjudicator, VerdictDraft
from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim


@dataclass
class FakeStat:
    """A stand-in for OfficialStatistic (adjudicator only needs these fields)."""

    id: int
    dimension_value: str
    value: float
    source_url: str | None = "https://example.org/s"


def _claim(assertion, dimension_value, claimed_value=None) -> StructuredClaim:
    return StructuredClaim(
        politician_id=1,
        statement_id=None,
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value=dimension_value,
        assertion=assertion,
        claimed_value=claimed_value,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/i/1",
        exact_quote="...",
    )


def _city_stats() -> list[FakeStat]:
    # 12 synthetic cities; "תל אביב" is near the TOP (rank 11 of 12 ascending),
    # so a "lowest in the country" claim about it is clearly false.
    rows = [FakeStat(id=i, dimension_value=f"עיר-{i}", value=float(i * 5)) for i in range(1, 12)]
    rows.append(FakeStat(id=99, dimension_value="תל אביב", value=58.0))
    return rows


def test_superlative_min_false_is_inconsistent_high_confidence() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "תל אביב"), _city_stats()
    )
    assert draft.outcome is VerdictOutcome.INCONSISTENT
    assert draft.confidence >= 0.85
    assert draft.primary_statistic_id == 99
    assert draft.numeric_gap is not None and draft.numeric_gap > 0


def test_superlative_min_true_is_consistent() -> None:
    stats = _city_stats()
    # Make "עיר-1" (value 5.0) the claimed dimension — it IS the minimum.
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "עיר-1"), stats
    )
    assert draft.outcome is VerdictOutcome.CONSISTENT


def test_value_claim_far_off_is_inconsistent() -> None:
    stats = [FakeStat(id=5, dimension_value="עיר-א", value=70.0)]
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.VALUE, "עיר-א", claimed_value=20.0), stats
    )
    assert draft.outcome is VerdictOutcome.INCONSISTENT
    assert draft.numeric_gap == -50.0


def test_no_stats_is_unverifiable_zero_confidence() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "תל אביב"), []
    )
    assert draft.outcome is VerdictOutcome.UNVERIFIABLE
    assert draft.confidence == 0.0


def test_unknown_dimension_is_unverifiable() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "עיר-לא-קיימת"), _city_stats()
    )
    assert draft.outcome is VerdictOutcome.UNVERIFIABLE
