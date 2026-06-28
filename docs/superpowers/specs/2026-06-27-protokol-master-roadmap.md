# פְּרוֹטוֹקוֹל — Master Roadmap & Feature Backlog

**Date:** 2026-06-27 · supersedes the stale `2026-06-26-claim-verification-*` plan.

**Vision:** a **unified accountability hub** for the general public/voters — Hebrew/RTL,
free static hosting (GitHub Pages), fed by a 24/7 ETL on the dedicated PC.

**Four co-equal pillars:** (1) the searchable public record, (2) contradictions vs
official data, (3) minister performance (data-only), (4) the leaderboard.

**Integrity backbone (applies to EVERY feature):** sourced or dropped — never
fabricate a stat/quote/URL; transcription/agent findings are CANDIDATES until human
review; performance = data only, correlation shown, causation never asserted; left
and right judged by the same yardstick.

---

## STANDING DIRECTIVE (user, 2026-06-27)

> Build the **entire** backlog, continuously. Never sit idle. When one feature is
> done, proceed to the next. Order is flexible — the user does not care which comes
> first — but **all of them must eventually ship**. The autonomous loop's MAIN BUILD
> step draws from this backlog and marks items done here as they land.

---

## Locked decisions (2026-06-27)

- **Publishing = multi-model consensus auto-publish.** A finding becomes public
  (`status: confirmed`, counted on the leaderboard) ONLY when two independent models
  agree it is a STRICT contradiction backed by a stat that directly measures the exact
  claimed quantity: a Claude extractor + an independent Claude adversarial verifier,
  and Gemini as a third vote when quota allows. Anything short of agreement stays a
  clearly-labeled `candidate` (shown on a candidates view, never on the leaderboard).
  **PM-review gate (added 2026-06-27, learned the hard way):** consensus-confirmed
  findings are NOT auto-merged — the PM reviews each before publish, because the
  consensus CAN over-reach on semantic precision. (First case: an MK's "100k haredi
  *not serving*" was flagged contradicted vs the ~66k *formal-deferral* count, but
  "not serving" is a broader population — so the stat didn't measure the exact
  quantity. Correctly held back.) The user spot-checks the published set.
- **Agent budget = go all-out.** Use Claude agents liberally (ultracode on).
- **Repo = stay in `knesset-osint` for now.** Migration is F10 (later).
- **X/Twitter (F5):** user will provide a throwaway X account — build the pipeline now,
  plug credentials in when given.

## Approach per feature (sketch — each gets its own detailed plan when built)

- **F1 Findings at scale:** fact-check Workflow — Claude agents read each transcript +
  the verified-stats catalog, extract STRICT claims and adjudicate (reusing the
  `factcheck.py` strict rules); an independent adversarial Claude verifier (+ Gemini when
  available) forms the consensus → agreeing findings become `confirmed`, else `candidate`.
- **F2 Minister series:** integrate the verified researched series into
  `portfolio_series.json` + catalog; research remaining ministries via the verify-workflow.
- **F3 Review console:** lightweight static page over findings.json to flip
  candidate→confirmed (optional safety net; consensus already auto-publishes).
- **F4 Consistency profile:** per-MK RAG over their transcripts; flag only hard measurable
  reversals (same metric, opposite direction, both dated + sourced).
- **F5 X/Twitter:** twscrape with the provided account → tweets through the same pipeline.
- **F6 Submissions + disputes:** static form → free backend (Formspree / GitHub issues);
  dispute records linked to findings.
- **F7 Connections engine:** sourced graph (people/claims/topics/outcomes); correlation only.
- **F8 Polish:** nav, mobile (playwright checks on the live site), share cards, favicons.
- **F9 Deeper crawl:** YouTube pagination + varied queries beyond the recent-25/MK cap.
- **F10 Own repo + Pages:** migrate cleanly off the old osint scorecard.

---

## Done / live

- [x] Parallel transcription ETL — 3 YouTube keys (rotating + quota failover), batched
      Whisper on the 3060, atomic state + corrupt-recovery, parallel downloads.
- [x] Interview galleries per MK + full-text search ("catch them on their words").
- [x] Minister performance tab (data-only) — page live; verified series researched.
- [x] Leaderboard — findings-based, integrity-gated (confirmed-only), honest empty state.
- [x] Strict fact-check pipeline (Gemini, parallel 3-key) — produces candidate findings
      (quota-limited on the free tier).
- [x] Roster (120 MKs) + directory / home / ministers / findings / search pages on Pages.

## Backlog — ALL to be built (order flexible)

- [x] **F1 · Findings at scale** — DONE (pipeline exercised; honest 0-yield): the cheap
      scanner pre-filters ranking/superlative claims (25: 22 interview, 3 tweet); an
      INDEPENDENT strict fact-check agent adjudicated all 25 against the 196-point verified
      catalog, and my own adjudication agreed → **all unverifiable, 0 contradicted, 0
      published**. The catalog simply has no stat that DIRECTLY measures the exact asserted
      quantity (femicide count, sector-specific enlistment, ministry budget deltas, all-time
      unemployment low, exhaustive poverty-by-group ranking). Recorded in
      `candidate_adjudications.json` (via `run_candidate_factcheck.py`) so we never re-pay to
      re-judge them. Same integrity-correct 0 as the full-corpus run (~7M tokens). The
      contradictions pillar stays honestly empty — rigor working as designed, not a failure.
      Full chain works: scanner → candidates → strict agent consensus → PM-gate → review
      console; a real contradiction would flow straight through to publish.
