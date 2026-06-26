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
