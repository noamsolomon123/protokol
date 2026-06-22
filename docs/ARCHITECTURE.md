# Architecture

This document explains how the Knesset OSINT platform is put together: the
two-database design, the ingestion pipeline, the verification / RAG layer, and
the path from the Netanyahu pilot to all 120 MKs plus additional public sources.

The guiding principle is the **objectivity mandate** (see the
[README](../README.md)): every stored datum is source-linked and never
fabricated, and the verification layer *flags* contradictions for human review
rather than asserting wrongdoing.

---

## 1. Two-database design

We deliberately split storage by access pattern.

### PostgreSQL — structured source-of-truth

The relational store holds the canonical, provenance-bearing records. SQLAlchemy
2.0 (typed `Mapped[...]` style) defines the schema; Alembic manages migrations.

Tables (see `src/knesset_osint/models/`):

| Model | Holds | Key external source |
|---|---|---|
| `Politician` | the MK / official; `knesset_person_id`, name, party, `external_ids` reconciliation map | `KNS_Person` (V4) |
| `Role` | positions over time (minister, faction, committee, government #) | `KNS_PersonToPosition` (V4) |
| `Bill`, `BillSponsorship` | bills and who initiated them (`is_initiator`, `ordinal`) | `KNS_Bill`, `KNS_BillInitiator` (V4) |
| `VoteEvent`, `Vote` | vote headers + each MK's stance | Votes.svc V3 tables |
| `Statement` | a public claim by the MK (`claim`, `topic`, `statement_type`, `verification_status`, optional `embedding`) | varied (often `manual` with a source_url) |
| `Action` | concrete actions/achievements (`action_type`) | varied |
| `Contradiction` | a flagged statement↔evidence mismatch | derived (verification layer) |

**Provenance is structural.** Every external-origin table mixes in
`ProvenanceMixin` (`source_type`, `source_name`, `source_url`,
`source_record_id`, `raw_payload`, `fetched_at`) and `TimestampMixin`
(`created_at`, `updated_at`). The evidence tables (`statements`, `actions`) add a
DB-level `CHECK (source_url IS NOT NULL)` so no claim can exist without a link.

**Enums** are stored as `VARCHAR + CHECK` (`Enum(native_enum=False)`), which keeps
migrations portable across Postgres (prod) and SQLite (tests) and lets us add
enum members (e.g. new `SourceType`s) without native-enum `ALTER` pain.

### Neo4j — entity / relationship graph

The graph store answers *relationship* questions that are awkward in SQL:
politician → party → coalition, sponsorship co-authorship networks, and (as we
scale) money/appointment links across people and organizations. It is **derived**
from the Postgres records, never a separate source of truth, and is toggled by
`settings.neo4j_enabled`. If Neo4j is disabled, ingestion and the API still work
against Postgres alone.

Connection settings: `neo4j_uri`, `neo4j_user`, `neo4j_password`,
`neo4j_enabled` (all from `core/config.py::settings`).

---

## 2. Ingestion pipeline

The pipeline is intentionally uniform so onboarding a new source or a new MK is
an adapter/config change, not a rewrite.

```
                 ┌──────────────┐
  live OData ───▶│ Source       │  subclass of BaseSource; uses ODataClient.
  (V4 / V3)      │ adapter      │  Exposes domain methods (get_person,
                 └──────┬───────┘  iter_bills, iter_votes, ...).
                        │ yields
                        ▼
                 ┌──────────────┐
                 │  RawRecord   │  {data, source_type, source_url,
                 │              │   source_record_id, fetched_at}
                 └──────┬───────┘
                        │ consumed by
                        ▼
                 ┌──────────────┐
                 │   Mapper     │  RawRecord -> ORM instance. Copies provenance
                 │              │  straight from the RawRecord onto the row.
                 └──────┬───────┘  Missing upstream value -> NULL (never invent).
                        │
                        ▼
                 ┌──────────────┐
                 │   Upsert     │  idempotent write keyed on the natural/unique
                 │ (Postgres)   │  key (e.g. knesset_person_id, unique
                 └──────┬───────┘  (politician_id, vote_event_id), etc.)
                        │ (optional)
                        ▼
                 ┌──────────────┐
                 │ Graph sync   │  project the new rows into Neo4j (if enabled).
                 └──────────────┘
```

### The shared `ODataClient`

`ingestion/sources/base.py::ODataClient` is a thin, dependency-light reader that
speaks **both** OData dialects:

- **V4** (ParliamentInfo): `$count=true`, `@odata.nextLink`.
- **V3** (Votes.svc): `$inlinecount=allpages`, `odata.nextLink` (sometimes
  relative), and `$skip` fallback paging.

It retries transient failures with exponential backoff (`tenacity`,
`settings.http_max_retries`), sets a civic User-Agent, and **defends against the
Imperva bot challenge**: if a `200` response is HTML instead of JSON it raises a
retryable error instead of feeding garbage to the JSON parser. We use V3
`Votes.svc` precisely because the V4 Votes endpoint is bot-protected — and we add
**no** challenge-evasion logic.

`iter_entities(...)` yields `RawRecord`s and transparently handles both
server-driven (`nextLink`) and client-driven (`$skip`) paging. `count(...)` is a
best-effort total.

### Idempotent upserts & reconciliation

Mappers write through upserts keyed on the model's natural key so re-running
ingestion is safe:

- `Politician` → `knesset_person_id` (unique).
- `Vote` → `unique(politician_id, vote_event_id)`.
- `BillSponsorship` → `unique(politician_id, bill_id)`.

**Person↔MK reconciliation** is the one subtlety: `KNS_Person.Id` (ParliamentInfo)
may differ from the Votes service's MK id. We reconcile by matching
`FirstName + LastName` via `View_Vote_MK_Individual` and store the result in
`Politician.external_ids['votes_mk_id']`. This map is what makes scaling to 120
MKs mechanical.

---

## 3. Verification / RAG layer

The verification layer turns claims into reviewable, evidence-linked flags.

1. **Statements** carry an optional `embedding` (JSON list) field. In Phase 2 we
   populate it with sentence embeddings (the optional `rag` extra:
   `sentence-transformers`, `pgvector`, `numpy` — currently commented out in
   `pyproject.toml`).
2. **Retrieval.** For a given statement we retrieve candidate contradicting
   evidence: the MK's own votes (`Vote`/`VoteEvent`), bill positions, and prior
   statements. Semantic similarity (embeddings / pgvector) surfaces candidates;
   structured filters (date, topic, vote stance) sharpen them.
3. **Flagging.** When a candidate mismatch is found, the detector writes a
   `Contradiction` row with:
   - `status = needs_review` (the default — **always**),
   - `statement_url` **and** `evidence_url` (both sides linked),
   - `evidence_kind` + `evidence_id`, a `score`, a `rationale`, and a
     `detector_version` for auditability.
4. **Human-in-the-loop.** A reviewer sets `human_verdict` /
   `status ∈ {confirmed, dismissed}`, `reviewed_by`, `reviewed_at`. The platform
   **never** auto-labels a statement a lie. `Statement.verification_status`
   mirrors the lifecycle (`unverified → needs_review → supported / contradicted`).

This design keeps the objectivity invariant intact: the machine proposes
evidence-backed candidates; a human adjudicates.

---

## 4. Scaling path

The pilot is one MK; the architecture targets the full Knesset and a widening set
of public-accountability sources.

### From 1 to 120 MKs

- **No schema change.** `Politician` is the central entity; everything else hangs
  off `politician_id`. Onboarding another MK is `knesset-osint ingest
  --person-id <KNS_Person.Id>` (see
  [ADDING_A_POLITICIAN.md](ADDING_A_POLITICIAN.md)).
- **Batch ingest.** Iterate `KNS_Person` where `IsCurrent eq true` and ingest
  each id; reconciliation via `external_ids['votes_mk_id']` handles the Votes-id
  mismatch per member.
- **Parties / roles** populate automatically from `KNS_PersonToPosition`
  (`faction_name`, `government_num`, `ministry_name`, committee, dates), so party
  membership and ministerial history come for free per MK.

### New sources (already reserved in the `SourceType` enum)

`budget_key` (Mafteach HaTaktsiv), `state_comptroller`, `court`,
`corporations_authority`. Each becomes a new `BaseSource` subclass + mapper that
emits provenance-bearing `RawRecord`s — no change to the core pipeline. See
[ADDING_A_SOURCE.md](ADDING_A_SOURCE.md). These sources mostly feed `Action`,
`Statement`, and `Contradiction` evidence (e.g. a comptroller finding that
contradicts a public claim), and enrich the Neo4j graph (e.g. corporate ties).

### Operational scaling

- **Config-driven endpoints.** All base URLs, paging size, timeouts, and retries
  live in `settings`; moving endpoints or tuning throughput is an env change.
- **Idempotent re-ingest** means scheduled refreshes (e.g. nightly) are safe.
- **Open Knesset** stays strictly enrichment/fallback
  (`enable_open_knesset_enrichment`), never source-of-truth, so the canonical
  record always traces to an official endpoint.
