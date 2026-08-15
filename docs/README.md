# Documentation Index

> ## ⛔ ARCHITECTURE FROZEN — 2026-08-05 · 🔒 EXECUTION MODE — 2026-08-06
>
> **Start here, in this order:**
>
> | # | Document | What it is |
> |---|---|---|
> | 1 | **[ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md)** | **The binding constraint set.** 20 architecture rules, 31 decisions, 10 migration rules, the frozen technology list, budgets, non-goals, and 18 known risks. Amendable only by a *failed measurement* |
> | 2 | **[EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md)** | **The binding process.** The 16-step session workflow, phase discipline, the public-repository hygiene review, git discipline, engineering priorities, and what may no longer be written. **The last planning document** |
> | 3 | **[34 — Implementation Plan](34-implementation-plan.md)** | **The execution guide.** 31 phases, 83 days, each deployable, testable, reversible and independently mergeable |
> | 4 | **[35 — Testing Strategy](35-testing-strategy.md)** | The gate every phase must pass, and the manual-guide template |
> | 5 | **[DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md)** | Where a good idea waits for the evidence that would justify building it — plus the open operator decisions |
> | 6 | **[36 — Skills Architecture](36-skills-architecture.md)** | Three skill namespaces, and why 13 of the 22 proposed "skills" are Python modules |
> | 7 | **[33 — Final Review](33-final-review.md)** | The freeze review: consistency verification, the final research pass, the authority rules |
>
> **Implementation proceeds one phase at a time**, gated by both automated and manual testing, and
> **stops for approval after every phase**. The `.claude/skills/phase-manager` skill is the
> executable form of [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) and must be loaded before any
> code is written.
>
> Everything numbered 00–32 below is **rationale**. It explains *why* the frozen design is what it
> is, and is retained for that purpose. Where a document below disagrees with the freeze, **the
> freeze wins** — the reconciliation list is [33 §4](33-final-review.md) and
> [32 §5](32-documentation-consistency.md).
>
> **Superseded:** [25](25-hermes-roadmap.md) → [34](34-implementation-plan.md) ·
> [26](26-documentation-plan.md) → [32](32-documentation-consistency.md) ·
> [31](31-execution-plan.md) is [34](34-implementation-plan.md)'s rationale.

---

## Execution record — what has actually been built

The documents above are the *plan*. These are the record of executing it, in phase order. They are
the ones to read when you want to know what exists rather than what is intended.

> ⚠️ **Two unrelated phase numberings live in this directory.** **P0–P30** is the frozen plan in
> [34](34-implementation-plan.md) and is the active scheme. **"Phase 01"–"Phase 08"**
> ([11](11-phase-01.md)…[18](18-phase-08.md), [PHASE-01-STATUS.md](PHASE-01-STATUS.md),
> [PHASE-02-STATUS.md](PHASE-02-STATUS.md), [testing/phase-0N-testing.md](testing/)) is the **legacy**
> scheme, completed 2026-07-30/31. `PHASE-01-STATUS.md` and `PHASE-01-COMPLETION-REPORT.md` are about
> **different phases**.

