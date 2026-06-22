"""Read-models for statements and contradiction findings.

``StatementRead``     = a sourced public claim made by a politician.
``ContradictionRead`` = a *flagged* statement-vs-evidence mismatch. Note the
                        objectivity invariant baked into the shape: it carries
                        BOTH source links and a ``status`` that defaults to
                        ``needs_review``. The platform surfaces evidence; it
                        never machine-asserts that a politician lied.
"""

from __future__ import annotations

from datetime import date, datetime

from knesset_osint.models.enums import (
    ContradictionStatus,
    StatementType,
    VerificationStatus,
)
from knesset_osint.schemas.common import ORMModel, ProvenanceFields


class StatementRead(ProvenanceFields):
    """A public statement / claim.

    ``source_url`` is mandatory upstream (DB CHECK constraint) — an unsourced
    claim never enters the system. The vector ``embedding`` is intentionally
    omitted from the wire model (large, internal to the RAG layer).
    """

    id: int
    politician_id: int
    statement_date: date | None = None
    topic: str | None = None
    claim: str
    full_text: str | None = None
    statement_type: StatementType
    language: str
    verification_status: VerificationStatus


class ContradictionRead(ORMModel):
    """A flagged statement<->evidence candidate, fully auditable.

    Does NOT inherit ProvenanceFields: a contradiction is a *derived analysis*
    record, not raw source data. Instead it exposes both sides' deep links
    (``statement_url`` + ``evidence_url``) and stays ``needs_review`` until a
    human rules — the only path to a verdict.
    """

    id: int
    statement_id: int
    evidence_kind: str
    evidence_id: int | None = None
    statement_url: str | None = None
    evidence_url: str | None = None
    score: float | None = None
    status: ContradictionStatus
    rationale: str | None = None
    detector_version: str | None = None
    detected_at: datetime | None = None
    human_verdict: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


__all__ = ["StatementRead", "ContradictionRead"]
