"""The central entity. Designed to scale from 1 pilot to all 120 MKs + officials."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin


class Politician(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "politicians"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Authoritative external key: KNS_Person.Id from ParliamentInfo (965 = Netanyahu).
    knesset_person_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)

    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(512), index=True)
    gender: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    current_party: Mapped[str | None] = mapped_column(String(255), index=True)

    # Cross-source id reconciliation map, e.g. {"votes_mk_id": 123, "open_knesset_id": 456}.
    # Critical for scaling: the Votes service keys members differently from ParliamentInfo.
    external_ids: Mapped[dict | None] = mapped_column(JSON, default=dict)

    roles: Mapped[list["Role"]] = relationship(
        back_populates="politician", cascade="all, delete-orphan"
    )
    votes: Mapped[list["Vote"]] = relationship(
        back_populates="politician", cascade="all, delete-orphan"
    )
    statements: Mapped[list["Statement"]] = relationship(
        back_populates="politician", cascade="all, delete-orphan"
    )
    actions: Mapped[list["Action"]] = relationship(
        back_populates="politician", cascade="all, delete-orphan"
    )
    bill_sponsorships: Mapped[list["BillSponsorship"]] = relationship(
        back_populates="politician", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Politician id={self.id} kns={self.knesset_person_id} {self.full_name!r}>"

# NOTE: string relationship targets ("Role", "Vote", ...) are resolved at mapper
# configuration time. `knesset_osint.models.__init__` imports every model module,
# which registers all classes on Base before mappers configure. Do not add
# bottom-of-file imports here.