| Phase | Status | Record | Manual guide |
|---|---|---|---|
| **P0** — Validation sprint | ✅ complete 2026-08-05 | [SPRINT-0-MEASUREMENTS.md](SPRINT-0-MEASUREMENTS.md) · [progress/P00-COMPLETE.md](progress/P00-COMPLETE.md) | [testing/P00-testing.md](testing/P00-testing.md) |
| **P1** — Run & job schema | ✅ complete 2026-08-05 | [PHASE-01-COMPLETION-REPORT.md](PHASE-01-COMPLETION-REPORT.md) · [PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md) · [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md) | [testing/P01-testing.md](testing/P01-testing.md) |
| **P2** — Job queue, worker, logging | ✅ complete 2026-08-06 | [PHASE-02-COMPLETION-REPORT.md](PHASE-02-COMPLETION-REPORT.md) · [PHASE-02-HANDOVER.md](PHASE-02-HANDOVER.md) · [progress/P02-COMPLETE.md](progress/P02-COMPLETE.md) | [testing/P02-testing.md](testing/P02-testing.md) |
| **P3** — Run service, API, run pages | ✅ complete 2026-08-07 | [PHASE-03-COMPLETION-REPORT.md](PHASE-03-COMPLETION-REPORT.md) · [PHASE-03-HANDOVER.md](PHASE-03-HANDOVER.md) · [progress/P03-COMPLETE.md](progress/P03-COMPLETE.md) | [testing/P03-testing.md](testing/P03-testing.md) |
| **P4** — Network provider abstraction | ✅ complete 2026-08-08 | [PHASE-04-COMPLETION-REPORT.md](PHASE-04-COMPLETION-REPORT.md) · [PHASE-04-HANDOVER.md](PHASE-04-HANDOVER.md) · [progress/P04-COMPLETE.md](progress/P04-COMPLETE.md) | [testing/P04-testing.md](testing/P04-testing.md) |
| **P5** — RSS client & Atom parser | ✅ complete 2026-08-08 | [PHASE-05-COMPLETION-REPORT.md](PHASE-05-COMPLETION-REPORT.md) · [PHASE-05-HANDOVER.md](PHASE-05-HANDOVER.md) · [progress/P05-COMPLETE.md](progress/P05-COMPLETE.md) · [P5-IMPLEMENTATION-REVIEW.md](P5-IMPLEMENTATION-REVIEW.md) · [P5-DECISION-ANALYSIS.md](P5-DECISION-ANALYSIS.md) | [testing/P05-testing.md](testing/P05-testing.md) |
| **P6** — Watermarks & incremental discovery | ✅ complete 2026-08-08 — **task 5's heuristic was deleted, not replaced** ([freeze §11.1](ARCHITECTURE_FREEZE.md)) | [PHASE-06-COMPLETION-REPORT.md](PHASE-06-COMPLETION-REPORT.md) · [PHASE-06-HANDOVER.md](PHASE-06-HANDOVER.md) · [progress/P06-COMPLETE.md](progress/P06-COMPLETE.md) · [P6-IMPLEMENTATION-REVIEW.md](P6-IMPLEMENTATION-REVIEW.md) | [testing/P06-testing.md](testing/P06-testing.md) |
| **P7** — Notification tier | ✅ complete 2026-08-10 — **five kinds, zero tokens, no migration**; grep fence 3 (R4) built after six phases of claiming it; **live Telegram delivery verified 2026-08-11**, closing blocker B1 | [PHASE-07-COMPLETION-REPORT.md](PHASE-07-COMPLETION-REPORT.md) · [PHASE-07-HANDOVER.md](PHASE-07-HANDOVER.md) · [progress/P07-COMPLETE.md](progress/P07-COMPLETE.md) · [P7-IMPLEMENTATION-REVIEW.md](P7-IMPLEMENTATION-REVIEW.md) · [P7-DECISION-ANALYSIS.md](P7-DECISION-ANALYSIS.md) · [P7-STAGE5-FLOW.md](P7-STAGE5-FLOW.md) | [testing/P07-testing.md](testing/P07-testing.md) |
| **P8** — Content & dedup schema | ✅ complete 2026-08-13 — `0006`; four empty tables, four `leads` columns, **four foreign keys deliberately left open until `0007`**. Found that `docs/05 §7` had been superseded by [31](31-execution-plan.md)'s reorder ([freeze §11.1](ARCHITECTURE_FREEZE.md)) | [PHASE-08-COMPLETION-REPORT.md](PHASE-08-COMPLETION-REPORT.md) · [PHASE-08-HANDOVER.md](PHASE-08-HANDOVER.md) · [progress/P08-COMPLETE.md](progress/P08-COMPLETE.md) · [P8-IMPLEMENTATION-REVIEW.md](P8-IMPLEMENTATION-REVIEW.md) · [P8-DECISION-ANALYSIS.md](P8-DECISION-ANALYSIS.md) · [P8-IMPLEMENTATION-CHECKLIST.md](P8-IMPLEMENTATION-CHECKLIST.md) | [testing/P08-testing.md](testing/P08-testing.md) |

| **P9** — Rule engine | ✅ complete 2026-08-14 — `src/rules/`, **no migration**; grep fence 2 built after eight phases of passing over paths that did not exist. A property test found a **67.8-second catastrophic backtrack** in P9's own AMA pattern, fixed under [`e24fb90`](PHASE-09-COMPLETION-REPORT.md). The acceptance row's *"11 rejection reasons"* was unsatisfiable and is reconciled to four ([freeze §11.1](ARCHITECTURE_FREEZE.md)) | [PHASE-09-COMPLETION-REPORT.md](PHASE-09-COMPLETION-REPORT.md) · [PHASE-09-HANDOVER.md](PHASE-09-HANDOVER.md) · [progress/P09-COMPLETE.md](progress/P09-COMPLETE.md) · [P9-IMPLEMENTATION-REVIEW.md](P9-IMPLEMENTATION-REVIEW.md) · [P9-DECISION-ANALYSIS.md](P9-DECISION-ANALYSIS.md) · [P9-IMPLEMENTATION-CHECKLIST.md](P9-IMPLEMENTATION-CHECKLIST.md) | [testing/P09-testing.md](testing/P09-testing.md) |

