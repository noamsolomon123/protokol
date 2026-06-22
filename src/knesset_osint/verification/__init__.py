"""Verification layer: embeddings + contradiction detection (STRUCTURE only).

This package owns the platform's fact-checking machinery. It is deliberately
shipped as *interfaces + a safe, non-LLM stub* so the rest of the system can
wire against stable contracts while the real RAG model lands in Phase 2.

Two responsibilities live here:

* ``embeddings`` — turn text into vectors so statements and evidence can be
  compared by meaning (cosine similarity). Phase 1 ships only the
  :class:`~knesset_osint.verification.embeddings.EmbeddingProvider` contract and
  a :class:`~knesset_osint.verification.embeddings.NullEmbeddingProvider` that
  refuses to fabricate vectors.
* ``contradiction`` — given a stored :class:`~knesset_osint.models.Statement`,
  pull the politician's hard record (votes/actions) as candidate evidence and
  *flag* potential mismatches as
  :class:`~knesset_osint.models.Contradiction` rows with
  ``status=needs_review``. It never asserts a verdict.

Objectivity invariant honoured throughout: the layer FLAGS candidates with BOTH
source links and leaves the verdict to a human. It never machine-asserts that a
politician lied. See module docstrings for the Phase 2 plan and how to extend
detection to more politicians and sources.
"""

from __future__ import annotations

from knesset_osint.verification.contradiction import (
    ContradictionDetector,
    HeuristicContradictionDetector,
)
from knesset_osint.verification.embeddings import (
    EmbeddingProvider,
    NullEmbeddingProvider,
)

__all__ = [
    "EmbeddingProvider",
    "NullEmbeddingProvider",
    "ContradictionDetector",
    "HeuristicContradictionDetector",
]
