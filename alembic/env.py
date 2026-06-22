"""Alembic migration environment for the Knesset OSINT platform.

Responsibilities
----------------
1. Make ``Base.metadata`` complete by importing ``knesset_osint.models`` (that
   package imports every model module, registering all 9 tables on the shared
   ``Base.metadata``). Autogenerate diffs the database against this metadata, so
   it MUST be fully populated before ``run_migrations_*`` is called.
2. Resolve the database URL from configuration, never from ``alembic.ini``
   (objectivity/security invariant: no secrets in source). Order of precedence:
       a. ``DATABASE_URL`` environment variable (lets you point at a throwaway
          SQLite db for autogenerate without a running Postgres);
       b. ``settings.database_url`` (the app's configured default).
3. Support both *offline* (emit SQL to stdout, no DB connection) and *online*
   (connect + apply) modes.

Extending for more politicians / sources
----------------------------------------
New tables/columns are added to the ORM models under ``knesset_osint.models``;
because this file imports the whole ``models`` package, they appear in
``target_metadata`` automatically. Just create a new revision with
``python -m alembic revision --autogenerate -m "add X"`` and review it.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importing the models package registers every table on Base.metadata.
import knesset_osint.models  # noqa: F401  (import for side effects)
from knesset_osint.core.config import settings
from knesset_osint.db.base import Base

# Alembic Config object — provides access to values within alembic.ini.
config = context.config

# Configure Python logging from the .ini, if a config file is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata autogenerate diffs against. All models are imported above, so
# this is the complete schema (politicians, roles, bills, bill_sponsorships,
# vote_events, votes, statements, actions, contradictions).
target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve the DB URL: env override first, then app settings.

    Keeping the URL out of alembic.ini means migrations honor the same
    configuration as the running app and never embed credentials in source.
    """
    return os.environ.get("DATABASE_URL") or settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no live DB connection).

    Useful for generating a SQL script to hand to a DBA:
        python -m alembic upgrade head --sql
    """
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Detect column type changes during autogenerate/diff.
        compare_type=True,
        # Render server-side defaults so they round-trip in generated scripts.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the DB and apply)."""
    # Build an engine config from alembic.ini, then inject the resolved URL so
    # the (intentionally blank) sqlalchemy.url in the .ini is never used.
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        # render_as_batch=True enables SQLite-friendly "batch" ALTER TABLE
        # operations, so the same migrations apply on the temp SQLite db used
        # for autogenerate AND on production Postgres.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
