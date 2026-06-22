"""Read-models for politicians and their directly-owned sub-resources.

Includes ``PoliticianRead`` (the core entity), the sub-resource read-models
(``RoleRead``, ``BillRead``, ``BillSponsorshipRead``, ``ActionRead``), and
``PoliticianDetail`` (the entity plus counts of related records).

``VoteRead``/``StatementRead``/``ContradictionRead`` live in their own modules
(``vote.py`` / ``statement.py``) but are re-exported from ``schemas/__init__``.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from knesset_osint.models.enums import ActionType
from knesset_osint.schemas.common import ORMModel, ProvenanceFields


class PoliticianRead(ProvenanceFields):
    """A politician as exposed over the API.

    ``id`` is our internal primary key (use it for all sub-resource lookups);
    ``knesset_person_id`` is the authoritative ParliamentInfo ``KNS_Person.Id``
    (965 = Netanyahu). ``external_ids`` carries cross-source reconciliation keys
    such as ``votes_mk_id`` — important when scaling to all 120 MKs.
    """

    id: int
    knesset_person_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str
    gender: str | None = None
    email: str | None = None
    is_current: bool
    current_party: str | None = None
    external_ids: dict | None = None


class RoleRead(ProvenanceFields):
    """An official position held over time (from ``KNS_PersonToPosition``)."""

    id: int
    politician_id: int
    position_id: int | None = None
    position_desc: str | None = None
    knesset_num: int | None = None
    government_num: int | None = None
    ministry_name: str | None = None
    faction_name: str | None = None
    committee_name: str | None = None
    start_date: date | None = None
    finish_date: date | None = None
    is_current: bool


class BillRead(ProvenanceFields):
    """A bill (from ``KNS_Bill``)."""

    id: int
    knesset_bill_id: int | None = None
    name: str | None = None
    bill_type_desc: str | None = None
    status_desc: str | None = None
    knesset_num: int | None = None
    summary: str | None = None


class BillSponsorshipRead(ProvenanceFields):
    """A politician's sponsorship of a bill (from ``KNS_BillInitiator``).

    ``bill`` is the nested bill when the ORM relationship is loaded, so a client
    listing a politician's bills gets the bill details inline without a second
    request.
    """

    id: int
    politician_id: int
    bill_id: int
    is_initiator: bool
    ordinal: int | None = None
    bill: BillRead | None = None


class ActionRead(ProvenanceFields):
    """A concrete action / achievement attributable to a politician.

    Backed by a CHECK constraint requiring ``source_url`` — every action is
    sourced.
    """

    id: int
    politician_id: int
    action_date: date | None = None
    action_type: ActionType
    title: str
    description: str | None = None


class PoliticianDetail(PoliticianRead):
    """A politician plus counts of their related records.

    The counts power a profile/overview view without forcing the client to page
    through every sub-resource. They are computed by the router (cheap COUNT
    queries), not stored on the model.
    """

    role_count: int = Field(default=0, ge=0)
    bill_count: int = Field(default=0, ge=0)
    vote_count: int = Field(default=0, ge=0)
    statement_count: int = Field(default=0, ge=0)
    action_count: int = Field(default=0, ge=0)


# Re-export ORMModel so siblings/tests can import a single base from here too.
__all__ = [
    "ORMModel",
    "PoliticianRead",
    "RoleRead",
    "BillRead",
    "BillSponsorshipRead",
    "ActionRead",
    "PoliticianDetail",
]
