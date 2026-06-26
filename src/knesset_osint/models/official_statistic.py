"""Curated 'official statistic' — the proof a claim is checked against.

Each row is one published figure (e.g. IDF enlistment rate for a given city in
a given year). It is sourced raw data, so it carries `ProvenanceMixin` and a
CHECK requiring `source_url`: an unsourced 'official statistic' is a
contradiction in terms and must never enter the catalog.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin


class OfficialStatistic(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "official_statistics"
    __table_args__ = (
        CheckConstraint(
            "source_url IS NOT NULL", name="ck_official_statistic_requires_source"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # What is measured, e.g. "idf_enlistment_rate".
    metric: Mapped[str] = mapped_column(String(128), index=True)
    # The breakdown axis and its value, e.g. ("city", "תל אביב") or ("sector", "חרדים").
    dimension_type: Mapped[str] = mapped_column(String(32), index=True)
    dimension_value: Mapped[str] = mapped_column(String(255), index=True)

    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    period: Mapped[str | None] = mapped_column(String(64))  # e.g. "2022" or "2020-2022"
    notes: Mapped[str | None] = mapped_column(Text)
