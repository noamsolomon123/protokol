"""Adjudicator: compare a structured claim to candidate statistics.

Pure logic — takes the claim and the matched statistics (any object exposing
`id`, `dimension_value`, `value`, `source_url`) and returns a `VerdictDraft`.
It NEVER writes to the DB and NEVER decides publication (that is the publish
gate's job). The confidence is an explicit, inspectable function — no model,
no magic — so a reviewer can reproduce every number by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knesset_osint.models.enums import VerdictOutcome
from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim


class _StatLike(Protocol):
    id: int
    dimension_value: str
    value: float
    source_url: str | None


@dataclass
class VerdictDraft:
    """The adjudicator's output (pre-publication)."""

    outcome: VerdictOutcome
    confidence: float
    numeric_gap: float | None
    primary_statistic_id: int | None
    statistic_ids: list[int]
    statistic_url: str | None
    rationale: str
    adjudicator_version: str


# A superlative ("lowest in the country") needs enough peers to be meaningful;
# below this we cap confidence proportionally.
MIN_SUPERLATIVE_COVERAGE = 10
# A VALUE claim within this relative tolerance is treated as consistent.
VALUE_CONSISTENT_REL = 0.05
# A VALUE claim beyond this relative gap is treated as inconsistent.
VALUE_INCONSISTENT_REL = 0.25


class Adjudicator:
    adjudicator_version: str = "rule-based-v0"

    def adjudicate(
        self, claim: StructuredClaim, statistics: list[_StatLike]
    ) -> VerdictDraft:
        if not statistics:
            return self._unverifiable("אין נתון רשמי תואם להכרעה.", [])

        ids = [s.id for s in statistics]
        if claim.assertion is ClaimAssertion.VALUE:
            return self._adjudicate_value(claim, statistics, ids)
        return self._adjudicate_superlative(claim, statistics, ids)

    # ------------------------------------------------------------- superlative
    def _adjudicate_superlative(
        self, claim: StructuredClaim, statistics: list[_StatLike], ids: list[int]
    ) -> VerdictDraft:
        ordered = sorted(statistics, key=lambda s: s.value)
        n = len(ordered)
        claimed = next(
            (s for s in ordered if s.dimension_value == claim.dimension_value), None
        )
        if claimed is None:
            return self._unverifiable(
                "הממד הנטען אינו קיים בקטלוג הנתונים הרשמי.", ids
            )

        is_min_claim = claim.assertion is ClaimAssertion.SUPERLATIVE_MIN
        extreme = ordered[0] if is_min_claim else ordered[-1]
        coverage = min(1.0, n / MIN_SUPERLATIVE_COVERAGE)

        if claimed.id == extreme.id:
            confidence = round(0.5 + 0.4 * coverage, 4)
            return VerdictDraft(
                outcome=VerdictOutcome.CONSISTENT,
                confidence=confidence,
                numeric_gap=0.0,
                primary_statistic_id=claimed.id,
                statistic_ids=ids,
                statistic_url=claimed.source_url,
                rationale=(
                    f"הטענה עקבית: {claim.dimension_value} הוא אכן הערך ה"
                    f"{'נמוך' if is_min_claim else 'גבוה'} ביותר מבין {n} ערכים."
                ),
                adjudicator_version=self.adjudicator_version,
            )

        # Distance of the claimed dimension from the asserted extreme, 0..1.
        idx = ordered.index(claimed)
        pos = idx / (n - 1) if n > 1 else 0.0
        distance = pos if is_min_claim else (1.0 - pos)
        confidence = round(min(0.97, distance * coverage), 4)
        gap = round(claimed.value - extreme.value, 4)
        return VerdictDraft(
            outcome=VerdictOutcome.INCONSISTENT,
            confidence=confidence,
            numeric_gap=gap,
            primary_statistic_id=claimed.id,
            statistic_ids=ids,
            statistic_url=claimed.source_url,
            rationale=(
                f"הטענה אינה תואמת נתונים רשמיים: {claim.dimension_value} אינו ה"
                f"{'נמוך' if is_min_claim else 'גבוה'} ביותר; ערכו {claimed.value} "
                f"לעומת הקיצון {extreme.value} (מתוך {n} ערכים)."
            ),
            adjudicator_version=self.adjudicator_version,
        )

    # ------------------------------------------------------------------ value
    def _adjudicate_value(
        self, claim: StructuredClaim, statistics: list[_StatLike], ids: list[int]
    ) -> VerdictDraft:
        match = next(
            (s for s in statistics if s.dimension_value == claim.dimension_value), None
        )
        if match is None or claim.claimed_value is None:
            return self._unverifiable("אין נתון מספרי תואם לאימות הערך הנטען.", ids)

        actual = match.value
        gap = round(claim.claimed_value - actual, 4)
        rel = abs(gap) / max(abs(actual), 1e-9)
        if rel <= VALUE_CONSISTENT_REL:
            outcome, confidence = VerdictOutcome.CONSISTENT, round(0.9, 4)
        elif rel >= VALUE_INCONSISTENT_REL:
            outcome, confidence = VerdictOutcome.INCONSISTENT, round(min(0.97, 0.6 + rel), 4)
        else:
            outcome, confidence = VerdictOutcome.UNVERIFIABLE, 0.5
        return VerdictDraft(
            outcome=outcome,
            confidence=confidence,
            numeric_gap=gap,
            primary_statistic_id=match.id,
            statistic_ids=ids,
            statistic_url=match.source_url,
            rationale=(
                f"הערך הנטען {claim.claimed_value} מול הנתון הרשמי {actual} "
                f"(פער {gap})."
            ),
            adjudicator_version=self.adjudicator_version,
        )

    # ------------------------------------------------------------------ helper
    def _unverifiable(self, rationale: str, ids: list[int]) -> VerdictDraft:
        return VerdictDraft(
            outcome=VerdictOutcome.UNVERIFIABLE,
            confidence=0.0,
            numeric_gap=None,
            primary_statistic_id=None,
            statistic_ids=ids,
            statistic_url=None,
            rationale=rationale,
            adjudicator_version=self.adjudicator_version,
        )
