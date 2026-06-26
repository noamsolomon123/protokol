"""Match a structured claim to the candidate official statistics it concerns.

For superlative claims ("lowest enlistment of any city") the adjudicator needs
the FULL set of same-metric, same-dimension_type rows to rank them, so the
matcher returns all of them — not just the claimed dimension. The concrete
matcher here is a simple exact metric + dimension_type filter; swap in a
fuzzier matcher later behind the same ABC without touching callers.
"""

from __future__ import annotations

import abc

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models.official_statistic import OfficialStatistic
from knesset_osint.verification.claims import StructuredClaim


class StatisticMatcher(abc.ABC):
    """Contract: given a claim, return candidate `OfficialStatistic` rows."""

    matcher_version: str = "abstract"

    @abc.abstractmethod
    def match(self, session: Session, claim: StructuredClaim) -> list[OfficialStatistic]:
        raise NotImplementedError


class DimensionStatisticMatcher(StatisticMatcher):
    """Exact match on `metric` + `dimension_type` (returns the whole peer set)."""

    matcher_version: str = "dimension-exact-v0"

    def match(self, session: Session, claim: StructuredClaim) -> list[OfficialStatistic]:
        stmt = (
            select(OfficialStatistic)
            .where(OfficialStatistic.metric == claim.metric)
            .where(OfficialStatistic.dimension_type == claim.dimension_type)
        )
        return list(session.scalars(stmt).all())