- [x] **F9 ACTIVATED (2026-06-28, supervised):** `run_harvester.bat` now passes `--deep`;
      restarted the supervisor cleanly (consolidated to one worker + its child helper). Deep
      combos (relevance/viewCount) firing, initial 429 burst settled within ~2 min, **22
      transcripts in the first 10 min** — corpus growing past the recent-25/MK cap as intended.
- [ ] **F2 · Integrate verified minister series** — fold the researched GDP/poverty/debt/…
      series into the performance tab; research the remaining ministry domains.
- [x] **F3 · Human review console** — DONE: `docs/review.html` (internal, noindex) reviews
      published findings; PM affirms or **retracts** each, exports a decisions JSON, and
      `merge_agent_findings.py --decisions reviewed.json` applies them. Retractions go to a
      blocklist (`retracted.json`) so a re-run can never republish a pulled false positive
      (the Tur-Paz case). Stable `F-####` ids on every finding. Linked from control.html.
- [x] **F4 · Consistency profile per MK** — DONE (mechanism + honest result):
      `scripts/scan_self_contradictions.py` finds candidate pairs (same MK, same covered
      metric, conflicting % across DIFFERENT interviews). Ran it → 38 raw candidates;
      **manually adjudicated all 38 → 0 genuine self-contradictions** (metric-conflation,
      different sub-populations, different time frames, level-vs-change). Same integrity-
      correct low yield as the main fact-check — nothing publishable, so nothing shown.
      `mk.html` renderFindings is now type-aware (`self_contradiction` → "סותר את עצמו",
      shows both moments), so a future PM/agent-confirmed reversal surfaces per-MK with the
      right framing. Verified both card types render, 0 console errors.
- [x] **F5 · X/Twitter** — DONE (display): user's X account (cookies session), verified-
      identity handle discovery (never misattributes), 85 MKs / ~4,800 tweets harvested,
      tweet timeline on every MK page. Remaining: feed tweets into the strict fact-check.
      Also delivered: `statistics.html` (all 19 official series, browsable) + tracking 6
      prominent non-MK figures (Bennett, Eisenkot, Y.Golan, Smotrich, Sa'ar, Gallant).
- [x] **F6 · Public submissions + disputes** — DONE: `docs/submit.html` — backend-free
      form (submission + dispute tabs) that builds a prefilled GitHub issue on the project
      repo (labels `submission`/`dispute`); the visitor posts it themselves, no server, no
      credentials. Public "what we check / what we don't" rules. Linked from home (card 07)
      + directory nav.
- [x] **F7 · Connections engine** — DONE: `scripts/build_connections.py` + `connections.html`
      — a sourced people↔topic↔official-statistic map. For each of the 19 catalog series we
      count, per MK, how many transcript segments mention the topic (content-phrase keywords,
      threshold ≥2), link MK→topic, and anchor each topic to its latest official value +
      source. 95 MKs / 273 edges. Topic-centric explorer (expand a topic → its official stat
      + ranked MKs, each linking to their page). **Correlation only**, causation never
      asserted (banner + footer). Tightened keyword precision (e.g. crime: dropped bare
      "רצח"/"נרצח" that caught political/terror contexts). Linked from home (card 08) +
      directory nav. Verified live: 0 console errors.
- [x] **F8 · Polish + ship for voters** — DONE (core): OG/Twitter summary share-cards on
      all 6 share-facing pages (findings, leaderboard, directory, search, ministers, mk) +
      tailored descriptions; favicon + viewport confirmed on every page; nav present on all;
      mobile chart clip fixed earlier. Deferred nice-to-have: a raster `og:image` card.
- [x] **F9 · Deeper crawl** — DONE (capability, tested; activation = 1-line toggle):
      `discovery.py` gains `order=` (date/relevance/viewCount) + `deep_search()` which runs a
      5-combo `DEEP_QUERY_PLAN` (varied phrasings × orders) and dedupes — surfaces the older/
      different videos the single date query misses. Worker gains `--deep`. Hardened
      `RotatingYouTubeSearch` to fail over on 429 (rate-limit) too, not just 403. 60 tests
      pass; **live smoke test: deep found 19 videos the single query missed (union 44 vs 25,
      ~1.8×)** even while rate-limited (resilient, no crash). **Activation deferred** (not done
      unsupervised while user away): add `--deep` to `run_harvester.bat` and restart the
      supervisor — costs ~5× quota/MK (≈60 deep MK-passes/day across 3 keys) so it trades
      MKs-per-day for depth, appropriate now the recent corpus is saturated.
- [x] **F10 · Own repo + Pages** — DONE (2026-06-28): platform migrated to its own public
      repo **`noamsolomon123/protokol`**, live at **https://noamsolomon123.github.io/protokol/**.
      Verified history was secret-free before the public push. Bare URL now redirects to the
      platform (`index.html` → `home.html`); the legacy OSINT scorecard stays ONLY at the old
      `knesset-osint` repo/URL (frozen, untouched). Local `origin` repointed to protokol;
      old remote kept as `knesset-osint-legacy`. All self-references (og:url/canonical, the
      submit-form GitHub-issue repo) repointed to protokol. Pages built; home, connections
      (live data), statistics all verified 200 with 0 console errors.

Each backlog item gets its own brainstorm → spec → plan when its turn comes. This file
is the source of truth for "what's left"; update the checkboxes as items ship.
