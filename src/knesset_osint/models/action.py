"""Concrete actions / achievements attributable to a politician.

Like Statement, every Action must carry a `source_url` (CHECK constraint):
'achievements' without a verifiable source are not recorded.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin
from knesset_osint.models.enums import ActionType


class Action(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint("source_url IS NOT NULL", name="ck_action_requires_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )

    action_date: Mapped[date | None] = mapped_column(Date, index=True)
    action_type: Mapped[ActionType] = mapped_column(
        SAEnum(ActionType, native_enum=False, length=32), default=ActionType.OTHER
    )
    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)

    politician: Mapped["Politician"] = relationship(back_populates="actions")
