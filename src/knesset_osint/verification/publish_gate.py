"""PublishGate: the confidence-gated hybrid publication rule.

A verdict auto-publishes only when ALL hold:
  * outcome is CONSISTENT or INCONSISTENT (never UNVERIFIABLE),
  * confidence >= threshold,
  * the statement's source is NOT transcription-derived.

Everything else is queued for human review (`published=False`, `pending`).
Transcription-sourced claims NEVER auto-publish, regardless of confidence — a
transcription error can fabricate a quote, which is the worst-case defamation,
so a human must confirm the quote first.
"""

from __future__ import annotations

from dataclasses import dataclass

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from knesset_osint.verification.adjudication import VerdictDraft

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
# Source types whose statements come from speech-to-text and must be
# human-confirmed before any verdict goes public (extended in Plan 3).
DEFAULT_TRANSCRIPTION_SOURCES: frozenset[SourceType] = frozenset()


@dataclass
class PublishDecision:
    published: bool
    auto_published: bool
    review_status: VerdictReviewStatus


class PublishGate:
    def __init__(
        self,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        transcription_source_types: frozenset[SourceType] | set[SourceType] = DEFAULT_TRANSCRIPTION_SOURCES,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.transcription_source_types = frozenset(transcription_source_types)

    def decide(self, draft: VerdictDraft, source_type: SourceType) -> PublishDecision:
        decisive = draft.outcome in (
            VerdictOutcome.CONSISTENT,
            VerdictOutcome.INCONSISTENT,
        )
        confident = draft.confidence >= self.confidence_threshold
        is_transcription = source_type in self.transcription_source_types

        if decisive and confident and not is_transcription:
            return PublishDecision(
                published=True,
                auto_published=True,
                review_status=VerdictReviewStatus.APPROVED,
            )
        return PublishDecision(
            published=False,
            auto_published=False,
            review_status=VerdictReviewStatus.PENDING,
        )
