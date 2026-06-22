"""Official roles / positions held over time (from KNS_PersonToPosition)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin


class Role(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )

    position_id: Mapped[int | None] = mapped_column(Integer)
    position_desc: Mapped[str | None] = mapped_column(String(512))
    knesset_num: Mapped[int | None] = mapped_column(Integer, index=True)
    government_num: Mapped[int | None] = mapped_column(Integer)
    ministry_name: Mapped[str | None] = mapped_column(String(512))
    faction_name: Mapped[str | None] = mapped_column(String(512))
    committee_name: Mapped[str | None] = mapped_column(String(512))
    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    finish_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)

    politician: Mapped["Politician"] = relationship(back_populates="roles")