| **P10** — Dedup cascade | ✅ complete 2026-08-14 — `src/dedupe/`, **no migration**; three tiers, 100% branch coverage, and **DI22 closed as an application guarantee** the schema cannot express. **A5 was measured before a line was written and the literal *"MinHash 128 perms"* reading failed it** — 6.36 s / 11.11 s against a 2 s budget — so the phase ships One-Permutation Hashing at 0.59 s / 0.87 s, *more* accurate than the classic form ([freeze §11.1](ARCHITECTURE_FREEZE.md)). The Metrics row's *"collapse rate > 8%"* measured **5.74%** and is reconciled as an intra-run quantity owed to P11. **Mutation testing found a real defect** — the cascade was grouping by *single* linkage, producing a 14-member group whose furthest pair was **0.445** similar; it is complete linkage now | [PHASE-10-COMPLETION-REPORT.md](PHASE-10-COMPLETION-REPORT.md) · [PHASE-10-HANDOVER.md](PHASE-10-HANDOVER.md) · [progress/P10-COMPLETE.md](progress/P10-COMPLETE.md) · [P10-DECISION-ANALYSIS.md](P10-DECISION-ANALYSIS.md) | [testing/P10-testing.md](testing/P10-testing.md) |
| **P11** — Pre-score, funnel & comments | ✅ complete 2026-08-15 — `src/scoring/`, `CommentScraper`, the funnel on the run page, **no migration**; **the first caller `src/dedupe/` and `src/rules/` have ever had**. Fence 2 reaches **4 of 6**, the rejection vocabulary reaches **8 of 11**, and **`SELECT COUNT(*) FROM ai_calls` is 0**. **Four Deferred Improvements were built** — DI24 (P6 had never matched a keyword), DI13 (unknown counts stored as a confident `0`; measured **0 of 492** live rows carried NULL where the schema always allowed it), DI23 (two vocabularies rendered on one page) and 🔴 **DI25**, the live defect discarding *"Our hiring process is broken and I need a tool to fix it"* — **and the holdout that measures it was built first, deliberately, so the evidence survived the fix**. Three reconciliations ([freeze §11.1](ARCHITECTURE_FREEZE.md)): 06c §3.1 never supplied the weights and three of its nine components have no data source until `0007`, so **six ship and three are declared absent**; the `prescores` CHECK wall P6 filed is discharged by persisting the 2% sample as `source='holdout_audit'` leads; and *"N distinct pre-scores"* is not literally satisfiable — measured, **two of 23 real groups are reposts created one minute apart**. **A2 measured: 75.4%** archive / **20.9%** in-window against the assumed 73% | [PHASE-11-COMPLETION-REPORT.md](PHASE-11-COMPLETION-REPORT.md) · [PHASE-11-HANDOVER.md](PHASE-11-HANDOVER.md) · [progress/P11-COMPLETE.md](progress/P11-COMPLETE.md) · [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md) | [testing/P11-testing.md](testing/P11-testing.md) |
| **P12** — Project & BKB schema | ✅ complete 2026-08-15 — **`0007`, the largest revision in the chain**: twelve tables, **six** deferred `project_id` foreign keys closed, and a conditional `vec0` pair **skipped** because `sqlite-vec` is not installed anywhere measured. Every table ships **empty** — P14 writes the BKB, P16 the first project. Three reconciliations ([freeze §11.1](ARCHITECTURE_FREEZE.md)), each **measured before code was written**: **`runs.project_id` is not tightened to `NOT NULL`** — 11 of 11 live runs are `NULL`, the rebuild fails on them, backfilling is the row rewrite **M5** forbids, and **AD-5** freezes project scoping as *additive and nullable*; **six FKs close, not four** — four documents gave four counts, and the `leads` rebuild was probed on a copy of the live database first (492 rows, fingerprint `9327a13dd9ef4185`, nine indexes, the `reddit_id` UNIQUE, all preserved); and **`payload_json` ships nullable with a `CHECK`**, because §5.1 and §5.1b cannot both hold — with `ideal_customer_profiles` **not** exempt. **Mutation testing found two real defects, both in P12's own tests**: two payload tests were passing on a *foreign-key* violation and never exercised the `CHECK` at all, and two guards guarded nothing. **DI28 was considered while the revision was open and deliberately declined**; [DI29](DEFERRED-IMPROVEMENTS.md) opened | [PHASE-12-COMPLETION-REPORT.md](PHASE-12-COMPLETION-REPORT.md) · [PHASE-12-HANDOVER.md](PHASE-12-HANDOVER.md) · [progress/P12-COMPLETE.md](progress/P12-COMPLETE.md) · [P12-DECISION-ANALYSIS.md](P12-DECISION-ANALYSIS.md) | [testing/P12-testing.md](testing/P12-testing.md) |

