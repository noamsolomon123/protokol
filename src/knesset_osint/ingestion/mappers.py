"""Pure RawRecord -> ORM mappers (the provenance-preserving translation layer).

Every function here is a *pure* transform: it takes a :class:`RawRecord` (data +
provenance, produced by a source adapter) and returns a freshly-constructed,
unsaved ORM instance. The pipeline owns the session and the get-or-create logic;
mappers only *shape* data and *copy provenance*. Keeping this split makes the
mappers trivially unit-testable (no DB, no network) and keeps the objectivity
invariant in one obvious place.

Objectivity invariants enforced here
------------------------------------
* **Provenance on every row.** :func:`_apply_provenance` copies ``source_type``,
  ``source_url``, ``source_record_id``, ``raw_payload`` (the verbatim upstream
  dict) and ``fetched_at`` from the RawRecord onto every ORM instance. Nothing
  leaves a mapper without provenance.
* **Never fabricate.** Missing upstream values become ``None`` (NULL), never a
  guessed default. Dates that don't parse become ``None``.

Defensive reads
---------------
Upstream column names drift and differ between the V3/V4 feeds, so every field is
read via :func:`_first`, which tries a list of candidate keys and returns the
first present, non-None value. To support a new upstream column, just add its key
to the relevant candidate list.

Extending to more sources / politicians
---------------------------------------
* New entity (e.g. a committee membership): add a ``map_<thing>(rec, ...)``
  function that builds the ORM row and calls :func:`_apply_provenance` before
  returning it. Follow the existing shape exactly.
* New politician: nothing changes here — mappers are person-agnostic. The
  pipeline passes the resolved ``politician_id`` / ``vote_event_id`` in.
* New upstream key for an existing field: append it to the candidate-key list in
  the relevant mapper. Order matters (most-specific / most-trusted first).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from knesset_osint.ingestion.sources.base import RawRecord
from knesset_osint.models import Bill, Politician, Role, Vote, VoteEvent
from knesset_osint.models.enums import VoteResult, VoteStance

__all__ = [
    "map_person",
    "map_bill",
    "map_role",
    "map_vote_header",
    "map_mk_vote",
    "stance_from_value",
    "result_from_header",
]


# ---------------------------------------------------------------------------
# Small, dependency-free helpers
# ---------------------------------------------------------------------------
def _first(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-None value among ``keys`` (defensive read).

    Upstream feeds rename/case-shift columns; passing several candidate keys lets
    one mapper survive that drift. Returns ``None`` if none of the keys are set.
    """
    for key in keys:
        if key in data:
            val = data.get(key)
            if val is not None:
                return val
    return None


def _to_int(value: Any) -> Optional[int]:
    """Best-effort int coercion; ``None`` on missing/garbage (never fabricate)."""
    if value is None:
        return None
    if isinstance(value, bool):
        # Guard: bool is an int subclass; we never want True/False -> 1/0 here.
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            # Some feeds send "965.0"; accept that, reject true floats-as-ids.
            return int(float(s))
        except ValueError:
            return None


