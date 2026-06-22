"""Command-line interface for the Knesset OSINT platform.

Exposed as the ``knesset-osint`` console script (see ``pyproject.toml``:
``knesset-osint = "knesset_osint.cli:app"``). Run ``knesset-osint --help``.

Commands
--------
* ``init-db``  create all tables from the ORM metadata (dev quick-start).
* ``ingest``   run the ingestion pipeline for one politician (default: the pilot,
               Netanyahu / KNS_Person.Id 965) and print the IngestionReport.
* ``info``     print the configured sources and pilot scope.

Scaling: ``ingest --person-id <KNS_Person.Id>`` works for any MK, so onboarding
the rest of the Knesset is a loop over ids, not a code change.
"""

from __future__ import annotations

import typer

from knesset_osint.core.config import settings
from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger

app = typer.Typer(
    name="knesset-osint",
    help="Objective OSINT platform for Israeli politicians (pilot: Netanyahu / Likud).",
    no_args_is_help=True,
    add_completion=False,
)

logger = get_logger("cli")


@app.callback()
def _main() -> None:
    """Runs before every command: make Hebrew output render on Windows consoles."""
    enable_utf8_console()


@app.command("init-db")
def init_db_command() -> None:
    """Create all database tables from the ORM metadata (idempotent).

    Delegates to ``scripts/init_db.py`` logic so there's a single source of truth
    for schema creation. For versioned migrations use Alembic instead.
    """
    configure_logging(settings.log_level)
    # Imported lazily so ``--help`` and other commands don't touch the DB engine.
    from scripts.init_db import init_db

    tables = init_db()
    typer.echo(f"Created/verified {len(tables)} tables:")
    for name in tables:
        typer.echo(f"  - {name}")


@app.command("ingest")
def ingest_command(
    person_id: int = typer.Option(
        settings.pilot_person_id,
        "--person-id",
        help="ParliamentInfo KNS_Person.Id to ingest (default: pilot = Netanyahu).",
    ),
    no_votes: bool = typer.Option(
        False,
        "--no-votes",
        help="Skip the Votes.svc ingestion step (persons/bills/roles only).",
    ),
) -> None:
    """Ingest one politician end-to-end and print the resulting IngestionReport.

    Opens a single ``SessionLocal`` transaction-scoped session and hands it to
    the ingestion pipeline (owned by the ingestion layer). On success the report
    is committed; on failure the session is rolled back and the error re-raised.
    """
    configure_logging(settings.log_level)

    # Imported lazily: the ingestion pipeline is a separate module; importing it
    # here keeps the CLI importable (e.g. for ``info``) even mid-build, and only
    # pays the import cost when actually ingesting.
    from knesset_osint.db.session import SessionLocal
    from knesset_osint.ingestion import ingest_politician

    db = SessionLocal()
    try:
        report = ingest_politician(db, person_id=person_id, include_votes=not no_votes)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Ingestion failed for person_id=%s", person_id)
        raise typer.Exit(code=1)
    finally:
        db.close()

    typer.echo(report)


@app.command("info")
def info_command() -> None:
    """Print the configured data sources and pilot scope (no network calls)."""
    typer.echo(f"{settings.app_name} (env={settings.environment})")
    typer.echo("")
    typer.echo("Configured sources:")
    typer.echo(f"  ParliamentInfo OData V4 : {settings.knesset_odata_v4_base}")
    typer.echo(f"  Votes OData V3 (.svc)   : {settings.knesset_votes_svc_base}")
    typer.echo(f"  Open Knesset pipelines  : {settings.open_knesset_pipelines_base}")
    typer.echo(f"  Knesset data (GCS)      : {settings.knesset_data_gcs_base}")
    typer.echo(
        "  Open Knesset enrichment : "
        f"{'enabled' if settings.enable_open_knesset_enrichment else 'disabled'}"
    )
    typer.echo("")
    typer.echo("Pilot scope:")
    typer.echo(f"  person_id : {settings.pilot_person_id}")
    typer.echo(f"  party     : {settings.pilot_party_he} ({settings.pilot_party_en})")


if __name__ == "__main__":  # pragma: no cover
    app()
