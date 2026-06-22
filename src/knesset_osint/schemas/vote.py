"""Read-models for voting records.

``VoteEventRead`` = the thing voted on (subject, date, outcome, tallies).
``VoteRead``      = how one politician voted on one event (their stance), with
                    the event's title + date surfaced inline so a client reading
                    a politician's votes immediately sees *what* they voted on.
"""

from __future__ import annotations

from datetime import date

from pydantic import model_validator

from knesset_osint.models.enums import VoteResult, VoteStance
from knesset_osint.schemas.common import ProvenanceFields


class VoteEventRead(ProvenanceFields):
    """A single vote event (the motion/law and its outcome)."""

    id: int
    knesset_vote_id: int | None = None
    title: str | None = None
    vote_date: date | None = None
    knesset_num: int | None = None
    session_num: int | None = None
    result: VoteResult
    total_for: int | None = None
    total_against: int | None = None
    total_abstain: int | None = None


class VoteRead(ProvenanceFields):
    """How one politician voted on one event.

    Always exposes ``stance`` and ``source_url`` (from ProvenanceFields).
    ``event`` carries the full nested event when loaded; ``event_title`` and
    ``event_date`` are convenience copies surfaced even when only the stance is
    needed, populated by a validator from the loaded ``event`` relationship.
    """

    id: int
    politician_id: int
    vote_event_id: int
    stance: VoteStance
    event: VoteEventRead | None = None

    # Convenience denormalized fields pulled from the loaded event relationship.
    event_title: str | None = None
    event_date: date | None = None

    @model_validator(mode="after")
    def _denormalize_event(self) -> "VoteRead":
        """Fill ``event_title``/``event_date`` from the nested event when loaded.

        Lets clients read the basics (what + when) without always expanding the
        full event object, while keeping a single source of truth.
        """
        if self.event is not None:
            if self.event_title is None:
                self.event_title = self.event.title
            if self.event_date is None:
                self.event_date = self.event.vote_date
        return self


__all__ = ["VoteEventRead", "VoteRead"]
