"""Quick-start database initializer (alternative to Alembic migrations).

This creates every table directly from the ORM metadata via
``Base.metadata.create_all``. It is the fastest way to get a working schema for
local development, demos, or a fresh SQLite/Postgres database. For anything that
needs versioned, reversible schema changes (i.e. real deployments), use Alembic:

    python -m alembic upgrade head

When to use which
-----------------
* ``python scripts/init_db.py`` -> stamp the full current schema onto an EMPTY
  database in one shot. No migration history is recorded. Idempotent for tables
  that already exist (``create_all`` is a no-op on existing tables).
* Alembic                      -> incremental, reversible migrations with a
  recorded history (the ``alembic_version`` table). Preferred everywhere except
  throwaway/dev databases.

Configuration
-------------
The target database is ``settings.database_url`` (driven by the ``DATABASE_URL``
environment variable). To target a throwaway SQLite file with no Postgres:

    # Windows cmd
    set DATABASE_URL=sqlite:///./_quickstart.db && python scripts/init_db.py

Extending for more politicians / sources
----------------------------------------
This script needs no changes when the schema grows: importing
``knesset_osint.models`` registers every model on ``Base.metadata``, so any new
tables are created automatically on the next run.
"""

from __future__ import annotations

import sys

# Importing the models package registers all tables on Base.metadata. Without
# this import, create_all() would create nothing (or an incomplete schema).
import knesset_osint.models  # noqa: F401  (import for side effects)
from knesset_osint.core.config import settings
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.db.base import Base
from knesset_osint.db.session import engine

logger = get_logger(__name__)


def init_db() -> list[str]:
    """Create all tables from the ORM metadata. Returns the table names created/known.

    ``create_all`` only issues ``CREATE TABLE`` for tables that do not already
    exist, so running this repeatedly is safe.
    """
    # Redact credentials before logging the target (never print secrets).
    safe_target = _redact_url(settings.database_url)
    logger.info("Initializing database schema at %s", safe_target)

    Base.metadata.create_all(bind=engine)

    tables = sorted(Base.metadata.tables.keys())
    logger.info("Schema ready: %d tables", len(tables))
    return tables


def _redact_url(url: str) -> str:
    """Hide any ``user:password@`` portion of a SQLAlchemy URL for safe logging."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
    return url


def main() -> int:
    configure_logging(settings.log_level)
    tables = init_db()
    # Print to stdout so a human running the script sees the result directly.
    print(f"Created/verified {len(tables)} tables in {_redact_url(settings.database_url)}:")
    for name in tables:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
