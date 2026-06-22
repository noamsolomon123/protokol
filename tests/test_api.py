"""API tests against the FastAPI app with an overridden in-memory DB session.

No network and no Postgres: the ``client`` fixture (see ``conftest.py``) overrides
``get_db`` so the app reads the same in-memory SQLite session the test seeds.

Covered:
* ``GET /health``                       -> ok (DB ``SELECT 1`` succeeds).
* ``GET /api/v1/politicians``           -> lists the seeded politician.
* ``GET /api/v1/politicians/{id}``      -> returns it (with related-record counts).
* ``GET /api/v1/politicians/{missing}`` -> 404.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from knesset_osint.models import Politician
from knesset_osint.models.enums import SourceType


@pytest.fixture()
def seeded_politician(db_session: Session) -> Politician:
    """Insert one fully-provenanced politician into the test session."""
    pol = Politician(
        knesset_person_id=965,
        first_name="בנימין",
        last_name="נתניהו",
        full_name="בנימין נתניהו",
        gender="זכר",
        email="pm@example.org",
        is_current=True,
        current_party="הליכוד",
        external_ids={"votes_mk_id": 965},
        source_type=SourceType.KNESSET_ODATA,
        source_name=SourceType.KNESSET_ODATA.value,
        source_url="https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)",
        source_record_id="965",
        raw_payload={"Id": 965},
        fetched_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )
    db_session.add(pol)
    db_session.commit()
    db_session.refresh(pol)
    return pol


def test_health_ok(client: TestClient) -> None:
    """``/health`` reports ok when the (in-memory) DB answers SELECT 1."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "neo4j" in body


def test_list_politicians_returns_seeded(
    client: TestClient, seeded_politician: Politician
) -> None:
    """``GET /api/v1/politicians`` returns the seeded politician in a Page envelope."""
    resp = client.get("/api/v1/politicians")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == seeded_politician.id
    assert item["full_name"] == "בנימין נתניהו"
    assert item["knesset_person_id"] == 965
    # Provenance surfaces on the wire (objectivity guarantee).
    assert item["source_url"].endswith("KNS_Person(965)")
    assert item["source_type"] == SourceType.KNESSET_ODATA.value


def test_list_politicians_search_filter(
    client: TestClient, seeded_politician: Politician
) -> None:
    """The ``q`` substring filter matches on full_name (and excludes non-matches)."""
    hit = client.get("/api/v1/politicians", params={"q": "נתניהו"})
    assert hit.status_code == 200
    assert hit.json()["total"] == 1

    miss = client.get("/api/v1/politicians", params={"q": "לא-קיים"})
    assert miss.status_code == 200
    assert miss.json()["total"] == 0


def test_get_politician_by_id(
    client: TestClient, seeded_politician: Politician
) -> None:
    """``GET /api/v1/politicians/{id}`` returns the entity plus zeroed counts."""
    resp = client.get(f"/api/v1/politicians/{seeded_politician.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == seeded_politician.id
    assert body["full_name"] == "בנימין נתניהו"
    # PoliticianDetail adds related-record counts (all zero for a bare seed).
    assert body["role_count"] == 0
    assert body["bill_count"] == 0
    assert body["vote_count"] == 0
    assert body["statement_count"] == 0
    assert body["action_count"] == 0


def test_get_missing_politician_is_404(client: TestClient) -> None:
    """A missing internal id returns 404 with a clear detail message."""
    resp = client.get("/api/v1/politicians/999999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