**Operational records** — verification passes between phases, not phases themselves:
[PRE-P2-VERIFICATION-REPORT.md](PRE-P2-VERIFICATION-REPORT.md) ·
[PRIVACY_REVIEW.md](PRIVACY_REVIEW.md) ·
[GITHUB_ACTIONS_REPORT.md](GITHUB_ACTIONS_REPORT.md) ·
[TAG_REPORT.md](TAG_REPORT.md) ·
[FINAL_PRE_P2_REVIEW.md](FINAL_PRE_P2_REVIEW.md) ·
[../CHANGELOG.md](../CHANGELOG.md)

[`progress/`](progress/) holds one `PNN-COMPLETE.md` per finished phase, each ending in a **resume
point**. It exists so an interruption — power loss, crash, context reset — can be recovered from
without re-deriving state. [`../RECOVERY_REPORT.md`](../RECOVERY_REPORT.md) is the audit produced the
first time that was needed.

**Legacy phases:** [PHASE-01-STATUS.md](PHASE-01-STATUS.md) ·
[MANUAL-TESTING-PHASE-01.md](MANUAL-TESTING-PHASE-01.md) · [PHASE-02-STATUS.md](PHASE-02-STATUS.md)

---

Planning and architecture documentation for the Reddit Lead Intelligence platform.

> **This section is rationale, and it is now historical.** It was written while the project was in
> Research Mode and described a documentation set with no application code behind it. That has not
> been true since P0/P1 shipped — see the **Execution record** above, and
> [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) for the process that governs everything from
> 2026-08-06 onward.

This is an **internal intelligence platform**, not a commercial SaaS. It optimises for lead quality,
research depth, AI efficiency, and long-term maintainability — never for onboarding simplicity or
per-seat pricing. **DeepSeek V4 Flash** is used as an *intelligent enrichment engine*, never as the
primary processing engine: every task deterministic local code can solve is solved locally, before
any provider call.

Read 00–02c for context, 03–09 for design, 10–18 for execution.

## Context

| Doc | Contents |
|---|---|
| [00 — Current State](00-current-state.md) | Codebase audit, live `old.reddit.com` probe, 10 confirmed defects, structural constraints, reuse map |
| [01 — Product Vision](01-product-vision.md) | Canonical flow, why the review gates are the defining constraint, non-goals |
| [02 — Research Findings](02-research-findings.md) | Market, Reddit blocking 2026, proxy practice, **DeepSeek V4 Flash (§6.2–6.7)**, **batch prompting arithmetic and quality ceiling (§6.8)**, **cache operational reality (§6.9)**, **three-tier semantic dedup (§6.10, revised)**, **the local-first principle (§6.11)**, **call consolidation (§6.12)**, 41-entry decision register |
| **[02a — Competitor Analysis](02a-competitor-analysis.md)** | **Tydal and RedShip** analysed from primary sources; the seven shared architectural assumptions we reject; capability comparison; where they are ahead, stated honestly; the SEO/GEO decision |
| **[02b — Deep Research 2026-07](02b-research-2026-07.md)** | **20 researched topics, each ending in a decision** — adopt / adopt-with-limits / defer / reject. Seven are rejections. Closes with the five decisions this research reversed |
| **[Startup & Improvements Report](STARTUP-AND-IMPROVEMENTS-REPORT.md)** | **Read this if `pnpm run dev` failed.** Startup audit, why there is no Node layer, provider-management improvements, and the project-architecture verdict |
| **[Phase 01 Status](PHASE-01-STATUS.md)** | What is actually built vs planned, live verification, and the six bugs found |
| **[02c — Final Architecture Review](02c-research-final-review.md)** | **Knowledge lifecycle, evidence, evolution, feedback, memory** — 11 topics, **six rejected wholly or in part**. Opens with the one correctness defect research found. Includes the competitor *architecture* comparison and a table of what stays unchanged |

