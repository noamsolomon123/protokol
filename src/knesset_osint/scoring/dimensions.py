"""The scorecard dimensions.

Each dimension is computed from sourced rows already in the database. A dimension
declares:
* ``available`` — is the data source wired AND is there data for this politician?
* ``scorable``  — can it be mapped to a principled 0–100 score *right now*?
* ``raw``       — the underlying counts/ratios (the receipts), always shown.
* ``source_urls`` / ``source_note`` — provenance for the numbers.
* ``pending_reason`` — if not available/scorable, why (and what Phase 2 unlocks it).

To add a dimension: write a ``_dim_*`` function returning a DimensionScore and add
it to ``compute_dimensions``. To make a "pending" dimension live, wire its source
adapter + ingestion, then flip ``available``/``scorable`` and compute from the rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knesset_osint.models import BillSponsorship, Politician, Vote
from knesset_osint.models.enums import VoteStance


@dataclass
class DimensionScore:
    key: str
    label_he: str
    label_en: str
    available: bool
    scorable: bool
    score: float | None  # 0..100 or None
    raw: dict[str, Any]
    weight: float
    source_note: str
    method: str
    source_urls: list[str] = field(default_factory=list)
    pending_reason: str | None = None


def _dim_participation(session: Session, p: Politician, weight: float) -> DimensionScore:
    """% of votes actually cast (for/against/abstain) out of those eligible
    (excludes NA = unknown). Higher = more present for the job."""
    counts = dict(
        session.execute(
            select(Vote.stance, func.count())
            .where(Vote.politician_id == p.id)
            .group_by(Vote.stance)
        ).all()
    )
    cast = sum(counts.get(s, 0) for s in (VoteStance.FOR, VoteStance.AGAINST, VoteStance.ABSTAIN))
    absent = counts.get(VoteStance.ABSENT, 0)
    eligible = cast + absent
    score = round(cast / eligible * 100, 1) if eligible else None
    return DimensionScore(
        key="participation",
        label_he="השתתפות בהצבעות",
        label_en="Vote participation",
        available=eligible > 0,
        scorable=eligible > 0,
        score=score,
        raw={"cast": cast, "absent": absent, "eligible": eligible, "by_stance": {
            (s.value if hasattr(s, "value") else str(s)): c for s, c in counts.items()
        }},
        weight=weight,
        source_note="Knesset Votes.svc roll-call records",
        method="(for + against + abstain) / (for + against + abstain + absent) × 100",
        pending_reason=None if eligible > 0 else "no roll-call votes ingested yet",
    )


def _dim_legislative_activity(session: Session, p: Politician, weight: float) -> DimensionScore:
    """How much legislation the MK initiates/co-signs. Shown as raw counts:
    a fair 0–100 needs a peer baseline (all MKs), which arrives when we ingest the
    full Knesset (Phase 2 percentile), so it is INFORMATIONAL for now."""
    sponsored = session.scalar(
        select(func.count()).select_from(BillSponsorship).where(BillSponsorship.politician_id == p.id)
    ) or 0
    as_initiator = session.scalar(
        select(func.count())
        .select_from(BillSponsorship)
        .where(BillSponsorship.politician_id == p.id, BillSponsorship.is_initiator.is_(True))
    ) or 0
    return DimensionScore(
        key="legislative_activity",
        label_he="פעילות חקיקתית",
        label_en="Legislative activity",
        available=sponsored > 0,
        scorable=False,  # no objective 0–100 without peer comparison yet
        score=None,
        raw={"bills_sponsored": sponsored, "as_lead_initiator": as_initiator},
        weight=weight,
        source_note="Knesset ParliamentInfo KNS_BillInitiator",
        method="counts only; objective 0–100 needs all-MK percentile (Phase 2)",
        pending_reason=None
        if sponsored > 0
        else "no bill sponsorships ingested; scoring needs peer baseline (Phase 2)",
    )


def _dim_pending(key: str, label_he: str, label_en: str, weight: float, source: str, reason: str) -> DimensionScore:
    """A dimension whose data source is not wired yet (Phase 2). Shown honestly
    as 'awaiting source' — never guessed, never scored."""
    return DimensionScore(
        key=key,
        label_he=label_he,
        label_en=label_en,
        available=False,
        scorable=False,
        score=None,
        raw={},
        weight=weight,
        source_note=source,
        method="not computed — source not wired yet",
        pending_reason=reason,
    )


def compute_dimensions(session: Session, p: Politician, weights: dict[str, float]) -> list[DimensionScore]:
    """Compute every scorecard dimension for a politician (some 'pending')."""
    return [
        _dim_participation(session, p, weights.get("participation", 0.0)),
        _dim_legislative_activity(session, p, weights.get("legislative_activity", 0.0)),
        _dim_pending(
            "integrity", "יושרה והליכים משפטיים", "Integrity & legal proceedings",
            weights.get("integrity", 0.0),
            "Court rulings + State Comptroller reports",
            "Phase 2: wire court-rulings and State Comptroller source adapters.",
        ),
        _dim_pending(
            "promise_keeping", "עמידה בהבטחות", "Promise-keeping",
            weights.get("promise_keeping", 0.0),
            "Public statements ↔ voting record (RAG)",
            "Phase 2: ingest statements and run the contradiction (RAG) engine.",
        ),
        _dim_pending(
            "financial_conflict", "כספים וניגוד עניינים", "Finance & conflicts of interest",
            weights.get("financial_conflict", 0.0),
            "Budget Key + Corporations Authority + entity graph",
            "Phase 2: wire Budget Key / Corporations Authority and the Neo4j graph.",
        ),
    ]
