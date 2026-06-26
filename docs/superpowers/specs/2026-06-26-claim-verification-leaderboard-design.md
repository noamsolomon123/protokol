# Claim Verification & Leaderboard — Design Spec

**Date:** 2026-06-26
**Status:** Approved design, pending implementation plan
**Module of:** `knesset-osint` (extends the existing FastAPI + PostgreSQL + Neo4j platform)

---

## 1. Purpose

Build a module that exposes **false factual statements by Israeli politicians** in a rigorous, non-partisan, lawsuit-proof way. The platform:

1. Ingests what the 120 Knesset members say (official Knesset transcripts + discovered/uploaded interviews).
2. Extracts **checkable factual claims** (not opinions, predictions, or promises).
3. Compares each claim against an **official, sourced statistic**.
4. Publishes a verdict — *consistent / inconsistent with official data / unverifiable* — with the data and source shown side by side.
5. Ranks all 120 MKs on a public **leaderboard** by count of statements contradicted by official sources.

The motivating example: a politician claims "Tel Aviv has the lowest IDF enlistment rate." The platform compares this against published enlistment data showing Tel Aviv is near the top, and publishes the contradiction with the source.

**Non-goals / guiding principles:**
- 100% fact-based, zero hallucinations, no political bias (left or right).
- Every verdict carries a verifiable official source link.
- The platform never asserts the bare word "liar/שקר." It states "statement inconsistent with official data" and shows the data.

---

## 2. Relationship to existing project

This is an **extension** of `knesset-osint`, not a new project. It reuses:
- The 120-MK roster and politician data model.
- Existing official-source clients (Knesset OData V4 ParliamentInfo, V3 Votes.svc, Open Knesset).
- PostgreSQL + SQLAlchemy + Alembic, Neo4j, Docker Compose.
- The static-site export pattern (`export_site_data.py` → JSON → GitHub Pages, Hebrew/RTL, mobile-first).
- pytest test harness, `core/console.py` UTF-8 Hebrew console handling.

New code is **additive**: new tables, new pipeline stages, new public views. It does not replace the existing Accountability Scorecard (that remains a separate module/layer).

---

## 3. Key decisions (locked in brainstorming, 2026-06-26)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Extend `knesset-osint` | Reuse roster, sources, objectivity framing, static-site pipeline |
| Claim types | **Only checkable factual/statistical claims** | The only class that is both automatable and defensible; verdict comes from a government dataset, not from us |
| Statement sources | Knesset transcripts (spine) + source-linked submissions + discovered/uploaded interviews | Official firehose first; viral content via interviews; never fragile social scraping in v1 |
| Verdict model | **Confidence-gated hybrid** | High-confidence clean contradictions auto-publish; ambiguous ones get a quick human OK (~70-80% automated) |
| Pilot domain | **IDF enlistment by city/sector** | Core motivating example; built as a curated sourced statistics table |
| Pilot breadth | **All 120 MKs** | Full roster + ingestion from day one; verdicts populate over time as checkable claims are found |
| Interview transcription | Pluggable `Transcriber`: local Whisper (default) ⇄ Gemini free API (fallback) | Deep coverage of interviews; local is free/private/unlimited, Gemini is the configurable alternative |
| Interview ingestion | **Automatic discovery** (YouTube Data API + podcast RSS over a curated channel allowlist) **+ manual upload** fallback | Best-effort crawler nets most clips; upload covers misses |
| Transcription safety | Transcription-sourced claims **never** auto-publish | A transcription error fabricates a quote → worst-case defamation; always human-reviewed |

---

## 4. Data model (new PostgreSQL tables)

- **`claim`** — one extracted factual claim.
  Fields: `id`, `politician_id` (FK), `exact_quote`, `claim_normalized`, `topic`, `dimension` (e.g. city/sector), `stated_at` (date), `source_type` (knesset_transcript / interview / submission), `source_url`, `media_source_id` (nullable FK), `status` (extracted / matched / adjudicated / published / rejected).

- **`official_statistic`** — the curated "proof" table.
  Fields: `id`, `metric` (e.g. "idf_enlistment_rate"), `dimension_type` (city / sector), `dimension_value` (e.g. "Tel Aviv", "חרדים"), `value`, `unit`, `period` (year/range), `source_org` (IDF spokesperson / CBS / State Comptroller / Knesset written answer), `source_url`, `notes`, `ingested_at`.

- **`verdict`** — links a claim to the statistic(s) checked against.
  Fields: `id`, `claim_id` (FK), `statistic_ids` (array/assoc), `outcome` (consistent / inconsistent / unverifiable), `confidence` (0–1), `numeric_gap` (nullable), `auto_published` (bool), `published` (bool), `reviewer` (nullable), `review_notes`, `created_at`, `published_at`.

- **`media_source`** — discovered or uploaded interview clips.
  Fields: `id`, `politician_id` (FK, nullable until confirmed), `url`, `channel`, `title`, `published_at`, `origin` (discovered / uploaded), `transcript`, `transcriber` (whisper / gemini), `status` (queued / downloaded / transcribed / processed / rejected), `created_at`.

- **`submission`** — crowdsourced claims awaiting triage.
  Fields: `id`, `submitted_quote`, `politician_name`, `primary_source_url` (**required**), `submitter_contact` (optional), `status` (pending / accepted / rejected), `created_at`. Submissions with no primary-source link are rejected automatically.

- **`dispute`** — public "dispute this verdict" submissions + resolution log.
  Fields: `id`, `verdict_id` (FK), `reason`, `submitter_contact` (optional), `status` (open / upheld / corrected / dismissed), `resolution_notes`, `created_at`, `resolved_at`.

---

## 5. Pipelines

