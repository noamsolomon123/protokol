"""The orchestrating ingestion pipeline (idempotent, provenance-preserving).

:func:`ingest_politician` is the single entry point that wires the source
adapters, mappers and reconciliation together into a repeatable run:

    person  ->  roles  ->  bill initiations (+ bills)  ->  votes

Design guarantees
-----------------
* **Idempotent.** Every write goes through a get-or-create keyed on a natural key
  (``knesset_person_id``, ``knesset_bill_id``, ``knesset_vote_id``) or a unique
  constraint (sponsorship: politician+bill; vote: politician+event). Running the
  pipeline twice produces no duplicates and simply refreshes provenance.
* **Provenance everywhere.** All ORM rows are built by the mappers, which copy
  ``source_type``/``source_url``/``raw_payload``/``fetched_at`` onto each row.
* **Fail soft, not loud.** Per-record errors are caught, logged, and appended to
  ``IngestionReport.warnings`` so one bad upstream row never aborts the whole run.
* **No fabrication.** Missing upstream values are stored as NULL; an unmatched
  Votes MK id means votes are skipped (with a warning), never invented.

Extending to more politicians / sources
---------------------------------------
* All MKs: loop over a list of ``KNS_Person.Id`` values and call
  :func:`ingest_politician` for each (or add an ``ingest_all`` wrapper). Nothing
  here is Netanyahu-specific; the pilot id is just the default.
* A new source: add an adapter + mappers, then thread an extra phase into
  :func:`ingest_politician` following the get-or-create pattern used below.
* Enrichment: the ``with_enrichment`` flag is plumbed through and best-effort
  enrichment is attached to ``Politician.external_ids`` without ever becoming
  source-of-truth; expand :func:`_enrich_politician` to fold in more fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion import mappers
from knesset_osint.ingestion.reconciliation import reconcile_votes_mk_id
from knesset_osint.ingestion.sources.knesset_odata import KnessetParliamentInfoSource
from knesset_osint.ingestion.sources.knesset_votes import KnessetVotesSource
from knesset_osint.ingestion.sources.open_knesset import OpenKnessetSource
from knesset_osint.models import (
    Bill,
    BillSponsorship,
    Politician,
    Vote,
    VoteEvent,
)

logger = get_logger("knesset_osint.ingestion.pipeline")


@dataclass
class IngestionReport:
    """Tally of what one :func:`ingest_politician` run created/updated.

    Counts reflect rows that were ingested this run (created *or* matched + kept).
    ``warnings`` collects human-readable, non-fatal problems (skipped records,
    unmatched ids, per-row errors) so an operator can audit a run at a glance.
    """

    politician_id: Optional[int] = None
    persons: int = 0
    bills: int = 0
    sponsorships: int = 0
    roles: int = 0
    vote_events: int = 0
    votes: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        """Record a non-fatal problem (also logged at WARNING level)."""
        logger.warning(msg)
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# get-or-create helpers (the idempotency backbone)
# ---------------------------------------------------------------------------
def _get_politician_by_kns(session: Any, kns_id: int) -> Optional[Politician]:
    return session.execute(
        select(Politician).where(Politician.knesset_person_id == kns_id)
    ).scalar_one_or_none()


def _get_bill_by_kns(session: Any, kns_bill_id: int) -> Optional[Bill]:
    return session.execute(
        select(Bill).where(Bill.knesset_bill_id == kns_bill_id)
    ).scalar_one_or_none()


def _get_vote_event_by_kns(session: Any, kns_vote_id: int) -> Optional[VoteEvent]:
    return session.execute(
        select(VoteEvent).where(VoteEvent.knesset_vote_id == kns_vote_id)
    ).scalar_one_or_none()


def _copy_provenance(dst: Any, src: Any) -> None:
    """Refresh provenance + key descriptive fields on an existing row from a
    freshly-mapped one. Keeps re-runs current with upstream without duplicating
    rows. We never null out an existing value with a missing new one beyond the
    provenance block (provenance always reflects the latest fetch)."""
    dst.source_type = src.source_type
    dst.source_name = src.source_name
    dst.source_url = src.source_url
    dst.source_record_id = src.source_record_id
    dst.raw_payload = src.raw_payload
    dst.fetched_at = src.fetched_at


# ---------------------------------------------------------------------------
# Phase: person
# ---------------------------------------------------------------------------
def _upsert_person(
    session: Any, odata: KnessetParliamentInfoSource, person_id: int, report: IngestionReport
) -> Optional[Politician]:
    """Fetch + upsert the politician by ``KNS_Person.Id``. Returns the row or None."""
    rec = odata.get_person(person_id)
    if rec is None:
        report.warn(f"KNS_Person Id={person_id} not found; aborting ingest.")
        return None

    mapped = mappers.map_person(rec)
    kns_id = mapped.knesset_person_id or person_id

    existing = _get_politician_by_kns(session, kns_id)
    if existing is None:
        session.add(mapped)
        session.flush()  # assign PK so downstream FKs resolve
        report.persons += 1
        logger.info("Created politician id=%s (kns=%s)", mapped.id, kns_id)
        return mapped

    # Update mutable descriptive fields + provenance; preserve external_ids map.
    existing.first_name = mapped.first_name
    existing.last_name = mapped.last_name
    existing.full_name = mapped.full_name or existing.full_name
    existing.gender = mapped.gender
    existing.email = mapped.email
    existing.is_current = mapped.is_current
    _copy_provenance(existing, mapped)
    session.flush()
    report.persons += 1
    logger.info("Updated existing politician id=%s (kns=%s)", existing.id, kns_id)
    return existing


# ---------------------------------------------------------------------------
# Phase: roles
# ---------------------------------------------------------------------------
def _ingest_roles(
    session: Any,
    odata: KnessetParliamentInfoSource,
    politician: Politician,
    report: IngestionReport,
) -> None:
    """Replace this politician's roles with the current upstream set.

    Roles (KNS_PersonToPosition) have no stable single natural key we expose, so
    for idempotency we clear the politician's existing roles and re-insert the
    current upstream snapshot. Cheap (a few dozen rows) and guarantees no dupes on
    re-run."""
    kns_id = politician.knesset_person_id or politician.id
    try:
        records = list(odata.iter_positions(kns_id))
    except Exception as exc:
        report.warn(f"Failed to fetch positions for kns={kns_id}: {exc}")
        return

    # Remove prior snapshot (cascade handles the delete) then re-add.
    if politician.roles:
        for old in list(politician.roles):
            session.delete(old)
        session.flush()

    added = 0
    for rec in records:
        try:
            role = mappers.map_role(rec, politician.id)
            session.add(role)
            added += 1
        except Exception as exc:  # one bad row must not sink the phase
            report.warn(f"Skipped a role row (kns={kns_id}): {exc}")
    session.flush()
    report.roles += added
    logger.info("Ingested %d roles for politician id=%s", added, politician.id)


# ---------------------------------------------------------------------------
# Phase: bills + sponsorships
# ---------------------------------------------------------------------------
def _upsert_bill(
    session: Any,
    odata: KnessetParliamentInfoSource,
    bill_id: int,
    report: IngestionReport,
) -> Optional[Bill]:
    """Get-or-create a Bill by KNS bill id, fetching its detail row. None on fail."""
    existing = _get_bill_by_kns(session, bill_id)
    rec = None
    try:
        rec = odata.get_bill(bill_id)
    except Exception as exc:
        report.warn(f"Failed to fetch KNS_Bill Id={bill_id}: {exc}")

    if rec is None:
        if existing is not None:
            return existing  # keep what we have; nothing new upstream
        report.warn(f"KNS_Bill Id={bill_id} not found; skipping sponsorship.")
        return None

    mapped = mappers.map_bill(rec)
    if existing is None:
        session.add(mapped)
        session.flush()
        report.bills += 1
        return mapped

    existing.name = mapped.name
    existing.bill_type_desc = mapped.bill_type_desc
    existing.status_desc = mapped.status_desc
    existing.knesset_num = mapped.knesset_num
    existing.summary = mapped.summary
    _copy_provenance(existing, mapped)
    session.flush()
    report.bills += 1
    return existing


def _get_or_create_sponsorship(
    session: Any,
    politician_id: int,
    bill_id: int,
    initiator_rec: Any,
    report: IngestionReport,
) -> None:
    """Get-or-create the unique (politician, bill) sponsorship row.

    Honours the ``uq_sponsorship_politician_bill`` constraint; on re-run it
    refreshes ``is_initiator`` / ``ordinal`` / provenance instead of inserting a
    duplicate."""
    data = initiator_rec.data
    is_initiator = bool(
        mappers._to_bool(mappers._first(data, "IsInitiator", "is_initiator")) or False
    )
    ordinal = mappers._to_int(mappers._first(data, "Ordinal", "ordinal"))

    existing = session.execute(
        select(BillSponsorship).where(
            BillSponsorship.politician_id == politician_id,
            BillSponsorship.bill_id == bill_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        sp = BillSponsorship(
            politician_id=politician_id,
            bill_id=bill_id,
            is_initiator=is_initiator,
            ordinal=ordinal,
        )
        mappers._apply_provenance(sp, initiator_rec)
        session.add(sp)
        report.sponsorships += 1
    else:
        existing.is_initiator = is_initiator
        existing.ordinal = ordinal
        mappers._apply_provenance(existing, initiator_rec)
        report.sponsorships += 1


def _ingest_bills(
    session: Any,
    odata: KnessetParliamentInfoSource,
    politician: Politician,
    report: IngestionReport,
) -> None:
    """Ingest the politician's bill initiations: upsert each Bill, then the
    (politician, bill) sponsorship. Commits once at the end of the phase."""
    kns_id = politician.knesset_person_id or politician.id
    try:
        initiations = list(odata.iter_bill_initiations(kns_id))
    except Exception as exc:
        report.warn(f"Failed to fetch bill initiations for kns={kns_id}: {exc}")
        return

    for rec in initiations:
        try:
            bill_kns_id = mappers._to_int(
                mappers._first(rec.data, "BillID", "BillId", "bill_id")
            )
            if bill_kns_id is None:
                report.warn(f"Initiator row without BillID; skipped: {rec.source_record_id}")
                continue
            bill = _upsert_bill(session, odata, bill_kns_id, report)
            if bill is None:
                continue
            _get_or_create_sponsorship(session, politician.id, bill.id, rec, report)
        except Exception as exc:  # isolate per-bill failures
            report.warn(f"Skipped a bill initiation (kns={kns_id}): {exc}")
    session.commit()
    logger.info(
        "Ingested bills/sponsorships for politician id=%s (bills=%d, sponsorships=%d)",
        politician.id,
        report.bills,
        report.sponsorships,
    )


# ---------------------------------------------------------------------------
# Phase: votes
# ---------------------------------------------------------------------------
def _upsert_vote_event(
    session: Any,
    votes_src: KnessetVotesSource,
    vote_kns_id: int,
    report: IngestionReport,
) -> Optional[VoteEvent]:
    """Get-or-create a VoteEvent by KNS vote id, fetching its header. None on fail."""
    existing = _get_vote_event_by_kns(session, vote_kns_id)
    if existing is not None:
        return existing  # header already ingested; reuse (idempotent)

    try:
        rec = votes_src.get_vote_header(vote_kns_id)
    except Exception as exc:
        report.warn(f"Failed to fetch vote header vote_id={vote_kns_id}: {exc}")
        return None
    if rec is None:
        report.warn(f"Vote header vote_id={vote_kns_id} not found (Approved set).")
        return None

    event = mappers.map_vote_header(rec)
    if event.knesset_vote_id is None:
        event.knesset_vote_id = vote_kns_id
    session.add(event)
    session.flush()
    report.vote_events += 1
    return event


def _get_or_create_vote(
    session: Any,
    politician_id: int,
    vote_event_id: int,
    mk_rec: Any,
    report: IngestionReport,
) -> None:
    """Get-or-create the unique (politician, event) Vote, with mapped stance."""
    raw_result = mappers._first(
        mk_rec.data, "vote_result", "VoteResult", "result", "vote_result_type"
    )
    stance = mappers.stance_from_value(raw_result)

    existing = session.execute(
        select(Vote).where(
            Vote.politician_id == politician_id,
            Vote.vote_event_id == vote_event_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        vote = mappers.map_mk_vote(mk_rec, politician_id, vote_event_id, stance)
        session.add(vote)
        report.votes += 1
    else:
        existing.stance = stance
        mappers._apply_provenance(existing, mk_rec)
        report.votes += 1


def _ingest_votes(
    session: Any,
    votes_src: KnessetVotesSource,
    politician: Politician,
    mk_id: int,
    report: IngestionReport,
    *,
    max_votes: Optional[int],
    batch_size: int = 100,
) -> None:
    """Iterate the MK's roll-call votes: upsert each VoteEvent + the per-MK Vote.

    Commits every ``batch_size`` votes so a long run checkpoints progress and a
    late failure doesn't lose everything already ingested."""
    try:
        records = votes_src.iter_mk_votes(mk_id, max_records=max_votes)
    except Exception as exc:
        report.warn(f"Failed to iterate votes for mk_id={mk_id}: {exc}")
        return

    processed = 0
    for rec in records:
        try:
            vote_kns_id = mappers._to_int(
                mappers._first(rec.data, "vote_id", "VoteId", "VoteID")
            )
            if vote_kns_id is None:
                report.warn(f"MK vote row without vote_id; skipped: {rec.source_record_id}")
                continue
            event = _upsert_vote_event(session, votes_src, vote_kns_id, report)
            if event is None:
                continue
            _get_or_create_vote(session, politician.id, event.id, rec, report)
            processed += 1
            if processed % batch_size == 0:
                session.commit()
                logger.info("Vote batch checkpoint: %d processed", processed)
        except Exception as exc:  # isolate per-vote failures
            report.warn(f"Skipped a vote (mk_id={mk_id}): {exc}")
    session.commit()
    logger.info(
        "Ingested votes for politician id=%s (events=%d, votes=%d)",
        politician.id,
        report.vote_events,
        report.votes,
    )


