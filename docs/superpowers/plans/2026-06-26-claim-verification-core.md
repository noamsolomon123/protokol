# Claim Verification Core — Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a structured factual claim by an MK, verify it against a curated catalog of official statistics, produce a confidence-scored verdict (consistent / inconsistent / unverifiable), gate publishing on confidence + source, and export a public leaderboard ranking MKs by statements contradicted by official data.

**Architecture:** Extends the existing `knesset-osint` platform. Reuses the existing `Statement` model as the checkable claim. Adds two ORM tables (`OfficialStatistic`, `StatisticVerdict`), a small set of pure-Python verification components (matcher → adjudicator → publish gate → orchestrator) following the existing `ContradictionDetector` ABC+stub pattern, a JSON catalog loader, and a static leaderboard export following the existing `export_site_data.py` pattern. No LLM and no network in this plan — claims arrive as structured dataclasses, which keeps the whole pipeline deterministically testable. (Plan 2 adds the LLM extractor that produces those structured claims from raw `Statement` text.)

**Tech Stack:** Python 3, SQLAlchemy 2.0 (typed `Mapped` style), Alembic, pytest + in-memory SQLite (`db_session` fixture), stdlib `dataclasses`/`json`, GitHub Pages static JSON export.

---

## Decomposition (the full spec → 4 plans)

The design spec (`docs/superpowers/specs/2026-06-26-claim-verification-leaderboard-design.md`) is large, so it is split into four independently-shippable plans:

1. **Plan 1 — Verification core (THIS PLAN).** Catalog + matcher + adjudicator + publish gate + verdict persistence + leaderboard export, driven by structured claims. Ships a working leaderboard end-to-end.
2. **Plan 2 — LLM claim extraction.** Turn raw `Statement` text (from Knesset transcripts) into the `StructuredClaim` objects Plan 1 consumes; wire the Knesset-transcript auto-publish path.
3. **Plan 3 — Interview pipeline.** `media_source` model, YouTube/RSS discovery, `yt-dlp` download, pluggable `Transcriber` (Whisper local / Gemini), upload + triage, mandatory human review for transcription-sourced claims.
4. **Plan 4 — Submissions, dispute & review console.** Public submission flow, `dispute` table + UI, the human review queue UI, Phase-2 polish.

Each later plan gets its own full bite-sized plan document when we reach it. The roadmap for them is at the end of this file.

---

## File Structure (Plan 1)

**New files:**
- `src/knesset_osint/models/official_statistic.py` — `OfficialStatistic` ORM model (the curated "proof" catalog row).
- `src/knesset_osint/models/statistic_verdict.py` — `StatisticVerdict` ORM model (derived verdict; both source links; defaults to unpublished/needs-review).
- `src/knesset_osint/verification/claims.py` — `ClaimAssertion` enum + `StructuredClaim` dataclass (the input contract).
- `src/knesset_osint/verification/matching.py` — `StatisticMatcher` ABC + `DimensionStatisticMatcher`.
- `src/knesset_osint/verification/adjudication.py` — `VerdictDraft` dataclass + `Adjudicator`.
- `src/knesset_osint/verification/publish_gate.py` — `PublishDecision` dataclass + `PublishGate`.
- `src/knesset_osint/verification/verify.py` — `verify_statement` orchestrator.
- `src/knesset_osint/ingestion/catalog.py` — `load_official_statistics` JSON catalog loader.
- `src/knesset_osint/ingestion/catalogs/idf_enlistment_by_city.json` — the curated catalog file (schema + instructions; real values filled from official sources).
- `scripts/export_leaderboard.py` — aggregates published verdicts → `docs/data/leaderboard.json`.
- `docs/leaderboard.html`, `docs/leaderboard.js` — minimal Hebrew/RTL leaderboard page.
- `tests/test_official_statistic_model.py`, `tests/test_statistic_verdict_model.py`, `tests/test_matching.py`, `tests/test_adjudication.py`, `tests/test_publish_gate.py`, `tests/test_verify.py`, `tests/test_catalog.py`, `tests/test_leaderboard_export.py`.

**Modified files:**
- `src/knesset_osint/models/enums.py` — add `VerdictOutcome`, `VerdictReviewStatus`; add `SourceType.CBS`, `SourceType.IDF_SPOKESPERSON`.
- `src/knesset_osint/models/__init__.py` — import/register the two new models + new enums.
- `alembic/versions/<new>.py` — migration creating `official_statistics` + `statistic_verdicts`.

---

## Conventions to follow (read before starting)

- Models: SQLAlchemy 2.0 typed style — `Mapped[...]` + `mapped_column(...)`, inherit `Base` (+ `TimestampMixin`, + `ProvenanceMixin` for sourced raw data). See `src/knesset_osint/models/statement.py` and `models/verification.py`.
- Enums: `(str, enum.Enum)`, persisted via `SAEnum(MyEnum, native_enum=False, length=32)`. See `models/enums.py`.
- Derived-analysis rows (verdicts) do NOT use `ProvenanceMixin`; they store BOTH source links and default to an unpublished/needs-review state — mirror `Contradiction` in `models/verification.py`.
- Verification components use an ABC + concrete implementation, with a `*_version` class attribute stamped on output — mirror `ContradictionDetector` in `verification/contradiction.py`.
- Tests: pytest, fixtures `db_session` / `client` from `tests/conftest.py` (in-memory SQLite, no network). Hebrew strings in tests are fine (UTF-8).
- **Test data MUST be synthetic** (e.g. cities `"עיר-א"`, `"עיר-ב"`). NEVER hard-code invented real-world enlistment numbers in tests or the catalog — fabricating "official" figures violates the entire premise of the project.
- Run a single test: `.venv\Scripts\python -m pytest tests/test_x.py::test_name -v`
- Run all tests: `.venv\Scripts\python -m pytest`

---

## Task 1: Add verdict enums + new source types

**Files:**
- Modify: `src/knesset_osint/models/enums.py`
- Test: `tests/test_official_statistic_model.py` (created here, expanded in Task 2)

- [ ] **Step 1: Write the failing test**

Create `tests/test_official_statistic_model.py`:

