"""Seed the database with the pilot politician (LIVE ingest end-to-end).

This is the one-command bootstrap that turns an empty database into a working
pilot dataset. It:

1. ensures every table exists (``Base.metadata.create_all`` — safe to re-run),
2. opens a real :data:`SessionLocal` against ``settings.database_url``,
3. runs the idempotent ingestion pipeline for ``settings.pilot_person_id``
   (Benjamin Netanyahu, 965): person -> roles -> bills -> votes (+ optional
   enrichment),
4. prints the :class:`IngestionReport` (per-entity counts + any warnings).

It makes **real network calls** (the pipeline pulls from the live Knesset feeds)
and **writes to the configured database**. Point ``DATABASE_URL`` at a throwaway
SQLite file to try it without Postgres::

    # Windows cmd
    set DATABASE_URL=sqlite:///./_pilot.db && python scripts/seed_pilot.py

The run is idempotent: every write is a get-or-create on a natural key / unique
constraint, so running it twice produces no duplicates (it just refreshes
provenance). Re-runs are the intended way to keep the pilot current.

Extending to more politicians
-----------------------------
``ingest_politician`` is parameterised by ``KNS_Person.Id``; to seed more MKs,
loop over a list of ids and call it once per id (the schema and pipeline need no
other change). The pilot id is just the default.
"""

from __future__ import annotations

import sys

# Importing the models package registers every table on Base.metadata so that
# create_all() builds the full schema (without this, tables would be missing).
import knesset_osint.models  # noqa: F401  (import for side effects)
from knesset_osint.core.config import settings
from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.db.base import Base
from knesset_osint.db.session import SessionLocal, engine
from knesset_osint.ingestion.pipeline import IngestionReport, ingest_politician

logger = get_logger("scripts.seed_pilot")


def _print_report(report: IngestionReport) -> None:
    """Print a human-readable summary of an ingestion run."""
    bar = "=" * 64
    print(bar)
    print("PILOT INGESTION REPORT")
    print(bar)
    print(f"  politician_id : {report.politician_id}")
    print(f"  persons       : {report.persons}")
    print(f"  roles         : {report.roles}")
    print(f"  bills         : {report.bills}")
    print(f"  sponsorships  : {report.sponsorships}")
    print(f"  vote_events   : {report.vote_events}")
    print(f"  votes         : {report.votes}")
    print(f"  warnings      : {len(report.warnings)}")
    for w in report.warnings:
        print(f"      - {w}")
    print(bar)


def seed_pilot() -> IngestionReport:
    """Create tables (if needed) and ingest the pilot politician. Returns the report."""
    # 1) Ensure the schema exists. create_all is a no-op for existing tables, so
    #    this is safe to run against an already-initialised database.
    logger.info("Ensuring schema exists (create_all)...")
    Base.metadata.create_all(bind=engine)

    # 2) Run the idempotent pipeline in a single owned session.
    session = SessionLocal()
    try:
        logger.info("Ingesting pilot person_id=%s ...", settings.pilot_person_id)
        report = ingest_politician(session, settings.pilot_person_id)
        return report
    finally:
        session.close()


def main() -> int:
    enable_utf8_console()  # render Hebrew correctly on the Windows console
    configure_logging(settings.log_level)
    report = seed_pilot()
    _print_report(report)
    # Surface a non-zero exit if the run produced no politician (hard failure),
    # while warnings alone (soft, per-record issues) still count as success.
    if report.politician_id is None:
        print("ERROR: pilot ingestion produced no politician (see warnings).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