def _to_bool(value: Any) -> Optional[bool]:
    """Coerce common truthy/falsey upstream encodings to a bool, else ``None``.

    Handles native bools, numeric flags (1/0), and string flags
    ("true"/"false"/"yes"/"no"/"1"/"0"). Unknown -> ``None`` so callers can
    decide a default rather than us silently picking one.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "y", "t"}:
        return True
    if s in {"false", "0", "no", "n", "f"}:
        return False
    return None


def _clean_str(value: Any) -> Optional[str]:
    """Trim a string; turn empty/whitespace into ``None`` (don't store blanks)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_date(value: Any) -> Optional[date]:
    """Parse an OData datetime/date string into a :class:`datetime.date`.

    Handles the shapes the Knesset feeds actually emit, and degrades to ``None``
    (never a fabricated date) on anything it can't confidently parse:

    * ISO-8601 with offset / 'Z' / microseconds:
      ``2023-12-31T09:30:00+02:00`` / ``...Z`` / ``...``.
    * Plain dates: ``2023-12-31``.
    * Legacy OData V2/V3 ``/Date(1234567890000)/`` epoch-millis tick syntax
      (some .svc endpoints still serialise dates this way).
    * Already-typed :class:`datetime`/:class:`date` objects pass straight
      through.

    To support another upstream date shape, add a branch here; everything else in
    the codebase routes dates through this single helper.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = str(value).strip()
    if not s:
        return None

    # Legacy Microsoft/OData tick syntax: /Date(1700000000000+0200)/
    if s.startswith("/Date(") and s.endswith(")/"):
        inner = s[len("/Date(") : -len(")/")]
        # Strip a trailing timezone offset like +0200 / -0500.
        for i, ch in enumerate(inner):
            if i > 0 and ch in "+-":
                inner = inner[:i]
                break
        try:
            millis = int(inner)
            return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            return None

    # Normalise a trailing 'Z' to an explicit UTC offset for fromisoformat.
    iso = s
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass

    # Last resort: take the date portion of a 'YYYY-MM-DD...' string.
    head = s[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _apply_provenance(obj: Any, rec: RawRecord) -> Any:
    """Copy the RawRecord's provenance onto an ORM instance and return it.

    This is the single chokepoint that guarantees the platform's core invariant:
    *every stored row knows where it came from*. ``raw_payload`` keeps the verbatim
    upstream dict so a human reviewer can always re-derive any field.
    """
    obj.source_type = rec.source_type
    # source_name records the logical feed; the adapter's RawRecord doesn't carry
    # it, so we derive a stable, human-readable label from the source_type value.
    obj.source_name = rec.source_type.value
    obj.source_url = rec.source_url
    obj.source_record_id = rec.source_record_id
    obj.raw_payload = rec.data
    obj.fetched_at = rec.fetched_at
    return obj


# ---------------------------------------------------------------------------
# Stance / result vocabulary mapping (defensive: Hebrew / English / codes)
# ---------------------------------------------------------------------------
# Verified upstream numeric vote_result codes (vote_result_type lookup, 2026-06-20):
#   0=בוטל(cancelled) 1=בעד(for) 2=נגד(against) 3=נמנע(abstain) 4=לא הצביע(absent).
_STANCE_BY_CODE: dict[int, VoteStance] = {
    0: VoteStance.NA,        # בוטל  (vote cancelled / not a real stance)
    1: VoteStance.FOR,       # בעד
    2: VoteStance.AGAINST,   # נגד
    3: VoteStance.ABSTAIN,   # נמנע
    4: VoteStance.ABSENT,    # לא הצביע
}

# Free-text encodings we might also see (Hebrew labels from the lookup table, and
# English fallbacks). Keys are lower-cased/stripped before lookup.
_STANCE_BY_TEXT: dict[str, VoteStance] = {
    # Hebrew (from vote_result_type)
    "בעד": VoteStance.FOR,
    "נגד": VoteStance.AGAINST,
    "נמנע": VoteStance.ABSTAIN,
    "נמנעים": VoteStance.ABSTAIN,
    "לא הצביע": VoteStance.ABSENT,
    "לא השתתף": VoteStance.ABSENT,
    "נעדר": VoteStance.ABSENT,
    "בוטל": VoteStance.NA,
    # English fallbacks
    "for": VoteStance.FOR,
    "in favor": VoteStance.FOR,
    "favor": VoteStance.FOR,
    "yes": VoteStance.FOR,
    "aye": VoteStance.FOR,
    "against": VoteStance.AGAINST,
    "no": VoteStance.AGAINST,
    "nay": VoteStance.AGAINST,
    "abstain": VoteStance.ABSTAIN,
    "abstention": VoteStance.ABSTAIN,
    "absent": VoteStance.ABSENT,
    "did not vote": VoteStance.ABSENT,
    "cancelled": VoteStance.NA,
    "canceled": VoteStance.NA,
    "na": VoteStance.NA,
}


def stance_from_value(value: Any) -> VoteStance:
    """Map any upstream vote decision (code / Hebrew / English) to a VoteStance.

    Tries, in order: a native VoteStance, a numeric ``vote_result`` code (the
    common case), then a free-text label (Hebrew or English). Unknown/missing
    values fall back to :attr:`VoteStance.NA` rather than guessing a real stance —
    we never assert how someone voted when the source is unclear.

    To support a new encoding, add it to :data:`_STANCE_BY_CODE` (numeric) or
    :data:`_STANCE_BY_TEXT` (label).
    """
    if value is None:
        return VoteStance.NA
    if isinstance(value, VoteStance):
        return value

    code = _to_int(value)
    if code is not None and code in _STANCE_BY_CODE:
        return _STANCE_BY_CODE[code]

    text = str(value).strip().lower()
    if text in _STANCE_BY_TEXT:
        return _STANCE_BY_TEXT[text]

    return VoteStance.NA


def result_from_header(data: dict[str, Any]) -> VoteResult:
    """Derive a :class:`VoteResult` from a vote-header row.

    ``View_vote_rslts_hdr_Approved`` carries ``is_accepted`` (1=passed, 0=failed).
    We also accept a couple of textual fallbacks. Anything we can't read becomes
    :attr:`VoteResult.UNKNOWN` (never a fabricated outcome).
    """
    accepted = _first(data, "is_accepted", "IsAccepted", "accepted")
    flag = _to_bool(accepted)
    if flag is True:
        return VoteResult.PASSED
    if flag is False:
        return VoteResult.FAILED
    return VoteResult.UNKNOWN


# ---------------------------------------------------------------------------
# ParliamentInfo OData V4 mappers (source of truth: persons, bills, roles)
# ---------------------------------------------------------------------------
def map_person(rec: RawRecord) -> Politician:
    """Map a ``KNS_Person`` RawRecord -> an (unsaved) :class:`Politician`.

    Verified V4 fields: Id, LastName, FirstName, GenderDesc, Email, IsCurrent.
    ``full_name`` is composed as ``FirstName + " " + LastName`` (Hebrew order);
    if one part is missing we use whatever is present rather than inventing one.
    """
    data = rec.data
    first = _clean_str(_first(data, "FirstName", "first_name"))
    last = _clean_str(_first(data, "LastName", "last_name"))
    full_name = " ".join(p for p in (first, last) if p) or ""

    politician = Politician(
        knesset_person_id=_to_int(_first(data, "Id", "ID", "id", "PersonID")),
        first_name=first,
        last_name=last,
        full_name=full_name,
        gender=_clean_str(_first(data, "GenderDesc", "Gender", "gender")),
        email=_clean_str(_first(data, "Email", "email")),
        is_current=bool(_to_bool(_first(data, "IsCurrent", "is_current")) or False),
        external_ids={},
    )
    return _apply_provenance(politician, rec)


def map_bill(rec: RawRecord) -> Bill:
    """Map a ``KNS_Bill`` RawRecord -> an (unsaved) :class:`Bill`.

    Verified-ish V4 fields: Id, Name, KnessetNum, SubTypeDesc, StatusID. Status is
    read from a description column when present (StatusDesc) or coerced from
    StatusID as a string fallback. Missing values stay NULL.
    """
    data = rec.data
    status = _first(data, "StatusDesc", "status_desc", "StatusID", "StatusId")
    bill = Bill(
        knesset_bill_id=_to_int(_first(data, "Id", "ID", "id", "BillID")),
        name=_clean_str(_first(data, "Name", "BillName", "name")),
        bill_type_desc=_clean_str(
            _first(data, "SubTypeDesc", "BillTypeDesc", "TypeDesc", "bill_type_desc")
        ),
        status_desc=_clean_str(status),
        knesset_num=_to_int(_first(data, "KnessetNum", "knesset_num")),
        summary=_clean_str(_first(data, "Summary", "summary")),
    )
    return _apply_provenance(bill, rec)


def map_role(rec: RawRecord, politician_id: int) -> Role:
    """Map a ``KNS_PersonToPosition`` RawRecord -> an (unsaved) :class:`Role`.

    Verified V4 fields: Id, PersonID, PositionID, KnessetNum, StartDate, FinishDate,
    GovMinistryID, GovMinistryName, DutyDesc, FactionID, FactionName, GovernmentNum,
    CommitteeID, CommitteeName, IsCurrent. The owning ``politician_id`` is supplied
    by the pipeline (after it has upserted the person).
    """
    data = rec.data
    role = Role(
        politician_id=politician_id,
        position_id=_to_int(_first(data, "PositionID", "PositionId", "position_id")),
        position_desc=_clean_str(
            _first(data, "DutyDesc", "PositionDesc", "position_desc")
        ),
        knesset_num=_to_int(_first(data, "KnessetNum", "knesset_num")),
        government_num=_to_int(_first(data, "GovernmentNum", "government_num")),
        ministry_name=_clean_str(
            _first(data, "GovMinistryName", "MinistryName", "ministry_name")
        ),
        faction_name=_clean_str(_first(data, "FactionName", "faction_name")),
        committee_name=_clean_str(_first(data, "CommitteeName", "committee_name")),
        start_date=_parse_date(_first(data, "StartDate", "start_date")),
        finish_date=_parse_date(_first(data, "FinishDate", "finish_date")),
        is_current=bool(_to_bool(_first(data, "IsCurrent", "is_current")) or False),
    )
    return _apply_provenance(role, rec)


# ---------------------------------------------------------------------------
# Votes.svc OData V3 mappers (source of truth: vote headers + per-MK stances)
# ---------------------------------------------------------------------------
def map_vote_header(rec: RawRecord) -> VoteEvent:
    """Map a ``View_vote_rslts_hdr_Approved`` RawRecord -> an unsaved VoteEvent.

    Verified V3 fields: vote_id, knesset_num, session_id, sess_item_dscr (title),
    vote_item_dscr (sub-title), vote_date, is_accepted, total_for, total_against,
    total_abstain, session_num. Title prefers the more specific ``vote_item_dscr``
    then falls back to ``sess_item_dscr``. Outcome comes from
    :func:`result_from_header`; counts/dates stay NULL when absent.
    """
    data = rec.data
    title = _clean_str(
        _first(data, "vote_item_dscr", "sess_item_dscr", "title", "Title")
    )
    event = VoteEvent(
        knesset_vote_id=_to_int(_first(data, "vote_id", "VoteId", "id", "Id")),
        title=title,
        vote_date=_parse_date(_first(data, "vote_date", "VoteDate", "date")),
        knesset_num=_to_int(_first(data, "knesset_num", "KnessetNum")),
        session_num=_to_int(_first(data, "session_num", "SessionNum", "session_id")),
        result=result_from_header(data),
        total_for=_to_int(_first(data, "total_for", "TotalFor")),
        total_against=_to_int(_first(data, "total_against", "TotalAgainst")),
        total_abstain=_to_int(_first(data, "total_abstain", "TotalAbstain")),
    )
    return _apply_provenance(event, rec)


def map_mk_vote(
    rec: RawRecord,
    politician_id: int,
    vote_event_id: int,
    stance: VoteStance,
) -> Vote:
    """Map a ``vote_rslts_kmmbr_shadow`` RawRecord -> an unsaved :class:`Vote`.

    The pipeline supplies the already-resolved ``politician_id`` and
    ``vote_event_id`` (from upserting the person and the vote header) and the
    ``stance`` (computed via :func:`stance_from_value` from the row's
    ``vote_result``). Keeping stance mapping out of this function keeps it a pure
    assembler; provenance still flows from the per-MK shadow row.
    """
    vote = Vote(
        politician_id=politician_id,
        vote_event_id=vote_event_id,
        stance=stance if isinstance(stance, VoteStance) else stance_from_value(stance),
    )
    return _apply_provenance(vote, rec)