# ---------------------------------------------------------------------------
# Phase: best-effort enrichment (never source-of-truth)
# ---------------------------------------------------------------------------
def _enrich_politician(
    session: Any,
    politician: Politician,
    mk_id: Optional[int],
    report: IngestionReport,
) -> None:
    """Attach best-effort Open Knesset enrichment to ``external_ids``.

    Enrichment is purely additive and must never break ingestion: any failure is
    swallowed (the adapter already degrades gracefully) and only logged. We store
    a pointer/payload under ``external_ids['open_knesset']`` rather than letting it
    override any authoritative field."""
    try:
        with OpenKnessetSource() as ok:
            if not ok.enabled:
                return
            # Open Knesset keys on mk_individual_id; the Votes mk_id is our best
            # available join key. If we never reconciled one, skip quietly.
            if mk_id is None:
                return
            rec = ok.get_member_enrichment(mk_id)
            if rec is None:
                return
            ext = dict(politician.external_ids or {})
            ext["open_knesset"] = {
                "source_url": rec.source_url,
                "mk_individual_id": rec.source_record_id,
                "data": rec.data,
            }
            politician.external_ids = ext
            flag_modified(politician, "external_ids")
            session.commit()
            logger.info("Attached Open Knesset enrichment to politician id=%s", politician.id)
    except Exception as exc:  # enrichment is never allowed to fail a run
        report.warn(f"Open Knesset enrichment skipped: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def ingest_politician(
    session: Any,
    person_id: int = settings.pilot_person_id,
    *,
    with_votes: bool = True,
    with_enrichment: Optional[bool] = None,
    max_votes: Optional[int] = None,
) -> IngestionReport:
    """Ingest one politician end-to-end, idempotently.

    Flow: upsert person -> roles -> bill initiations (bills + sponsorships) ->
    (optional) reconcile Votes MK id and ingest votes -> (optional) enrichment.

    Parameters
    ----------
    session:
        An active SQLAlchemy ``Session`` (the caller owns its lifecycle).
    person_id:
        ``KNS_Person.Id`` to ingest. Defaults to the pilot (Netanyahu, 965). To
        ingest more MKs, call this once per id.
    with_votes:
        If ``True`` (default) reconcile the Votes MK id and ingest roll-call votes.
    with_enrichment:
        Override for Open Knesset enrichment. ``None`` (default) defers to
        ``settings.enable_open_knesset_enrichment``.
    max_votes:
        Cap on votes pulled this run. ``None`` (default) = no cap = the
        politician's ENTIRE digitized voting career. Pass an int (e.g. 500) for
        a fast partial run. Idempotent, so a long full-career pull resumes safely.

    Returns
    -------
    An :class:`IngestionReport` with per-entity counts and any warnings. Safe to
    call repeatedly: natural-key/unique-constraint get-or-create means no dupes.
    """
    report = IngestionReport()
    if with_enrichment is None:
        with_enrichment = settings.enable_open_knesset_enrichment

    logger.info(
        "Starting ingest: person_id=%s with_votes=%s with_enrichment=%s max_votes=%s",
        person_id,
        with_votes,
        with_enrichment,
        max_votes,
    )

    odata = KnessetParliamentInfoSource()
    votes_src: Optional[KnessetVotesSource] = None
    try:
        # --- person ---
        politician = _upsert_person(session, odata, person_id, report)
        if politician is None:
            session.rollback()
            return report
        session.commit()
        report.politician_id = politician.id

        # --- roles ---
        _ingest_roles(session, odata, politician, report)
        session.commit()

        # --- bills + sponsorships ---
        _ingest_bills(session, odata, politician, report)

        # --- votes (reconcile id first) ---
        mk_id: Optional[int] = None
        if with_votes:
            votes_src = KnessetVotesSource()
            mk_id = reconcile_votes_mk_id(session, politician, votes_src)
            session.commit()
            if mk_id is None:
                report.warn(
                    f"No votes_mk_id for politician id={politician.id}; "
                    "skipping vote ingestion."
                )
            else:
                _ingest_votes(
                    session, votes_src, politician, mk_id, report, max_votes=max_votes
                )

        # --- enrichment (best-effort, additive) ---
        if with_enrichment:
            _enrich_politician(session, politician, mk_id, report)

    except Exception as exc:  # top-level guard: report rather than explode
        session.rollback()
        report.warn(f"Ingestion aborted with error: {exc}")
        logger.exception("Ingestion failed for person_id=%s", person_id)
    finally:
        odata.close()
        if votes_src is not None:
            votes_src.close()

    logger.info(
        "Ingest complete: person=%s persons=%d roles=%d bills=%d sponsorships=%d "
        "vote_events=%d votes=%d warnings=%d",
        report.politician_id,
        report.persons,
        report.roles,
        report.bills,
        report.sponsorships,
        report.vote_events,
        report.votes,
        len(report.warnings),
    )
    return report
