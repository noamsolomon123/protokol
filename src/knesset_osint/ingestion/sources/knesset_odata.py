"""Knesset ParliamentInfo OData V4 adapter (source-of-truth).

This adapter reads the **open, official** ParliamentInfo OData V4 feed
(`settings.knesset_odata_v4_base`). It is the authoritative source for
politicians, the bills they initiated, and the positions/roles they held.

Every method returns `RawRecord`s (data + provenance) — mappers downstream turn
those into ORM rows, copying ``source_type`` / ``source_url`` / ``raw_payload``
/ ``fetched_at`` straight into :class:`ProvenanceMixin`. Nothing here writes to
the DB; this layer only *reads* and *preserves provenance*.

Verified live shapes (2026-06-20):
  * ``KNS_Person``           : Id, LastName, FirstName, GenderDesc, Email,
                               IsCurrent, LastUpdatedDate. (Netanyahu Id=965.)
  * ``KNS_BillInitiator``    : Id, BillID, PersonID, IsInitiator, Ordinal.
                               (Netanyahu PersonID=965 -> 31 rows.)
  * ``KNS_Bill``             : Id, Name, KnessetNum, SubTypeDesc, StatusID, ...
  * ``KNS_PersonToPosition`` : Id, PersonID, PositionID, KnessetNum, StartDate,
                               FinishDate, GovMinistryID, GovMinistryName,
                               DutyDesc, FactionID, FactionName, GovernmentNum,
                               CommitteeID, CommitteeName, IsCurrent.

Extending to more politicians / sources
---------------------------------------
* More politicians: nothing to change here — every method is parameterised by
  ``person_id`` / ``bill_id``. The pilot id (965) lives in
  ``settings.pilot_person_id``; iterate over any list of person ids you like.
* More ParliamentInfo entity sets (e.g. KNS_Committee, KNS_Faction): add a thin
  method that calls ``self.client.iter_entities("KNS_<Set>", filter=...)`` and
  returns the records. Keep the OData ``$filter`` syntax (Hebrew literals are
  fine; httpx URL-encodes params automatically).
"""

from __future__ import annotations

from collections.abc import Iterator

from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.sources.base import BaseSource, ODataClient, RawRecord
from knesset_osint.models.enums import SourceType

logger = get_logger("knesset_osint.sources.knesset_odata")


def _odata_str(value: str) -> str:
    """Quote a string for an OData ``$filter`` literal, escaping single quotes.

    OData escapes a ``'`` by doubling it. We do *not* URL-encode here — httpx
    encodes query params for us when the filter is passed through ``params``.
    """
    return "'" + value.replace("'", "''") + "'"


class KnessetParliamentInfoSource(BaseSource):
    """Adapter over the ParliamentInfo OData V4 feed (persons, bills, positions)."""

    source_type = SourceType.KNESSET_ODATA
    name = "knesset_parliamentinfo"

    # Entity set names (kept as constants so callers and tests can reference them).
    PERSON_SET = "KNS_Person"
    BILL_INITIATOR_SET = "KNS_BillInitiator"
    BILL_SET = "KNS_Bill"
    PERSON_TO_POSITION_SET = "KNS_PersonToPosition"

    def __init__(self, client: ODataClient | None = None) -> None:
        """Build (or accept) an OData V4 client for ParliamentInfo.

        Passing a ``client`` is handy for tests (inject a stub) and for reusing a
        single pooled ``httpx.Client`` across adapters.
        """
        self.client = client or ODataClient(
            settings.knesset_odata_v4_base,
            SourceType.KNESSET_ODATA,
            odata_version=4,
        )

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "KnessetParliamentInfoSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- persons -------------------------------------------------------------
    def get_person(self, person_id: int) -> RawRecord | None:
        """Fetch one ``KNS_Person`` by Id, or ``None`` if not found."""
        flt = f"Id eq {int(person_id)}"
        for record in self.client.iter_entities(
            self.PERSON_SET, filter=flt, max_records=1
        ):
            return record
        logger.warning("KNS_Person Id=%s not found", person_id)
        return None

    def find_persons_by_name(
        self, last_name: str, first_name: str | None = None
    ) -> list[RawRecord]:
        """Find persons by exact LastName (optionally + FirstName).

        Names are matched case-/exact as stored upstream (Hebrew literals work).
        Returns *all* matches — there can legitimately be more than one MK with
        the same surname, so reconciliation/disambiguation is the caller's job.
        """
        clauses = [f"LastName eq {_odata_str(last_name)}"]
        if first_name:
            clauses.append(f"FirstName eq {_odata_str(first_name)}")
        flt = " and ".join(clauses)
        records = list(self.client.iter_entities(self.PERSON_SET, filter=flt))
        if not records:
            logger.warning(
                "No KNS_Person for LastName=%r FirstName=%r", last_name, first_name
            )
        return records

    # -- bills ---------------------------------------------------------------
    def iter_bill_initiations(self, person_id: int) -> Iterator[RawRecord]:
        """Yield every ``KNS_BillInitiator`` row for a person (their sponsorships).

        Each row carries BillID + IsInitiator + Ordinal; pair with
        :meth:`get_bill` to resolve the bill itself.
        """
        flt = f"PersonID eq {int(person_id)}"
        yield from self.client.iter_entities(self.BILL_INITIATOR_SET, filter=flt)

    def get_bill(self, bill_id: int) -> RawRecord | None:
        """Fetch one ``KNS_Bill`` by Id, or ``None`` if not found."""
        flt = f"Id eq {int(bill_id)}"
        for record in self.client.iter_entities(
            self.BILL_SET, filter=flt, max_records=1
        ):
            return record
        logger.warning("KNS_Bill Id=%s not found", bill_id)
        return None

    # -- positions / roles ---------------------------------------------------
    def iter_positions(self, person_id: int) -> Iterator[RawRecord]:
        """Yield every ``KNS_PersonToPosition`` row for a person (their roles).

        Covers ministry/faction/committee memberships with start/finish dates —
        the raw material for :class:`Role` rows.
        """
        flt = f"PersonID eq {int(person_id)}"
        yield from self.client.iter_entities(self.PERSON_TO_POSITION_SET, filter=flt)