### 5.1 Knesset-transcript path (the spine)
1. **Ingest** — pull plenum/committee protocols for all 120 MKs (automated, idempotent).
2. **Extract** — LLM pass pulls checkable factual claims; keeps exact quote + source link.
3. **Match** — match claim to relevant `official_statistic` row(s) by topic + dimension.
4. **Adjudicate** — compute outcome + confidence + numeric gap.
5. **Publish gate** — high-confidence clean contradictions auto-publish; ambiguous → human review queue.

### 5.2 Interview path (deep coverage)
`Discover (YouTube Data API + RSS, curated allowlist, relevance filter) ▸ OR Manual upload ▸ Download audio (yt-dlp) ▸ Transcribe (Whisper local / Gemini) ▸ Extract ▸ Match ▸ Adjudicate + confidence ▸ ALWAYS human review ▸ Publish`

Transcription-sourced claims are **never** auto-published — a human verifies the transcribed quote matches the audio before any verdict goes live.

### 5.3 Submission path
`User submits quote + required primary-source link ▸ triage queue ▸ accepted submissions enter Extract ▸ (rest of pipeline) ▸ human review ▸ Publish`

---

## 6. New components / services

- **`discovery` service** — YouTube Data API + podcast RSS crawler over a curated allowlist of Israeli news/politics channels (ערוץ 12/13/14, כאן, גלי צה"ל, major podcasts). Relevance filter confirms the clip features the target MK and is new (dedupe). Best-effort, quota-aware.
- **`Transcriber` interface** — pluggable: `WhisperLocalTranscriber` (default, `large-v3`/`faster-whisper`, Hebrew) and `GeminiTranscriber` (free-tier fallback). Selectable per job.
- **`ClaimExtractor`** — LLM-based extraction of checkable factual claims from raw statement text; filters out opinion/rhetoric/prediction/promise.
- **`StatisticMatcher`** — maps a claim to `official_statistic` rows by topic + dimension.
- **`Adjudicator`** — computes outcome, confidence score, numeric gap.
- **`PublishGate`** — applies confidence thresholds + the transcription-never-auto rule; routes to auto-publish or review queue.
- **Upload endpoint + triage UI/queue** — for interviews the crawler missed and for submissions.

---

## 7. Verdict language (legal shield)

- Verdicts read **"אמירה שאינה תואמת נתונים רשמיים"** ("statement inconsistent with official data") — never "שקר/liar."
- Each verdict shows: the exact quote → the official dataset value → the verdict → official source link(s).
- The leaderboard ranks by **count of statements contradicted by official data**.
- Every verdict carries a visible **"ערער על הקביעה / dispute"** link feeding the `dispute` table, plus a public correction log.

Rationale: under Israeli defamation law (חוק איסור לשון הרע), a bare "liar" accusation against a public figure is actionable without proof of harm. A sourced "inconsistent with official data" statement, with the data shown, is defensible and more credible.

---

## 8. Public site (Hebrew / RTL, extends existing Pages site)

- **Leaderboard page** — all 120 MKs, sortable, ranked by verified-contradiction count, with topic filter (IDF enlistment first). MKs with no checked claims show 0 honestly.
- **MK profile page** — each verified claim as a card: quote → official data → verdict → source links → dispute link.
- Reuses the existing static export pattern (`export_site_data.py` → JSON → `/docs` → GitHub Pages, `.nojekyll`).

---

## 9. Official-statistics catalog (pilot)

For the pilot domain (IDF enlistment by city & sector), seed a curated `official_statistic` table from:
- IDF spokesperson releases
- CBS / הלמ"ס
- State Comptroller reports
- Official Knesset written answers (שאילתות / תשובות שרים)

Every row carries its official `source_url`. This is the deliberate, auditable answer to "there is no single clean enlistment API."

---

## 10. Phasing

- **Phase 1 (this build):** all 120 ingested from Knesset transcripts; IDF-enlistment catalog seeded; extraction → match → confidence-gated verdict; interview path (discovery + upload + transcription, human-reviewed); leaderboard + profiles live.
- **Phase 2:** more statistical domains (economy/cost-of-living, crime); social-media sources via official APIs; verdict-weight tuning; richer front-end.

---

## 11. Testing

- Unit tests per new component (extractor, matcher, adjudicator, publish gate, transcriber interface with a fake backend, discovery relevance filter).
- Pipeline idempotency tests (re-ingest produces no duplicates).
- Publish-gate rule tests: transcription-sourced claim is never auto-published; high-confidence clean Knesset claim auto-publishes; ambiguous queues for review.
- Verdict-language test: rendered output never contains a bare accusation label.
- Follow existing repo conventions; run `.venv\Scripts\python -m pytest`.

---

## 12. Explicitly OUT of scope (YAGNI for v1)

- Twitter/X scraping or any fragile social scraping.
- Auto-publishing without confidence gating; auto-publishing any transcription-sourced claim.
- Opinion / prediction / promise checking.
- Non-statistical claims.
- Mayors / public officials beyond the 120 MKs.
- The adjustable Accountability Index (separate existing module).
- Rehosting downloaded media (store transcript + short quote + link to original only).

---

## 13. Open risks / honest caveats

- **Discovery is best-effort**, not exhaustive: YouTube API quota limits, relevance-filter false positives, and it only sees YouTube/podcast feeds. Manual upload is the safety net.
- **Hebrew transcription is good-not-perfect**; the mandatory human review on transcription-sourced claims is the mitigation.
- **IDF enlistment data is sensitive** and sometimes only available via news/Knesset answers — the curated sourced table absorbs this rather than pretending a clean API exists.
- **Media download legal posture:** quotation for criticism/fact-checking, link to original, never rehost full media.
