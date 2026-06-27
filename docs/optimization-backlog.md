# Optimization Backlog

Maintained by the **efficiency-optimizer** agent / **efficiency-check** skill. Newest first.
Each entry: the measured bottleneck + ranked changes. Mark items done as they ship.

---

## 2026-06-27 · F1 fact-check validated — the real lever is CATALOG COVERAGE

**Measured:** F1 multi-model fact-check ran over 24 transcripts (24 agents, ~1.8M tokens) →
**0 findings**. Inspection of the subagent transcripts proved the pipeline works perfectly:
agents read the full transcript + all catalog points, no errors, and returned empty with
correct reasoning. Example: MK Akram Hasson made many hard numeric claims (333,500 students;
11 doctors working as waiters; 10,000 unemployed Arab teachers) — all **higher-education**,
a topic the catalog doesn't cover, so they were correctly rejected (strict bar holding).

**Bottleneck (binding):** the catalog only covers 6 topics. The agents *find* hard claims;
we lack official stats to check them against. Findings are coverage-limited, not pipeline-limited.

**Top recommendation:** build a **claims-harvest feedback loop** — F1 agents also emit the hard
quantitative claims they find that have NO matching stat; aggregate these into a "stats-wanted"
list; dispatch the **research-agent** to source those exact official stats; expand the catalog;
re-check. The catalog then grows toward what MKs actually claim. Self-improving.

**Ranked changes:**
1. Claims-harvest loop (above) — biggest win; turns every transcript into catalog-growth signal.
2. Broaden `TOPIC_KEYWORDS` in `factcheck.py` to new domains (education, health, GDP/debt/deficit,
   defense) so more claims are checkable — needs matching sourced stats first.
3. Target F1 batches at MKs whose portfolios intersect the catalog topics (higher hit rate per token)
   instead of sorted-by-id batches.

**Done this session:**
- Integrated 8 verified research series → performance tab; poverty + food-prices → catalog.
  עוני coverage 26 stats, יוקר 62 stats (was a handful). Re-running F1 on poverty/cost-of-living
  talk should now produce findings.
- Fixed workflow-output parsing (return value is under the `result` key).

## Already well-optimized (don't re-litigate)
- Transcription: batched, ~75x realtime — far ahead of the search-quota bottleneck.
- Discovery: 3 YouTube keys rotating, ~300s cadence (~3x throughput); failover on 403.
- Harvester state: atomic writes + corrupt-recovery.
