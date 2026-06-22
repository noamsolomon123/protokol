"""Accountability scoring layer.

Turns the sourced facts in the database into a *transparent scorecard* and an
*adjustable composite index* — never a black-box "good/bad" verdict.

Design rules (the objectivity guarantee):
* Each dimension is a ratio/count of sourced facts, with the raw numbers exposed.
* A dimension is only folded into the composite index if it is BOTH ``available``
  (the data source is wired and has data) AND ``scorable`` (it has a principled
  0–100 mapping right now). Everything else is shown as "awaiting source".
* The index reports its ``coverage`` (e.g. 1 of 5 dimensions) so a partial score
  is never mistaken for a full verdict. Weights are explicit and caller-adjustable.
"""

from knesset_osint.scoring.dimensions import DimensionScore, compute_dimensions
from knesset_osint.scoring.scorecard import (
    AccountabilityIndex,
    Scorecard,
    compute_scorecard,
)
from knesset_osint.scoring.weights import DEFAULT_WEIGHTS, normalize_weights

__all__ = [
    "DimensionScore",
    "compute_dimensions",
    "AccountabilityIndex",
    "Scorecard",
    "compute_scorecard",
    "DEFAULT_WEIGHTS",
    "normalize_weights",
]
