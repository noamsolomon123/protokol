"""End-to-end (no LLM, no network): claim -> persisted StatisticVerdict."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models import (
    OfficialStatistic,
    Politician,
    Statement,
    StatisticVerdict,
)
from knesset_osint.models.enums import (
    SourceType,
    StatementType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim
from knesset_osint.verification.verify import verify_statement


def _seed_cities(session: Session) -> None:
    for i in range(1, 12):
        session.add(
            OfficialStatistic(
                metric="idf_enlistment_rate",
                dimension_type="city",
                dimension_value=f"עיר-{i}",
                value=float(i * 5),
                unit="percent",
                period="2022",
                source_type=SourceType.IDF_SPOKESPERSON,
                source_url=f"https://example.org/idf/{i}",
                fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
            )
        )
    session.add(
        OfficialStatistic(
            metric="idf_enlistment_rate",
            dimension_type="city",
            dimension_value="תל אביב",
            value=58.0,
            unit="percent",
            period="2022",
            source_type=SourceType.IDF_SPOKESPERSON,
            source_url="https://example.org/idf/tlv",
            fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
        )
    )


def _politician_and_statement(session: Session, source_type: SourceType) -> Statement:
    pol = Politician(
        knesset_person_id=965,
        full_name="בנימין נתניהו",
        is_current=True,
        source_type=SourceType.KNESSET_ODATA,
        source_url="https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    stmt = Statement(
        politician=pol,
        claim="תל אביב עם שיעור הגיוס הנמוך בארץ.",
        statement_type=StatementType.PLENUM,
        source_type=source_type,
        source_url="https://knesset.gov.il/plenum/transcript/1#p3",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    session.add_all([pol, stmt])
    session.flush()
    return stmt


def _claim_for(stmt: Statement) -> StructuredClaim:
    return StructuredClaim(
        politician_id=stmt.politician_id,
        statement_id=stmt.id,
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value="תל אביב",
        assertion=ClaimAssertion.SUPERLATIVE_MIN,
        claimed_value=None,
        source_type=stmt.source_type,
        source_url=stmt.source_url,
        exact_quote=stmt.claim,
    )


def test_verify_persists_inconsistent_and_auto_publishes_knesset(db_session: Session) -> None:
    _seed_cities(db_session)
    stmt = _politician_and_statement(db_session, SourceType.KNESSET_ODATA)
    db_session.commit()

    verdict = verify_statement(db_session, _claim_for(stmt))
    db_session.commit()

    loaded = db_session.execute(select(StatisticVerdict)).scalar_one()
    assert loaded.id == verdict.id
    assert loaded.outcome is VerdictOutcome.INCONSISTENT
    assert loaded.published is True
    assert loaded.auto_published is True
    assert loaded.review_status is VerdictReviewStatus.APPROVED
    # Auditability: both links present.
    assert loaded.statement_url.startswith("https://knesset.gov.il/")
    assert loaded.statistic_url == "https://example.org/idf/tlv"


def test_verify_transcription_source_queues_for_review(db_session: Session) -> None:
    _seed_cities(db_session)
    # MANUAL stands in for a transcription-derived interview statement.
    stmt = _politician_and_statement(db_session, SourceType.MANUAL)
    db_session.commit()

    verify_statement(
        db_session,
        _claim_for(stmt),
        transcription_source_types={SourceType.MANUAL},
    )
    db_session.commit()

    loaded = db_session.execute(select(StatisticVerdict)).scalar_one()
    assert loaded.outcome is VerdictOutcome.INCONSISTENT  # still computed
    assert loaded.published is False                       # but not public
    assert loaded.review_status is VerdictReviewStatus.PENDING
