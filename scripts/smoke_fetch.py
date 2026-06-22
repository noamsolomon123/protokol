"""LIVE smoke test: prove the ingestion pipeline pulls REAL Knesset data.

This script makes **real network calls** to the official open Knesset OData
feeds and prints a human-readable summary. It writes **nothing** to a database
-- it only *reads* and *reports*, so it is safe to run anywhere with internet
access and proves end-to-end that the source adapters work against the live APIs.

What it does (for the pilot, Benjamin Netanyahu, KNS_Person.Id=965)
-------------------------------------------------------------------
1. ParliamentInfo OData V4 (``KnessetParliamentInfoSource``):
   * fetch the person row (name, gender, current flag),
   * count their bill initiations and fetch one bill's detail,
   * count their official positions/roles.
2. Votes OData V3 (``KnessetVotesSource``):
   * reconcile the politician's Votes MK id by matching first+last name,
   * fetch a sample of their roll-call votes and one vote's header (title/date).

Exit codes
----------
* ``0`` on success (real data fetched and summarised).
* non-zero with a clear ``ERROR:`` message on any failure (e.g. no network,
  the person not found, or an upstream shape we couldn't read).

Extending to more politicians / sources
---------------------------------------
* Other MKs: pass a different ``KNS_Person.Id`` via ``--person-id`` (or change
  ``settings.pilot_person_id``). Nothing here is hardcoded to Netanyahu beyond
  the default.
* More fields/sources: every adapter method already returns ``RawRecord``s; add
  another adapter call and print its result the same way.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from knesset_osint.core.config import settings
from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging
from knesset_osint.ingestion.mappers import (
    map_bill,
    map_person,
    map_vote_header,
    stance_from_value,
)
from knesset_osint.ingestion.sources.knesset_odata import KnessetParliamentInfoSource
from knesset_osint.ingestion.sources.knesset_votes import KnessetVotesSource


class SmokeError(RuntimeError):
    """Raised on any condition that should fail the smoke test loudly."""


def _hr(char: str = "-", width: int = 64) -> str:
    return char * width


def smoke(person_id: int, *, sample_votes: int = 5) -> None:
    """Run the live, read-only smoke test for one politician.

    Raises :class:`SmokeError` with a clear message on any failure so ``main``
    can turn it into a non-zero exit + a human-readable ``ERROR:`` line.
    """
    print(_hr("="))
    print("KNESSET OSINT — LIVE SMOKE TEST (fetch-only, no database)")
    print(f"ParliamentInfo V4 : {settings.knesset_odata_v4_base}")
    print(f"Votes V3 (.svc)   : {settings.knesset_votes_svc_base}")
    print(f"Pilot person id   : {person_id}")
    print(_hr("="))

    # --- ParliamentInfo V4: person, bills, roles ---------------------------
    with KnessetParliamentInfoSource() as odata:
        person_rec = odata.get_person(person_id)
        if person_rec is None:
            raise SmokeError(
                f"KNS_Person Id={person_id} not found on the live ParliamentInfo "
                "feed (check the id or network connectivity)."
            )
        # map_person is a pure transform; we use it only to read fields cleanly.
        politician = map_person(person_rec)
        print("\n[1] PERSON (ParliamentInfo V4, source of truth)")
        print(f"    full_name        : {politician.full_name}")
        print(f"    first / last     : {politician.first_name} / {politician.last_name}")
        print(f"    knesset_person_id: {politician.knesset_person_id}")
        print(f"    gender           : {politician.gender}")
        print(f"    is_current       : {politician.is_current}")
        print(f"    source_url       : {person_rec.source_url}")

        # Bill initiations: count them, then resolve one bill's detail.
        initiations = list(odata.iter_bill_initiations(person_id))
        bills_count = len(initiations)
        print("\n[2] BILL INITIATIONS (KNS_BillInitiator)")
        print(f"    initiations found: {bills_count}")
        if bills_count == 0:
            raise SmokeError(
                f"Expected at least one bill initiation for person {person_id}; "
                "got none (upstream shape change or wrong id?)."
            )

        # Resolve the first bill we can read a BillID from.
        sample_bill_name: Optional[str] = None
        for init_rec in initiations:
            bill_kns_id = _first_int(init_rec.data, "BillID", "BillId", "bill_id")
            if bill_kns_id is None:
                continue
            bill_rec = odata.get_bill(bill_kns_id)
            if bill_rec is not None:
                bill = map_bill(bill_rec)
                sample_bill_name = bill.name
                print("\n[3] SAMPLE BILL (KNS_Bill detail)")
                print(f"    bill id          : {bill.knesset_bill_id}")
                print(f"    name             : {bill.name}")
                print(f"    type             : {bill.bill_type_desc}")
                print(f"    knesset_num      : {bill.knesset_num}")
                print(f"    source_url       : {bill_rec.source_url}")
                break
        if sample_bill_name is None:
            raise SmokeError(
                "Could not resolve any KNS_Bill detail from the initiations "
                "(no readable BillID, or bills not found upstream)."
            )

        # Roles / positions: just a count proves the positions endpoint works.
        positions = list(odata.iter_positions(person_id))
        print("\n[4] POSITIONS / ROLES (KNS_PersonToPosition)")
        print(f"    positions found  : {len(positions)}")

    # --- Votes V3: reconcile MK id + sample a vote -------------------------
    first = politician.first_name or ""
    last = politician.last_name or ""
    with KnessetVotesSource() as votes:
        mk_id, mk_rec = votes.find_mk_id(first, last)
        print("\n[5] VOTES MK RECONCILIATION (View_Vote_MK_Individual)")
        if mk_id is None:
            raise SmokeError(
                f"Could not reconcile a Votes MK id for {first!r} {last!r} "
                "in the live Votes directory (name mismatch / column drift)."
            )
        print(f"    matched votes_mk_id: {mk_id}")
        if mk_rec is not None:
            print(f"    directory source_url: {mk_rec.source_url}")

        sample = list(votes.iter_mk_votes(mk_id, max_records=sample_votes))
        print("\n[6] SAMPLE ROLL-CALL VOTES (vote_rslts_kmmbr_shadow)")
        print(f"    sample size       : {len(sample)} (capped at {sample_votes})")
        if not sample:
            raise SmokeError(
                f"No roll-call votes returned for votes_mk_id={mk_id} "
                "(upstream shape change or empty record)."
            )

        # Resolve one vote's header to prove the header join works too.
        for vote_rec in sample:
            vote_kns_id = _first_int(vote_rec.data, "vote_id", "VoteId", "VoteID")
            raw_result = vote_rec.data.get("vote_result")
            stance = stance_from_value(raw_result)
            if vote_kns_id is None:
                continue
            header_rec = votes.get_vote_header(vote_kns_id)
            print("\n[7] SAMPLE VOTE DETAIL")
            print(f"    vote_id          : {vote_kns_id}")
            print(f"    stance (mapped)  : {stance.value}")
            if header_rec is not None:
                event = map_vote_header(header_rec)
                print(f"    title            : {event.title}")
                print(f"    vote_date        : {event.vote_date}")
                print(f"    result           : {event.result.value}")
                print(f"    header source_url: {header_rec.source_url}")
            break

    # --- Summary ----------------------------------------------------------
    print("\n" + _hr("="))
    print("SUMMARY")
    print(f"  Politician     : {politician.full_name} (kns={politician.knesset_person_id})")
    print(f"  Bill initiations: {bills_count}")
    print(f"  Sample bill    : {sample_bill_name}")
    print(f"  Votes MK id    : {mk_id}")
    print(f"  Votes sampled  : {len(sample)}")
    print("  RESULT         : OK — live pipeline pulled REAL data from official feeds.")
    print(_hr("="))


def _first_int(data: dict, *keys: str) -> Optional[int]:
    """Return the first present, int-coercible value among ``keys`` (defensive)."""
    for key in keys:
        val = data.get(key)
        if val is None:
            continue
        try:
            return int(str(val).strip())
        except (TypeError, ValueError):
            continue
    return None


def main() -> int:
    enable_utf8_console()  # render Hebrew correctly on the Windows console
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--person-id",
        type=int,
        default=settings.pilot_person_id,
        help=f"KNS_Person.Id to probe (default: pilot {settings.pilot_person_id}).",
    )
    parser.add_argument(
        "--sample-votes",
        type=int,
        default=5,
        help="How many roll-call votes to sample (default: 5).",
    )
    args = parser.parse_args()

    configure_logging(settings.log_level)
    try:
        smoke(args.person_id, sample_votes=args.sample_votes)
    except SmokeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # network/parse/etc. — fail loudly with context
        print(f"\nERROR: live smoke test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
