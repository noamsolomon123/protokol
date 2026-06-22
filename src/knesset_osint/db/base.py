"""Declarative base for all ORM models (SQLAlchemy 2.0 typed style)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative base. All models inherit from this so that
    `Base.metadata` knows the full schema (used by Alembic autogenerate).

    Import side note: `knesset_osint.models` imports every model module, which
    is what actually registers tables on this metadata. Always import models
    (or `knesset_osint.db.base_all`) before calling `create_all`/autogenerate.
    """
