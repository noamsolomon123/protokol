"""Pydantic v2 read-models (DTOs) for the public API.

These schemas are the *serialization contract* between the SQLAlchemy ORM layer
and HTTP clients. They are deliberately separate from the ORM models so that:

* the wire format is stable even if internal columns are renamed,
* we expose only what is safe/useful (and always the ``source_url`` provenance),
* response shapes can be validated and documented (OpenAPI) automatically.

Every read-model sets ``model_config = ConfigDict(from_attributes=True)`` so a
router can simply do ``PoliticianRead.model_validate(orm_obj)``.

Extending for more politicians / sources
----------------------------------------
The schemas are entity-shaped, not politician-specific: the very same
``PoliticianRead`` serves 1 pilot or all 120 MKs. To surface a new field, add it
to the matching ``*Read`` model here (and ensure the ORM column exists); to add a
whole new entity, create a new ``*Read`` model and a router that returns it.
"""

from __future__ import annotations

from knesset_osint.schemas.common import Page
from knesset_osint.schemas.politician import (
    ActionRead,
    BillRead,
    BillSponsorshipRead,
    PoliticianDetail,
    PoliticianRead,
    RoleRead,
)
from knesset_osint.schemas.statement import ContradictionRead, StatementRead
from knesset_osint.schemas.vote import VoteEventRead, VoteRead

__all__ = [
    "Page",
    "PoliticianRead",
    "PoliticianDetail",
    "RoleRead",
    "BillRead",
    "BillSponsorshipRead",
    "VoteEventRead",
    "VoteRead",
    "StatementRead",
    "ActionRead",
    "ContradictionRead",
]
