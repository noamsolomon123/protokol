# פְּרוֹטוֹקוֹל — PM Operating Model & Agent Org

**You** = product owner / stakeholder. **Me (Claude)** = Product Manager + supervisor over all
agents. I break the backlog into tasks, assign each to the right specialist agent, keep them in
sync, gate quality, and report up to you. You can talk to any agent by name and I'll route it.

## The agent org (talk to them by name)

| Agent | Owns | Say things like… |
|-------|------|------------------|
| **etl-agent** | discovery, download, batched transcription, the 24/7 harvester, throughput | "check the ETL agent — how's throughput?" |
| **backend-agent** | Python engine: models, db, fact-check core, catalog, exporters, API | "have the backend agent add a metric" |
| **frontend-agent** | the public Hebrew/RTL site under `docs/` (design, mobile, share cards) | "tell the frontend agent to redo the MK page" |
| **factcheck-agent** | strict claim extraction, adjudication, Claude+Gemini consensus, findings | "ask the fact-check agent why findings are empty" |
| **research-agent** | sourced official Israeli stats for the catalog + minister series | "send the research agent after energy prices" |
| **qa-agent** | tests, regressions, live-site validation — the gate before "done" | "have QA verify the leaderboard" |
| **devops-agent** | 24/7 ops: supervisor, processes, drives, key rotation, git, Pages deploy | "is everything up? ask devops" |
| **efficiency-optimizer** | relentless speed/cost/parallelism audits; reminds the PM of the next win | "what's the efficiency agent's top recommendation?" |

## How I supervise (keeping them in sync)

1. **One source of truth:** the master roadmap (`2026-06-27-protokol-master-roadmap.md`, features F1–F10) and the shared conventions in `CLAUDE.md` + the integrity backbone. Every agent works to these.
2. **Break down → assign:** I split a feature into scoped tasks and hand each to its owner agent with exactly the context it needs.
3. **Serialize file edits:** two agents never edit the same files at once — I sequence them so there are no conflicts.
4. **Hand-offs are explicit:** research → backend (integrate data), backend → frontend (data shapes), any → qa (verify). Each agent's charter lists who it hands to.
5. **QA gates "done":** nothing is marked done in the roadmap until **qa-agent** confirms (tests green + site validated).
6. **Efficiency loop:** every few autonomous ticks I run **efficiency-optimizer**; its #1 recommendation is surfaced to you and logged in `docs/optimization-backlog.md`.
7. **I report up:** progress, what shipped, what's next, and anything that needs your call.

## Monitoring — how to watch them all

- **Local mission-control board:** open `docs/control.html` (served by the local http server, or on Pages). Shows harvester throughput, transcript/finding counts, backlog F1–F10 progress, and the current efficiency reminder. Refreshed from `docs/data/status.json`, which the loop rewrites every tick.
- **Live subagent traces (recommended community tool):** `disler/claude-code-hooks-multi-agent-observability` — a hook-based real-time dashboard of every tool call / agent handoff. Fits your setup (you already use Claude Code hooks for the audio notify). Heavier alternative: `hoangsonww/Claude-Code-Agent-Monitor` (Kanban + native app).
- **Built-in:** `/workflows` shows live progress of any running workflow; background tasks notify on completion.

## How you drive it day-to-day

- Name an agent → I dispatch it scoped and relay the result in plain language.
- Or just say the goal ("make findings real") → I (PM) pick the agents, sequence them, and run it.
- Say "stop the alarms" to pause the autonomous loop.