```python
"""Tests for the verdict enums and the official-statistics catalog model."""

from __future__ import annotations

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)


def test_verdict_outcome_values() -> None:
    assert VerdictOutcome.CONSISTENT.value == "consistent"
    assert VerdictOutcome.INCONSISTENT.value == "inconsistent"
    assert VerdictOutcome.UNVERIFIABLE.value == "unverifiable"


def test_verdict_review_status_values() -> None:
    assert VerdictReviewStatus.PENDING.value == "pending"
    assert VerdictReviewStatus.APPROVED.value == "approved"
    assert VerdictReviewStatus.REJECTED.value == "rejected"


def test_new_official_source_types() -> None:
    assert SourceType.CBS.value == "cbs"
    assert SourceType.IDF_SPOKESPERSON.value == "idf_spokesperson"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_official_statistic_model.py -v`
Expected: FAIL with `ImportError` / `AttributeError` for `VerdictOutcome`.

- [ ] **Step 3: Add the enums**

In `src/knesset_osint/models/enums.py`, add the two new `SourceType` members inside the existing `SourceType` class (next to `STATE_COMPTROLLER`):

```python
    CBS = "cbs"                              # Central Bureau of Statistics / הלמ"ס
    IDF_SPOKESPERSON = "idf_spokesperson"    # IDF spokesperson published figures
```

Then append two new enum classes at the end of the file:

```python
class VerdictOutcome(str, enum.Enum):
    """Result of checking a structured claim against official statistics."""

    CONSISTENT = "consistent"        # claim matches the official data
    INCONSISTENT = "inconsistent"    # claim contradicted by the official data
    UNVERIFIABLE = "unverifiable"    # no/insufficient official data to judge


class VerdictReviewStatus(str, enum.Enum):
    """Human-review lifecycle of a verdict. A verdict is only public when
    `published` is True; review status records whether a human has ruled."""

    PENDING = "pending"      # not yet human-reviewed
    APPROVED = "approved"    # a human (or the auto-gate) approved publication
    REJECTED = "rejected"    # a human rejected it; never publish
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_official_statistic_model.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/models/enums.py tests/test_official_statistic_model.py
git commit -m "feat: add verdict enums and official source types"
```

---

## Task 2: `OfficialStatistic` catalog model

**Files:**
- Create: `src/knesset_osint/models/official_statistic.py`
- Modify: `src/knesset_osint/models/__init__.py`
- Test: `tests/test_official_statistic_model.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_official_statistic_model.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models import OfficialStatistic


def test_official_statistic_round_trips(db_session: Session) -> None:
    stat = OfficialStatistic(
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value="עיר-א",
        value=72.5,
        unit="percent",
        period="2022",
        notes="נתון סינתטי לבדיקה בלבד",
        source_type=SourceType.IDF_SPOKESPERSON,
        source_name=SourceType.IDF_SPOKESPERSON.value,
        source_url="https://example.org/idf/report-2022",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    db_session.add(stat)
    db_session.commit()

    loaded = db_session.execute(select(OfficialStatistic)).scalar_one()
    assert loaded.metric == "idf_enlistment_rate"
    assert loaded.dimension_value == "עיר-א"
    assert loaded.value == 72.5
    assert loaded.source_url == "https://example.org/idf/report-2022"
    assert loaded.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_official_statistic_model.py::test_official_statistic_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'OfficialStatistic'`.

- [ ] **Step 3: Create the model**

Create `src/knesset_osint/models/official_statistic.py`:

```python
"""Curated 'official statistic' — the proof a claim is checked against.

Each row is one published figure (e.g. IDF enlistment rate for a given city in
a given year). It is sourced raw data, so it carries `ProvenanceMixin` and a
CHECK requiring `source_url`: an unsourced 'official statistic' is a
contradiction in terms and must never enter the catalog.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import ProvenanceMixin, TimestampMixin


class OfficialStatistic(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "official_statistics"
    __table_args__ = (
        CheckConstraint(
            "source_url IS NOT NULL", name="ck_official_statistic_requires_source"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # What is measured, e.g. "idf_enlistment_rate".
    metric: Mapped[str] = mapped_column(String(128), index=True)
    # The breakdown axis and its value, e.g. ("city", "תל אביב") or ("sector", "חרדים").
    dimension_type: Mapped[str] = mapped_column(String(32), index=True)
    dimension_value: Mapped[str] = mapped_column(String(255), index=True)

    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    period: Mapped[str | None] = mapped_column(String(64))  # e.g. "2022" or "2020-2022"
    notes: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Register the model**

In `src/knesset_osint/models/__init__.py`:
- add import: `from knesset_osint.models.official_statistic import OfficialStatistic`
- add the new enums to the existing enum import block: `VerdictOutcome, VerdictReviewStatus`
- add `"OfficialStatistic"`, `"VerdictOutcome"`, `"VerdictReviewStatus"` to `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_official_statistic_model.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/knesset_osint/models/official_statistic.py src/knesset_osint/models/__init__.py tests/test_official_statistic_model.py
git commit -m "feat: add OfficialStatistic catalog model"
```

---

## Task 3: `StatisticVerdict` model

**Files:**
- Create: `src/knesset_osint/models/statistic_verdict.py`
- Modify: `src/knesset_osint/models/__init__.py`
- Test: `tests/test_statistic_verdict_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_statistic_verdict_model.py`:

```python
"""StatisticVerdict defaults: unpublished + pending until the gate/human rules."""

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


def _politician() -> Politician:
    return Politician(
        knesset_person_id=965,
        first_name="בנימין",
        last_name="נתניהו",
        full_name="בנימין נתניהו",
        is_current=True,
        source_type=SourceType.KNESSET_ODATA,
        source_url="https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person(965)",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )


