# 25 — Updated Implementation Roadmap

> ⚠️ **SUPERSEDED by [31 — Execution Plan](31-execution-plan.md) (2026-08-05).**
>
> The reasoning here remains valid and is *why* the successor reached different conclusions. Three
> things in this document are **withdrawn** and must not be implemented:
>
> | Withdrawn | Replaced by | Reason |
> |---|---|---|
> | The **H1–H4 execution order** (Hermes at position 4) | [31 §2](31-execution-plan.md) — validate in Sprint 0, integrate in Sprint 7 | Hermes' skills need leads, quality metrics and a BKB that do not exist until Sprint 6 |
> | Migration **`0005_agent_tier`** and the `0005`–`0009` → `0006`–`0010` renumbering (§2.0) | [31 §5](31-execution-plan.md) — **the agent tier adds no tables** | `ai_calls` already carries every column an agent turn needs; notification idempotency rides on the state machine's transition guard ([27 §5](27-architecture-review.md), AD-29) |
> | **13 skills / 17 seam tools** at first delivery | [31 §4](31-execution-plan.md) — 3 skills, 5 tools | MVP discipline; Level-0 metadata and tool schemas are a per-turn token tax |
>
> Retained rather than deleted so the reversal and its reasoning stay on the record.

> **Step 11.** Every existing phase is reviewed and given a disposition. No phase is discarded, no
> Alembic revision is renumbered, and the migration chain stays linear with a single head. Four
> Hermes phases (**H1–H4**) are interleaved at the points where their dependencies are actually
> satisfied, rather than appended at the end where they would deliver nothing until month six.
>
> Basis: [10 — Implementation Roadmap](10-implementation-roadmap.md), [20](20-hermes-vs-current.md),
> [21](21-hermes-architecture.md), [22](22-hermes-skills.md), [24](24-cost-optimization.md).

---

## 1. Review of every existing phase

| Phase | Doc | Status | Disposition | What changes |
|---|---|---|---|---|
| **1 — AI Foundation & DeepSeek** | [11](11-phase-01.md) | ✅ **Shipped** | **Keep, unchanged** | Nothing. `AIService` remains the only pipeline path to a model. Hermes uses a *separate* key and never touches this package |
| **2 — Proxy & Transport** | [12](12-phase-02.md) | ✅ **Shipped** | **Keep, unchanged** | Nothing. `src/net/` is Reddit-agnostic and stays so |
| **3 — Orchestration** | [13](13-phase-03.md) | Pending | **Modify** | Scheduler work is **deferred to H2** (`hermes cron` replaces `schedule`). Adds an event-emission point that H1 consumes. Otherwise unchanged |
| **4 — Business Knowledge Base** | [14](14-phase-04.md) | Pending | **Keep, unchanged** | Nothing. The BKB stays the platform's asset ([23 §4](23-hermes-memory-and-knowledge.md)) |
| **5 — Discovery, Keywords & Gates** | [15](15-phase-05.md) | Pending | **Modify** | Gates emit `gate.reached`, consumed by H1's notification tier. Gate *approval* from Telegram lands in H2 |
| **6 — Scrape & Local Pipeline** | [16](16-phase-06.md) | Pending | **Modify** | Adds [24 §4.4](24-cost-optimization.md) — comment candidates ordered by pre-score, not `intent_score` |
| **7 — Adaptive Enrichment & Confidence** | [17](17-phase-07.md) | Pending | **Modify** | Adds [24 §4.2](24-cost-optimization.md) cross-project negative-result reuse, flagged and double-sampled by the audit |
| **8 — Quality, Dashboard, Export, Production** | [18](18-phase-08.md) | Pending | **Split** | The quality suite, exports and monitoring stay as Phase 8. **Production hardening and deployment move to H4**, because deployment now has two containers and a CI pipeline |
| — | — | — | **Add: H1** | Hermes foundation, measurement, and the zero-LLM notification tier |
| — | — | — | **Add: H2** | The seam, skills, governor, cron migration, Telegram gate approvals |
| — | — | — | **Add: H3** | Triage, knowledge, quality and cost skills; outreach drafting |
| — | — | — | **Add: H4** | Docker, VPS, CI/CD, security review, production readiness |
| — | — | — | **Delete: none** | Nothing in the existing plan is invalidated by Hermes |

**Four Modify, one Split, four Add, zero Delete.** That ratio is the finding: Hermes attaches to this
architecture at its edges. Had it required deleting a phase, the boundary in
[21 §1](21-hermes-architecture.md) would have been drawn in the wrong place.

### 1.1 Why Phase 8 splits rather than absorbs

Phase 8 currently carries two unrelated jobs: *"is the system still right?"* (golden set, calibration,
drift, `/health/quality`) and *"can an operator run this?"* (deployment, runbook, security review).

The first is a data-plane concern and is unchanged. The second is now a **two-container, two-key,
CI-deployed** concern that did not exist when Phase 8 was written. Merging them would mean the
quality suite could not ship until the deployment story was finished, which inverts their real
dependency — quality measurement is needed *during* the Hermes work, not after it.