## Design

| Doc | Contents |
|---|---|
| [03 — Architecture](03-architecture.md) | Layered monolith incl. the **Knowledge** and **Feedback** tiers, package layout, **AD-1…AD-19** — notably AD-10a (local-first), AD-13 (BKB as core asset), AD-14 (derived budget), AD-15 (faithful explanations), AD-16 (optional semantic layer), **AD-17 (knowledge accretes)**, **AD-18 (four memory classes)**, **AD-19 (version pinning)** |
| [04 — System Design](04-system-design.md) | Run state machine, job queue, worker, proxy, Reddit client, AI subsystem, discovery, scraping, **hybrid confidence engine (§9)**, observability |
| [05 — Database Plan](05-database-plan.md) | Project scoping, full DDL incl. **the Business Knowledge Base (§5.1a)**, **overlapping-section rule (§5.1b)**, **lifecycle / evidence / entity status (§5.1c–d)**, **AI infrastructure (§5.4a)**, **dedup / prescores / gate audits (§5.4b)**, **budget + quality (§5.4c)**, **patterns (§5.4d)**, authoritative migration sequence (§7), intra-revision ordering (§7.1a) |
| [06 — AI Pipeline](06-ai-pipeline.md) | End-to-end map, **one consolidated intelligence call (§3)**, local stages (§4), **batched enrichment (§5)**, schemas, prompts, failures, evaluation |
| **[06a — AI Service Layer](06a-ai-service-layer.md)** | **4 model-invoking methods**, provider abstraction, prompt manager, frozen prefix, repair ladder, **6-level cache hierarchy**, concurrency, extensibility |
| **[06b — DeepSeek Optimization](06b-deepseek-optimization.md)** | Wire format, prefix-cache engineering, **13 techniques ranked by what they actually save (§4)**, **measured batch-size procedure (§4.6)**, cost model, config |
| **[06c — Local-First Pipeline](06c-local-first-pipeline.md)** | **Never call AI if it isn't required**: the two funnels, what never touches AI, rule engine, pre-score, the **adaptive** gate, 3-tier dedup, incremental, **holdout audit** |
| **[06d — AI Budget & Scale](06d-ai-budget-and-scale.md)** | **Call and cost budgets for 100 → 10,000 posts**, mode comparison, cold-cache sensitivity, monthly cost, **why this beats one-call-per-post** |
| **[06e — Business Knowledge Base](06e-business-knowledge-base.md)** | **23 typed sections**, entity resolution, the knowledge-graph decision, **the semantic-layer reversal**, what enters the enrichment prefix and what does not, how the knowledge base learns |
| **[06f — Adaptive AI Budget](06f-adaptive-budget.md)** | **Why the fixed threshold was wrong**; knee detection, quality floor, marginal value, clamps; **five worked distributions**; how the holdout audit validates the knee |
| **[06g — Explainability & Quality](06g-explainability-and-quality.md)** | **Faithful by construction**: the 10 explanation fields and their provenance; the quality suite — precision, FP/FN, gate miss rate, ECE/Brier, PSI drift, span grounding; what happens when a metric goes red |
| **[06h — Knowledge Lifecycle](06h-knowledge-lifecycle.md)** | **Staleness without decay**, typed evidence, knowledge accretion from Reddit, per-type freshness policy, **the origin write-path guard**, pattern discovery as a `GROUP BY`, entity lifecycle |
| **[06i — Feedback, Memory & Provenance](06i-feedback-and-memory.md)** | **The degenerate-loop fix**, label reasons, **Tier 2 enrichment**, four memory classes in one file, version pinning and the reproduction guarantee, the researcher view |
| [07 — Scraping Pipeline](07-scraping-pipeline.md) | Endpoints, corrected pagination, extraction, rate limiting, dedup, caching, golden fixtures |
| [08 — Proxy Service](08-proxy-service.md) | Credential rules, proxy state machine, manager, client, circuit breaker, metrics |
| [09 — Dashboard Plan](09-dashboard-plan.md) | Information architecture, **`/settings/ai` (§2a)**, **the BKB browser with staleness and origin markers (§3.2)**, **explainable lead detail + researcher view (§3.8)**, **`/projects/<id>/patterns` (§3.8a)**, **`/health/quality` (§3.9)**, API surface, export |

