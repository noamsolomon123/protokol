"""Embedding provider contract + a safe no-op implementation (Phase 1).

WHY THIS EXISTS
---------------
The contradiction layer (see ``contradiction.py``) ultimately needs to compare a
politician's *statement* against their *hard record* (votes / actions / bills) by
**meaning**, not just keywords. The standard way to do that is:

    text  ->  embedding vector  ->  cosine similarity  ->  nearest evidence

This module defines the *interface* for the "text -> vector" step so the rest of
the codebase can depend on a stable contract today, while the real model is
deferred to Phase 2. Nothing here imports a heavyweight ML library at module
top — keeping import time and the dependency surface light is intentional.

OBJECTIVITY INVARIANT
---------------------
An embedding provider must NEVER fabricate vectors. Returning fake/zero vectors
would silently corrupt similarity scores and could make the system "find"
contradictions that do not exist. The Phase 1 stub therefore *refuses* to
produce numbers (see :class:`NullEmbeddingProvider`).

PHASE 2: WIRING A REAL MODEL
----------------------------
To go live, add a concrete provider that implements :class:`EmbeddingProvider`.
A typical local-first choice is ``sentence-transformers`` with a multilingual
model (statements here are Hebrew by default — see ``Statement.language``):

    # pip install sentence-transformers   (add to project deps, NOT imported here)
    from sentence_transformers import SentenceTransformer

    class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
        # Lazy-import the model inside __init__ so importing this module stays cheap.
        def __init__(self, model_name: str = "intfloat/multilingual-e5-base") -> None:
            from sentence_transformers import SentenceTransformer  # local import
            self._model = SentenceTransformer(model_name)
            self._dim = self._model.get_sentence_embedding_dimension()

        @property
        def dimension(self) -> int:
            return self._dim

        def embed(self, texts: list[str]) -> list[list[float]]:
            if not texts:
                return []
            vectors = self._model.encode(
                texts, normalize_embeddings=True, convert_to_numpy=True
            )
            return [v.tolist() for v in vectors]

STORAGE / RETRIEVAL (pgvector)
------------------------------
``Statement.embedding`` is currently a portable JSON ``list[float]`` column so it
works on SQLite (tests) and Postgres alike. In Phase 2, for fast nearest-neighbor
search at scale, migrate that column to ``pgvector``:

    1. ``CREATE EXTENSION IF NOT EXISTS vector;`` (Postgres).
    2. Replace the JSON column with ``Vector(dim)`` from ``pgvector.sqlalchemy``
       in an Alembic migration (keep JSON for the SQLite test backend, or skip
       vector search there).
    3. Backfill: for each Statement, ``embed([statement.claim])`` and store.
    4. Retrieve with an ORDER BY on the ``<=>`` (cosine distance) operator and a
       suitable index (IVFFlat / HNSW) for sub-linear search.

The :class:`EmbeddingProvider` contract is what keeps all of the above swappable
without touching call sites.
"""

from __future__ import annotations

from typing import Protocol

from knesset_osint.core.logging import get_logger

logger = get_logger("verification.embeddings")


# NOTE: intentionally NOT @runtime_checkable. A runtime-checkable Protocol makes
# `isinstance(x, EmbeddingProvider)` probe members via hasattr(); since
# NullEmbeddingProvider.dimension is a property that *raises* (by design, to
# refuse fabricating a dimension), such an isinstance() check would propagate
# that error instead of returning a bool. Use static typing for conformance; do
# not rely on isinstance() against this Protocol.
class EmbeddingProvider(Protocol):
    """Structural contract for anything that turns text into vectors.

    A :class:`typing.Protocol` (not an ABC) so concrete implementations don't
    need to inherit from us — any object exposing a matching ``embed`` (and,
    optionally, ``dimension``) satisfies the type. This keeps third-party model
    wrappers easy to drop in.

    Contract:

    * ``embed(texts)`` returns one vector per input text, **in the same order**.
    * Every returned vector must have the same length (``dimension``).
    * ``embed([])`` returns ``[]`` (no inputs -> no vectors).
    * Implementations MUST NOT fabricate vectors for text they cannot embed —
      raise instead, so callers never silently compare against junk.
    """

    @property
    def dimension(self) -> int:
        """The fixed length of every vector this provider returns."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` -> list of equal-length float vectors (same order)."""
        ...


class NullEmbeddingProvider:
    """Phase 1 placeholder. Does not — and will not — invent vectors.

    Behaviour:

    * ``embed([])`` returns ``[]`` — the honest answer for "no inputs".
    * ``embed([...])`` with any real text raises :class:`NotImplementedError`
      with a clear message pointing to where to wire a real model.
    * ``dimension`` raises for the same reason: there is no model, so there is
      no dimension to report.

    This makes it safe to inject as a default everywhere: code paths that only
    ever pass empty lists keep working, while any path that actually needs an
    embedding fails loudly and early instead of producing garbage similarity
    scores. That failure mode is intentional — silently fabricating numbers
    would violate the platform's "never fabricate data" invariant.
    """

    #: Surfaced in errors and reused by detectors as a provenance/version tag.
    name: str = "null-embedding-provider"

    _PHASE2_MSG = (
        "NullEmbeddingProvider cannot produce embeddings. This is the Phase 1 "
        "structural stub. Wire a real model in Phase 2: implement "
        "EmbeddingProvider (e.g. a SentenceTransformerEmbeddingProvider using "
        "sentence-transformers + a multilingual model), then inject it where "
        "NullEmbeddingProvider is used. See the module docstring of "
        "knesset_osint.verification.embeddings for the full pgvector plan."
    )

    @property
    def dimension(self) -> int:
        """No model is wired, so there is no vector dimension to report."""
        raise NotImplementedError(self._PHASE2_MSG)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return ``[]`` for no inputs; otherwise refuse (do not fabricate)."""
        if not texts:
            # No inputs -> no vectors. Honest and harmless.
            return []
        logger.warning(
            "NullEmbeddingProvider.embed() called with %d text(s) but no model "
            "is wired (Phase 1 stub). Refusing to fabricate vectors.",
            len(texts),
        )
        raise NotImplementedError(self._PHASE2_MSG)
