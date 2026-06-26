"""Orchestrate one claim through match -> adjudicate -> gate -> persist.

Builds a `StatisticVerdict` row (flushed for its id) but does NOT commit — the
caller owns the transaction, matching the convention in
`verification/contradiction.py`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from knesset_osint.core.logging import get_logger
from knesset_osint.models.enums import SourceType
from knesset_osint.models.statistic_verdict import StatisticVerdict
from knesset_osint.verification.adjudication import Adjudicator
from knesset_osint.verification.claims import StructuredClaim
from knesset_osint.verification.matching import (
    DimensionStatisticMatcher,
    StatisticMatcher,
)
from knesset_osint.verification.publish_gate import PublishGate

logger = get_logger("verification.verify")


def verify_statement(
    session: Session,
    claim: StructuredClaim,
    *,
    matcher: StatisticMatcher | None = None,
    adjudicator: Adjudicator | None = None,
    gate: PublishGate | None = None,
    transcription_source_types: set[SourceType] | None = None,
) -> StatisticVerdict:
    """Verify one structured claim and persist (flush) the resulting verdict."""
    matcher = matcher or DimensionStatisticMatcher()
    adjudicator = adjudicator or Adjudicator()
    if gate is None:
        gate = PublishGate(
            transcription_source_types=frozenset(transcription_source_types or set())
        )

    statistics = matcher.match(session, claim)
    draft = adjudicator.adjudicate(claim, statistics)
    decision = gate.decide(draft, claim.source_type)

    verdict = StatisticVerdict(
        statement_id=claim.statement_id,
        official_statistic_id=draft.primary_statistic_id,
        statistic_ids=draft.statistic_ids,
        outcome=draft.outcome,
        confidence=draft.confidence,
        numeric_gap=draft.numeric_gap,
        statement_url=claim.source_url,
        statistic_url=draft.statistic_url,
        rationale=draft.rationale,
        adjudicator_version=draft.adjudicator_version,
        published=decision.published,
        auto_published=decision.auto_published,
        review_status=decision.review_status,
    )
    session.add(verdict)
    session.flush()
    logger.info(
        "Verdict id=%s outcome=%s confidence=%.3f published=%s (statement_id=%s)",
        verdict.id,
        verdict.outcome.value,
        verdict.confidence,
        verdict.published,
        verdict.statement_id,
    )
    return verdict
