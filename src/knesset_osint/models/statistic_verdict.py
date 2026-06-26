"""Verdict: a structured claim checked against official statistics.

Like `Contradiction`, this is a *derived analysis* record (no ProvenanceMixin).
It stores BOTH source links (`statement_url` + `statistic_url`) so any verdict is
independently auditable, and it is born UNPUBLISHED and `review_status=pending`.
The only paths to `published=True` are (a) the confidence gate auto-approving a
high-confidence, non-transcription verdict, or (b) a human approving it. The
platform never silently makes a false-statement verdict public.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import TimestampMixin
from knesset_osint.models.enums import VerdictOutcome, VerdictReviewStatus


class StatisticVerdict(Base, TimestampMixin):
    __tablename__ = "statistic_verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"), index=True
    )
    # The single statistic the verdict primarily turned on (nullable for
    # UNVERIFIABLE), plus the full set considered (for auditability).
    official_statistic_id: Mapped[int | None] = mapped_column(
        ForeignKey("official_statistics.id", ondelete="SET NULL")
    )
    statistic_ids: Mapped[list | None] = mapped_column(JSON)

    outcome: Mapped[VerdictOutcome] = mapped_column(
        SAEnum(VerdictOutcome, native_enum=False, length=32)
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    numeric_gap: Mapped[float | None] = mapped_column(Float)

    # Both source links, always — the core of auditability.
    statement_url: Mapped[str | None] = mapped_column(String(1024))
    statistic_url: Mapped[str | None] = mapped_column(String(1024))

    rationale: Mapped[str | None] = mapped_column(Text)
    adjudicator_version: Mapped[str | None] = mapped_column(String(64))

    # Publication state — unpublished + pending until the gate or a human rules.
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_published: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[VerdictReviewStatus] = mapped_column(
        SAEnum(VerdictReviewStatus, native_enum=False, length=32),
        default=VerdictReviewStatus.PENDING,
    )
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    statement: Mapped["Statement"] = relationship()
