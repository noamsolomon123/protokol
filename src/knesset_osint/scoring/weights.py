"""Default index weights + renormalization.

Weights are deliberately explicit and overridable: the composite index is a
*lens chosen by whoever sets the weights*, not an objective truth. The UI exposes
these as sliders. When only some dimensions are available, weights are
renormalized over the available subset so the index stays on a 0–100 scale.
"""

from __future__ import annotations

# Sum is 1.0. Integrity / promise-keeping are weighted highest because that is a
# common civic priority — but this is a value choice, surfaced to the user, not a
# fact. Change freely.
DEFAULT_WEIGHTS: dict[str, float] = {
    "participation": 0.15,
    "legislative_activity": 0.15,
    "integrity": 0.30,
    "promise_keeping": 0.20,
    "financial_conflict": 0.20,
}


def normalize_weights(keys: list[str], weights: dict[str, float] | None = None) -> dict[str, float]:
    """Return weights for ``keys`` renormalized to sum to 1.0.

    If the requested keys have zero total weight (or none given), fall back to an
    equal split so the index is still well-defined.
    """
    w = weights or DEFAULT_WEIGHTS
    subset = {k: float(w.get(k, 0.0)) for k in keys}
    total = sum(subset.values())
    if total <= 0:
        if not keys:
            return {}
        equal = 1.0 / len(keys)
        return {k: equal for k in keys}
    return {k: v / total for k, v in subset.items()}
