"""Contradiction detection: interface + a safe non-LLM heuristic stub (Phase 1).

WHAT THIS LAYER DOES (AND DELIBERATELY DOES NOT DO)
---------------------------------------------------
Given a stored :class:`~knesset_osint.models.Statement` (a checkable public claim
by a politician), this layer pulls that politician's *hard record* — their
:class:`~knesset_osint.models.Vote` and :class:`~knesset_osint.models.Action`
rows — as candidate **evidence**, and FLAGS possible statement/record mismatches
as :class:`~knesset_osint.models.Contradiction` rows.

It NEVER asserts that a politician lied. Every flag:

* is created with ``status = ContradictionStatus.NEEDS_REVIEW`` (never CONFIRMED),
* leaves ``human_verdict`` as ``None`` (only a human sets a verdict),
* stores BOTH source links — ``statement_url`` and the evidence's ``source_url`` —
  so the flag is independently auditable from primary sources,
* records a plain-text ``rationale``, a ``detector_version`` tag, and
  ``detected_at`` so reviewers know how and when it was produced.

This is the platform's core objectivity guarantee in code: the machine surfaces
candidates with receipts; humans rule.

PHASE 2: THE REAL RAG CONTRADICTION FLOW
----------------------------------------
The :class:`HeuristicContradictionDetector` below is a structural stub: it flags
candidates by linking a statement to the politician's evidence without semantic
judgment. The production flow (Phase 2) keeps the SAME output contract (rows with
``status=needs_review`` + both links) but selects candidates intelligently:

    1. EMBED   — embed the statement claim and each piece of evidence with an
                 EmbeddingProvider (see ``verification/embeddings.py``).
    2. RETRIEVE — cosine-similarity search to fetch only the top-K most
                 topically-relevant evidence rows for the statement (pgvector
                 nearest-neighbor at scale), instead of all of them.
    3. COMPARE  — for each retrieved (statement, evidence) pair, ask an LLM (or a
                 trained NLI/stance model): does the evidence CONTRADICT,
                 SUPPORT, or is it NEUTRAL to the claim? Capture a confidence
                 ``score`` and a short ``rationale``.
    4. FLAG     — for likely contradictions, write a Contradiction row with
                 ``status=needs_review`` and both source links. STILL no verdict.
    5. REVIEW   — a human confirms/dismisses, which is the only path that sets
                 ``status`` to CONFIRMED/DISMISSED and fills ``human_verdict``.

EXTENDING TO MORE POLITICIANS AND SOURCES
-----------------------------------------
* More politicians: nothing here is pilot-specific. ``detect()`` works for any
  Statement; run it over every politician's statements (the relationships are
  already keyed by ``politician_id``).
* More evidence kinds: add a ``_candidate_*`` helper that yields
  ``(evidence_kind, evidence_id, evidence_url)`` tuples for the new source
  (e.g. bills, budget records, court rulings) and include it in
  ``_gather_evidence``. ``evidence_kind`` is a free-text tag on the model, so no
  schema change is needed to onboard a new source.
* Real detection: implement a new :class:`ContradictionDetector` subclass (e.g.
  ``RagContradictionDetector``) that takes an ``EmbeddingProvider`` + an LLM
  client and follows the 5-step flow above. Callers depend only on the
  ``ContradictionDetector`` ABC, so swapping detectors is a one-line change.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from knesset_osint.core.logging import get_logger
from knesset_osint.models.action import Action
from knesset_osint.models.statement import Statement
from knesset_osint.models.vote import Vote
from knesset_osint.models.verification import Contradiction
from knesset_osint.models.enums import ContradictionStatus

logger = get_logger("verification.contradiction")


class ContradictionDetector(abc.ABC):
    """Contract for any statement-vs-evidence contradiction detector.

    Implementations turn one :class:`Statement` into zero or more
    :class:`Contradiction` candidate rows. The contract every implementation
    MUST honour (this is the objectivity guarantee, not a style preference):

    * Returned rows have ``status == ContradictionStatus.NEEDS_REVIEW``.
    * ``human_verdict`` is ``None`` — the detector never rules.
    * Both ``statement_url`` and ``evidence_url`` are populated when the
      underlying records have a source URL, so flags are auditable.
    * ``detector_version`` and ``detected_at`` are set for traceability.

    Whether returned rows are added/committed to the session is the caller's
    decision; ``detect`` only constructs them (it may ``flush`` to obtain ids —
    see concrete implementations). This keeps transaction control with the
    pipeline that orchestrates detection.
    """

    #: Override per concrete detector; stored on every Contradiction it emits.
    detector_version: str = "abstract"

    @abc.abstractmethod
    def detect(self, session: Session, statement: Statement) -> list[Contradiction]:
        """Inspect ``statement`` and return candidate :class:`Contradiction` rows.

        Args:
            session: an open SQLAlchemy session used to read candidate evidence
                (votes/actions) for the statement's politician.
            statement: the persisted statement to check.

        Returns:
            A list of Contradiction rows, each ``status=needs_review`` with both
            source links populated. May be empty.
        """
        raise NotImplementedError


class HeuristicContradictionDetector(ContradictionDetector):
    """Non-LLM structural stub: links a statement to its politician's record.

    This Phase 1 implementation does NO semantic judgment. It exists to exercise
    the full contradiction *plumbing* end-to-end (read evidence -> build flagged
    rows with both source links -> hand back for human review) so the schema,
    the auditability invariants, and downstream consumers can be built and tested
    before the real RAG model lands.

    What it does, per statement:

    * loads the statement's politician and their Vote and Action rows,
    * for each piece of evidence that carries a ``source_url``, creates one
      ``needs_review`` Contradiction candidate that pairs the statement with that
      evidence and records both source links plus a rationale,
    * optionally caps how many candidates it emits (``max_candidates``) to keep
      the review queue sane while iterating.

    What it explicitly does NOT do (by contract):

    * never sets ``status=confirmed`` (always ``needs_review``),
    * never sets ``human_verdict`` (stays ``None``),
    * never claims the statement is false — the ``rationale`` only says a human
      should compare the claim against this record entry.

    Replace this with a real :class:`ContradictionDetector` per the Phase 2 RAG
    flow in this module's docstring. The output contract stays identical, so
    nothing downstream changes.
    """

    detector_version: str = "heuristic-stub-v0"

    def __init__(
        self,
        *,
        require_evidence_source_url: bool = True,
        max_candidates: int | None = None,
    ) -> None:
        """Configure the stub.

        Args:
            require_evidence_source_url: when ``True`` (default, recommended),
                skip evidence rows lacking a ``source_url`` — an un-sourced flag
                is not auditable, so we do not emit it.
            max_candidates: optional cap on the number of candidate rows emitted
                per statement (``None`` = no cap). Useful while iterating to
                avoid flooding the human review queue.
        """
        self.require_evidence_source_url = require_evidence_source_url
        self.max_candidates = max_candidates

    # ------------------------------------------------------------------ public

    def detect(self, session: Session, statement: Statement) -> list[Contradiction]:
        """Build ``needs_review`` candidates pairing ``statement`` with evidence.

        Reads the politician's votes/actions, builds one Contradiction per
        sourced evidence row, and flushes so each row gets an id. Does NOT
        commit — the caller owns the transaction.
        """
        detected_at = datetime.now(timezone.utc)
        candidates: list[Contradiction] = []

        for evidence_kind, evidence_id, evidence_url, label in self._gather_evidence(
            session, statement
        ):
            if self.require_evidence_source_url and not evidence_url:
                # No source URL -> not independently auditable -> do not flag.
                continue

            contradiction = Contradiction(
                statement_id=statement.id,
                evidence_kind=evidence_kind,
                evidence_id=evidence_id,
                # BOTH links, always — the core of auditability.
                statement_url=statement.source_url,
                evidence_url=evidence_url,
                # No semantic model in Phase 1: leave the confidence score NULL
                # rather than fabricate a number.
                score=None,
                # NON-NEGOTIABLE: candidates only. Never CONFIRMED here.
                status=ContradictionStatus.NEEDS_REVIEW,
                rationale=self._build_rationale(statement, evidence_kind, label),
                detector_version=self.detector_version,
                detected_at=detected_at,
                # human_verdict / reviewed_by / reviewed_at intentionally left
                # None — only a human sets a verdict.
            )
            candidates.append(contradiction)

            if self.max_candidates is not None and len(candidates) >= self.max_candidates:
                break

        if candidates:
            # Add + flush so each row receives a primary key (for logging/links),
            # but do NOT commit: the orchestrating pipeline controls the txn.
            session.add_all(candidates)
            session.flush()

        logger.info(
            "HeuristicContradictionDetector flagged %d needs_review candidate(s) "
            "for statement id=%s (politician_id=%s).",
            len(candidates),
            statement.id,
            statement.politician_id,
        )
        return candidates

    # ----------------------------------------------------------------- helpers

    def _gather_evidence(
        self, session: Session, statement: Statement
    ) -> list[tuple[str, int | None, str | None, str | None]]:
        """Collect candidate evidence as ``(kind, id, source_url, label)`` tuples.

        Phase 1 evidence = the politician's votes and actions. To onboard a new
        evidence source (bills, budget records, court rulings, ...), add another
        ``_candidate_*`` call here and yield the same 4-tuple shape; no schema
        change is required because ``Contradiction.evidence_kind`` is free text.
        """
        evidence: list[tuple[str, int | None, str | None, str | None]] = []
        evidence.extend(self._candidate_votes(session, statement.politician_id))
        evidence.extend(self._candidate_actions(session, statement.politician_id))
        return evidence

    def _candidate_votes(
        self, session: Session, politician_id: int
    ) -> list[tuple[str, int | None, str | None, str | None]]:
        """Yield this politician's votes as ``("vote", id, source_url, label)``.

        We link to the per-MK :class:`Vote` row (provenance lives there) and
        label it with the vote-event title + stance so the rationale is readable
        in the review queue.
        """
        rows: list[tuple[str, int | None, str | None, str | None]] = []
        votes = (
            session.query(Vote)
            .filter(Vote.politician_id == politician_id)
            .all()
        )
        for vote in votes:
            # The Vote row carries its own provenance (ProvenanceMixin).
            source_url = vote.source_url
            event = vote.event
            title = event.title if event is not None else None
            stance = vote.stance.value if vote.stance is not None else "na"
            label = f"vote ({stance}) on {title!r}" if title else f"vote ({stance})"
            rows.append(("vote", vote.id, source_url, label))
        return rows

    def _candidate_actions(
        self, session: Session, politician_id: int
    ) -> list[tuple[str, int | None, str | None, str | None]]:
        """Yield this politician's actions as ``("action", id, source_url, label)``."""
        rows: list[tuple[str, int | None, str | None, str | None]] = []
        actions = (
            session.query(Action)
            .filter(Action.politician_id == politician_id)
            .all()
        )
        for action in actions:
            label = action.title or (
                action.action_type.value if action.action_type is not None else "action"
            )
            rows.append(("action", action.id, action.source_url, label))
        return rows

    def _build_rationale(
        self, statement: Statement, evidence_kind: str, label: str | None
    ) -> str:
        """Compose a neutral, review-oriented rationale string.

        The wording is deliberately non-accusatory: it asks a human to COMPARE,
        and never asserts the statement is false. Carries the detector version
        so reviewers know it came from the Phase 1 structural stub (no semantic
        judgment), not a real RAG comparison.
        """
        claim = (statement.claim or "").strip()
        claim_preview = (claim[:200] + "...") if len(claim) > 200 else claim
        evidence_label = label or evidence_kind
        return (
            f"[{self.detector_version}] Candidate for human review (NOT a verdict). "
            f"This {evidence_kind} record ({evidence_label}) is part of the "
            f"politician's voting/action history and may be relevant to the claim: "
            f'"{claim_preview}". A reviewer should compare the claim against this '
            f"record using both linked sources. No contradiction is asserted; this "
            f"flag was produced by a non-LLM structural stub pending the Phase 2 "
            f"RAG comparison."
        )
