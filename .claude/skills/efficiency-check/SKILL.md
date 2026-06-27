---
name: efficiency-check
description: Use periodically (and inside the autonomous loop, every few ticks) to keep the פְּרוֹטוֹקוֹל pipeline getting faster and cheaper. Dispatches the efficiency-optimizer agent to audit the live run, logs its ranked findings to docs/optimization-backlog.md, and reminds the PM of the single biggest next speedup.
---

# Efficiency Check

Keep the project relentlessly fast and cheap. There is always a next bottleneck — surface it.

## When to run
- Every few autonomous-loop ticks (don't run every tick — measuring has a cost).
- On demand when the user asks "what's slow / how do we speed this up / efficiency agent."
- After a big architectural change (new pipeline stage, new agent fan-out).

## Steps
1. **Dispatch the `efficiency-optimizer` agent** (read-and-measure only) to audit the live run: harvester throughput + GPU idle, transcription realtime factor, download parallelism, multi-model fact-check throughput, agent/token cost, site export, disk, and quota headroom.
2. **Take its ranked report.** Append new items to `docs/optimization-backlog.md` (create it if missing) with date, the measured bottleneck, and each `{change, expected_win, effort, risk, how_to_verify}`. Mark already-applied items done.
3. **Remind the PM** of the single `top_recommendation` — one line, with the number that proves it (e.g. "GPU idles ~13 min/cycle waiting on search quota → add a 2nd YouTube key for ~2× discovery"). The user wants this reminder kept in front of the PM.
4. **Apply only safe, reversible, tested wins automatically** (config-level, behind the integrity rules); flag anything risky or behavior-changing for the user before applying.

## Hard rules
- Never trade away integrity for speed (sourced-or-dropped, candidates until consensus, data-only performance).
- Never propose ToS-breaking evasion.
- Measure with real numbers before proposing — no guessing.
