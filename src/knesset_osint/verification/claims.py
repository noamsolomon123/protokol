"""The input contract for verification: a single structured factual claim.

Plan 1 consumes `StructuredClaim` objects directly (constructed in tests / by a
seed script). Plan 2's LLM extractor will produce them from raw `Statement`
text. Keeping this a plain dataclass means the matcher/adjudicator/gate are
fully deterministic and testable with no LLM and no DB-write coupling.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from knesset_osint.models.enums import SourceType


class ClaimAssertion(str, enum.Enum):
    """What the claim asserts about the metric for its dimension."""

    SUPERLATIVE_MIN = "superlative_min"   # "the lowest ... in the country"
    SUPERLATIVE_MAX = "superlative_max"   # "the highest ..."
    VALUE = "value"                       # "the rate is X%"


@dataclass
class StructuredClaim:
    """One checkable claim, normalised for adjudication.

    Attributes:
        politician_id: FK to the politician who made the claim.
        statement_id: FK to the source `Statement` (None when verifying ad hoc).
        metric: e.g. "idf_enlistment_rate".
        dimension_type: breakdown axis, e.g. "city" or "sector".
        dimension_value: the specific dimension the claim is about, e.g. "תל אביב".
        assertion: the kind of assertion (superlative / value).
        claimed_value: numeric value asserted (only for assertion=VALUE).
        source_type: provenance of the statement (drives the publish gate).
        source_url: link to the statement source.
        exact_quote: the verbatim quote, for display and auditability.
    """

    politician_id: int
    statement_id: int | None
    metric: str
    dimension_type: str
    dimension_value: str | None
    assertion: ClaimAssertion
    claimed_value: float | None
    source_type: SourceType
    source_url: str | None
    exact_quote: str | None
