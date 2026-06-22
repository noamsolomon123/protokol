"""Export a politician's record to static JSON for the GitHub Pages site.

The published site is a *static* front-end (GitHub Pages can't run our backend),
so this script does the work once and writes a JSON file the page fetches:

    1. ensure tables exist, ingest the politician (idempotent),
    2. compute the Accountability Scorecard,
    3. write ``docs/data/<slug>.json`` + update ``docs/data/politicians.json``.

Run it with a throwaway SQLite DB so no Postgres is needed::

    set DATABASE_URL=sqlite:///./_site_build.db
    python scripts/export_site_data.py --person-id 965 --max-votes 1200

Re-run any time to refresh the site data. Every value written carries the
official ``source_url`` it came from — the front-end renders those as links.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import knesset_osint.models  # noqa: F401  (register tables)
from knesset_osint.core.config import settings
from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.db.base import Base
from knesset_osint.db.session import SessionLocal, engine
from knesset_osint.ingestion.pipeline import ingest_politician
from knesset_osint.models import Bill, BillSponsorship, Politician, Vote, VoteEvent
from knesset_osint.scoring import compute_scorecard
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

logger = get_logger("export_site")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "data"


def _iso(d: Any) -> str | None:
    return d.isoformat() if d is not None else None


def _slug(politician: Politician) -> str:
    return f"person-{politician.knesset_person_id or politician.id}"


def _counts(session: Session, p: Politician) -> dict[str, int]:
    def c(model: type, fk: Any) -> int:
        return session.scalar(select(func.count()).select_from(model).where(fk == p.id)) or 0

    return {
        "roles": c(__import__("knesset_osint.models", fromlist=["Role"]).Role, _role_fk()),
        "bills": c(BillSponsorship, BillSponsorship.politician_id),
        "votes": c(Vote, Vote.politician_id),
    }


def _role_fk():  # tiny helper to avoid a top-level Role import name clash
    from knesset_osint.models import Role

    return Role.politician_id


def _sample_bills(session: Session, p: Politician, limit: int = 12) -> list[dict]:
    rows = session.scalars(
        select(BillSponsorship)
        .where(BillSponsorship.politician_id == p.id)
        .options(joinedload(BillSponsorship.bill))
        .order_by(BillSponsorship.is_initiator.desc(), BillSponsorship.ordinal.asc().nullslast())
        .limit(limit)
    ).all()
    out = []
    for sp in rows:
        b: Bill | None = sp.bill
        if b is None:
            continue
        out.append(
            {
                "name": b.name,
                "knesset_num": b.knesset_num,
                "is_lead_initiator": bool(sp.is_initiator),
                "source_url": b.source_url,
            }
        )
    return out


def _recent_votes(session: Session, p: Politician, limit: int = 20) -> list[dict]:
    rows = session.scalars(
        select(Vote)
        .where(Vote.politician_id == p.id)
        .options(joinedload(Vote.event))
        .order_by(Vote.id.desc())
        .limit(limit)
    ).all()
    out = []
    for v in rows:
        ev: VoteEvent | None = v.event
        out.append(
            {
                "stance": v.stance.value if v.stance else None,
                "event_title": ev.title if ev else None,
                "date": _iso(ev.vote_date) if ev else None,
                "source_url": v.source_url or (ev.source_url if ev else None),
            }
        )
    return out


def _scorecard_json(session: Session, p: Politician) -> dict:
    sc = compute_scorecard(session, p)
    return {
        "index": {
            "value": sc.index.value,
            "coverage_scored": sc.index.coverage_scored,
            "coverage_total": sc.index.coverage_total,
            "label": sc.index.label,
            "included": sc.index.included,
            "weights_used": sc.index.weights_used,
        },
        "dimensions": [asdict(d) for d in sc.dimensions],
        "disclaimer_he": sc.disclaimer_he,
        "disclaimer_en": sc.disclaimer_en,
        "notes": sc.notes,
    }


def export_politician(session: Session, person_id: int, max_votes: int | None, generated_at: str) -> dict:
    report = ingest_politician(session, person_id, max_votes=max_votes)
    session.commit()
    p = session.scalar(select(Politician).where(Politician.knesset_person_id == person_id))
    if p is None:
        raise RuntimeError(f"Ingestion produced no politician for person_id={person_id}")

    data = {
        "schema_version": 1,
        "generated_at": generated_at,
        "politician": {
            "id": p.id,
            "knesset_person_id": p.knesset_person_id,
            "full_name": p.full_name,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "is_current": p.is_current,
            "current_party": p.current_party,
            "source_url": p.source_url,
        },
        "counts": _counts(session, p),
        "votes_ingested_note": f"participation computed over {report.votes} ingested votes"
        + ("" if max_votes is None else f" (capped at {max_votes} for this build)"),
        "scorecard": _scorecard_json(session, p),
        "sample_bills": _sample_bills(session, p),
        "recent_votes": _recent_votes(session, p),
        "sources": {
            "parliamentinfo_v4": settings.knesset_odata_v4_base,
            "votes_v3": settings.knesset_votes_svc_base,
        },
    }
    return data


def main() -> int:
    enable_utf8_console()
    configure_logging(settings.log_level)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--person-id", type=int, default=settings.pilot_person_id)
    parser.add_argument(
        "--max-votes",
        type=int,
        default=1200,
        help="Cap votes for build speed/size (use 0 for entire career).",
    )
    parser.add_argument("--generated-at", default="", help="ISO date stamp (optional).")
    args = parser.parse_args()
    max_votes = None if args.max_votes == 0 else args.max_votes

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        data = export_politician(session, args.person_id, max_votes, args.generated_at)
    finally:
        session.close()

    slug = f"person-{args.person_id}"
    out_path = OUT_DIR / f"{slug}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Maintain a small manifest so the site can list all available politicians.
    manifest_path = OUT_DIR / "politicians.json"
    manifest: list[dict] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = []
    manifest = [m for m in manifest if m.get("slug") != slug]
    manifest.append(
        {
            "slug": slug,
            "full_name": data["politician"]["full_name"],
            "party": data["politician"]["current_party"],
            "file": f"{slug}.json",
            "index_value": data["scorecard"]["index"]["value"],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"Updated {manifest_path} ({len(manifest)} politician(s))")
    idx = data["scorecard"]["index"]
    print(
        f"Index: {idx['value']} ({idx['label']}, coverage {idx['coverage_scored']}/{idx['coverage_total']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