---

## 2. Execution order

```
  ✅ P1 ──► ✅ P2 ──► P3 ──► H1 ──► P4 ──► P5 ──► H2 ──► P6 ──► P7 ──► H3 ──► P8 ──► H4
           shipped        │      │              │                    │           │
                          │      └─ Telegram    └─ gate approvals    │           └─ production
                          │         alerts live    from Telegram     └─ triage /
                          └─ runs exist                                 knowledge /
                                                                        quality chat
```

| # | Phase | Migration | Days | Cumulative |
|---|---|---|---:|---:|
| ✅ | 1 — AI Foundation | `0001`–`0002` | — | 14% |
| ✅ | 2 — Proxy & Transport | `0003` | — | 24% |
| 3 | Orchestration | `0004` | 8 | 32% |
| **H1** | **Hermes Foundation & Notifications** | **`0005`** *(new)* | **6** | **38%** |
| 4 | Business Knowledge Base | `0006` *(was `0005`)* | 12 | 50% |
| 5 | Discovery, Keywords & Gates | `0007` *(was `0006`)* | 8 | 59% |
| **H2** | **Agent Tier: seam, skills, cron, gates** | — | **9** | **68%** |
| 6 | Scrape & Local Pipeline | `0008` *(was `0007`)* | 10 | 76% |
| 7 | Adaptive Enrichment & Confidence | `0009` *(was `0008`)* | 12 | 86% |
| **H3** | **Operator Intelligence Skills** | — | **6** | **91%** |
| 8 | Quality, Dashboard & Export | `0010` *(was `0009`)* | 10 | 97% |
| **H4** | **Deployment & Production Readiness** | — | **8** | **100%** |
| | | | **89 days** | |

### 2.0 The migration renumbering

Because H1 runs between Phases 3 and 4, its migration must sort between `0004` and the
knowledge-base revision. Giving it `0010` would produce an applied order of `0004 → 0010 → 0005 → …`
and a `down_revision` pointing at a file that does not yet exist — the two-heads failure
[05 §7](05-database-plan.md) calls out and forbids.

**→ The agent-tier tables take `0005`; the planned revisions shift down by one.** Full table and
reasoning in [21 §13.1](21-hermes-architecture.md).

This is legitimate because **only `0001`–`0003` have shipped**. [05 §7](05-database-plan.md)'s rule
protects a *deployed* database from being asked to apply a revision that sorts before its head;
renumbering unshipped files costs a find-and-replace and preserves exactly that property. The chain
remains `0001 → … → 0010`, linear, one head. `0005_agent_tier` is additive (`agent_events`,
`notification_log`) and touches no existing table — the same property that let `0002` ship in Phase 1.

**One deferred FK**, handled as `ai_calls.project_id` already is: `agent_events.project_id` is
created without a `REFERENCES` clause in `0005` and constrained in `0006` via `batch_alter_table`
([05 §7.1](05-database-plan.md)).

### 2.1 Why H1 sits at position four

H1 needs exactly one thing: a run that can complete. That exists after Phase 3.

Placing it there buys three things that placing it last would not:

1. **The measurement tasks that de-risk everything else run first.** Eight of the forty research
   topics carry a gap ([19 §41](19-hermes-research.md)) — tool-schema token cost, Level-0 cost,
   compose behaviour, retry semantics. H1 measures them while the design can still change cheaply.
   Discovering in month five that tool schemas cost 25k tokens per turn would invalidate
   [24 §5](24-cost-optimization.md) after the skills were written.
2. **Telegram alerts become useful immediately** — *"run 14 complete, 23 leads"* is worth having from
   Phase 3 onward, and it costs nothing because it never invokes a model.
3. **The seam is exercised early.** An HTTP boundary that is designed in month one and first called
   in month five is a boundary with unknown defects.

---

## 3. Phase 3 — Orchestration *(modified)*

**Objectives.** Replace the fire-and-forget thread with a persisted run state machine and durable job
queue, so the pipeline can pause at human gates, survive restarts, and report real progress.

**Deliverables.** As [13-phase-03.md](13-phase-03.md), with three changes:

