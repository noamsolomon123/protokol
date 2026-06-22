"""Reusable column mixins.

`ProvenanceMixin` is the heart of the platform's objectivity guarantee: every
row that originates from an external source carries WHERE it came from
(`source_url`), WHAT system (`source_type`/`source_name`), the upstream record id
(`source_record_id`), the verbatim payload (`raw_payload`), and WHEN it was
fetched (`fetched_at`). Nothing enters the database without provenance.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from knesset_osint.models.enums import SourceType


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProvenanceMixin:
    """Source-of-truth tracking. `source_url` is nullable here so derived/manual
    rows can exist, but evidence tables (statements, actions) add a CHECK
    constraint requiring it — see those models."""

    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, native_enum=False, length=32),
        nullable=False,
        default=SourceType.MANUAL,
    )
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
