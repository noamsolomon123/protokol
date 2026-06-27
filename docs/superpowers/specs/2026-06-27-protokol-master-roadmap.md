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

- [ ] **F1 · Findings at scale** — multi-model agent fact-check: Claude agents (no Gemini
      quota) **+** Gemini, working together; flag the user when one model is clearly
      better. Unblocks the contradictions pillar. **← chosen first.**
- [ ] **F2 · Integrate verified minister series** — fold the researched GDP/poverty/debt/…
      series into the performance tab; research the remaining ministry domains.
- [ ] **F3 · Human review console** — confirm candidate → published (integrity-critical;
      the leaderboard only counts confirmed contradictions, so this unblocks it).
- [ ] **F4 · Consistency profile per MK** — RAG over each MK's own record; flag only hard,
      measurable self-contradictions / reversals over time.
- [ ] **F5 · X/Twitter integration** — tweets via a throwaway X account (user-provided),
      fact-checked through the same pipeline.
- [ ] **F6 · Public submissions + disputes** — public submits clips/claims; MKs can appeal
      a verdict.
- [ ] **F7 · Connections engine** — sourced knowledge-graph linking people/claims/topics/
      outcomes; correlation shown, causation never asserted.
- [ ] **F8 · Polish + ship for voters** — navigation, mobile, share cards, favicons,
      unified-hub UX.
- [ ] **F9 · Deeper crawl** — pagination/varied queries beyond the recent-25/MK cap to grow
      the historical corpus.
- [ ] **F10 · Own repo + Pages** — migrate the platform to its own repo, fully separate
      from the old `knesset-osint` OSINT scorecard.

Each backlog item gets its own brainstorm → spec → plan when its turn comes. This file
is the source of truth for "what's left"; update the checkboxes as items ship.