| Change | Detail |
|---|---|
| **Removed** | `scheduler.py` per-project scheduling — deferred to H2, where `hermes cron` replaces it. Phase 3 ships the `maintenance` job only |
| **Added** | `emit_event()` gains a **notification hook point**: events named in the [22 §4.12](22-hermes-skills.md) policy table also write a `notification_log` row (delivery is H1's job) |
| **Added** | `RunService.progress()` returns the funnel counts H1's notification renderer needs |

**Architecture changes.** None beyond [13 §3](13-phase-03.md). The worker remains the sole bulk
writer — a property H1 and H2 depend on absolutely ([HR4](20-hermes-vs-current.md)).

**Skills / Agents.** None. Hermes does not exist yet.

**Testing.** [testing/phase-03-testing.md](testing/phase-03-testing.md) unchanged, plus: an event
that should notify writes exactly one `notification_log` row; a job re-run after lease expiry writes
**zero** additional rows (the `ux_notification_dedup` guarantee).

**Documentation.** Update [13](13-phase-03.md) §2.1 to move scheduling out of scope and reference H2.

**Acceptance criteria.** AC1–AC15 of [13 §13](13-phase-03.md), plus:
- [ ] **AC16** — Notification-worthy events write exactly one `notification_log` row, idempotent under retry

**Dependencies.** Phases 1–2 (shipped).

**Risks.** Unchanged from [13 §11](13-phase-03.md). The one addition — a notification hook inside a
transaction — is mitigated by writing the row in the *same* transaction as the state transition, so a
rolled-back stage cannot notify.

**Estimated time.** 8 days (unchanged; the scheduler removal offsets the hook).

---

## 4. Phase H1 — Hermes Foundation & Notification Tier *(new)*

**Objectives.** Stand up Hermes as a bounded, measured, credential-isolated runtime; deliver Telegram
notifications at **zero token cost**; and close the eight measurement gaps from
[19 §41](19-hermes-research.md) before any design depends on their answers.

**Deliverables.**

| # | Deliverable |
|---|---|
| 1 | Hermes v0.20.0 installed; a dedicated profile created with `--no-skills`; `hermes-home/` committed to the repository (no secrets) |
| 2 | `config.yaml`: `model` pinned to `deepseek-v4-flash`, **separate agent key**, `agent.disabled_toolsets`, `memory.write_approval: true`, `skills.write_approval: true`, `compression.micro_compact: false`, `telegram` block |
| 3 | `SOUL.md` and `AGENTS.md` per [23 §4.3–4.4](23-hermes-memory-and-knowledge.md) |
| 4 | Telegram bot registered; `TELEGRAM_ALLOWED_USERS` set to one operator; DM pairing verified |
| 5 | **`src/notify/`** — `service.py` (policy table), `renderers.py` (markdown from SQL), `transport.py` (**one interface, three implementations**: T1 serve-RPC, T2 subprocess, T3 direct Bot API — selected by M-9/M-10) |
| 6 | Migration **`0005_agent_tier`** — `agent_events`, `notification_log`, five `settings` rows; **plus the `0005`→`0006` … `0009`→`0010` renumbering of unshipped revisions** (§2.0) |
| 7 | Notification kinds live: `run.started`, `run.complete`, `run.failed`, `budget.warning`, `proxy.pool_degraded` |
| 8 | **The measurement report** (§4.1) |

### 4.1 The measurement tasks — H1's most valuable output

| # | Measures | Method | Decides |
|---|---|---|---|
| M-1 | Tool-schema tokens, pruned vs unpruned | `hermes -z --usage-file` with and without `disabled_toolsets` | Whether [24 §5.2/2](24-cost-optimization.md)'s 30–60% claim holds |
| M-2 | Level-0 skill metadata tokens | Same, 0 vs 13 skills | The [22 §8](22-hermes-skills.md) `test_level0_budget` ceiling |
| M-3 | Baseline turn cost, no tools called | One trivial prompt | Validates the [21 §6.5](21-hermes-architecture.md) ~9k in / ~700 out estimate |
| M-4 | Whether DeepSeek reports `prompt_cache_hit_tokens` through Hermes | Two identical turns, inspect usage | Confirms or refutes the zero-cache-credit assumption in [24 §5.3](24-cost-optimization.md) |
| M-5 | `hermes send` cost | Send 10 notifications, check `agent_events` | **Must be exactly zero.** If not, the entire notification design changes |
| M-6 | Retry/backoff behaviour on 429 | Scripted provider error | Fills the [19 §38](19-hermes-research.md) gap |
| M-7 | `docker compose` bring-up from the repo file | Run it | De-risks H4 |
| M-8 | Enumerate bundled skills | `hermes skills browse --source official` | Fills the [19 §32](19-hermes-research.md) gap |
| **M-9** | **Is `hermes send` reachable over a network interface** (`hermes serve` JSON-RPC/WebSocket, or the API server) rather than CLI-only? | Start `hermes serve`; inspect `GET /v1/capabilities`; attempt a send over the interface | **Decides the notification transport** across the H4 container split ([21 §7.1](21-hermes-architecture.md)): T1 if yes, T3 if no |
| **M-10** | **Does `hermes send` write into the session transcript?** | Send, then `session_search` for the body | Decides what T3 costs. If sends are invisible to search, T3 loses nothing |

**M-5 is a go/no-go.** [24 §5.2](24-cost-optimization.md)'s largest saving rests on `hermes send`
running *"without spinning up an agent or gateway loop"*. If a notification costs tokens, the agent
tier's monthly estimate roughly triples and the notification policy must be rewritten before H2
starts.

**M-9 is the second go/no-go, and it is a deployment blocker rather than a cost one.** `hermes send`
is documented as a CLI command. The subprocess form works in H1, where both planes are co-located,
and **stops working in H4**, where they are separate containers and the `hermes` binary is absent
from the platform image. Mounting the Docker socket to `docker exec` across the boundary is rejected
outright — it hands the data plane host-level control, a larger hole than anything
[21 §11](21-hermes-architecture.md) defends.

`src/notify/transport.py` is therefore written to an interface with **three implementations** (T1
serve-RPC, T2 subprocess, T3 direct Bot API), and M-9/M-10 select one by configuration rather than by
rewrite. **T3 is a good outcome, not a consolation:** it is zero-cost *by construction*, because no
agent runtime is in the path at all, and it removes the M-5 dependency entirely.

**Architecture changes.** Introduces the control plane, one direction only: the platform *emits*
events, `src/notify/` *renders* and *sends*. **No Hermes tool exists yet** — the seam is H2. Hermes
in H1 is an outbound transport with a persona, nothing more.

**Skills.** None. Deliberately: notifications must be proven to cost nothing *before* any skill
exists to make them cost something.

**Agents.** The Operator Agent exists but has no platform tools. It can converse, remember, and
search sessions.

**Testing.**

| Test | Asserts |
|---|---|
| `test_notification_dedup` | Re-running `finalize_run` sends one message, not two |
| `test_notification_zero_cost` | Ten notifications → zero `agent_events` with non-zero tokens (M-5) |
| `test_notification_offline` | Hermes down → `notification_log.delivered=0`, run unaffected |
| `test_renderer_no_model` | `src/notify/renderers.py` imports neither `src.ai` nor any HTTP client |
| `test_quiet_hours` | Non-critical notifications suppressed; `budget.warning` and `run.failed` are not |
| `test_config_invariants` | `micro_compact` false; both `write_approval` true; toolsets disabled; agent key ≠ pipeline key |
| `test_soul_rules` | `SOUL.md` carries all four load-bearing rules |

**Documentation.** New: `docs/HERMES-SETUP.md`. Updated: [README](README.md) (agent tier), `.env.example`.

**Acceptance criteria.**
- [ ] **H1-AC1** — A completed run delivers a Telegram message within 10 s
- [ ] **H1-AC2** — That message costs **$0.00**; `agent_events` shows zero tokens (M-5)
- [ ] **H1-AC3** — Stopping Hermes leaves every pipeline capability working ([21 §14](21-hermes-architecture.md))
- [ ] **H1-AC4** — Migration `0005_agent_tier` up/down on a copy of the live DB; 459 leads intact; **`alembic heads` returns exactly one head** after the §2.0 renumbering
- [ ] **H1-AC4b** — `alembic upgrade head` from empty produces the full `0001`→`0005` chain; every renumbered file's `down_revision` is consistent
- [ ] **H1-AC5** — Two distinct provider keys configured and verified
- [ ] **H1-AC6** — `agent.disabled_toolsets` verified at runtime: terminal, file, browser, code, web, media absent
- [ ] **H1-AC7** — An unknown Telegram user is denied and issued a pairing code
- [ ] **H1-AC8** — The measurement report is written to `docs/HERMES-MEASUREMENTS.md` with all eight results
- [ ] **H1-AC9** — All 17 legacy endpoints unchanged; `GET /` byte-identical

**Dependencies.** Phase 3 (runs and events).

**Risks.**

| Risk | Mitigation |
|---|---|
| **M-5 fails** — notifications cost tokens | Go/no-go. Fall back to **T3**, a direct Bot API call from the platform; Hermes then owns conversation only |
| **M-9 unfavourable** — send is CLI-only | Transport becomes **T3** from H1 onward rather than at H4. Discovered here, it is a config choice; discovered at H4 it would be a rewrite five phases late |
| Telegram token leaked | `.env` only; `RedactingFilter` pattern added; grep test |
| Hermes v0.20.0 pre-1.0 breakage | Image pinned; `hermes update` disabled in-container |
| Notification fatigue from day one | Policy table starts deliberately narrow — five kinds — and widens on request |

**Estimated time.** 6 days (2 setup + config, 2 notification tier, 1 measurement, 1 tests/docs).

---

## 5. Phase 4 — Business Knowledge Base *(unchanged)*

**Keep exactly as [14-phase-04.md](14-phase-04.md).** 30 acceptance criteria, migration
**`0006`** (renumbered from `0005`, §2.0 — content unchanged), the
23-section BKB, entity resolution, evidence typing, the `origin` guard, the semantic index, the
prefix builder.

**Nothing about Hermes changes this phase**, and that is the point: [23 §4](23-hermes-memory-and-knowledge.md)
concluded that the BKB is the correct home for business knowledge and Hermes memory is roughly an
order of magnitude too small to hold it. The only forward-looking addition is that
`GET /api/agent/bkb/search` in H2 will read what this phase builds — a consumer, not a change.

**Estimated time.** 12 days (unchanged).

---

## 6. Phase 5 — Discovery, Keywords & Review Gates *(modified)*

**Keep [15-phase-05.md](15-phase-05.md)**, plus:

| Addition | Detail |
|---|---|
| `gate.reached` notification | Both gates emit it. The renderer produces the [21 §7.2](21-hermes-architecture.md) card: counts, top candidates, rejected summary, estimate, and a dashboard deep link |
| Estimate in the notification | `GET /api/runs/<id>/estimate` output is included, so the operator sees cost before approving |

**Not in this phase:** approving *from* Telegram. That needs the seam and the
`reddit-run-control` skill, both of which land in H2. Phase 5 notifies; H2 acts.

**Acceptance criteria.** AC1–AC16 of [15 §13](15-phase-05.md), plus:
- [ ] **AC17** — Reaching a gate delivers one Telegram card containing the counts, the rejected summary, the estimate and a working dashboard link
- [ ] **AC18** — The card is delivered exactly once per gate per run, and costs $0.00

**Estimated time.** 8 days (+0.5 for the renderer, absorbed).

---

## 7. Phase H2 — Agent Tier: seam, skills, governor, cron *(new)*

**Objectives.** Build the HTTP seam and its plugin; ship the first five skills; enforce the
agent-tier budget ceiling; migrate scheduling to `hermes cron`; enable gate approval from Telegram.

**Deliverables.**

| # | Deliverable |
|---|---|
| 1 | `src/dashboard/routes_agent.py` — the `/api/agent/*` blueprint, bearer-token auth, bound to localhost |
| 2 | `hermes-home/plugins/hermes_reddit/` — `register()` exposing the seam tools, plus the two hooks |
| 3 | **The governor** — `pre_llm_call`, `agent.max_cost_per_day_usd`, default $1.00 ([21 §9](21-hermes-architecture.md)) |
| 4 | **The ledger** — `post_llm_call` → `POST /api/agent/events` → `agent_events` |
| 5 | Skills: `reddit-run-control`, `operator-onboarding`, `notify-policy`, `run-diagnosis`, `daily-summary` |
| 6 | **Scheduler migration** — `schedule` removed; `hermes cron` jobs create runs via `POST /api/agent/runs` |
| 7 | Telegram gate approval end to end |
| 8 | `/health/ai` gains an **Agent tier** band |

### 7.1 The seam, delivered in two halves

Only the tools whose data exists after Phase 5 ship here:

| Ships in H2 | Deferred to H3 |
|---|---|
| `platform_status`, `list_runs`, `run_detail`, `start_run`, `approve_gate`, `cancel_run`, `cost_report` | `list_leads`, `lead_detail`, `label_lead`, `knowledge_query`, `knowledge_suggestions`, `patterns_query`, `quality_report`, `enrich_run`, `draft_outreach` |

Splitting on data availability rather than on convenience means every tool shipped in H2 can be
tested against real data on the day it lands.

### 7.2 The scheduler migration

```
Before:  main.py schedule → schedule lib → RunService.create()
After:   hermes cron  ──►  POST /api/agent/runs  ──►  RunService.create()
                                                      └─ worker executes under the state machine
```

**The cron job triggers; it never executes.** Everything after `POST` is the existing pipeline, under
the existing budget ceilings, in the existing worker. `cron.model_drift_guard: true` and an explicit
per-job model pin close [HR7](20-hermes-vs-current.md).

**Architecture changes.** The seam becomes real and bidirectional (tools in, webhooks out). The
platform gains one blueprint and zero imports of Hermes — asserted by the new grep fence
([21 §8.4](21-hermes-architecture.md)).

**Skills.** Five, per [22](22-hermes-skills.md).

**Agents.** The Operator Agent becomes functional. Delegation is **configured but unused** —
`max_spawn_depth: 1`, `max_concurrent_children: 3`.

**Testing.**

| Test | Asserts |
|---|---|
| `test_governor_blocks` | At the cap, a turn issues **zero** provider calls |
| `test_governor_allows_notifications` | With the agent capped, `hermes send` still delivers |
| `test_seam_auth` | Missing/wrong bearer token → 401; the blueprint is not reachable off-localhost |
| `test_approve_gate_parity` | Telegram approval and dashboard button produce identical `runs` and `run_events` rows |
| `test_no_approve_all` | The skill body has no accept-all affordance; `selection="all"` requires an explicit count confirmation |
| `test_agent_events_recorded` | Every agent turn writes exactly one `agent_events` row |
| `test_cron_triggers_only` | A cron job's process does no scraping and makes no provider call beyond its own turn |
| `test_platform_no_hermes_import` | `grep` over `src/` returns zero |

**Documentation.** New: `docs/HERMES-SEAM.md` (the 17 tools, auth, error shapes). Updated:
[13](13-phase-03.md) §scheduling, [09](09-dashboard-plan.md) `/health/ai`.

**Acceptance criteria.**
- [ ] **H2-AC1** — Approving Gate 1 from Telegram advances the run identically to the dashboard
- [ ] **H2-AC2** — The governor blocks at the cap with zero provider calls; notifications keep flowing
- [ ] **H2-AC3** — Every agent turn appears in `agent_events` and on `/health/ai`
- [ ] **H2-AC4** — A scheduled monitoring run is created by `hermes cron` and executed by the worker
- [ ] **H2-AC5** — No `hermes` import exists in `src/`
- [ ] **H2-AC6** — Seam endpoints require the bearer token and are not reachable from outside the compose network
- [ ] **H2-AC7** — Level-0 metadata is within the M-2 ceiling
- [ ] **H2-AC8** — Agent-tier spend for a representative week is within ±25% of [21 §6.5](21-hermes-architecture.md)

**Dependencies.** H1 (runtime, notifications, measurements), Phase 5 (gates).

**Risks.**

| Risk | Mitigation |
|---|---|
| [HR1](20-hermes-vs-current.md) — a second path to a model | Separate key; every turn ledgered; grep fence |
| [HR2](20-hermes-vs-current.md) — unbounded spend | The governor, tested at the boundary |
| [HR10](20-hermes-vs-current.md) — gates rubber-stamped | No accept-all; the card always shows rejects and cost |
| Cron migration loses a schedule | Both run in parallel for one week; `runs` rows compared |
| Seam sprawl | The 17 tools of [21 §4](21-hermes-architecture.md) are the *complete* surface; adding one is a design change |

**Estimated time.** 9 days (3 seam + plugin, 2 governor + ledger, 2 skills, 1 cron migration, 1 tests).

---

## 8. Phase 6 — Scrape Execution & Local Pipeline *(modified)*

**Keep [16-phase-06.md](16-phase-06.md)**, plus one cost change:

| Addition | Detail |
|---|---|
| [24 §4.4](24-cost-optimization.md) | Comment candidates ordered by **pre-score**, not `intent_score`, and skipped when already below the run's admission floor. Saves proxy requests *and* candidates |

**Acceptance criteria.** AC1–AC22 of [16 §13](16-phase-06.md), plus:
- [ ] **AC23** — Comment candidate selection uses pre-score ordering; collected comments fall ≥5% with **no** reduction in admitted items

**Estimated time.** 10 days (+0.5, absorbed).

---

## 9. Phase 7 — Adaptive Enrichment & Explainable Confidence *(modified)*

**Keep [17-phase-07.md](17-phase-07.md)** — all 31 acceptance criteria — plus:

| Addition | Detail |
|---|---|
| [24 §4.2](24-cost-optimization.md) | Cross-project reuse of **negative** analyses only (`is_lead=false`, no matched slugs). Flagged in `prescores`; **double-sampled by the holdout audit** for the first 200 occurrences |
| [24 §4.1](24-cost-optimization.md) | Label reasons route to deterministic **rule proposals** as well as knowledge suggestions — operator-gated, never auto-applied |

**Acceptance criteria.** AC1–AC31, plus:
- [ ] **AC32** — Cross-project reuse never shares a positive judgement; a fixture with `is_lead=true` is not reused across projects
- [ ] **AC33** — Reused decisions are flagged and sampled at double rate; the gate miss rate does not rise
- [ ] **AC34** — A recurring `competitor_staff` reason produces a *pending* author-filter proposal, never an applied one

**Risks.** Adds one to [17 §11](17-phase-07.md): *cross-project reuse leaks a wrong negative between
projects with different ICPs.* Mitigated by restricting reuse to no-slug negatives and by the
double-rate audit — and reverted outright if the gate miss rate moves.

**Estimated time.** 12 days (+1 for reuse and its guards).

---

## 10. Phase H3 — Operator Intelligence Skills *(new)*

**Objectives.** Now that leads, analyses, patterns and quality metrics exist, give the operator
conversational access to them — and ship outreach drafting under its permanent constraint.

**Deliverables.**

| # | Deliverable |
|---|---|
| 1 | Seam tools: `list_leads`, `lead_detail`, `label_lead`, `knowledge_query`, `knowledge_suggestions`, `patterns_query`, `quality_report`, `enrich_run`, `draft_outreach` |
| 2 | Skills: `lead-triage`, `knowledge-query`, `patterns-analyst`, `quality-analyst`, `cost-analyst`, `outreach-draft`, `weekly-summary`, `monthly-cost-review` |
| 3 | The `/triage` bundle |
| 4 | `untrusted_content` envelope on every route returning Reddit text ([AD-24](21-hermes-architecture.md)) |
| 5 | `lead.high_confidence` notification, quota-limited per run |
| 6 | Research Worker delegation enabled for `run-diagnosis` and `patterns-analyst` only |

**Architecture changes.** The seam completes at 17 tools. No new component.

**The one constraint that governs this phase.** `draft_outreach` calls
`AIService.suggest_outreach()` in the data plane — never Hermes — so drafts are cached on
`(content_hash, prompt_version)`, budget-accounted, and repaired by the existing ladder. And the
platform has no Reddit write path, so *"draft-only"* is a property of the system rather than a
promise in a prompt.

**Testing.**

| Test | Asserts |
|---|---|
| `test_untrusted_envelope` | Every route returning Reddit text wraps it; an injection fixture triggers no tool call |
| `test_explanation_passthrough` | `confidence_reasoning` is rendered by `scoring/explain.py` and reproduced verbatim by the agent |
| `test_outreach_never_sends` | No seam tool can post to Reddit; the skill body carries the no-send clause |
| `test_outreach_cached` | A repeated draft request makes zero additional `AIService` calls |
| `test_knowledge_cites_evidence` | Every `knowledge-query` answer includes section + evidence span |
| `test_insufficient_data` | An under-powered metric is reported as `insufficient_data`, never estimated |
| `test_delegation_bounded` | `max_spawn_depth: 1`; a leaf child cannot call `delegate_task` |

**Acceptance criteria.**
- [ ] **H3-AC1** — *"Show me today's best leads"* returns correctly filtered leads with stored breakdowns
- [ ] **H3-AC2** — *"Why did lead N score 92?"* reproduces `confidence_reasoning` byte-identically
- [ ] **H3-AC3** — A lead body containing an injection string produces a *report*, not an action
- [ ] **H3-AC4** — A draft is produced, cached, and accompanied by its BKB angle and the "you send this" line
- [ ] **H3-AC5** — Asking the agent to post to Reddit produces a plain refusal naming the platform limitation
- [ ] **H3-AC6** — `/triage` answers quality, cost and leads in one turn within the per-turn token budget
- [ ] **H3-AC7** — Agent-tier monthly spend remains ≤ $1.00 with all 13 skills live

**Dependencies.** Phase 7 (leads, analyses), Phase 4 (BKB), H2 (seam, governor).

**Risks.**

| Risk | Mitigation |
|---|---|
| Prompt injection from lead text | AD-23 (no dangerous toolsets) + AD-24 (envelope) + `SOUL.md` rule + a test fixture |
| The agent invents an explanation | Explanations are passed through, never generated; `test_explanation_passthrough` |
| Drafting drifts toward sending | No write path exists anywhere in the platform |
| Skill count creeps past 15 | `test_skill_count`; two slots held in reserve |

**Estimated time.** 6 days.

---

## 11. Phase 8 — Quality, Dashboard & Export *(split — data plane only)*

**Keep [18-phase-08.md](18-phase-08.md)** minus §9.5 (security review) and the deployment/runbook
items, which move to H4.

In scope: migration **`0010`** (renumbered from `0009`), `lead_labels` with reason chips, `patterns`, the researcher view,
retention by memory class, the golden set as a **blocking** gate, ECE/Brier/isotonic calibration,
PSI drift, `/health/quality`, CSV/JSON/XLSX export, empty and error states, performance work.

**Additions.**

| Addition | Detail |
|---|---|
| Retention covers the **fifth memory class** ([23 §5.2](23-hermes-memory-and-knowledge.md)) — `agent_events`, `notification_log`, Hermes sessions, cron output |
| `/health/quality` gains an **Agent tier** row: turns, cost, blocked-by-governor count, notification delivery rate |
| The [23 §5.1](23-hermes-memory-and-knowledge.md) assertion joins the acceptance suite |

**Acceptance criteria.** AC1–AC33 of [18 §13](18-phase-08.md) minus AC13 (moves to H4), plus:
- [ ] **AC34** — Deleting `~/.hermes/memories/` and `state.db` changes no score, no BKB section, and no run outcome
- [ ] **AC35** — `agent_events` is aggregated into `metrics` before purge, exactly as `ai_calls` is

**Estimated time.** 10 days (was 12; security review and runbook move out).

---

## 12. Phase H4 — Deployment & Production Readiness *(new)*

**Objectives.** Two containers on one VPS, behind TLS, deployed by CI, with a runbook, a security
review covering both planes, and the full production checklist ticked.

**Deliverables.**

| # | Deliverable |
|---|---|
| 1 | `Dockerfile` (platform), `docker-compose.yml` (two services), `Caddyfile` (TLS + basic auth) |
| 2 | Volume layout: `./data` platform-only (writable), `./hermes-home` Hermes-only. **`./data` is not mounted into the Hermes container** ([HR4](20-hermes-vs-current.md)) |
| 3 | GitHub Actions: lint → offline tests → **three grep fences** → skill lint → migration up/down on a live-DB copy → image build → deploy → smoke |
| 4 | Backup: nightly `leads.db` snapshot via the SQLite backup API + `hermes-home` archive, with a tested restore |
| 5 | `docs/RUNBOOK.md` — backup, restore, rollback, key rotation, proxy expansion, Hermes upgrade, gateway recovery |
| 6 | Security review across both planes ([21 §11](21-hermes-architecture.md)) |
| 7 | Production readiness checklist, extended for the agent tier |

**Architecture changes.** From one process to two containers. **Not** a distributed system: one host,
one SQLite file, one writer, localhost HTTP between the planes, and no Redis
([21 §8.3](21-hermes-architecture.md)).

**Testing.**

| Test | Asserts |
|---|---|
| `test_compose_volumes` | The Hermes service has **no** mount granting access to `leads.db` |
| `test_seam_not_public` | `/api/agent/*` is unreachable through Caddy from outside |
| `test_backup_restore` | A restored backup opens, has 459+ leads, and renders `GET /` |
| `test_hermes_down` | Stopping the gateway leaves every pipeline capability working (**[21 §14](21-hermes-architecture.md)'s acceptance criterion**) |
| `test_deploy_rollback` | The previous image starts and serves after a rollback |
| Security suite | Both planes: secrets in repo/DB/logs/exports, `|safe` usage, `pip-audit`, injection fixtures, key redaction |

**Acceptance criteria.**
- [ ] **H4-AC1** — `docker compose up -d` on a clean VPS yields a working platform and gateway
- [ ] **H4-AC2** — Stopping `hermes-gateway` breaks nothing in the pipeline
- [ ] **H4-AC3** — The Hermes container cannot open `leads.db` (mount list asserted)
- [ ] **H4-AC4** — CI blocks on any failing lint, test, grep fence, or migration
- [ ] **H4-AC5** — Backup and restore verified against a copy of the live database
- [ ] **H4-AC6** — Full security checklist passes across both planes; `pip-audit` clean
- [ ] **H4-AC7** — Hermes is pinned; in-container `hermes update` is disabled
- [ ] **H4-AC8** — All eight Part B suites plus H1–H3 acceptance re-executed
- [ ] **H4-AC9** — 459 legacy leads intact and exportable; all 17 legacy endpoints unchanged
- [ ] **H4-AC10** — The extended production readiness checklist is fully ticked

**Dependencies.** All prior phases.

**Risks.**

| Risk | Mitigation |
|---|---|
| SQLite in a container volume — locking under load | WAL + `busy_timeout` already; single writer; the volume is local disk, never NFS |
| Hermes upgrade breaks the seam | Pinned image; the seam is HTTP, so a mismatch is a 4xx not a crash; upgrades are a tested deploy |
| VPS compromise exposes both keys | Separate keys limit blast radius; `.env` is `0600`; documented rotation in the runbook |
| Deploy breaks the live database | Backup before every migration ([05 §7.1](05-database-plan.md)); tested downgrade; rollback drill in CI |
| Two containers becomes three, then four | The [21 §8.3](21-hermes-architecture.md) Redis analysis is the standing answer: no new process without an observed problem |

**Estimated time.** 8 days.

---

## 13. What is deliberately *not* in this roadmap

| Not doing | Why |
|---|---|
| Agent-orchestrated pipeline | [02b §2](02b-research-2026-07.md); the steps are known in advance |
| Multiple Hermes profiles | [21 §5](21-hermes-architecture.md) — profiles cannot communicate; the trigger is a second human operator |
| MCP servers | Largest single expansion of attack surface and per-turn cost, for no current need |
| Redis, Postgres, Celery | [21 §8.3](21-hermes-architecture.md) — no observed problem to solve |
| Hermes batch runner for enrichment | One full agent loop per item — exactly the wrong shape |
| Automated Reddit engagement | Permanent non-goal ([02a §7](02a-competitor-analysis.md)). Drafting is allowed; sending is not |
| Voice, image generation, browser automation, cloud terminals | No use case; each is Level-0 tax and attack surface |
| External memory providers | Second source of truth for what the BKB already owns |

---

## 14. Definition of done — extended

Every existing item in [10 §7](10-implementation-roadmap.md), plus, for any phase touching the agent
tier:

- [ ] `ruff` clean; `pytest` passes; **no live API calls in CI** (`FakeProvider` + `FakeHermes`)
- [ ] **Three grep fences pass** — no `deepseek` outside `providers/`; no `src.ai` in
      `rules|dedupe|scoring|knowledge|feedback`; **no `hermes` import anywhere in `src/`**
- [ ] Skill lint passes: ≤15 skills, descriptions ≤12 words, all four sections present
- [ ] Every new agent capability has a stated token cost and appears in `agent_events`
- [ ] The governor is exercised by at least one test in the phase's suite
- [ ] Stopping the Hermes container leaves the pipeline fully functional
- [ ] 459 leads intact; `GET /` byte-identical; CSV export 13 columns

---

## 15. Summary

| | |
|---|---|
| Phases reviewed | 8 |
| Kept unchanged | 4 (P1, P2, P4, and P8's data-plane half) |
| Modified | 4 (P3, P5, P6, P7) |
| Split | 1 (P8 → P8 + H4) |
| Deleted | **0** |
| Added | 4 (H1–H4) |
| Migrations added | **1** (`0005_agent_tier`, additive; unshipped `0005`–`0009` renumbered to `0006`–`0010`; one head preserved) |
| Remaining effort | **89 days** — 60 existing, 29 Hermes |
| Expected monthly cost at production | **$0.59** ([24 §7](24-cost-optimization.md)) |
| Hard monthly ceiling | $180 |

**Twenty-nine days of the eighty-nine are Hermes**, and roughly a third of that is deployment and
CI — work that a production system needs whether or not an agent is involved. The agent tier itself
is about nineteen days for a conversational operator surface, a real scheduler, and Telegram
alerting that costs nothing to run.
