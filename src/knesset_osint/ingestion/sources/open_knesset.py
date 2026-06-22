"""Open Knesset (Hasadna) enrichment adapter — best-effort, never source-of-truth.

Open Knesset is a community mirror/derivative of the official Knesset data. We
use it **only** to *enrich* records we already trust from the official OData/Votes
feeds (e.g. add a slug, a knesset.org member page, extra biographical bits). It
is explicitly NOT authoritative: the official ParliamentInfo + Votes feeds win
on every conflict.

Because it is a third-party best-effort source, **every method degrades
gracefully**: on any failure (network, non-JSON, missing resource, parse error)
it logs a warning and returns ``None`` / ``[]``. Enrichment can therefore never
break ingestion. It also respects ``settings.enable_open_knesset_enrichment`` —
when that flag is off, every method short-circuits to the empty result.

Data layout (probed 2026-06-20):
  * Both ``settings.open_knesset_pipelines_base`` and
    ``settings.knesset_data_gcs_base`` serve frictionless "datapackage"
    directories. A dataset's ``datapackage.json`` lists ``resources`` (each with
    a ``name``, a CSV ``path`` and a column ``schema``).
  * Example dataset ``members/mk_individual`` exposes a resource
    ``mk_individual_positions`` keyed by ``mk_individual_id`` — the SAME id as
    Votes' ``View_Vote_MK_Individual.mk_individual_id`` (90 for Netanyahu), which
    is how we line enrichment up with a politician.

Extending to more enrichment
----------------------------
* Add a method per dataset you care about; reuse :meth:`fetch_datapackage` to
  discover resource paths, then :meth:`_fetch_csv_rows` to pull rows, and filter
  client-side by the relevant id. Keep the try/except-return-default shape so the
  graceful-degradation contract holds.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

import httpx

from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.sources.base import BaseSource, RawRecord
from knesset_osint.models.enums import SourceType

logger = get_logger("knesset_osint.sources.open_knesset")


class OpenKnessetSource(BaseSource):
    """Best-effort enrichment over the Open Knesset (Hasadna) datapackages."""

    source_type = SourceType.OPEN_KNESSET
    name = "open_knesset"

    # Default enrichment dataset (members → mk_individual datapackage).
    MK_DATASET = "members/mk_individual"
    MK_POSITIONS_RESOURCE = "mk_individual_positions"

    def __init__(
        self,
        *,
        pipelines_base: str | None = None,
        gcs_base: str | None = None,
        client: httpx.Client | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Set up the enrichment client.

        We try ``pipelines_base`` first and fall back to ``gcs_base`` (the GCS
        mirror), since one is occasionally unavailable. ``enabled`` defaults to
        ``settings.enable_open_knesset_enrichment``.
        """
        self.pipelines_base = (pipelines_base or settings.open_knesset_pipelines_base).rstrip("/")
        self.gcs_base = (gcs_base or settings.knesset_data_gcs_base).rstrip("/")
        self.enabled = (
            settings.enable_open_knesset_enrichment if enabled is None else enabled
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={
                "User-Agent": settings.http_user_agent,
                "Accept": "application/json, text/csv, */*",
            },
            follow_redirects=True,
        )

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenKnessetSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level fetch (both bases, graceful) ------------------------------
    def _candidate_urls(self, rel_path: str) -> list[str]:
        """Build ``[pipelines, gcs]`` URLs for a dataset-relative path."""
        rel = rel_path.lstrip("/")
        return [f"{self.pipelines_base}/{rel}", f"{self.gcs_base}/{rel}"]

    def _get(self, rel_path: str) -> httpx.Response | None:
        """GET a dataset-relative path, trying both bases. ``None`` on failure."""
        if not self.enabled:
            logger.debug("Open Knesset enrichment disabled; skipping %s", rel_path)
            return None
        for url in self._candidate_urls(rel_path):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                logger.warning("Open Knesset fetch failed (%s): %s", url, exc)
        return None

    def fetch_datapackage(self, dataset: str) -> dict[str, Any] | None:
        """Fetch a dataset's ``datapackage.json`` (resource index). ``None`` on fail."""
        resp = self._get(f"{dataset}/datapackage.json")
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            logger.warning("Open Knesset datapackage not JSON for %s: %s", dataset, exc)
            return None

    def _resource_path(self, dataset: str, resource_name: str) -> str | None:
        """Look up a resource's CSV path inside a dataset's datapackage."""
        pkg = self.fetch_datapackage(dataset)
        if not pkg:
            return None
        for res in pkg.get("resources", []) or []:
            if res.get("name") == resource_name:
                path = res.get("path")
                if path:
                    return f"{dataset}/{path}"
        logger.warning(
            "Open Knesset resource %r not in dataset %r", resource_name, dataset
        )
        return None

    def _fetch_csv_rows(self, rel_path: str) -> list[dict[str, str]]:
        """Fetch and parse a CSV resource into dict rows. ``[]`` on any failure."""
        resp = self._get(rel_path)
        if resp is None:
            return []
        try:
            text = resp.text
            reader = csv.DictReader(io.StringIO(text))
            return list(reader)
        except Exception as exc:  # pragma: no cover - defensive parse guard
            logger.warning("Open Knesset CSV parse failed for %s: %s", rel_path, exc)
            return []

    # -- enrichment surface --------------------------------------------------
    def get_member_enrichment(self, mk_individual_id: int) -> RawRecord | None:
        """Return an enrichment RawRecord for one MK, or ``None`` if unavailable.

        ``mk_individual_id`` is the Votes ``mk_individual_id`` (e.g. 90). We pull
        the ``mk_individual_positions`` resource and return the first matching
        row wrapped in a RawRecord (provenance = OPEN_KNESSET + the CSV URL).

        Returns ``None`` rather than raising on *any* problem — this is
        enrichment, it must never break the pipeline.
        """
        if not self.enabled:
            return None
        rel = self._resource_path(self.MK_DATASET, self.MK_POSITIONS_RESOURCE)
        if rel is None:
            return None
        rows = self._fetch_csv_rows(rel)
        if not rows:
            return None

        target = str(mk_individual_id)
        match: dict[str, str] | None = None
        for row in rows:
            rid = row.get("mk_individual_id") or row.get("Mk_Individual_Id")
            if rid is not None and str(rid).strip() == target:
                match = row
                break
        if match is None:
            logger.warning(
                "No Open Knesset enrichment row for mk_individual_id=%s",
                mk_individual_id,
            )
            return None

        url = self._candidate_urls(rel)[0]
        return RawRecord(
            data=match,
            source_type=SourceType.OPEN_KNESSET,
            source_url=url,
            source_record_id=target,
            fetched_at=datetime.now(timezone.utc),
        )

    def iter_dataset_rows(
        self, dataset: str, resource_name: str
    ) -> list[RawRecord]:
        """Return *all* rows of a dataset resource as RawRecords. ``[]`` on fail.

        Generic helper for onboarding new enrichment datasets. Each row becomes a
        RawRecord with OPEN_KNESSET provenance pointing at the CSV resource URL.
        """
        if not self.enabled:
            return []
        rel = self._resource_path(dataset, resource_name)
        if rel is None:
            return []
        rows = self._fetch_csv_rows(rel)
        if not rows:
            return []
        url = self._candidate_urls(rel)[0]
        fetched = datetime.now(timezone.utc)
        records: list[RawRecord] = []
        for row in rows:
            rid = row.get("id") or row.get("Id") or row.get("mk_individual_id")
            records.append(
                RawRecord(
                    data=row,
                    source_type=SourceType.OPEN_KNESSET,
                    source_url=url,
                    source_record_id=str(rid).strip() if rid is not None else None,
                    fetched_at=fetched,
                )
            )
        return records
