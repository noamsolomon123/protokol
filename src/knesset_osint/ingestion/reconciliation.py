"""Cross-source id reconciliation.

ParliamentInfo (``KNS_Person.Id``) and the Votes service key members
*differently*, so before we can pull a politician's roll-call votes we must
resolve their **Votes MK id**. We do this by matching first+last name in the
Votes ``View_Vote_MK_Individual`` directory and persisting the result in
``Politician.external_ids['votes_mk_id']``. That stored mapping is what lets the
platform scale from one pilot MK to all 120 without re-resolving every run.

Objectivity note: we never guess an id. If the name can't be matched we leave the
mapping absent and return ``None`` — the pipeline then records a warning and
simply skips votes for that politician rather than attaching the wrong person's
record.

Extending to more politicians / sources
---------------------------------------
* More politicians: this function is fully name-driven; call it per politician.
* Another cross-source id (e.g. an Open Knesset ``mk_individual_id``): write a
  sibling ``reconcile_<source>_id`` that resolves and stores its own key under
  ``external_ids``. Keep the "match, then persist into external_ids" shape so the
  reconciliation map stays the single source of cross-source linkage.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm.attributes import flag_modified

from knesset_osint.core.logging import get_logger
from knesset_osint.models import Politician

logger = get_logger("knesset_osint.ingestion.reconciliation")

# The key under Politician.external_ids where the resolved Votes MK id lives.
VOTES_MK_ID_KEY = "votes_mk_id"


def _existing_votes_mk_id(politician: Politician) -> Optional[int]:
    """Return a previously-stored Votes MK id, if any (keeps runs idempotent)."""
    ext = politician.external_ids or {}
    raw = ext.get(VOTES_MK_ID_KEY)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def reconcile_votes_mk_id(
    session: Any,
    politician: Politician,
    votes_source: Any,
    *,
    force: bool = False,
) -> Optional[int]:
    """Resolve and persist a politician's Votes MK id.

    Looks up the id in the Votes ``View_Vote_MK_Individual`` directory by matching
    ``first_name`` + ``last_name`` (via ``votes_source.find_mk_id``), stores it in
    ``politician.external_ids['votes_mk_id']``, and returns it.

    Parameters
    ----------
    session:
        The active SQLAlchemy session (used to flush the updated ``external_ids``).
    politician:
        A persisted :class:`Politician` (must already have ``first_name`` /
        ``last_name`` populated by the person mapper).
    votes_source:
        A ``KnessetVotesSource`` (or any object exposing
        ``find_mk_id(first_name, last_name) -> (int | None, RawRecord | None)``).
    force:
        Re-resolve even if an id is already stored. Default ``False`` makes repeat
        runs cheap and idempotent (no needless directory scan).

    Returns
    -------
    The resolved Votes MK id as ``int``, or ``None`` if it couldn't be matched.
    """
    # Idempotency fast-path: reuse a previously-resolved id unless forced.
    if not force:
        cached = _existing_votes_mk_id(politician)
        if cached is not None:
            logger.debug(
                "votes_mk_id already reconciled for politician id=%s -> %s",
                politician.id,
                cached,
            )
            return cached

    first = (politician.first_name or "").strip()
    last = (politician.last_name or "").strip()
    if not first and not last:
        logger.warning(
            "Cannot reconcile votes_mk_id: politician id=%s has no name",
            politician.id,
        )
        return None

    try:
        mk_id, _record = votes_source.find_mk_id(first, last)
    except Exception as exc:  # defensive: never let reconciliation crash a run
        logger.warning(
            "votes_mk_id lookup failed for %r %r: %s", first, last, exc
        )
        return None

    if mk_id is None:
        logger.warning(
            "No Votes MK id matched for politician id=%s (%r %r)",
            politician.id,
            first,
            last,
        )
        return None

    # Persist into the JSON reconciliation map. Reassign a *new* dict so the
    # ORM/JSON column reliably detects the change; flag_modified is belt-and-braces
    # for in-place mutation cases.
    ext = dict(politician.external_ids or {})
    ext[VOTES_MK_ID_KEY] = int(mk_id)
    politician.external_ids = ext
    flag_modified(politician, "external_ids")
    session.flush()

    logger.info(
        "Reconciled votes_mk_id=%s for politician id=%s (%r %r)",
        mk_id,
        politician.id,
        first,
        last,
    )
    return int(mk_id)
