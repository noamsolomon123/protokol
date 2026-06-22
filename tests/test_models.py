"""ORM model tests: relationships, defaults, and the provenance invariant.

These run entirely against the in-memory SQLite engine (see ``conftest.py``) with
no network. They lock in three guarantees the platform depends on:

1. A ``Politician`` -> ``Statement`` relationship round-trips correctly.
2. A ``Contradiction`` defaults to ``status=needs_review`` (the platform never
   auto-asserts a lie — a human must rule).
3. Provenance columns (source_type / source_url / raw_payload / fetched_at)
   persist exactly as written (the objectivity backbone).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models import (
    Contradiction,
    Politician,
    Statement,
)
from knesset_osint.models.enums import (
    ContradictionStatus,
    SourceType,
    StatementType,
    VerificationStatus,
)


def _make_politician() -> Politician:
    """A minimal, fully-provenanced politician for use across the tests."""
    return Politician(
        knesset_person_id=965,
        first_name="בנימין",
        last_name="נתניהו",
        full_name="בנימין נתניהו",
        gender="זכר",
        is_current=True,
        external_ids={"votes_mk_id": 965},
        source_type=SourceType.KNESSET_ODATA,
        source_name=SourceType.KNESSET_ODATA.value,
        source_url="https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)",
        source_record_id="965",
        raw_payload={"Id": 965, "LastName": "נתניהו", "FirstName": "בנימין"},
        fetched_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
    )


def test_politician_statement_relationship(db_session: Session) -> None:
    """Inserting a politician + statement links them both directions."""
    pol = _make_politician()
    stmt = Statement(
        politician=pol,  # set the relationship; FK is resolved on flush
        statement_date=date(2024, 1, 15),
        topic="כלכלה",
        claim="הורדנו את יוקר המחיה.",
        full_text="בנאום מלא: הורדנו את יוקר המחיה.",
        statement_type=StatementType.SPEECH,
        language="he",
        # source_url is mandatory (CHECK constraint) — a statement is always sourced.
        source_type=SourceType.MANUAL,
        source_name=SourceType.MANUAL.value,
        source_url="https://example.org/speech/123",
        source_record_id="speech-123",
        raw_payload={"speech_id": 123},
        fetched_at=datetime(2026, 6, 20, 12, 5, tzinfo=timezone.utc),
    )
    db_session.add(pol)
    db_session.add(stmt)
    db_session.commit()

    # Forward: politician -> statements
    loaded_pol = db_session.execute(
        select(Politician).where(Politician.knesset_person_id == 965)
    ).scalar_one()
    assert len(loaded_pol.statements) == 1
    assert loaded_pol.statements[0].claim == "הורדנו את יוקר המחיה."

    # Backward: statement -> politician
    loaded_stmt = db_session.execute(select(Statement)).scalar_one()
    assert loaded_stmt.politician.id == loaded_pol.id
    assert loaded_stmt.politician.full_name == "בנימין נתניהו"
    # Defaults applied by the model.
    assert loaded_stmt.verification_status == VerificationStatus.UNVERIFIED


def test_contradiction_defaults_to_needs_review(db_session: Session) -> None:
    """A new Contradiction is 'needs_review' until a human rules — never auto-asserted."""
    pol = _make_politician()
    stmt = Statement(
        politician=pol,
        claim="טענה כלשהי הניתנת לבדיקה.",
        statement_type=StatementType.PRESS_RELEASE,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/press/9",
        fetched_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )
    db_session.add_all([pol, stmt])
    db_session.flush()  # assign stmt.id for the FK

    contra = Contradiction(
        statement_id=stmt.id,
        evidence_kind="vote",
        evidence_id=4242,
        # Both source links, always — the core of auditability.
        statement_url="https://example.org/press/9",
        evidence_url="https://knesset.gov.il/Odata/Votes.svc/View_vote_rslts_hdr_Approved(4242)",
        score=0.81,
        rationale="הצביע בניגוד לטענה (לבדיקת אדם).",
        detector_version="test-0.0",
        detected_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        # NOTE: status deliberately NOT set — we assert the model default.
    )
    db_session.add(contra)
    db_session.commit()

    loaded = db_session.execute(select(Contradiction)).scalar_one()
    assert loaded.status == ContradictionStatus.NEEDS_REVIEW
    # No human verdict yet — the only path to a verdict is human review.
    assert loaded.human_verdict is None
    assert loaded.reviewed_by is None
    # Both deep links survive the round-trip (independent auditability).
    assert loaded.statement_url == "https://example.org/press/9"
    assert loaded.evidence_url.endswith("(4242)")
    # The contradiction is reachable from its statement.
    assert loaded.statement.id == stmt.id


def test_provenance_columns_persist(db_session: Session) -> None:
    """Every provenance column round-trips exactly as written (objectivity backbone)."""
    pol = _make_politician()
    db_session.add(pol)
    db_session.commit()

    loaded = db_session.execute(select(Politician)).scalar_one()
    assert loaded.source_type == SourceType.KNESSET_ODATA
    assert loaded.source_name == "knesset_odata"
    assert loaded.source_url == (
        "https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)"
    )
    assert loaded.source_record_id == "965"
    # raw_payload (JSON) preserves the verbatim upstream dict.
    assert loaded.raw_payload == {"Id": 965, "LastName": "נתניהו", "FirstName": "בנימין"}
    assert loaded.fetched_at is not None
    # external_ids reconciliation map persists too.
    assert loaded.external_ids == {"votes_mk_id": 965}
    # Timestamp mixin populates created_at / updated_at on insert.
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
