"""Load a curated official-statistics catalog (JSON) into the DB, idempotently.

Catalog file shape::

    {
      "metric": "idf_enlistment_rate",
      "dimension_type": "city",
      "source_type": "idf_spokesperson",   # optional, default manual
      "unit": "percent",                    # optional
      "rows": [
        {"dimension_value": "תל אביב", "value": 58.0, "period": "2022",
         "source_url": "https://...", "notes": "..."}
      ]
    }

Hard rules (the objectivity guarantee):
  * a row with no `source_url` is REJECTED (never enters the catalog),
  * a row whose `dimension_value` is "_TEMPLATE" is skipped (it documents shape),
  * re-loading the same file does not duplicate rows (idempotent upsert on
    metric + dimension_type + dimension_value + period).
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.core.logging import get_logger
from knesset_osint.models.enums import SourceType
from knesset_osint.models.official_statistic import OfficialStatistic

logger = get_logger("ingestion.catalog")

TEMPLATE_SENTINEL = "_TEMPLATE"


def load_official_statistics(session: Session, path: str) -> int:
    """Upsert statistics from the catalog at `path`. Returns rows inserted/updated."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    metric = payload["metric"]
    dimension_type = payload["dimension_type"]
    unit = payload.get("unit")
    source_type = SourceType(payload.get("source_type", SourceType.MANUAL.value))

    affected = 0
    for row in payload.get("rows", []):
        dim = row.get("dimension_value")
        source_url = (row.get("source_url") or "").strip()
        if dim == TEMPLATE_SENTINEL:
            continue
        if not source_url:
            logger.warning("Skipping unsourced catalog row dimension_value=%r", dim)
            continue

        period = row.get("period")
        existing = session.scalar(
            select(OfficialStatistic)
            .where(OfficialStatistic.metric == metric)
            .where(OfficialStatistic.dimension_type == dimension_type)
            .where(OfficialStatistic.dimension_value == dim)
            .where(OfficialStatistic.period == period)
        )
        if existing is None:
            session.add(
                OfficialStatistic(
                    metric=metric,
                    dimension_type=dimension_type,
                    dimension_value=dim,
                    value=float(row["value"]),
                    unit=unit,
                    period=period,
                    notes=row.get("notes"),
                    source_type=source_type,
                    source_name=source_type.value,
                    source_url=source_url,
                )
            )
        else:
            existing.value = float(row["value"])
            existing.unit = unit
            existing.notes = row.get("notes")
            existing.source_url = source_url
        affected += 1

    logger.info("Catalog %s: %d row(s) loaded for metric=%s.", path, affected, metric)
    return affected