def test_verdict_defaults_to_unpublished_pending(db_session: Session) -> None:
    pol = _politician()
    stmt = Statement(
        politician=pol,
        claim="תל אביב עם שיעור הגיוס הנמוך בארץ.",
        statement_type=StatementType.INTERVIEW,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/interview/1",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    db_session.add_all([pol, stmt])
    db_session.flush()

    verdict = StatisticVerdict(
        statement_id=stmt.id,
        official_statistic_id=None,
        statistic_ids=[1, 2, 3],
        outcome=VerdictOutcome.INCONSISTENT,
        confidence=0.92,
        numeric_gap=14.0,
        statement_url=stmt.source_url,
        statistic_url="https://example.org/idf/report-2022",
        rationale="לבדיקה: הטענה אינה תואמת את הדירוג בנתונים.",
        adjudicator_version="test-0.0",
        # published / auto_published / review_status deliberately NOT set.
    )
    db_session.add(verdict)
    db_session.commit()

    loaded = db_session.execute(select(StatisticVerdict)).scalar_one()
    assert loaded.published is False
    assert loaded.auto_published is False
    assert loaded.review_status == VerdictReviewStatus.PENDING
    assert loaded.reviewer is None
    assert loaded.outcome == VerdictOutcome.INCONSISTENT
    assert loaded.statement_url == "https://example.org/interview/1"
    assert loaded.statistic_ids == [1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_statistic_verdict_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'StatisticVerdict'`.

- [ ] **Step 3: Create the model**

Create `src/knesset_osint/models/statistic_verdict.py`:

```python
"""Verdict: a structured claim checked against official statistics.

Like `Contradiction`, this is a *derived analysis* record (no ProvenanceMixin).
It stores BOTH source links (`statement_url` + `statistic_url`) so any verdict is
independently auditable, and it is born UNPUBLISHED and `review_status=pending`.
The only paths to `published=True` are (a) the confidence gate auto-approving a
high-confidence, non-transcription verdict, or (b) a human approving it. The
platform never silently makes a false-statement verdict public.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knesset_osint.db.base import Base
from knesset_osint.db.mixins import TimestampMixin
from knesset_osint.models.enums import VerdictOutcome, VerdictReviewStatus


class StatisticVerdict(Base, TimestampMixin):
    __tablename__ = "statistic_verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"), index=True
    )
    # The single statistic the verdict primarily turned on (nullable for
    # UNVERIFIABLE), plus the full set considered (for auditability).
    official_statistic_id: Mapped[int | None] = mapped_column(
        ForeignKey("official_statistics.id", ondelete="SET NULL")
    )
    statistic_ids: Mapped[list | None] = mapped_column(JSON)

    outcome: Mapped[VerdictOutcome] = mapped_column(
        SAEnum(VerdictOutcome, native_enum=False, length=32)
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    numeric_gap: Mapped[float | None] = mapped_column(Float)

    # Both source links, always — the core of auditability.
    statement_url: Mapped[str | None] = mapped_column(String(1024))
    statistic_url: Mapped[str | None] = mapped_column(String(1024))

    rationale: Mapped[str | None] = mapped_column(Text)
    adjudicator_version: Mapped[str | None] = mapped_column(String(64))

    # Publication state — unpublished + pending until the gate or a human rules.
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_published: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[VerdictReviewStatus] = mapped_column(
        SAEnum(VerdictReviewStatus, native_enum=False, length=32),
        default=VerdictReviewStatus.PENDING,
    )
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    statement: Mapped["Statement"] = relationship()
```

- [ ] **Step 4: Register the model**

In `src/knesset_osint/models/__init__.py`: add `from knesset_osint.models.statistic_verdict import StatisticVerdict` and `"StatisticVerdict"` to `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_statistic_verdict_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/knesset_osint/models/statistic_verdict.py src/knesset_osint/models/__init__.py tests/test_statistic_verdict_model.py
git commit -m "feat: add StatisticVerdict model (unpublished/pending by default)"
```

---

## Task 4: Alembic migration for the two new tables

**Files:**
- Create: `alembic/versions/<autogenerated>.py`

- [ ] **Step 1: Generate the migration**

Run (uses a throwaway sqlite so no Postgres is needed):

```bash
set DATABASE_URL=sqlite:///./_alembic_tmp.db
.venv\Scripts\alembic revision --autogenerate -m "add official_statistics and statistic_verdicts"
```

Expected: a new file under `alembic/versions/` whose `upgrade()` calls `op.create_table("official_statistics", ...)` and `op.create_table("statistic_verdicts", ...)`.

- [ ] **Step 2: Review the migration**

Open the generated file. Confirm both tables are created with the columns from Tasks 2–3, the CHECK constraint `ck_official_statistic_requires_source`, and the two foreign keys on `statistic_verdicts`. Confirm `downgrade()` drops both tables. Delete any spurious ops unrelated to these two tables.

- [ ] **Step 3: Verify it applies cleanly**

```bash
set DATABASE_URL=sqlite:///./_alembic_tmp.db
.venv\Scripts\alembic upgrade head
```

Expected: no error. Then delete the temp DB: `del _alembic_tmp.db`.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions
git commit -m "feat: migration for official_statistics and statistic_verdicts"
```

---

## Task 5: `StructuredClaim` input contract

**Files:**
- Create: `src/knesset_osint/verification/claims.py`
- Test: `tests/test_matching.py` (started here, used in Task 6)

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching.py`:

```python
"""Tests for the structured-claim contract and the statistic matcher."""

from __future__ import annotations

from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim
from knesset_osint.models.enums import SourceType


def _claim(**over) -> StructuredClaim:
    base = dict(
        politician_id=1,
        statement_id=None,
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value="תל אביב",
        assertion=ClaimAssertion.SUPERLATIVE_MIN,
        claimed_value=None,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/interview/1",
        exact_quote="לתל אביב שיעור הגיוס הנמוך בארץ",
    )
    base.update(over)
    return StructuredClaim(**base)


def test_structured_claim_holds_fields() -> None:
    c = _claim()
    assert c.metric == "idf_enlistment_rate"
    assert c.assertion is ClaimAssertion.SUPERLATIVE_MIN
    assert c.dimension_value == "תל אביב"
    assert c.source_type is SourceType.MANUAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_matching.py::test_structured_claim_holds_fields -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.verification.claims`.

- [ ] **Step 3: Create the contract**

Create `src/knesset_osint/verification/claims.py`:

```python
"""The input contract for verification: a single structured factual claim.

Plan 1 consumes `StructuredClaim` objects directly (constructed in tests / by a
seed script). Plan 2's LLM extractor will produce them from raw `Statement`
text. Keeping this a plain dataclass means the matcher/adjudicator/gate are
fully deterministic and testable with no LLM and no DB-write coupling.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from knesset_osint.models.enums import SourceType


class ClaimAssertion(str, enum.Enum):
    """What the claim asserts about the metric for its dimension."""

    SUPERLATIVE_MIN = "superlative_min"   # "the lowest ... in the country"
    SUPERLATIVE_MAX = "superlative_max"   # "the highest ..."
    VALUE = "value"                       # "the rate is X%"


@dataclass
class StructuredClaim:
    """One checkable claim, normalised for adjudication.

    Attributes:
        politician_id: FK to the politician who made the claim.
        statement_id: FK to the source `Statement` (None when verifying ad hoc).
        metric: e.g. "idf_enlistment_rate".
        dimension_type: breakdown axis, e.g. "city" or "sector".
        dimension_value: the specific dimension the claim is about, e.g. "תל אביב".
        assertion: the kind of assertion (superlative / value).
        claimed_value: numeric value asserted (only for assertion=VALUE).
        source_type: provenance of the statement (drives the publish gate).
        source_url: link to the statement source.
        exact_quote: the verbatim quote, for display and auditability.
    """

    politician_id: int
    statement_id: int | None
    metric: str
    dimension_type: str
    dimension_value: str | None
    assertion: ClaimAssertion
    claimed_value: float | None
    source_type: SourceType
    source_url: str | None
    exact_quote: str | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_matching.py::test_structured_claim_holds_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/verification/claims.py tests/test_matching.py
git commit -m "feat: add StructuredClaim verification input contract"
```

---

## Task 6: `StatisticMatcher` — find candidate statistics

**Files:**
- Create: `src/knesset_osint/verification/matching.py`
- Test: `tests/test_matching.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_matching.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from knesset_osint.models import OfficialStatistic
from knesset_osint.verification.matching import DimensionStatisticMatcher


def _stat(dim_value: str, value: float) -> OfficialStatistic:
    return OfficialStatistic(
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value=dim_value,
        value=value,
        unit="percent",
        period="2022",
        source_type=SourceType.IDF_SPOKESPERSON,
        source_url=f"https://example.org/idf/{dim_value}",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )


def test_matcher_returns_same_metric_and_dimension_type(db_session: Session) -> None:
    db_session.add_all([_stat("עיר-א", 50.0), _stat("עיר-ב", 70.0)])
    # A different metric that must NOT be matched:
    other = _stat("עיר-א", 1.0)
    other.metric = "crime_rate"
    db_session.add(other)
    db_session.commit()

    matcher = DimensionStatisticMatcher()
    matches = matcher.match(db_session, _claim(dimension_value="עיר-א"))

    metrics = {m.metric for m in matches}
    assert metrics == {"idf_enlistment_rate"}
    assert len(matches) == 2  # both cities of the same metric+dimension_type


def test_matcher_empty_when_no_metric(db_session: Session) -> None:
    matcher = DimensionStatisticMatcher()
    matches = matcher.match(db_session, _claim(metric="unknown_metric"))
    assert matches == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.verification.matching`.

- [ ] **Step 3: Create the matcher**

Create `src/knesset_osint/verification/matching.py`:

```python
"""Match a structured claim to the candidate official statistics it concerns.

For superlative claims ("lowest enlistment of any city") the adjudicator needs
the FULL set of same-metric, same-dimension_type rows to rank them, so the
matcher returns all of them — not just the claimed dimension. The concrete
matcher here is a simple exact metric + dimension_type filter; swap in a
fuzzier matcher later behind the same ABC without touching callers.
"""

from __future__ import annotations

import abc

from sqlalchemy import select
from sqlalchemy.orm import Session

from knesset_osint.models.official_statistic import OfficialStatistic
from knesset_osint.verification.claims import StructuredClaim


class StatisticMatcher(abc.ABC):
    """Contract: given a claim, return candidate `OfficialStatistic` rows."""

    matcher_version: str = "abstract"

    @abc.abstractmethod
    def match(self, session: Session, claim: StructuredClaim) -> list[OfficialStatistic]:
        raise NotImplementedError


class DimensionStatisticMatcher(StatisticMatcher):
    """Exact match on `metric` + `dimension_type` (returns the whole peer set)."""

    matcher_version: str = "dimension-exact-v0"

    def match(self, session: Session, claim: StructuredClaim) -> list[OfficialStatistic]:
        stmt = (
            select(OfficialStatistic)
            .where(OfficialStatistic.metric == claim.metric)
            .where(OfficialStatistic.dimension_type == claim.dimension_type)
        )
        return list(session.scalars(stmt).all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_matching.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/verification/matching.py tests/test_matching.py
git commit -m "feat: add DimensionStatisticMatcher"
```

---

## Task 7: `Adjudicator` — outcome + confidence + numeric gap

**Files:**
- Create: `src/knesset_osint/verification/adjudication.py`
- Test: `tests/test_adjudication.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_adjudication.py`:

```python
"""Adjudicator: turns (claim, statistics) into a VerdictDraft. Pure, no DB."""

from __future__ import annotations

from dataclasses import dataclass

from knesset_osint.models.enums import SourceType, VerdictOutcome
from knesset_osint.verification.adjudication import Adjudicator, VerdictDraft
from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim


@dataclass
class FakeStat:
    """A stand-in for OfficialStatistic (adjudicator only needs these fields)."""

    id: int
    dimension_value: str
    value: float
    source_url: str | None = "https://example.org/s"


def _claim(assertion, dimension_value, claimed_value=None) -> StructuredClaim:
    return StructuredClaim(
        politician_id=1,
        statement_id=None,
        metric="idf_enlistment_rate",
        dimension_type="city",
        dimension_value=dimension_value,
        assertion=assertion,
        claimed_value=claimed_value,
        source_type=SourceType.MANUAL,
        source_url="https://example.org/i/1",
        exact_quote="...",
    )


def _city_stats() -> list[FakeStat]:
    # 12 synthetic cities; "תל אביב" is near the TOP (rank 11 of 12 ascending),
    # so a "lowest in the country" claim about it is clearly false.
    rows = [FakeStat(id=i, dimension_value=f"עיר-{i}", value=float(i * 5)) for i in range(1, 12)]
    rows.append(FakeStat(id=99, dimension_value="תל אביב", value=58.0))
    return rows


def test_superlative_min_false_is_inconsistent_high_confidence() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "תל אביב"), _city_stats()
    )
    assert draft.outcome is VerdictOutcome.INCONSISTENT
    assert draft.confidence >= 0.85
    assert draft.primary_statistic_id == 99
    assert draft.numeric_gap is not None and draft.numeric_gap > 0


def test_superlative_min_true_is_consistent() -> None:
    stats = _city_stats()
    # Make "עיר-1" (value 5.0) the claimed dimension — it IS the minimum.
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "עיר-1"), stats
    )
    assert draft.outcome is VerdictOutcome.CONSISTENT


