"""Shared schema building blocks: a provenance mixin and a generic page envelope.

``ProvenanceFields`` mirrors :class:`knesset_osint.db.mixins.ProvenanceMixin` so
that any read-model can inherit the standard provenance columns and *always*
expose ``source_url`` (the platform's objectivity guarantee on the wire).

``Page`` is a generic pagination envelope used by every list endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from knesset_osint.models.enums import SourceType

# Generic item type for the paginated envelope.
ItemT = TypeVar("ItemT")


class ORMModel(BaseModel):
    """Base for all read-models: enable ``from_attributes`` ORM serialization."""

    model_config = ConfigDict(from_attributes=True)


class ProvenanceFields(ORMModel):
    """The provenance columns shared by every source-backed record.

    Inherit this in any read-model whose ORM row uses ``ProvenanceMixin``. We
    surface ``source_url`` (and the rest) on every response so a consumer can
    always click through to the official source — never an unattributed claim.
    ``raw_payload`` is intentionally omitted from the wire model to keep
    responses lean; the deep-link ``source_url`` is the auditable handle.
    """

    source_type: SourceType
    source_name: str | None = None
    source_url: str | None = None
    source_record_id: str | None = None
    fetched_at: datetime | None = None


class Page(BaseModel, Generic[ItemT]):
    """Generic pagination envelope returned by every list endpoint.

    ``total`` is the full count matching the query (not just this page), so a
    client can render correct pagination controls. ``limit``/``offset`` echo the
    request window.
    """

    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=0)
    offset: int = Field(ge=0)
