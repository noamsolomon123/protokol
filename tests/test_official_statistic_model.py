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
