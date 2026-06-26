"""Export the public leaderboard: MKs ranked by statements contradicted by
official data (PUBLISHED, INCONSISTENT verdicts only).

Writes ``docs/data/leaderboard.json`` for the static GitHub Pages site. Mirrors
``scripts/export_site_data.py`` (run against a throwaway sqlite). The wording is
deliberately "contradicted by official data", never "liar".
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import knesset_osint.models  # noqa: F401  (register tables)
from knesset_osint.db.base import Base
from knesset_osint.db.session import SessionLocal, engine
from knesset_osint.models import Politician, Statement, StatisticVerdict
from knesset_osint.models.enums import VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "data"


def build_leaderboard(session: Session) -> list[dict]:
    """Return [{slug, full_name, party, contradicted_count}, ...] desc by count."""
    count_col = func.count(StatisticVerdict.id).label("n")
    rows = session.execute(
        select(Politician, count_col)
        .select_from(StatisticVerdict)
        .join(Statement, Statement.id == StatisticVerdict.statement_id)
        .join(Politician, Politician.id == Statement.politician_id)
        .where(StatisticVerdict.published.is_(True))
        .where(StatisticVerdict.outcome == VerdictOutcome.INCONSISTENT)
        .group_by(Politician.id)
        .order_by(count_col.desc(), Politician.id.asc())
    ).all()
    board = []
    for pol, n in rows:
        board.append(
            {
                "slug": f"person-{pol.knesset_person_id or pol.id}",
                "full_name": pol.full_name,
                "party": pol.current_party,
                "contradicted_count": int(n),
            }
        )
    return board


def main() -> int:
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        board = build_leaderboard(session)
    finally:
        session.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "leaderboard.json"
    out_path.write_text(
        json.dumps(
            {"schema_version": 1, "metric": "statements_contradicted_by_official_data",
             "rows": board},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out_path} ({len(board)} politician(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
