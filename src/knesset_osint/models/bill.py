"""Bills and per-politician sponsorship (from KNS_Bill + KNS_BillInitiator)."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin


class Bill(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    knesset_bill_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(Text)
    bill_type_desc: Mapped[str | None] = mapped_column(String(255))
    status_desc: Mapped[str | None] = mapped_column(String(255))
    knesset_num: Mapped[int | None] = mapped_column(Integer, index=True)
    summary: Mapped[str | None] = mapped_column(Text)

    sponsorships: Mapped[list["BillSponsorship"]] = relationship(
        back_populates="bill", cascade="all, delete-orphan"
    )


class BillSponsorship(Base, TimestampMixin, ProvenanceMixin):
    """Join row: politician initiated / co-signed a bill (KNS_BillInitiator)."""

    __tablename__ = "bill_sponsorships"
    __table_args__ = (
        UniqueConstraint("politician_id", "bill_id", name="uq_sponsorship_politician_bill"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), index=True)
    is_initiator: Mapped[bool] = mapped_column(Boolean, default=False)
    ordinal: Mapped[int | None] = mapped_column(Integer)

    politician: Mapped["Politician"] = relationship(back_populates="bill_sponsorships")
    bill: Mapped["Bill"] = relationship(back_populates="sponsorships")
