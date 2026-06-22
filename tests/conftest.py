"""Shared pytest fixtures: an in-memory SQLite DB, a Session, and a TestClient.

No network and no Postgres: every test runs against a fresh, in-memory SQLite
engine with the full ORM schema created via ``Base.metadata.create_all``. The
FastAPI app's ``get_db`` dependency is overridden to yield the *same* test
session so API tests see exactly what the test seeded.

Design notes
------------
* ``StaticPool`` + a single shared connection keep one in-memory database alive
  for the whole test (each new SQLite ``:memory:`` connection is otherwise a
  separate, empty DB).
* The dependency override targets ``knesset_osint.db.session.get_db`` — the same
  function object the routers depend on (``api.deps`` merely re-exports it), so
  the override is guaranteed to take effect.
* Importing ``knesset_osint.models`` registers every table on ``Base.metadata``
  before ``create_all`` runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Import models for side effects: registers all tables on Base.metadata.
import knesset_osint.models  # noqa: F401
from knesset_osint.db.base import Base
from knesset_osint.db.session import get_db


@pytest.fixture()
def engine():
    """A fresh in-memory SQLite engine with the full schema, per test.

    ``StaticPool`` makes every connection reuse the one underlying ``:memory:``
    database so the schema created here is visible to the session and the API.
    """
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    """A SQLAlchemy ``Session`` bound to the in-memory engine (test-scoped)."""
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """A FastAPI ``TestClient`` with ``get_db`` overridden to the test session.

    The override yields the *same* ``db_session`` the test uses, so anything the
    test writes is immediately visible to the API (and vice versa).
    """
    # Imported lazily so the app (which builds a Postgres engine at import time,
    # lazily — no connection is opened) is only constructed when a test needs it.
    from knesset_osint.main import app

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