## Execution

| Doc | Phase | Migration | Cumulative |
|---|---|---|---:|
| [10 — Implementation Roadmap](10-implementation-roadmap.md) | Overview, **§1.1 what research invalidated**, **§1.2 the final review**, critical path, 31 risks, tech debt, production checklist, **§11 why this stays maintainable for 3–5 years** | — | — |
| [11 — Phase 01](11-phase-01.md) | AI Foundation & DeepSeek Integration | `0001`–`0002` | 14% |
| [12 — Phase 02](12-phase-02.md) | Proxy Service & Scraping Transport | `0003` | 24% |
| [13 — Phase 03](13-phase-03.md) | Orchestration: Runs, Jobs, Worker | `0004` | 34% |
| [14 — Phase 04](14-phase-04.md) | **The Business Knowledge Base** — one consolidated call | `0005` | 50% |
| [15 — Phase 05](15-phase-05.md) | Discovery, Keywords & Review Gates — **zero AI** | `0006` | 63% |
| [16 — Phase 06](16-phase-06.md) | Scraping, Comments & **the Local Processing Pipeline** | `0007` | 75% |
| [17 — Phase 07](17-phase-07.md) | **Adaptive, Batched** Enrichment & **Explainable** Confidence | `0008` | 90% |
| [18 — Phase 08](18-phase-08.md) | **Quality Measurement**, Dashboard, Export & Production Readiness | `0009` | 100% |

## Testing

Every phase has **Part A — Claude Verification** (architecture · compilation · lint · imports ·
typing · edge cases · error handling · security · performance · scalability · logging · retries ·
**AI verification & efficiency** · regression) and **Part B — Manual Testing** (per feature: test
case · preconditions · steps · expected · failure · edge cases · success criteria).

| Doc | Manual tests |
|---|---:|
| [Phase 01](testing/phase-01-testing.md) — AI foundation | 14 |
| [Phase 02](testing/phase-02-testing.md) — proxy & transport | 18 |
| [Phase 03](testing/phase-03-testing.md) | 11 |
| [Phase 04](testing/phase-04-testing.md) — incl. 23 sections, entity resolution, **origin guard**, **evidence typing** | 17 |
| [Phase 05](testing/phase-05-testing.md) — incl. channel 4, zero-AI | 11 |
| [Phase 06](testing/phase-06-testing.md) — incl. 3-tier dedup, pre-score, zero-AI | 15 |
| [Phase 07](testing/phase-07-testing.md) — incl. adaptive budget, explainability, **exploration loop**, **version pinning** | 25 |
| [Phase 08](testing/phase-08-testing.md) — incl. golden-set gate, calibration, drift, **cache-is-not-state**, patterns | 18 |
| | **129** |

---

## Deliverable map

| # | Deliverable | Location |
|---|---|---|
| 1 | Research summary — 20 topics | [02b](02b-research-2026-07.md) |
| 2 | Competitive analysis (Tydal, RedShip) | [02a](02a-competitor-analysis.md) |
| 3 | Where we can be significantly better | [02a §5](02a-competitor-analysis.md) · [02a §8](02a-competitor-analysis.md) |
| 4 | **Business Knowledge Base design** — 23 sections | [06e](06e-business-knowledge-base.md) · [05 §5.1a](05-database-plan.md) |
| 5 | Structured knowledge / vector index recommendation | [06e §3.1, §5](06e-business-knowledge-base.md) · [02b §7–9](02b-research-2026-07.md) — **KB yes, graph no, local vectors yes** |
| 6 | **Adaptive AI budget** (no fixed gating %) | [06f](06f-adaptive-budget.md) |
| 7 | Updated AI architecture | [03 §2, AD-13…AD-16](03-architecture.md) · [06a](06a-ai-service-layer.md) |
| 8 | Updated DeepSeek optimisation strategy | [06b §4](06b-deepseek-optimization.md) · [06e §6](06e-business-knowledge-base.md) (prefix discipline) |
| 9 | Updated cost & call budget by scrape size | [06d §2, §2.1](06d-ai-budget-and-scale.md) |
| 10 | **Explainable leads** — 10 fields | [06g Part I](06g-explainability-and-quality.md) · [09 §3.8](09-dashboard-plan.md) |
| 11 | **Expanded quality monitoring** | [06g Part II](06g-explainability-and-quality.md) · [09 §3.9](09-dashboard-plan.md) |
| 12 | Entity resolution & semantic matching | [06e §4, §5](06e-business-knowledge-base.md) · [02b §10](02b-research-2026-07.md) |
| 13 | **Refactored implementation roadmap** | [10](10-implementation-roadmap.md) |
| 14 | **What the research invalidated, and why** | [10 §1.1](10-implementation-roadmap.md) · [02b — closing table](02b-research-2026-07.md) |
| 15 | Updated testing plan | [testing/](testing/) — 129 manual tests, 8 suites |

