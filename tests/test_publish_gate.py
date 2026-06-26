"""PublishGate: who gets auto-published vs. queued for human review."""

from __future__ import annotations

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from knesset_osint.verification.adjudication import VerdictDraft
from knesset_osint.verification.publish_gate import PublishGate


def _draft(outcome=VerdictOutcome.INCONSISTENT, confidence=0.95) -> VerdictDraft:
    return VerdictDraft(
        outcome=outcome,
        confidence=confidence,
        numeric_gap=10.0,
        primary_statistic_id=1,
        statistic_ids=[1, 2],
        statistic_url="https://example.org/s",
        rationale="...",
        adjudicator_version="rule-based-v0",
    )


def test_high_confidence_knesset_auto_publishes() -> None:
    d = PublishGate().decide(_draft(confidence=0.95), SourceType.KNESSET_ODATA)
    assert d.published is True
    assert d.auto_published is True
    assert d.review_status is VerdictReviewStatus.APPROVED


def test_low_confidence_queues_for_review() -> None:
    d = PublishGate().decide(_draft(confidence=0.6), SourceType.KNESSET_ODATA)
    assert d.published is False
    assert d.auto_published is False
    assert d.review_status is VerdictReviewStatus.PENDING


def test_transcription_source_never_auto_publishes_even_at_high_confidence() -> None:
    # MANUAL here stands for an interview/transcription-derived statement.
    d = PublishGate(transcription_source_types={SourceType.MANUAL}).decide(
        _draft(confidence=0.99), SourceType.MANUAL
    )
    assert d.published is False
    assert d.auto_published is False
    assert d.review_status is VerdictReviewStatus.PENDING


def test_unverifiable_never_auto_publishes() -> None:
    d = PublishGate().decide(
        _draft(outcome=VerdictOutcome.UNVERIFIABLE, confidence=0.0),
        SourceType.KNESSET_ODATA,
    )
    assert d.published is False
    assert d.review_status is VerdictReviewStatus.PENDING
