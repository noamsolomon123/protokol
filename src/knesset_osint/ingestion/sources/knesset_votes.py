"""Knesset Votes OData V3 (.svc) adapter (source-of-truth for roll-call votes).

We use the **V3 .svc** feed only (`settings.knesset_votes_svc_base`). The V4
Votes endpoint is bot-protected (Imperva) and we never attempt to defeat that
challenge — the open V3 service gives us everything we need.

LIVE-PROBED COLUMNS (curl, 2026-06-20 — read these defensively with row.get,
because the Knesset occasionally renames/adds columns):

``View_Vote_MK_Individual`` — a *directory* of MKs (one row per MK, ~1112 rows;
NOT one row per vote). Maps an MK name to the ids used by the votes tables:
    vip_id (str, zero-padded e.g. "000000965"),
    mk_individual_id (int, e.g. 90 for Netanyahu),
    mk_individual_name (Hebrew surname), mk_individual_name_eng,
    mk_individual_first_name (Hebrew), mk_individual_first_name_eng.
    NOTE: for Netanyahu vip_id == KNS_Person.Id == 965 (zero-padded). That is a
    happy coincidence, not a guarantee — always reconcile by name, then persist
    the resolved id in Politician.external_ids['votes_mk_id'].

``vote_rslts_kmmbr_shadow`` — the per-MK roll-call results (one row per MK per
vote; Netanyahu has 6038 rows). This is the table iter_mk_votes reads:
    vote_id (int), kmmbr_id (str, == the zero-padded vip_id),
    kmmbr_name (Hebrew full name), vote_result (int, see VOTE_RESULT_MAP),
    knesset_num (int), faction_id (int), faction_name (Hebrew),
    reason, modifier, remark.

``View_vote_rslts_hdr_Approved`` — the vote *headers* (one row per vote):
    vote_id (int), knesset_num (int), session_id, sess_item_dscr (Hebrew title),
    vote_item_dscr (Hebrew sub-title), vote_date (ISO datetime), vote_time,
    is_accepted (1=passed/0=failed), total_for, total_against, total_abstain,
    session_num, vote_nbr_in_sess, reason, modifier, remark.

``vote_result_type`` — lookup for vote_result codes:
    0=בוטל(cancelled) 1=בעד(for) 2=נגד(against) 3=נמנע(abstain) 4=לא הצביע(absent).

Extending to more politicians / sources
---------------------------------------
* More politicians: call :meth:`find_mk_id` with each MK's first+last name to
  resolve their votes id, then :meth:`iter_mk_votes`. Nothing here is hardcoded
  to Netanyahu.
* The mapper that turns a vote RawRecord into a :class:`Vote` should translate
  ``vote_result`` via :data:`VOTE_RESULT_MAP` (kept here next to the probe notes
  so the mapping stays close to the verified upstream codes).
"""

from __future__ import annotations

from collections.abc import Iterator

from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.sources.base import BaseSource, ODataClient, RawRecord
from knesset_osint.models.enums import SourceType, VoteStance

logger = get_logger("knesset_osint.sources.knesset_votes")

# Upstream vote_result code -> our VoteStance enum. Verified against the
# vote_result_type lookup (2026-06-20). Mappers should use this; unknown codes
# fall back to VoteStance.NA rather than guessing.
VOTE_RESULT_MAP: dict[int, VoteStance] = {
    0: VoteStance.NA,        # בוטל  (vote cancelled)
    1: VoteStance.FOR,       # בעד
    2: VoteStance.AGAINST,   # נגד
    3: VoteStance.ABSTAIN,   # נמנע
    4: VoteStance.ABSENT,    # לא הצביע
}


def _first(row: dict, *keys: str):
    """Return the first present, non-None value among ``keys`` (defensive read)."""
    for key in keys:
        val = row.get(key)
        if val is not None:
            return val
    return None


def _odata_str(value: str) -> str:
    """Quote a string for an OData ``$filter`` literal, escaping single quotes."""
    return "'" + value.replace("'", "''") + "'"


def _to_kmmbr_id(mk_id: int | str) -> str:
    """Normalise a votes MK id to the 9-char zero-padded string the tables use.

    The shadow table stores ``kmmbr_id`` as e.g. ``"000000965"``. We accept an
    int (965) or an already-padded string and return the padded form.
    """
    s = str(mk_id).strip()
    if s.isdigit():
        return s.zfill(9)
    return s