### Final review deliverables ([02c](02c-research-final-review.md))

| # | Deliverable | Location |
|---|---|---|
| 1 | Research summary — 11 topics | [02c §1–§11](02c-research-final-review.md) |
| 2 | Adopt / Reject / Defer decisions | [02c §14](02c-research-final-review.md) — and **§12 what stays correct** |
| 3 | Updated Business Knowledge architecture | [06h](06h-knowledge-lifecycle.md) · [05 §5.1c–d](05-database-plan.md) |
| 4 | Knowledge lifecycle strategy | [06h §2](06h-knowledge-lifecycle.md) — staleness, **not** decay |
| 5 | Evidence model | [06h §3](06h-knowledge-lifecycle.md) — five source types; inference never self-promotes |
| 6 | Knowledge evolution strategy | [06h §4](06h-knowledge-lifecycle.md) — aggregate-only, operator-gated |
| 7 | Human feedback strategy | [06i §2](06i-feedback-and-memory.md) — incl. **the degeneracy fix** |
| 8 | Progressive enrichment strategy | [06i §3](06i-feedback-and-memory.md) — Tier 1 batched, Tier 2 for the top slice |
| 9 | Explainability improvements | [06i §5–§6](06i-feedback-and-memory.md) — version pinning, researcher view |
| 10 | Confidence calibration strategy | [06g §4.2](06g-explainability-and-quality.md) — **re-confirmed unchanged** |
| 11 | Memory architecture | [06i §4](06i-feedback-and-memory.md) — four classes, one file |
| 12 | Competitor architectural comparison | [02c §13](02c-research-final-review.md) |
| 13 | Updated implementation roadmap | [10 §1.2](10-implementation-roadmap.md) |
| 14 | Updated testing strategy | [testing/](testing/) — +9 tests |
| 15 | Risks and trade-offs | [10 §5](10-implementation-roadmap.md) — R27–R31 |
| — | **Why this stays maintainable 3–5 years** | [10 §11](10-implementation-roadmap.md) |

---

## The efficiency architecture in one table

Per 1,000 collected Reddit posts, `balanced` mode, typical distribution:

| Design | AI calls | Cost |
|---|---:|---:|
| Naive A: one call per post, **cold** cache, no filter | 1,000 | $0.560 |
| Naive B: one call per post, cache working | 1,000 | $0.148 |
| \+ pre-filter & dedup | 270 | $0.040 |
| \+ **adaptive** admission gate (knee at 176) | 176 | $0.026 |
| \+ batching B=8 | **22** | $0.025 |
| \+ holdout audit (quality insurance) | 23 | $0.026 |
| \+ website BKB call (once per site version) | **24** | **$0.030** |

**98% fewer calls; 95% lower cost vs. Naive A, 80% vs. Naive B — and unlike either, the filtering
is measured.** Full decomposition in [06d §3](06d-ai-budget-and-scale.md).

Note that adaptive budgeting made this *slightly more* expensive than the fixed cut it replaced
($0.030 vs $0.026), and that this is the correct direction: the fixed cut was cheaper because it was
discarding leads on the steep part of the score curve. **The goal is the fewest calls that do not
lose real leads** — the holdout audit is what distinguishes the two.

## The nine things that matter most

1. **AI is the last enrichment step, never the first.** Keyword matching, regex, dedup, URL and HTML
   parsing, age and score arithmetic, competitor alias resolution, sorting, filtering, ranking and
   similarity hashing are deterministic. None of them may reach a provider.
2. **The website becomes a Business Knowledge Base, not an artefact.** 23 versioned, entity-resolved,
   evidence-backed sections that every later stage reads from — and that outlive every run. This is
   the platform's core asset and the thing neither competitor has.
