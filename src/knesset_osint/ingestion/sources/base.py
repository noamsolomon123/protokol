"""Source-adapter contract + a shared OData client.

`ODataClient` speaks both OData V4 (ParliamentInfo: `$count=true`,
`@odata.nextLink`) and OData V3 (Votes.svc: `$inlinecount=allpages`,
`odata.nextLink`, sometimes relative). Every row it yields is a `RawRecord`
carrying full provenance (source type, deep-link URL, upstream id, fetch time).

`BaseSource` is the interface every adapter implements. To add a new source,
subclass it and return `RawRecord`s — see docs/ADDING_A_SOURCE.md.
"""

from __future__ import annotations

import logging
from abc import ABC
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knesset_osint.core.config import settings
from knesset_osint.models.enums import SourceType

logger = logging.getLogger("knesset_osint.sources")


@dataclass(slots=True)
class RawRecord:
    """A single upstream record plus its provenance. Mappers turn these into
    ORM rows; the provenance fields flow straight into ProvenanceMixin columns."""

    data: dict[str, Any]
    source_type: SourceType
    source_url: str
    source_record_id: Optional[str] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ODataClient:
    """Thin, dependency-light OData reader for V3 and V4 feeds."""

    def __init__(
        self,
        base_url: str,
        source_type: SourceType,
        *,
        odata_version: int = 4,
        page_size: int | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.source_type = source_type
        self.odata_version = odata_version
        self.page_size = page_size or settings.odata_page_size
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout or settings.http_timeout_seconds,
            headers={
                "User-Agent": user_agent or settings.http_user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ODataClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- helpers -------------------------------------------------------------
    def entity_url(self, entity_set: str) -> str:
        return f"{self.base_url}/{entity_set}"

    @retry(
        reraise=True,
        stop=stop_after_attempt(settings.http_max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            # Defensive: a bot-challenge/HTML page (e.g. the Imperva-protected V4
            # Votes endpoint) returns 200 + HTML. Treat as a retryable failure
            # rather than crashing the JSON parser with a confusing error.
            raise httpx.HTTPStatusError(
                f"Expected JSON from {url} but got content-type {ctype!r} "
                f"(possible bot-challenge / wrong endpoint).",
                request=resp.request,
                response=resp,
            )
        return resp.json()

    def count(self, entity_set: str, *, filter: str | None = None) -> int:
        """Best-effort total count (0 if the server doesn't support inline count)."""
        params: dict[str, str] = {"$format": "json", "$top": "0"}
        if self.odata_version >= 4:
            params["$count"] = "true"
        else:
            params["$inlinecount"] = "allpages"
        if filter:
            params["$filter"] = filter
        try:
            data = self._get(self.entity_url(entity_set), params=params)
        except httpx.HTTPError:
            return 0
        raw = data.get("@odata.count", data.get("odata.count"))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def iter_entities(
        self,
        entity_set: str,
        *,
        filter: str | None = None,
        select: str | None = None,
        expand: str | None = None,
        order_by: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> Iterator[RawRecord]:
        """Yield every matching row, transparently handling server-driven
        (nextLink) and client-driven ($skip) paging."""
        page_size = page_size or self.page_size
        base_params: dict[str, str] = {"$format": "json", "$top": str(page_size)}
        if filter:
            base_params["$filter"] = filter
        if select:
            base_params["$select"] = select
        if expand:
            base_params["$expand"] = expand
        if order_by:
            base_params["$orderby"] = order_by

        url = self.entity_url(entity_set)
        params: dict | None = dict(base_params)
        skip = 0
        yielded = 0

        while True:
            data = self._get(url, params=params)
            rows = data.get("value") or []
            for row in rows:
                yield self._to_record(entity_set, row)
                yielded += 1
                if max_records and yielded >= max_records:
                    return

            next_link = data.get("@odata.nextLink") or data.get("odata.nextLink")
            if next_link:
                url = (
                    next_link
                    if next_link.startswith("http")
                    else urljoin(self.base_url + "/", next_link)
                )
                params = None  # nextLink already carries the query string
                continue

            # No nextLink: fall back to $skip paging until a short page arrives.
            if len(rows) < page_size:
                return
            skip += page_size
            url = self.entity_url(entity_set)
            params = dict(base_params)
            params["$skip"] = str(skip)

    # -- internals -----------------------------------------------------------
    def _record_id(self, row: dict) -> Optional[str]:
        for key in ("Id", "ID", "id"):
            if row.get(key) is not None:
                return str(row[key])
        return None

    def _to_record(self, entity_set: str, row: dict) -> RawRecord:
        rid = self._record_id(row)
        url = f"{self.entity_url(entity_set)}({rid})" if rid else self.entity_url(entity_set)
        return RawRecord(
            data=row,
            source_type=self.source_type,
            source_url=url,
            source_record_id=rid,
        )


class BaseSource(ABC):
    """Interface marker for all data-source adapters.

    Concrete adapters expose domain methods (e.g. `get_person`, `iter_bills`,
    `iter_votes`) that return `RawRecord` objects. Keeping a common base lets the
    pipeline treat every source uniformly and makes onboarding a new source a
    matter of adding one file. See docs/ADDING_A_SOURCE.md.
    """

    source_type: SourceType
    name: str
