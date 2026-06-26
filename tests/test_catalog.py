"""Catalog loader: upserts official statistics from a JSON file; skips templates
and rejects rows without a source_url."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.ingestion.catalog import load_official_statistics
from knesset_osint.models import OfficialStatistic


def _write(tmp_path, rows) -> str:
    p = tmp_path / "cat.json"
    p.write_text(
        json.dumps(
            {"metric": "idf_enlistment_rate", "dimension_type": "city", "rows": rows},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return str(p)


def test_loader_inserts_valid_rows(db_session: Session, tmp_path) -> None:
    path = _write(
        tmp_path,
        [
            {"dimension_value": "עיר-א", "value": 50.0, "period": "2022",
             "source_url": "https://example.org/a"},
            {"dimension_value": "עיר-ב", "value": 70.0, "period": "2022",
             "source_url": "https://example.org/b"},
        ],
    )
    n = load_official_statistics(db_session, path)
    db_session.commit()
    assert n == 2
    assert db_session.scalar(select(OfficialStatistic).where(
        OfficialStatistic.dimension_value == "עיר-א")) is not None


def test_loader_skips_template_and_unsourced_rows(db_session: Session, tmp_path) -> None:
    path = _write(
        tmp_path,
        [
            {"dimension_value": "_TEMPLATE", "value": 0.0, "source_url": "https://x"},
            {"dimension_value": "עיר-ג", "value": 60.0, "source_url": ""},  # no source
            {"dimension_value": "עיר-ד", "value": 65.0, "source_url": "https://example.org/d"},
        ],
    )
    n = load_official_statistics(db_session, path)
    db_session.commit()
    assert n == 1  # only עיר-ד


def test_loader_is_idempotent(db_session: Session, tmp_path) -> None:
    rows = [{"dimension_value": "עיר-א", "value": 50.0, "source_url": "https://example.org/a"}]
    path = _write(tmp_path, rows)
    load_official_statistics(db_session, path)
    db_session.commit()
    load_official_statistics(db_session, path)  # second run must not duplicate
    db_session.commit()
    count = len(db_session.scalars(select(OfficialStatistic)).all())
    assert count == 1
