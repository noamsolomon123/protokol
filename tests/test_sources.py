"""Source-adapter tests with respx (mocked HTTP — no real network).

These prove the shared ``ODataClient`` correctly drives both flavours of OData
paging, and that a concrete adapter method (``get_person``) returns a
``RawRecord`` carrying the right provenance:

* V4 (ParliamentInfo): server-driven paging via the absolute ``@odata.nextLink``.
* V3 (Votes.svc): server-driven paging via the (possibly relative) ``odata.nextLink``.
* Provenance: ``get_person`` yields a ``RawRecord`` whose ``source_type`` /
  ``source_url`` / ``source_record_id`` are set from the response.

respx intercepts httpx, so nothing leaves the process. We always return a JSON
``content-type`` because ``ODataClient._get`` treats non-JSON 200s as a
(retryable) failure — a guard against bot-challenge HTML pages.
"""

from __future__ import annotations

import httpx
import respx

from knesset_osint.ingestion.sources.base import ODataClient, RawRecord
from knesset_osint.ingestion.sources.knesset_odata import KnessetParliamentInfoSource
from knesset_osint.models.enums import SourceType

# Bases mirror the live endpoints (and the config defaults). They are only used
# as mock targets here — no real request is ever made.
V4_BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
V3_BASE = "https://knesset.gov.il/Odata/Votes.svc"

_JSON = {"content-type": "application/json"}


@respx.mock
def test_v4_paging_follows_odata_at_nextlink() -> None:
    """V4 server-driven paging: follow the absolute ``@odata.nextLink`` to page 2.

    A single responder keyed on the request URL emulates a real server: page 1
    (no ``$skiptoken``) returns an absolute ``@odata.nextLink``; page 2 (with the
    skiptoken) is terminal. This avoids respx path-only routes ambiguously
    matching BOTH requests (which would loop forever).
    """
    entity = "KNS_Person"
    next_url = f"{V4_BASE}/{entity}?$skiptoken=page2"

    def responder(request: httpx.Request) -> httpx.Response:
        if "$skiptoken" in request.url.query.decode():
            # Page 2: terminal (no nextLink, short page).
            return httpx.Response(200, json={"value": [{"Id": 3, "LastName": "ג"}]}, headers=_JSON)
        # Page 1: carries an ABSOLUTE @odata.nextLink (the V4 shape).
        return httpx.Response(
            200,
            json={
                "value": [{"Id": 1, "LastName": "א"}, {"Id": 2, "LastName": "ב"}],
                "@odata.nextLink": next_url,
            },
            headers=_JSON,
        )

    respx.get(url__startswith=f"{V4_BASE}/{entity}").mock(side_effect=responder)

    client = ODataClient(V4_BASE, SourceType.KNESSET_ODATA, odata_version=4, page_size=2)
    records = list(client.iter_entities(entity))
    client.close()

    assert [r.data["Id"] for r in records] == [1, 2, 3]
    # Provenance is attached per row, with a deep-link source_url keyed by Id.
    assert records[0].source_type == SourceType.KNESSET_ODATA
    assert records[0].source_url == f"{V4_BASE}/{entity}(1)"
    assert records[0].source_record_id == "1"


@respx.mock
def test_v3_paging_follows_odata_nextlink_relative() -> None:
    """V3 server-driven paging: follow a RELATIVE ``odata.nextLink`` (the .svc shape).

    As above, one URL-keyed responder emulates the server so the page-1 and
    page-2 requests are matched distinctly (no infinite loop).
    """
    entity = "vote_rslts_kmmbr_shadow"
    # V3 nextLink is often relative to the service root.
    relative_next = f"{entity}?$skiptoken=42"

    def responder(request: httpx.Request) -> httpx.Response:
        if "$skiptoken" in request.url.query.decode():
            return httpx.Response(200, json={"value": [{"vote_id": 12}]}, headers=_JSON)
        return httpx.Response(
            200,
            json={
                "value": [{"vote_id": 10}, {"vote_id": 11}],
                # NOTE the V3 key has no leading '@'.
                "odata.nextLink": relative_next,
            },
            headers=_JSON,
        )

    respx.get(url__startswith=f"{V3_BASE}/{entity}").mock(side_effect=responder)

    client = ODataClient(V3_BASE, SourceType.KNESSET_VOTES, odata_version=3, page_size=2)
    records = list(client.iter_entities(entity))
    client.close()

    assert [r.data["vote_id"] for r in records] == [10, 11, 12]
    assert records[0].source_type == SourceType.KNESSET_VOTES


@respx.mock
def test_get_person_returns_rawrecord_with_provenance() -> None:
    """``get_person`` returns a ``RawRecord`` with correct source_url / provenance."""
    entity = "KNS_Person"
    route = respx.get(f"{V4_BASE}/{entity}").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "Id": 965,
                        "LastName": "נתניהו",
                        "FirstName": "בנימין",
                        "IsCurrent": True,
                    }
                ]
            },
            headers=_JSON,
        )
    )

    # Inject a client pointed at the mocked base (adapter accepts a client).
    client = ODataClient(V4_BASE, SourceType.KNESSET_ODATA, odata_version=4)
    source = KnessetParliamentInfoSource(client=client)
    rec = source.get_person(965)
    source.close()

    assert isinstance(rec, RawRecord)
    assert rec is not None
    assert rec.data["Id"] == 965
    assert rec.data["LastName"] == "נתניהו"
    # Provenance: source type + deep-link URL + upstream id.
    assert rec.source_type == SourceType.KNESSET_ODATA
    assert rec.source_url == f"{V4_BASE}/{entity}(965)"
    assert rec.source_record_id == "965"
    assert rec.fetched_at is not None

    # The request actually used the OData $filter we expect (by Id).
    assert route.called
    sent = route.calls.last.request
    assert "Id+eq+965" in str(sent.url) or "Id eq 965" in str(sent.url)


@respx.mock
def test_get_person_returns_none_when_absent() -> None:
    """An empty ``value`` array yields ``None`` (never a fabricated person)."""
    respx.get(f"{V4_BASE}/KNS_Person").mock(
        return_value=httpx.Response(200, json={"value": []}, headers=_JSON)
    )
    client = ODataClient(V4_BASE, SourceType.KNESSET_ODATA, odata_version=4)
    source = KnessetParliamentInfoSource(client=client)
    assert source.get_person(999999) is None
    source.close()
