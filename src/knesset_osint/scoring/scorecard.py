"""Assemble dimensions into a scorecard + a coverage-aware composite index."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from knesset_osint.models import Politician
from knesset_osint.scoring.dimensions import DimensionScore, compute_dimensions
from knesset_osint.scoring.weights import DEFAULT_WEIGHTS, normalize_weights

DISCLAIMER = (
    "מדד זה מבוסס אך ורק על נתונים ציבוריים רשמיים ומקושר למקור לכל נתון. "
    "זהו כלי תצוגה אובייקטיבי — לא חוות דעת. המדד משוקלל לפי הקריטריונים שתבחר/י, "
    "ואינו קובע אם אדם 'טוב' או 'רע'. שיפוט נתון לקורא."
)
DISCLAIMER_EN = (
    "This index is built only from official public data, with a source link for "
    "every figure. It is an objective display tool, not an opinion. It is weighted "
    "by the criteria you choose and never labels a person 'good' or 'bad' — judgment "
    "is left to the reader."
)


@dataclass
class AccountabilityIndex:
    value: float | None          # 0..100 over the AVAILABLE+SCORABLE subset, or None
    coverage_scored: int         # how many dimensions fed the index
    coverage_total: int          # total dimensions defined
    label: str                   # "preliminary" | "partial" | "full"
    included: list[str]          # dimension keys that fed the index
    weights_used: dict[str, float]  # renormalized weights actually applied


@dataclass
class Scorecard:
    politician_id: int
    dimensions: list[DimensionScore]
    index: AccountabilityIndex
    disclaimer_he: str = DISCLAIMER
    disclaimer_en: str = DISCLAIMER_EN
    notes: list[str] = field(default_factory=list)


def compute_scorecard(
    session: Session,
    politician: Politician,
    weights: dict[str, float] | None = None,
) -> Scorecard:
    """Build the full scorecard + index. ``weights`` overrides the defaults."""
    w = weights or DEFAULT_WEIGHTS
    dims = compute_dimensions(session, politician, w)

    scored = [d for d in dims if d.available and d.scorable and d.score is not None]
    keys = [d.key for d in scored]
    applied = normalize_weights(keys, w)

    value: float | None
    if scored:
        value = round(sum(d.score * applied[d.key] for d in scored), 1)  # type: ignore[arg-type]
    else:
        value = None

    total = len(dims)
    n = len(scored)
    label = "full" if n == total else ("partial" if n > 1 else "preliminary")

    notes = []
    if n < total:
        notes.append(
            f"Index reflects {n} of {total} dimensions; the rest await Phase 2 data sources."
        )

    index = AccountabilityIndex(
        value=value,
        coverage_scored=n,
        coverage_total=total,
        label=label,
        included=keys,
        weights_used=applied,
    )
    return Scorecard(politician_id=politician.id, dimensions=dims, index=index, notes=notes)
