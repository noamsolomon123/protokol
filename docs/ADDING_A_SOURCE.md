# Adding a data source

The pipeline is uniform on purpose: a source is one adapter that yields
`RawRecord`s, plus a mapper that turns those into provenance-bearing ORM rows.
Adding a source is five small, mechanical steps and **never** touches the core
pipeline. Reserved future sources (`budget_key`, `state_comptroller`, `court`,
`corporations_authority`) already have `SourceType` enum members waiting.

> The **objectivity mandate** binds every source: each `RawRecord` must carry a
> real `source_url`, the verbatim payload, and a fetch time; missing upstream
> values become `NULL`, never invented; and official endpoints are
> source-of-truth while Open Knesset is enrichment-only.

---

## Step 1 — Add a `SourceType` enum member

In `src/knesset_osint/models/enums.py`, add a member to `SourceType` (skip this
if you're using an already-reserved one). Because enums are stored as
`VARCHAR + CHECK` (`native_enum=False`), adding a member needs an Alembic
migration only if you tighten the CHECK; the value itself stores fine.

```python
class SourceType(str, enum.Enum):
    ...
    BUDGET_KEY = "budget_key"          # Mafteach HaTaktsiv
    # NEW:
    MY_SOURCE = "my_source"            # one-line description of the source
```

---

## Step 2 — Subclass `BaseSource`

Create `src/knesset_osint/ingestion/sources/my_source.py`. Set the two required
class attrs (`source_type`, `name`) and expose domain methods that return
`RawRecord`s. For an OData feed, reuse the shared `ODataClient` (it handles V3/V4
paging, retries, and the bot-challenge guard for you).

```python
"""Adapter for <My Source>. Returns RawRecord objects with full provenance."""

from __future__ import annotations

from collections.abc import Iterator

from knesset_osint.core.config import settings
from knesset_osint.ingestion.sources.base import BaseSource, ODataClient, RawRecord
from knesset_osint.models.enums import SourceType


class MySource(BaseSource):
    source_type = SourceType.MY_SOURCE
    name = "My Source"

    def __init__(self) -> None:
        # If the source is OData, build a client. Add the base URL to settings
        # (Step 0) rather than hardcoding it.
        self._client = ODataClient(
            base_url=settings.my_source_base,   # add this field to core/config.py
            source_type=self.source_type,
            odata_version=4,                    # or 3 for a .svc feed
        )

    def iter_records(self, person_id: int) -> Iterator[RawRecord]:
        # ODataClient already wraps each row in a RawRecord with source_type,
        # source_url (deep link), source_record_id, and fetched_at.
        yield from self._client.iter_entities(
            "MyEntitySet",
            filter=f"PersonID eq {person_id}",
        )

    def close(self) -> None:
        self._client.close()
```

**If the source is NOT OData** (HTML page, CSV dump, REST/JSON API), build the
`RawRecord` yourself so provenance is explicit and honest:

```python
from datetime import datetime, timezone

RawRecord(
    data=parsed_row,                      # the verbatim upstream object (dict)
    source_type=SourceType.MY_SOURCE,
    source_url="https://.../the/exact/page-or-record",  # a real deep link
    source_record_id=str(parsed_row.get("id")),         # or None if none exists
    fetched_at=datetime.now(timezone.utc),
)
```

> **No challenge evasion.** If a source is bot-protected (like the V4 Votes
> endpoint behind Imperva), use the open official path instead — do **not** add
> code to defeat the challenge. `ODataClient._get` already turns an HTML
> challenge response into a retryable error.

> **Probe before you code.** For feeds whose columns aren't pre-verified, hit
> them live first and read defensively with `row.get()` over candidate keys.
> Example: `curl -s "https://knesset.gov.il/Odata/Votes.svc/View_Vote_MK_Individual?\$top=1&\$format=json"`.
> Record the columns you found in a comment in the mapper.

---

## Step 3 — Write a mapper (`RawRecord` → ORM row)

Create `src/knesset_osint/ingestion/mappers/my_source.py`. The mapper's one job
is to translate fields and **copy provenance straight from the `RawRecord`** onto
the `ProvenanceMixin` columns. Missing upstream values → `None` (NULL).

```python
"""Map My Source RawRecords onto ORM rows. Columns observed live: <list them>."""

from __future__ import annotations

from knesset_osint.ingestion.sources.base import RawRecord
from knesset_osint.models.action import Action
from knesset_osint.models.enums import ActionType


def to_action(rec: RawRecord, *, politician_id: int) -> Action:
    d = rec.data
    return Action(
        politician_id=politician_id,
        action_type=ActionType.OTHER,                 # map from the source
        title=d.get("Title"),                          # NULL if absent — never invent
        description=d.get("Description"),
        # --- provenance: copy verbatim from the RawRecord ---
        source_type=rec.source_type,
        source_name="My Source",
        source_url=rec.source_url,                      # REQUIRED for Action/Statement
        source_record_id=rec.source_record_id,
        raw_payload=d,
        fetched_at=rec.fetched_at,
    )
```

`Action` and `Statement` enforce `source_url NOT NULL` at the DB level, so a
mapper that drops the link will (correctly) fail to insert.

---

## Step 4 — Call it from the pipeline (idempotent upsert)

Wire the adapter + mapper into the ingestion pipeline (e.g.
`src/knesset_osint/ingestion/pipeline.py`) and write through an **idempotent
upsert** on the model's natural/unique key so re-ingest is safe.

```python
from knesset_osint.db.session import SessionLocal
from knesset_osint.ingestion.sources.my_source import MySource
from knesset_osint.ingestion.mappers.my_source import to_action


def ingest_my_source(person_id: int, politician_id: int) -> int:
    src = MySource()
    n = 0
    with SessionLocal() as db:
        for rec in src.iter_records(person_id):
            row = to_action(rec, politician_id=politician_id)
            db.merge(row)          # or a key-based upsert if there's a unique key
            n += 1
        db.commit()
    src.close()
    return n
```

Hook `ingest_my_source` into the per-person ingest flow so it runs alongside the
existing person/roles/bills/votes steps.

---

## Step 5 — Test, migrate, run

```bash
# Unit-test the adapter with respx (mock the HTTP) and the mapper with a fixture
# RawRecord; assert provenance fields are populated and missing values are NULL.
C:/Users/noams/knesset-osint/.venv/Scripts/python.exe -m pytest tests/ -k my_source

# If you added/changed columns, generate + apply a migration:
C:/Users/noams/knesset-osint/.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add my_source"
C:/Users/noams/knesset-osint/.venv/Scripts/python.exe -m alembic upgrade head

# Then re-ingest the pilot and confirm the new rows + their source links:
knesset-osint ingest --person-id 965
```

---

## Checklist

- [ ] `SourceType` member added (or reuse a reserved one).
- [ ] (If OData) base URL added to `core/config.py::Settings` + `.env.example`.
- [ ] Adapter subclasses `BaseSource`, sets `source_type` + `name`, returns `RawRecord`s.
- [ ] Every `RawRecord` has a real `source_url` and the verbatim `data`.
- [ ] Mapper copies all provenance fields; missing upstream values → `NULL`.
- [ ] Pipeline call uses an idempotent upsert on the natural key.
- [ ] Tests (respx + fixtures) and, if schema changed, an Alembic migration.
- [ ] No challenge-evasion code; official endpoint is source-of-truth.
