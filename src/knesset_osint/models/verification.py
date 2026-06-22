"""Contradiction findings: statement vs. hard evidence (vote/action/bill).

This is a *derived analysis* record, not raw source data, so it does not use
ProvenanceMixin. Instead it stores BOTH sides' source links
(`statement_url` + `evidence_url`) so any flag is independently auditable, and a
`status` that stays NEEDS_REVIEW until a human rules. The platform surfaces
evidence; it never machine-asserts that a politician lied.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import TimestampMixin
from knesset_osint.models.enums import ContradictionStatus


class Contradiction(Base, TimestampMixin):
    __tablename__ = "contradictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"), index=True
    )

    # The evidence the statement is checked against.
    evidence_kind: Mapped[str] = mapped_column(String(32))  # "vote" | "action" | "bill" | "statement"
    evidence_id: Mapped[int | None] = mapped_column(Integer)

    # Both source links, always — the core of auditability.
    statement_url: Mapped[str | None] = mapped_column(String(1024))
    evidence_url: Mapped[str | None] = mapped_column(String(1024))

    score: Mapped[float | None] = mapped_column(Float)  # detector confidence [0..1]
    status: Mapped[ContradictionStatus] = mapped_column(
        SAEnum(ContradictionStatus, native_enum=False, length=32),
        default=ContradictionStatus.NEEDS_REVIEW,
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    detector_version: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Human review — the only path to a verdict.
    human_verdict: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    statement: Mapped["Statement"] = relationship(back_populates="contradictions")