def test_value_claim_far_off_is_inconsistent() -> None:
    stats = [FakeStat(id=5, dimension_value="עיר-א", value=70.0)]
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.VALUE, "עיר-א", claimed_value=20.0), stats
    )
    assert draft.outcome is VerdictOutcome.INCONSISTENT
    assert draft.numeric_gap == -50.0


def test_no_stats_is_unverifiable_zero_confidence() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "תל אביב"), []
    )
    assert draft.outcome is VerdictOutcome.UNVERIFIABLE
    assert draft.confidence == 0.0


def test_unknown_dimension_is_unverifiable() -> None:
    draft = Adjudicator().adjudicate(
        _claim(ClaimAssertion.SUPERLATIVE_MIN, "עיר-לא-קיימת"), _city_stats()
    )
    assert draft.outcome is VerdictOutcome.UNVERIFIABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_adjudication.py -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.verification.adjudication`.

- [ ] **Step 3: Create the adjudicator**

Create `src/knesset_osint/verification/adjudication.py`:

```python
"""Adjudicator: compare a structured claim to candidate statistics.

Pure logic — takes the claim and the matched statistics (any object exposing
`id`, `dimension_value`, `value`, `source_url`) and returns a `VerdictDraft`.
It NEVER writes to the DB and NEVER decides publication (that is the publish
gate's job). The confidence is an explicit, inspectable function — no model,
no magic — so a reviewer can reproduce every number by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knesset_osint.models.enums import VerdictOutcome
from knesset_osint.verification.claims import ClaimAssertion, StructuredClaim


class _StatLike(Protocol):
    id: int
    dimension_value: str
    value: float
    source_url: str | None


@dataclass
class VerdictDraft:
    """The adjudicator's output (pre-publication)."""

    outcome: VerdictOutcome
    confidence: float
    numeric_gap: float | None
    primary_statistic_id: int | None
    statistic_ids: list[int]
    statistic_url: str | None
    rationale: str
    adjudicator_version: str


# A superlative ("lowest in the country") needs enough peers to be meaningful;
# below this we cap confidence proportionally.
MIN_SUPERLATIVE_COVERAGE = 10
# A VALUE claim within this relative tolerance is treated as consistent.
VALUE_CONSISTENT_REL = 0.05
# A VALUE claim beyond this relative gap is treated as inconsistent.
VALUE_INCONSISTENT_REL = 0.25


class Adjudicator:
    adjudicator_version: str = "rule-based-v0"

    def adjudicate(
        self, claim: StructuredClaim, statistics: list[_StatLike]
    ) -> VerdictDraft:
        if not statistics:
            return self._unverifiable("אין נתון רשמי תואם להכרעה.", [])

        ids = [s.id for s in statistics]
        if claim.assertion is ClaimAssertion.VALUE:
            return self._adjudicate_value(claim, statistics, ids)
        return self._adjudicate_superlative(claim, statistics, ids)

    # ------------------------------------------------------------- superlative
    def _adjudicate_superlative(
        self, claim: StructuredClaim, statistics: list[_StatLike], ids: list[int]
    ) -> VerdictDraft:
        ordered = sorted(statistics, key=lambda s: s.value)
        n = len(ordered)
        claimed = next(
            (s for s in ordered if s.dimension_value == claim.dimension_value), None
        )
        if claimed is None:
            return self._unverifiable(
                "הממד הנטען אינו קיים בקטלוג הנתונים הרשמי.", ids
            )

        is_min_claim = claim.assertion is ClaimAssertion.SUPERLATIVE_MIN
        extreme = ordered[0] if is_min_claim else ordered[-1]
        coverage = min(1.0, n / MIN_SUPERLATIVE_COVERAGE)

        if claimed.id == extreme.id:
            confidence = round(0.5 + 0.4 * coverage, 4)
            return VerdictDraft(
                outcome=VerdictOutcome.CONSISTENT,
                confidence=confidence,
                numeric_gap=0.0,
                primary_statistic_id=claimed.id,
                statistic_ids=ids,
                statistic_url=claimed.source_url,
                rationale=(
                    f"הטענה עקבית: {claim.dimension_value} הוא אכן הערך ה"
                    f"{'נמוך' if is_min_claim else 'גבוה'} ביותר מבין {n} ערכים."
                ),
                adjudicator_version=self.adjudicator_version,
            )

        # Distance of the claimed dimension from the asserted extreme, 0..1.
        idx = ordered.index(claimed)
        pos = idx / (n - 1) if n > 1 else 0.0
        distance = pos if is_min_claim else (1.0 - pos)
        confidence = round(min(0.97, distance * coverage), 4)
        gap = round(claimed.value - extreme.value, 4)
        return VerdictDraft(
            outcome=VerdictOutcome.INCONSISTENT,
            confidence=confidence,
            numeric_gap=gap,
            primary_statistic_id=claimed.id,
            statistic_ids=ids,
            statistic_url=claimed.source_url,
            rationale=(
                f"הטענה אינה תואמת נתונים רשמיים: {claim.dimension_value} אינו ה"
                f"{'נמוך' if is_min_claim else 'גבוה'} ביותר; ערכו {claimed.value} "
                f"לעומת הקיצון {extreme.value} (מתוך {n} ערכים)."
            ),
            adjudicator_version=self.adjudicator_version,
        )

    # ------------------------------------------------------------------ value
    def _adjudicate_value(
        self, claim: StructuredClaim, statistics: list[_StatLike], ids: list[int]
    ) -> VerdictDraft:
        match = next(
            (s for s in statistics if s.dimension_value == claim.dimension_value), None
        )
        if match is None or claim.claimed_value is None:
            return self._unverifiable("אין נתון מספרי תואם לאימות הערך הנטען.", ids)

        actual = match.value
        gap = round(claim.claimed_value - actual, 4)
        rel = abs(gap) / max(abs(actual), 1e-9)
        if rel <= VALUE_CONSISTENT_REL:
            outcome, confidence = VerdictOutcome.CONSISTENT, round(0.9, 4)
        elif rel >= VALUE_INCONSISTENT_REL:
            outcome, confidence = VerdictOutcome.INCONSISTENT, round(min(0.97, 0.6 + rel), 4)
        else:
            outcome, confidence = VerdictOutcome.UNVERIFIABLE, 0.5
        return VerdictDraft(
            outcome=outcome,
            confidence=confidence,
            numeric_gap=gap,
            primary_statistic_id=match.id,
            statistic_ids=ids,
            statistic_url=match.source_url,
            rationale=(
                f"הערך הנטען {claim.claimed_value} מול הנתון הרשמי {actual} "
                f"(פער {gap})."
            ),
            adjudicator_version=self.adjudicator_version,
        )

    # ------------------------------------------------------------------ helper
    def _unverifiable(self, rationale: str, ids: list[int]) -> VerdictDraft:
        return VerdictDraft(
            outcome=VerdictOutcome.UNVERIFIABLE,
            confidence=0.0,
            numeric_gap=None,
            primary_statistic_id=None,
            statistic_ids=ids,
            statistic_url=None,
            rationale=rationale,
            adjudicator_version=self.adjudicator_version,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_adjudication.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/verification/adjudication.py tests/test_adjudication.py
git commit -m "feat: add rule-based Adjudicator with explicit confidence"
```

---

## Task 8: `PublishGate` — confidence + source gating

**Files:**
- Create: `src/knesset_osint/verification/publish_gate.py`
- Test: `tests/test_publish_gate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_gate.py`:

```python
"""PublishGate: who gets auto-published vs. queued for human review."""

from __future__ import annotations

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from knesset_osint.verification.adjudication import VerdictDraft
from knesset_osint.verification.publish_gate import PublishGate


def _draft(outcome=VerdictOutcome.INCONSISTENT, confidence=0.95) -> VerdictDraft:
    return VerdictDraft(
        outcome=outcome,
        confidence=confidence,
        numeric_gap=10.0,
        primary_statistic_id=1,
        statistic_ids=[1, 2],
        statistic_url="https://example.org/s",
        rationale="...",
        adjudicator_version="rule-based-v0",
    )


def test_high_confidence_knesset_auto_publishes() -> None:
    d = PublishGate().decide(_draft(confidence=0.95), SourceType.KNESSET_ODATA)
    assert d.published is True
    assert d.auto_published is True
    assert d.review_status is VerdictReviewStatus.APPROVED


def test_low_confidence_queues_for_review() -> None:
    d = PublishGate().decide(_draft(confidence=0.6), SourceType.KNESSET_ODATA)
    assert d.published is False
    assert d.auto_published is False
    assert d.review_status is VerdictReviewStatus.PENDING


def test_transcription_source_never_auto_publishes_even_at_high_confidence() -> None:
    # MANUAL here stands for an interview/transcription-derived statement.
    d = PublishGate(transcription_source_types={SourceType.MANUAL}).decide(
        _draft(confidence=0.99), SourceType.MANUAL
    )
    assert d.published is False
    assert d.auto_published is False
    assert d.review_status is VerdictReviewStatus.PENDING


def test_unverifiable_never_auto_publishes() -> None:
    d = PublishGate().decide(
        _draft(outcome=VerdictOutcome.UNVERIFIABLE, confidence=0.0),
        SourceType.KNESSET_ODATA,
    )
    assert d.published is False
    assert d.review_status is VerdictReviewStatus.PENDING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_publish_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.verification.publish_gate`.

- [ ] **Step 3: Create the gate**

Create `src/knesset_osint/verification/publish_gate.py`:

```python
"""PublishGate: the confidence-gated hybrid publication rule.

A verdict auto-publishes only when ALL hold:
  * outcome is CONSISTENT or INCONSISTENT (never UNVERIFIABLE),
  * confidence >= threshold,
  * the statement's source is NOT transcription-derived.

Everything else is queued for human review (`published=False`, `pending`).
Transcription-sourced claims NEVER auto-publish, regardless of confidence — a
transcription error can fabricate a quote, which is the worst-case defamation,
so a human must confirm the quote first.
"""

from __future__ import annotations

from dataclasses import dataclass

from knesset_osint.models.enums import (
    SourceType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from knesset_osint.verification.adjudication import VerdictDraft

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
# Source types whose statements come from speech-to-text and must be
# human-confirmed before any verdict goes public (extended in Plan 3).
DEFAULT_TRANSCRIPTION_SOURCES: frozenset[SourceType] = frozenset()


@dataclass
class PublishDecision:
    published: bool
    auto_published: bool
    review_status: VerdictReviewStatus


class PublishGate:
    def __init__(
        self,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        transcription_source_types: frozenset[SourceType] | set[SourceType] = DEFAULT_TRANSCRIPTION_SOURCES,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.transcription_source_types = frozenset(transcription_source_types)

    def decide(self, draft: VerdictDraft, source_type: SourceType) -> PublishDecision:
        decisive = draft.outcome in (
            VerdictOutcome.CONSISTENT,
            VerdictOutcome.INCONSISTENT,
        )
        confident = draft.confidence >= self.confidence_threshold
        is_transcription = source_type in self.transcription_source_types

        if decisive and confident and not is_transcription:
            return PublishDecision(
                published=True,
                auto_published=True,
                review_status=VerdictReviewStatus.APPROVED,
            )
        return PublishDecision(
            published=False,
            auto_published=False,
            review_status=VerdictReviewStatus.PENDING,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_publish_gate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/verification/publish_gate.py tests/test_publish_gate.py
git commit -m "feat: add confidence-gated PublishGate"
```

---

## Task 9: `verify_statement` orchestrator (match → adjudicate → gate → persist)

**Files:**
- Create: `src/knesset_osint/verification/verify.py`
- Test: `tests/test_verify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_verify.py -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.verification.verify`.

- [ ] **Step 3: Create the orchestrator**

Create `src/knesset_osint/verification/verify.py`:

```python
"""Orchestrate one claim through match -> adjudicate -> gate -> persist.

Builds a `StatisticVerdict` row (flushed for its id) but does NOT commit — the
caller owns the transaction, matching the convention in
`verification/contradiction.py`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from knesset_osint.core.logging import get_logger
from knesset_osint.models.enums import SourceType
from knesset_osint.models.statistic_verdict import StatisticVerdict
from knesset_osint.verification.adjudication import Adjudicator
from knesset_osint.verification.claims import StructuredClaim
from knesset_osint.verification.matching import (
    DimensionStatisticMatcher,
    StatisticMatcher,
)
from knesset_osint.verification.publish_gate import PublishGate

logger = get_logger("verification.verify")


def verify_statement(
    session: Session,
    claim: StructuredClaim,
    *,
    matcher: StatisticMatcher | None = None,
    adjudicator: Adjudicator | None = None,
    gate: PublishGate | None = None,
    transcription_source_types: set[SourceType] | None = None,
) -> StatisticVerdict:
    """Verify one structured claim and persist (flush) the resulting verdict."""
    matcher = matcher or DimensionStatisticMatcher()
    adjudicator = adjudicator or Adjudicator()
    if gate is None:
        gate = PublishGate(
            transcription_source_types=frozenset(transcription_source_types or set())
        )

    statistics = matcher.match(session, claim)
    draft = adjudicator.adjudicate(claim, statistics)
    decision = gate.decide(draft, claim.source_type)

    verdict = StatisticVerdict(
        statement_id=claim.statement_id,
        official_statistic_id=draft.primary_statistic_id,
        statistic_ids=draft.statistic_ids,
        outcome=draft.outcome,
        confidence=draft.confidence,
        numeric_gap=draft.numeric_gap,
        statement_url=claim.source_url,
        statistic_url=draft.statistic_url,
        rationale=draft.rationale,
        adjudicator_version=draft.adjudicator_version,
        published=decision.published,
        auto_published=decision.auto_published,
        review_status=decision.review_status,
    )
    session.add(verdict)
    session.flush()
    logger.info(
        "Verdict id=%s outcome=%s confidence=%.3f published=%s (statement_id=%s)",
        verdict.id,
        verdict.outcome.value,
        verdict.confidence,
        verdict.published,
        verdict.statement_id,
    )
    return verdict
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_verify.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/knesset_osint/verification/verify.py tests/test_verify.py
git commit -m "feat: add verify_statement orchestrator"
```

---

## Task 10: Catalog loader + curated catalog file

**Files:**
- Create: `src/knesset_osint/ingestion/catalog.py`
- Create: `src/knesset_osint/ingestion/catalogs/idf_enlistment_by_city.json`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: knesset_osint.ingestion.catalog`.

- [ ] **Step 3: Create the loader**

Create `src/knesset_osint/ingestion/catalog.py`:

```python
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
```

- [ ] **Step 4: Create the curated catalog file**

Create `src/knesset_osint/ingestion/catalogs/idf_enlistment_by_city.json`. **The `_TEMPLATE` row documents the shape; replace it with REAL rows whose `value` and `source_url` come from official IDF spokesperson / CBS / State Comptroller / Knesset-answer sources. Do NOT invent figures.**

```json
{
  "metric": "idf_enlistment_rate",
  "dimension_type": "city",
  "source_type": "idf_spokesperson",
  "unit": "percent",
  "rows": [
    {
      "dimension_value": "_TEMPLATE",
      "value": 0.0,
      "period": "YYYY",
      "source_url": "https://OFFICIAL-SOURCE-URL",
      "notes": "Replace with a real, sourced figure. Rows without source_url are rejected."
    }
  ]
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_catalog.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/knesset_osint/ingestion/catalog.py src/knesset_osint/ingestion/catalogs/idf_enlistment_by_city.json tests/test_catalog.py
git commit -m "feat: add idempotent official-statistics catalog loader"
```

---

## Task 11: Leaderboard aggregation + export

**Files:**
- Create: `scripts/export_leaderboard.py`
- Test: `tests/test_leaderboard_export.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_leaderboard_export.py`:

```python
"""Leaderboard aggregation: counts PUBLISHED inconsistent verdicts per politician."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from knesset_osint.models import Politician, Statement, StatisticVerdict
from knesset_osint.models.enums import (
    SourceType,
    StatementType,
    VerdictOutcome,
    VerdictReviewStatus,
)
from scripts.export_leaderboard import build_leaderboard


def _pol(session: Session, pid: int, name: str) -> Politician:
    p = Politician(
        knesset_person_id=pid,
        full_name=name,
        is_current=True,
        source_type=SourceType.KNESSET_ODATA,
        source_url=f"https://knesset.gov.il/p/{pid}",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


def _verdict(session: Session, pol: Politician, *, outcome, published) -> None:
    stmt = Statement(
        politician_id=pol.id,
        claim="טענה לבדיקה",
        statement_type=StatementType.PLENUM,
        source_type=SourceType.KNESSET_ODATA,
        source_url="https://knesset.gov.il/t/1",
        fetched_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    session.add(stmt)
    session.flush()
    session.add(
        StatisticVerdict(
            statement_id=stmt.id,
            outcome=outcome,
            confidence=0.9,
            statement_url=stmt.source_url,
            statistic_url="https://example.org/s",
            published=published,
            review_status=(
                VerdictReviewStatus.APPROVED if published else VerdictReviewStatus.PENDING
            ),
        )
    )
    session.flush()


def test_leaderboard_counts_only_published_inconsistent(db_session: Session) -> None:
    a = _pol(db_session, 1, "פוליטיקאי א")
    b = _pol(db_session, 2, "פוליטיקאי ב")
    # a: 2 published inconsistent + 1 unpublished inconsistent (must not count)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=True)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=True)
    _verdict(db_session, a, outcome=VerdictOutcome.INCONSISTENT, published=False)
    # a: 1 published CONSISTENT (must not count toward contradictions)
    _verdict(db_session, a, outcome=VerdictOutcome.CONSISTENT, published=True)
    # b: 1 published inconsistent
    _verdict(db_session, b, outcome=VerdictOutcome.INCONSISTENT, published=True)
    db_session.commit()

    board = build_leaderboard(db_session)

    assert [r["full_name"] for r in board] == ["פוליטיקאי א", "פוליטיקאי ב"]  # sorted desc
    assert board[0]["contradicted_count"] == 2
    assert board[1]["contradicted_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_leaderboard_export.py -v`
Expected: FAIL with `ModuleNotFoundError: scripts.export_leaderboard`.

(Note: tests already import other `scripts.*` modules — `scripts` is importable from repo root. If collection errors on `scripts` not being a package, add an empty `scripts/__init__.py` as part of this task.)

- [ ] **Step 3: Create the export script**

Create `scripts/export_leaderboard.py`:

```python
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
from knesset_osint.models import Politician, StatisticVerdict
from knesset_osint.models.enums import VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "data"


def build_leaderboard(session: Session) -> list[dict]:
    """Return [{slug, full_name, party, contradicted_count}, ...] desc by count."""
    count_col = func.count(StatisticVerdict.id).label("n")
    rows = session.execute(
        select(Politician, count_col)
        .join(StatisticVerdict.statement)  # verdict -> statement
        .join(Politician, Politician.id == knesset_osint.models.Statement.politician_id)
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
```

If the `join` expression above is awkward against the existing mapper, an equivalent explicit form is acceptable: `select(Politician.full_name, Politician.current_party, Politician.knesset_person_id, Politician.id, count_col).select_from(StatisticVerdict).join(Statement, Statement.id == StatisticVerdict.statement_id).join(Politician, Politician.id == Statement.politician_id)...`. Use whichever passes the test; keep the WHERE/GROUP BY/ORDER BY identical.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_leaderboard_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/export_leaderboard.py tests/test_leaderboard_export.py
git commit -m "feat: add leaderboard aggregation + export"
```

---

## Task 12: Minimal Hebrew/RTL leaderboard page

**Files:**
- Create: `docs/leaderboard.html`
- Create: `docs/leaderboard.js`

- [ ] **Step 1: Create the page**

Create `docs/leaderboard.html` (RTL, mobile-first, matches the existing static site; fetches `data/leaderboard.json`):

```html
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>לוח אמירות שסותרות נתונים רשמיים</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="container">
    <h1>אמירות שסותרות נתונים רשמיים</h1>
    <p class="disclaimer">
      הדירוג מבוסס על אמירות שנמצאו <strong>לא תואמות נתונים רשמיים</strong>, עם קישור למקור הרשמי לכל קביעה.
      זו אינה קביעה ש"פלוני שקרן" — כל פריט ניתן לבדיקה עצמאית מול המקור.
    </p>
    <ol id="board" class="board"></ol>
    <p id="empty" hidden>אין עדיין נתונים מפורסמים.</p>
  </main>
  <script src="leaderboard.js"></script>
</body>
</html>
```

Create `docs/leaderboard.js`:

```javascript
// Render the leaderboard from the static JSON the export script produced.
fetch("data/leaderboard.json")
  .then((r) => (r.ok ? r.json() : { rows: [] }))
  .then((data) => {
    const rows = (data && data.rows) || [];
    const board = document.getElementById("board");
    if (!rows.length) {
      document.getElementById("empty").hidden = false;
      return;
    }
    for (const row of rows) {
      const li = document.createElement("li");
      li.className = "board-row";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = row.full_name + (row.party ? ` (${row.party})` : "");
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = row.contradicted_count;
      li.append(name, count);
      board.appendChild(li);
    }
  })
  .catch(() => {
    document.getElementById("empty").hidden = false;
  });
```

- [ ] **Step 2: Verify it renders locally**

Run: `.venv\Scripts\python scripts/export_leaderboard.py` (writes `docs/data/leaderboard.json`; with an empty DB it writes an empty board), then open `docs/leaderboard.html` in a browser. Expected: the page loads, RTL, and shows either rows or the "אין עדיין נתונים" message. (No automated test — this is static markup.)

- [ ] **Step 3: Commit**

```bash
git add docs/leaderboard.html docs/leaderboard.js
git commit -m "feat: add minimal Hebrew/RTL leaderboard page"
```

---

## Task 13: Full suite green + wrap-up

- [ ] **Step 1: Run the entire test suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all tests pass (the original 12 + the new ones from Tasks 1–11).

- [ ] **Step 2: If anything fails, fix before proceeding**

Use superpowers:systematic-debugging if a failure is non-obvious. Do not move on with a red suite.

- [ ] **Step 3: Final commit (if any fixes were made)**

```bash
git add -A
git commit -m "test: full suite green for claim-verification core"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** §4 data model → Tasks 2,3 (+ reuse of existing `Statement`); §5 pipelines (the verdict core) → Tasks 6–9; §5 publish gate → Task 8; §9 statistics catalog → Task 10; §6/§8 leaderboard → Tasks 11–12; §7 verdict language → enforced in adjudicator rationales (Task 7) and the page copy (Task 12). **Deferred by design to later plans:** Knesset-transcript ingestion + LLM extraction (Plan 2), interviews/discovery/transcription + `media_source` (Plan 3), submissions + `dispute` + review console (Plan 4). These deferrals are listed in the roadmap below so nothing is silently dropped.
- **Placeholder scan:** none — every step has concrete code/commands. The catalog JSON `_TEMPLATE` row is intentional (and the loader + a test enforce that template/unsourced rows are skipped), not a plan placeholder.
- **Type consistency:** `StructuredClaim`, `ClaimAssertion`, `VerdictDraft`, `PublishDecision`, `VerdictOutcome`, `VerdictReviewStatus`, `verify_statement`, `build_leaderboard`, `load_official_statistics`, `DimensionStatisticMatcher.match`, `Adjudicator.adjudicate`, `PublishGate.decide` are named identically everywhere they appear across tasks.

---

## Roadmap: Plans 2–4 (each gets its own full plan later)

### Plan 2 — LLM claim extraction (Knesset-transcript path)
- Ingest plenum/committee protocols for all 120 MKs into `Statement` (extend existing ingestion sources).
- `ClaimExtractor` (LLM) turning `Statement.full_text` → zero or more `StructuredClaim` (filters opinion/rhetoric/promise; keeps exact quote + source link).
- Batch driver: extract → `verify_statement` → high-confidence Knesset verdicts auto-publish.
- Tests with a fake LLM client (no network), asserting only checkable claims are extracted.

### Plan 3 — Interview pipeline (deep coverage)
- `media_source` model (discovered/uploaded clips: url, channel, MK, transcript, status).
- `discovery` service: YouTube Data API + podcast RSS over a curated channel allowlist + relevance filter + dedupe.
- `yt-dlp` audio download; pluggable `Transcriber` ABC with `WhisperLocalTranscriber` (default) and `GeminiTranscriber` (fallback).
- Upload endpoint + triage queue.
- Wire transcription source types into `PublishGate.transcription_source_types` so these claims ALWAYS route to human review.

### Plan 4 — Submissions, dispute & review console
- `submission` model + public submit flow (primary-source link REQUIRED, else auto-reject).
- `dispute` model + public "ערער על הקביעה" flow + correction log.
- Human review console: the queue of `pending` verdicts, one-tap approve/reject (sets `review_status`, `published`, `reviewer`, `reviewed_at`).
- Profile-page verdict cards (quote → official data → verdict → source links → dispute link).
```
