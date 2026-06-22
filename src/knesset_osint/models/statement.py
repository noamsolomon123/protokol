"""Public statements / claims made by a politician.

A Statement is the raw material the RAG layer cross-references against the
voting record and actions to surface contradictions. `source_url` is mandatory
(CHECK constraint): an unsourced claim has no place in an objective system.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum as SAEnum,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin
from knesset_osint.models.enums import StatementType, VerificationStatus


class Statement(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint("source_url IS NOT NULL", name="ck_statement_requires_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )

    statement_date: Mapped[date | None] = mapped_column(Date, index=True)
    topic: Mapped[str | None] = mapped_column(String(512), index=True)
    claim: Mapped[str] = mapped_column(Text)  # the specific, checkable assertion
    full_text: Mapped[str | None] = mapped_column(Text)
    statement_type: Mapped[StatementType] = mapped_column(
        SAEnum(StatementType, native_enum=False, length=32), default=StatementType.OTHER
    )
    language: Mapped[str] = mapped_column(String(8), default="he")
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, native_enum=False, length=32),
        default=VerificationStatus.UNVERIFIED,
    )

    # RAG embedding placeholder. Kept as JSON for portability; swap to pgvector
    # (Phase 2) without touching callers — see verification/embeddings.py.
    embedding: Mapped[list | None] = mapped_column(JSON)

    politician: Mapped["Politician"] = relationship(back_populates="statements")
    contradictions: Mapped[list["Contradiction"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )
