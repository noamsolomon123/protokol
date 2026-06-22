"""Voting records.

`VoteEvent` = the thing voted on (the "law"/motion, its date, the outcome).
`Vote`      = how one politician voted on one event (the "stance").

This split is what lets the spec's `Vote (law, date, stance)` scale to 120 MKs:
one event row, many per-MK stance rows, no duplication.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin
from knesset_osint.models.enums import VoteResult, VoteStance


class VoteEvent(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "vote_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    knesset_vote_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(Text)  # subject / law voted on
    vote_date: Mapped[date | None] = mapped_column(Date, index=True)
    knesset_num: Mapped[int | None] = mapped_column(Integer, index=True)
    session_num: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[VoteResult] = mapped_column(
        SAEnum(VoteResult, native_enum=False, length=32), default=VoteResult.UNKNOWN
    )
    total_for: Mapped[int | None] = mapped_column(Integer)
    total_against: Mapped[int | None] = mapped_column(Integer)
    total_abstain: Mapped[int | None] = mapped_column(Integer)

    votes: Mapped[list["Vote"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class Vote(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("politician_id", "vote_event_id", name="uq_vote_politician_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    vote_event_id: Mapped[int] = mapped_column(
        ForeignKey("vote_events.id", ondelete="CASCADE"), index=True
    )
    stance: Mapped[VoteStance] = mapped_column(
        SAEnum(VoteStance, native_enum=False, length=32), default=VoteStance.NA
    )

    politician: Mapped["Politician"] = relationship(back_populates="votes")
    event: Mapped["VoteEvent"] = relationship(back_populates="votes")