class KnessetVotesSource(BaseSource):
    """Adapter over the Votes.svc OData V3 feed (roll-call votes + headers)."""

    source_type = SourceType.KNESSET_VOTES
    name = "knesset_votes"
    odata_version = 3

    # Entity set names (constants for callers/tests).
    MK_INDIVIDUAL_SET = "View_Vote_MK_Individual"
    KMMBR_SHADOW_SET = "vote_rslts_kmmbr_shadow"
    HEADER_SET = "View_vote_rslts_hdr_Approved"

    def __init__(self, client: ODataClient | None = None) -> None:
        """Build (or accept) an OData V3 client for Votes.svc."""
        self.client = client or ODataClient(
            settings.knesset_votes_svc_base,
            SourceType.KNESSET_VOTES,
            odata_version=3,
        )

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "KnessetVotesSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- reconciliation ------------------------------------------------------
    def find_mk_id(
        self, first_name: str, last_name: str
    ) -> tuple[int | None, RawRecord | None]:
        """Resolve an MK's votes id by matching first+last name.

        Returns ``(vip_id_as_int, RawRecord)`` on a match, else ``(None, None)``.
        ``vip_id`` is the id used to join into ``vote_rslts_kmmbr_shadow`` (as a
        zero-padded ``kmmbr_id``). Store the returned int in
        ``Politician.external_ids['votes_mk_id']``.

        We first try an exact server-side ``$filter`` on the Hebrew name columns;
        if that yields nothing (column-name drift, accents, etc.) we fall back to
        a defensive client-side scan of the (small, ~1.1k row) MK directory.
        """
        # --- fast path: server-side exact filter on the probed column names ---
        flt = (
            f"mk_individual_name eq {_odata_str(last_name)} and "
            f"mk_individual_first_name eq {_odata_str(first_name)}"
        )
        try:
            for record in self.client.iter_entities(
                self.MK_INDIVIDUAL_SET, filter=flt, max_records=1
            ):
                vip = self._extract_vip_id(record.data)
                if vip is not None:
                    return vip, record
        except Exception as exc:  # pragma: no cover - network/edge defensive
            logger.warning("find_mk_id server-side filter failed: %s", exc)

        # --- fallback: scan the directory and match defensively ---------------
        try:
            for record in self.client.iter_entities(self.MK_INDIVIDUAL_SET):
                data = record.data
                ln = _first(
                    data, "mk_individual_name", "mk_individual_name_eng", "LastName"
                )
                fn = _first(
                    data,
                    "mk_individual_first_name",
                    "mk_individual_first_name_eng",
                    "FirstName",
                )
                if ln == last_name and fn == first_name:
                    vip = self._extract_vip_id(data)
                    if vip is not None:
                        return vip, record
        except Exception as exc:  # pragma: no cover - network/edge defensive
            logger.warning("find_mk_id directory scan failed: %s", exc)

        logger.warning(
            "Votes MK id not found for first=%r last=%r", first_name, last_name
        )
        return None, None

    @staticmethod
    def _extract_vip_id(data: dict) -> int | None:
        """Pull the votes MK id out of a directory row (defensive on key names)."""
        raw = _first(data, "vip_id", "mk_id", "Id", "ID")
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    # -- votes ---------------------------------------------------------------
    def iter_mk_votes(
        self, mk_id: int, *, max_records: int | None = None
    ) -> Iterator[RawRecord]:
        """Yield one RawRecord per roll-call vote cast by an MK.

        ``mk_id`` is the votes id returned by :meth:`find_mk_id` (e.g. 965). We
        join on ``vote_rslts_kmmbr_shadow.kmmbr_id`` using the zero-padded form.
        Each record's ``data`` includes ``vote_id`` (join key for the header) and
        ``vote_result`` (translate via :data:`VOTE_RESULT_MAP`).
        """
        kmmbr_id = _to_kmmbr_id(mk_id)
        flt = f"kmmbr_id eq {_odata_str(kmmbr_id)}"
        yield from self.client.iter_entities(
            self.KMMBR_SHADOW_SET, filter=flt, max_records=max_records
        )

    def get_vote_header(self, vote_id: int) -> RawRecord | None:
        """Fetch one approved vote header by ``vote_id``, or ``None``.

        The header carries the title (``sess_item_dscr`` / ``vote_item_dscr``),
        ``vote_date``, ``is_accepted`` (1=passed) and the for/against/abstain
        totals — everything a :class:`VoteEvent` needs.
        """
        flt = f"vote_id eq {int(vote_id)}"
        for record in self.client.iter_entities(
            self.HEADER_SET, filter=flt, max_records=1
        ):
            return record
        logger.warning("Vote header vote_id=%s not found (Approved set)", vote_id)
        return None