3. **How much AI runs is derived from the data, not configured.** Knee detection over the pre-score
   distribution, bounded by a quality floor, marginal value, and clamps — with the deciding rule
   persisted and displayed on every run.
4. **Calls scale with unique high-value candidates, not scraped volume** — ~1 call per 42 collected
   posts, and **$0.00** for a re-run with nothing new.
5. **Batching's honest value is cache-miss insurance and latency**, not headline cost. It saves ~5%
   with a hot prefix cache and ~67% with a cold one, and cuts call count 8×. The dollars come from
   the gate, dedup, and incremental processing.
6. **The AI never produces the final score, and never writes the explanation.** It emits categorical
   judgements and closed-set slug selections; deterministic Python blends them and renders the
   reasoning — so re-ranking is free, calibration is possible, and the explanation *is* the
   computation rather than a story told about it.
7. **Aggressive filtering demands continuous measurement.** The holdout audit re-admits 2% of
   rejects and publishes a **gate miss rate**; the golden set blocks any prompt version that drops
   F1 by more than 0.02. Unmeasured cost optimisation is indistinguishable from quality loss.
8. **Roughly one twentieth of AI spend goes to measuring the other nineteen twentieths.** For a
   system whose entire cost argument rests on *not* calling the model, that is the minimum
   responsible ratio.
9. **Knowledge accretes and never silently disappears.** Reddit teaches the knowledge base new
   terminology, competitors and objections — but only from aggregate patterns, only with operator
   acceptance, and regeneration can never delete what was learned. The holdout audit does double
   duty as the exploration channel that stops the learning loop confirming its own gate.

## Empirical verification performed

- **`old.reddit.com`, 2026-07-29** — listing and search both HTTP 200; page size 25; the current
  search-pagination selector targets a tag that does not exist.
- **DeepSeek V4 Flash, 2026-07-30** — pricing, 1M context, OpenAI-compatible endpoint, implicit
  64-token-chunk prefix caching (**best-effort, hours-to-days TTL, no guaranteed hit rate**), JSON
  mode requirements and documented failure modes, error-code retryability, **absence of a batch
  endpoint**, announced-but-inactive 2× peak surcharge.
- **Batch prompting, 2026-07-30** — quality holds to b<16 for simple classification, b<8 for
  reasoning, ~4 for heterogeneous items; degradation mechanism is attention dilution.
- **Semantic dedup, 2026-07-30** — MinHash+LSH at Jaccard ≥ 0.85 is the CPU-only tier; **static
  embeddings (Model2Vec, ~30 MB, CPU, 50–100k docs/sec) with `sqlite-vec` add a third tier at no
  API cost** — reversing the earlier exclusion, see [06e §5.1](06e-business-knowledge-base.md).
- **Tydal and RedShip, 2026-07-30** — positioning, pricing, workflow, scoring approach and stated
  automation philosophy, from primary sources ([02a](02a-competitor-analysis.md)); re-reviewed for
  **knowledge flow and orchestration** rather than features ([02c §13](02c-research-final-review.md)).
- **Knowledge freshness, feedback loops and cascades, 2026-07-30** — staleness degrades silently;
  degenerate feedback loops are mitigated by exploration; LLM cascades cut cost up to 90%;
  implicit feedback carries position bias; voice-of-customer themes need 4–6 weeks of volume
  ([02c](02c-research-final-review.md)).
- **Budget arithmetic, 2026-07-30** — all five distributions in
  [06f §4](06f-adaptive-budget.md) and every figure in [06d §2](06d-ai-budget-and-scale.md) computed,
  not estimated.

---

Start with [00 — Current State](00-current-state.md), then
[02c — Final Architecture Review](02c-research-final-review.md),
[06e — Business Knowledge Base](06e-business-knowledge-base.md), and
[10 — Implementation Roadmap](10-implementation-roadmap.md).

**Three review passes are recorded here** ([02b](02b-research-2026-07.md),
[02c](02c-research-final-review.md), and the DeepSeek re-evaluation folded into
[02](02-research-findings.md)). Each ends in explicit Adopt / Reject / Defer decisions, and each
rejected more than it adopted. That ratio is the point: the architecture is one Python process, one
SQLite file, one linear migration chain, and one AI boundary — and every piece of machinery beyond
that had to argue for itself.
