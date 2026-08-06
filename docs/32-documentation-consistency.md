# 32 — Documentation Consistency Plan

> **Part 11.** Which documents must change, which diagrams change, which architecture decisions
> change, which ADRs to add, and which documents are now superseded.
>
> **No existing document has been modified in this pass.** As in [26](26-documentation-plan.md), each
> edit lands with the sprint that makes it true.

---

## 1. Documents created in this review

| Doc | Covers | Brief part |
|---|---|---|
| [27 — Architecture Review](27-architecture-review.md) | Gaps, weak assumptions, complexity, duplication, risks, missing production concerns | 1 |
| [28 — Discovery Redesign](28-discovery-redesign.md) | RSS, incremental sync, layered reduction, adaptive polling, discovery agent | 3, 4, 7 |
| [29 — Network & Proxy Strategy](29-network-and-proxy-strategy.md) | Egress policy, provider interface, managed-provider comparison | 5, 6 |
| [30 — AI Call Inventory](30-ai-call-inventory.md) | All 17 model paths; cache / replace / delay / skip; savings | 8 |
| [31 — Execution Plan](31-execution-plan.md) | Sprint order, Sprint 0, updated roadmap | 2, 9, 10 |
| **32 — Documentation Consistency** | This document | 11 |

---

## 2. Superseded documents — stated first, because two of them are mine

▶ A review that produces a second roadmap without retiring the first has made the documentation
*less* consistent, not more.

| Doc | Status | Disposition |
|---|---|---|
| [25 — Updated Implementation Roadmap](25-hermes-roadmap.md) | **Superseded by [31](31-execution-plan.md)** | **Retain, with a header note.** Its phase-by-phase reasoning is carried forward; its *ordering* (H1 at position 4, migration `0005_agent_tier`, the `0005`–`0010` renumbering) is withdrawn |
| [26 — Documentation Plan](26-documentation-plan.md) | **Superseded by this document** | **Retain, with a header note.** Most of its update list survives; the migration-renumbering rows are withdrawn |

**Header to add to both, verbatim:**

> ⚠️ **Superseded by [31 — Execution Plan](31-execution-plan.md) / [32 — Documentation Consistency
> Plan](32-documentation-consistency.md) (2026-08-05).** The reasoning here remains valid and is why
> the successor reached different conclusions. The execution order, the migration numbering, and the
> `agent_events` / `notification_log` tables specified here are **withdrawn** — see
> [27 §5](27-architecture-review.md).

▶ Retaining rather than deleting matches the practice this doc set already follows: every reversal is
recorded with its reasoning ([02b closing table](02b-research-2026-07.md),
[10 §1.1](10-implementation-roadmap.md), [06e §5.1](06e-business-knowledge-base.md)). A deleted
document invites the same idea to be re-proposed a month later.

---

## 3. The consistency ledger

Every contradiction found in [27 §1](27-architecture-review.md), and where each is closed.

| # | Contradiction | Authority | Fixed in | Sprint |
|---|---|---|---|---|
| C1 | Confidence weights differ between [04 §9.1](04-system-design.md) and [09 §3.8](09-dashboard-plan.md) | **[04 §9.1](04-system-design.md)** | Regenerate the [09](09-dashboard-plan.md) example from real weights | S6 |
| C2 | **[09 §3.8](09-dashboard-plan.md)'s "signal boost" contradicts [AD-11](03-architecture.md)/[AD-15](03-architecture.md)** | **[04 §9](04-system-design.md)** | Remove the boost; the example must sum exactly; add a reconciliation test | S6 |
| C3 | Golden set is 40 items in [06 §9](06-ai-pipeline.md)/[17](17-phase-07.md), 100 in [06g §4.4](06g-explainability-and-quality.md)/[18](18-phase-08.md) | **Both, sequentially** | State the expansion: 40 for the S6 batch sweep, 100 for the S8 blocking gate | S6, S8 |
| C4 | Cost figures drift across five documents | **[06d](06d-ai-budget-and-scale.md)** | Every other document cites, never restates | S4 |
| C5 | `ai_artifacts` survives in [14 §9.2](14-phase-04.md) but is removed by [05 §5.1](05-database-plan.md) | **[05](05-database-plan.md)** | Replace the code sample with `bkb`/`bkb_sections` supersede logic | S4 |
| C6 | [README](README.md) counts 18 tests from a superseded `testing/phase-02-testing.md` | **[12 §14](12-phase-02.md)** | Correct the count and note the supersession | S2 |

---

## 4. New architecture decisions

▶ **Continue the existing `AD-NN` convention inside [03 §6](03-architecture.md). Do not introduce a
separate `docs/adr/` directory.**

The brief asks which ADRs to add. This repository already has a working decision record — twenty-four
numbered decisions with rationale, consequences, and explicit rejections, living beside the
architecture they govern. Adding a parallel ADR directory would create two places to look for the
same kind of statement, and [10 §11.5](10-implementation-roadmap.md)'s standing principle is that
machinery must argue for itself. ▶ A second convention for the same artefact does not.

### AD-25 — Egress is a policy, not a mandate

**Context.** [07 §1](07-scraping-pipeline.md) requires all traffic via rotating proxy;
[08 §7](08-proxy-service.md) sets `fail_closed: true`. ✅ [PHASE-02-STATUS §4.1](PHASE-02-STATUS.md)
measured a 67% block rate through the pool, with 8 of 10 proxies blacklisted, while
[00 §3](00-current-state.md) recorded the direct connection returning 200.

**Decision.** Egress is selected **per request class** by a `NetworkPolicy` over pluggable
`NetworkProvider`s. RSS, health checks and the customer's own website are always direct. Bulk HTML
prefers a proxy and degrades under `on_pool_exhausted`, bounded by `max_requests_per_hour` and
logged to `run_events`.

**Consequences.** The IP-exposure goal is preserved; the throughput penalty is not. Degradation is
bounded and visible rather than absent. Vendor swap becomes a config change
([29 §5.4](29-network-and-proxy-strategy.md)).

**Rejected.** Removing proxies entirely — IP exposure at volume is a real concern and the goal was
always correct. Keeping `fail_closed` — a truncated run is worse than a slower one, and the original
objection (*unbounded* silent fallback) is answered by the governor.

### AD-26 — Discovery is metadata-first

**Context.** 62% of the [07 §5](07-scraping-pipeline.md) request budget is the search path; every
discovered post is downloaded in full before any filter runs. ✅ RSS returns 100 items per request,
supports multireddit combining and search, and is a stable Atom schema.

**Decision.** Discovery uses RSS for change detection, incremental sync and keyword search. Bodies
are fetched only for items surviving metadata triage, by a **density-adaptive** choice between an
HTML listing walk (≥25% survivors) and per-post permalinks (<25%).

**Consequences.** Steady-state requests fall 64–93%. The highest-frequency path moves off fragile
CSS parsing onto a versioned schema, reducing exposure to [R1](10-implementation-roadmap.md). A new
rejection stage is introduced — and therefore inherits [AD-10b](03-architecture.md)'s audit
obligation ([28 §9 D6](28-discovery-redesign.md)).

**Rejected.** Replacing HTML with RSS outright — an HTML listing page carries 25 posts *with body and
score*; RSS carries 100 *without*. Both are retained. The `user=`/`feed=` rate-limit workaround —
it requires a Reddit account and violates [D1](02-research-findings.md).

### AD-27 — The watermark is the sync primitive, and overflow is an error

**Context.** RSS returns at most 100 items and does not paginate. A subreddit producing more than 100
posts between polls silently loses the excess.

**Decision.** One `discovery_watermarks` row per (subreddit, channel, query). Every poll checks
whether the feed's oldest item is newer than `last_seen_utc`; if so this is **logged as an error**
and triggers an HTML fallback walk plus a shortened interval.

**Consequences.** Incremental sync becomes reliable rather than hopeful. Adaptive polling
(`observed_rate_per_hour`, `consecutive_empty`) becomes possible with zero AI.

**Rejected.** Treating a short feed as "nothing new" — the failure would be invisible, which is the
one property [AD-10b](03-architecture.md) forbids in any filtering mechanism.

### AD-28 — Notifications never invoke a model

**Context.** ✅ `hermes send` is documented as working *"without spinning up an agent or gateway
loop"*; a direct Bot API call involves no agent at all.

**Decision.** Every routine notification body is rendered from SQL in `src/notify/renderers.py` and
delivered through a transport interface with three implementations. `src/notify/` imports neither
`src.ai` nor any agent runtime.

**Consequences.** ~30 messages/month at **$0.00**. Notifications survive the agent budget ceiling —
a cost control that silenced alerts would be switched off. Telegram alerting ships in Sprint 2
instead of waiting for the agent tier.

**Rejected.** A `telegram-notifier` skill ([22 §7](22-hermes-skills.md)) — it would convert the most
frequent message in the system from free to metered.

### AD-29 — The agent tier adds no tables

**Context.** [21 §13](21-hermes-architecture.md) proposed `agent_events` and `notification_log`,
forcing a migration renumbering. ◐ `ai_calls` already carries provider, model, stage, tokens, cost,
latency and outcome; the state machine's transition guard already provides notification idempotency.

**Decision.** Agent turns are written to `ai_calls` with `stage='agent.<skill>'`. Notification
dedup rides on `run_events` plus the transition guard.

**Consequences.** Hermes adds **zero migrations**, so the agent tier can be resequenced freely.
`/health/ai` shows one spend figure without a union. **Required:** every efficiency query gains
`WHERE stage NOT LIKE 'agent.%'`, with a test asserting an agent row does not move the calls-per-1,000
metric.

**Rejected.** Separate tables — they would duplicate a schema that already fits and would couple the
agent tier's position in the plan to a migration ordering constraint.

### AD-30 — Deployment is systemd and unix users, not containers

**Context.** [21 §8](21-hermes-architecture.md) specified two containers, Compose, a registry and an
image pipeline, principally to guarantee that Hermes cannot open `leads.db`.

**Decision.** Two systemd units under two unix users on one VPS. `data/leads.db` is `0600`, owned by
the platform user. Hermes is pinned by version in its own venv with `hermes update` disabled.

**Consequences.** The isolation guarantee is *stronger* — file permissions survive a misconfigured
mount — and is assertable by attempting a read as the Hermes user. Removes an image build, a
registry, a Compose file and a container network hop. Uses the mechanism Hermes itself documents
(`hermes gateway install --system`).

**Rejected.** Docker — reconsidered when there is a second host, a second operator, or a need to run
outside this VPS. **Trade-off accepted:** rollback is a symlink switch rather than an image tag, and
dependency resolution is reproducible only via a lockfile.

### AD-31 — Framework defaults are audited, not inherited

**Context.** ✅ Hermes ships with `title_generation: true`, `approvals: smart`, a per-turn memory
background review, and automatic skill creation — **four model-invoking paths that no budget in this
plan accounted for** ([30 §2](30-ai-call-inventory.md)).

**Decision.** Before any framework is integrated, its effective configuration is diffed against its
documented defaults and **every model-invoking path is enumerated and assigned a measured
frequency**. Paths without a consumer are disabled explicitly rather than left inert.

**Consequences.** `title_generation: false`, `approvals: off`, `max_turns: 12`, memory review
disabled if per-turn (M-11). ◐ Up to 42% of projected platform AI spend.

**Rejected.** Trusting that disabling a toolset removes its auxiliary paths — the `approvals: smart`
assessor is configured independently of whether a terminal exists.

### 4.1 Amendments to existing decisions

| AD | Change |
|---|---|
| **AD-1** | *Unchanged in principle.* `src/net/` stays Reddit-agnostic; it gains a provider layer beneath it |
| **AD-2** | **Extended.** `RedditClient` gains `get_feed()`. Additive only — every existing signature and return shape is frozen |
| **AD-10b** | **Extended to the metadata-triage stage.** A 2% holdout on Stage-3 rejections ([28 §9 D6](28-discovery-redesign.md)). The obligation follows the gate, not the phase |
| **AD-16** | Unchanged; Sprint 0 V-3/V-4 verify the degradation path on the real host |
| **AD-19** | **Amended.** Version pinning is required *unless* `reused_cross_project = 1`, where `bkb_id IS NULL` because the row makes no knowledge-referencing claim ([24 §4.2](24-cost-optimization.md)) |
| **AD-21** | Unchanged and reinforced — the agent tier moves to Sprint 7 precisely because it is separable |

---

## 5. Documents that must be updated

### 5.1 Critical — an architectural invariant changes

| Doc | Change | Sprint |
|---|---|---|
| **[03 — Architecture](03-architecture.md)** | Add **AD-25…AD-31**; amend AD-2, AD-10b, AD-19. Add `src/notify/`, `src/net/providers/`, `src/discovery/{feed_parser,watermarks,policy}.py` to §3. Add the **fourth grep fence** (`no hermes import in src/`) to §2. Add a **network provider** row to §8. Update §9 evolution paths (Docker becomes an option, not a plan) | S2, S7 |
| **[05 — Database Plan](05-database-plan.md)** | **Rewrite §7 to the sprint-order chain** ([31 §5](31-execution-plan.md)). Add `discovery_watermarks` DDL, `prescores.stage`, `lead_analysis.reused_cross_project`. Make `dedup_groups.project_id` / `minhash_bands.project_id` **nullable** with FKs deferred to `0007`. Extend §7.1's deferred-FK table. Add retention for `discovery_watermarks`. State that **renumbering unshipped revisions is permitted** and why | S2, S3 |
| **[07 — Scraping Pipeline](07-scraping-pipeline.md)** | §1: *"All traffic via rotating proxy"* → *"via the network policy; egress is per request class"*. **New §2a — RSS endpoints and the Atom schema.** Replace §5's request budget with [28 §4](28-discovery-redesign.md). §7 dedup gains the watermark as layer 0. §8 cache: discovery bypasses `http_cache`; search TTL 60 min | S2 |
| **[08 — Proxy Service](08-proxy-service.md)** | `fail_closed` → the three-value `on_pool_exhausted`. **New §3a — the `NetworkProvider` interface.** §3.4 gains target-acceptance health. §10: `WebsiteFetcher` moves **off** the pool. §3.1: record LRU as shipped; make `exclude=tried` explicit | S2 |
| **[10 — Roadmap](10-implementation-roadmap.md)** | §1 phase table → the **sprint table** ([31 §2](31-execution-plan.md)). **New §1.4 — "what the final review changed"**, in the shape of §1.1/§1.2. §5 gains X1–X8 and the [27 §9](27-architecture-review.md) production gaps. §6 gains five anti-patterns (§8). §10 checklist gains discovery, network-policy and agent-tier sections | S1, then each sprint |
| **[04 — System Design](04-system-design.md)** | §5 `RedditClient` gains `get_feed()`. **New §5a — the discovery state machine** ([28 §3](28-discovery-redesign.md)). **New §12 — the agent seam** (5 tools at S7). §11 observability gains disk, discovery policy, and `stage='agent.%'` separation. **New §9a — the three scores and why each exists** ([27 §8.1](27-architecture-review.md)) | S2, S7 |

### 5.2 Important — a specified behaviour changes

| Doc | Change | Sprint |
|---|---|---|
| [06c](06c-local-first-pipeline.md) | §2 "what never touches AI" gains scheduling, notification rendering, feed parsing, watermark diffing. **§3 gains L0 (scheduler) and L1 (conditional GET)**. §6 holdout extends to Stage-3 triage. §8 worked example re-derived | S2, S3 |
| [06d](06d-ai-budget-and-scale.md) | §2.4 monthly cost → **$0.34** ([30 §5](30-ai-call-inventory.md)) with the agent tier separated. §4 gains the fifth ceiling. §5 gains the [24 §8](24-cost-optimization.md) targets. **Becomes the single source for every cost figure** (C4) | S4, S6 |
| [09](09-dashboard-plan.md) | §3.8 example regenerated from real weights; **the "signal boost" line removed** (C1, C2). §2 IA gains Telegram and `/health` disk. **New: a discovery panel** — per-subreddit interval, rate, watermark age, yield. §4.2 gains `/api/agent/*` | S2, S6, S7 |
| [13](13-phase-03.md) | Maps to **S1**; scheduling deferred to S7; notification hook added | S1 |
| [14](14-phase-04.md) | Maps to **S4**; migration `0007`; **§9.2 code sample replaced** (C5); `WebsiteFetcher` egress is direct | S4 |
| [15](15-phase-05.md) | Maps to **S5**; migration `0008`; collection mechanics moved to S2; gate notifications reference `src/notify/` | S5 |
| [16](16-phase-06.md) | **Split** — collection to S2, local pipeline to S3; migration `0006`; comment ordering by pre-score | S2, S3 |
| [17](17-phase-07.md) | Maps to **S6**; migration `0009`; lazy Tier 2; `reused_cross_project`; AC29 amended; **golden set stated as 40-for-sweep** (C3) | S6 |
| [18](18-phase-08.md) | **Split** — quality to S8, hardening to S9; migration `0010`; **golden set stated as 100-for-gate** (C3) | S8, S9 |
| [21](21-hermes-architecture.md) | **§13 rewritten** — the agent tier adds no tables; the renumbering is withdrawn (AD-29). **§8 rewritten** — systemd, not Docker (AD-30). §12 layout updated. §4 seam reduced to 5 tools at first delivery | S7 |
| [24](24-cost-optimization.md) | §5 and §7 incorporate [30 §5](30-ai-call-inventory.md): platform total **$0.34**. §3 layer table gains L0/L1 | S2, S7 |
| [22](22-hermes-skills.md) | First delivery is **3 skills**, not 13; the rest are a backlog with an entry criterion | S7 |
| [README](README.md) | Index gains 27–32. Execution table → sprints. Efficiency table gains the discovery line. Correct the manual-test count (C6). Add a tenth item: *collection is metadata-first* | S1, S9 |

### 5.3 Minor

| Doc | Change |
|---|---|
| [00](00-current-state.md) | §7 dependency posture: no new runtime dependencies for discovery — Atom parses with `lxml`, already present |
| [02](02-research-findings.md) | §2.1 gains RSS as a fourth access mode with its 2025-06 rate-limit history; §6.2 price table re-verified (Sprint 0 V-2) |
| [06a](06a-ai-service-layer.md) | §1: `suggest_outreach` is preceded by a deterministic template ([30 §3.6](30-ai-call-inventory.md)) |
| [06b](06b-deepseek-optimization.md) | §1: state the OpenRouter 5× vs DeepSeek 50× differential and which the document assumes; §9 config gains the agent block |
| [06e](06e-business-knowledge-base.md) | §2 §19 `outreach_angles` is now a *retrieval target for a template*, not only prose context |
| [06g](06g-explainability-and-quality.md) | §4.4 golden set: 100, with the 40-item precursor named |
| [06i](06i-feedback-and-memory.md) | §4.1 gains the fifth memory class ([23 §5](23-hermes-memory-and-knowledge.md)) |
| [11](11-phase-01.md), [12](12-phase-02.md) | Sprint mapping only; both shipped |
| [19](19-hermes-research.md) | ✅ already corrected this pass — inline-button scope and the M-9/M-10 gaps |
| [23](23-hermes-memory-and-knowledge.md) | §5 retention table drops `agent_events`/`notification_log` (AD-29) |
| [25](25-hermes-roadmap.md), [26](26-documentation-plan.md) | **Supersession header** (§2) |

---

## 6. Diagrams

| Diagram | Change | Sprint |
|---|---|---|
| [03 §2](03-architecture.md) — layer diagram | Add the control plane above presentation (one-way arrow); add `src/notify/`, `src/discovery/`, `src/net/providers/` | S2 |
| [03 §5](03-architecture.md) — run data flow | Replace the scrape block with the six discovery stages; mark notification emissions **$0.00** | S2 |
| [05 §6](05-database-plan.md) — ERD | Add `discovery_watermarks`. **Do not add `agent_events`/`notification_log`** (AD-29) | S2 |
| [06c §1.2](06c-local-first-pipeline.md) — enrichment funnel | Add L0 scheduler and L1 conditional GET above the existing stages | S3 |
| **[07 — new](07-scraping-pipeline.md)** | The discovery stage machine ([28 §3](28-discovery-redesign.md)) | S2 |
| **[08 — new](08-proxy-service.md)** | The provider/policy diagram ([29 §3.1](29-network-and-proxy-strategy.md)) | S2 |
| [09 §2](09-dashboard-plan.md) — IA | Add Telegram as a second surface; add the discovery panel | S2 |
| [21 §8.1](21-hermes-architecture.md) — deployment | **Redraw as systemd + two unix users** (AD-30) | S9 |
| [21 §2](21-hermes-architecture.md) — two-plane | **Unchanged** — the boundary held | — |
| [06 §1](06-ai-pipeline.md) — AI pipeline map | **Unchanged** — visual proof that discovery optimisation did not touch the enrichment funnel | — |
| [04 §9](04-system-design.md) — confidence engine | **Unchanged** — except that [09 §3.8](09-dashboard-plan.md)'s rendering must now match it (C2) | — |

▶ **The three "unchanged" rows are deliberate entries.** A reader comparing before and after should
see at a glance that the AI pipeline, the scoring engine and the plane boundary are untouched by a
review that rewrote collection and deployment.

---

## 7. New documents

| Doc | Purpose | Sprint |
|---|---|---|
| `SPRINT-0-MEASUREMENTS.md` | The sixteen results, dated, with method and raw output. **Closes every ❓ in [27 §10](27-architecture-review.md)** | S0 |
| `testing/sprint-00-testing.md` … `sprint-09-testing.md` | Part A / Part B in the house format, one per sprint | Each |
| `HERMES-SETUP.md` | Install, profile, config walkthrough, Telegram registration, pairing | S7 |
| `HERMES-SEAM.md` | The 5 tools: signature, route, auth, error shapes, `untrusted_content` envelope | S7 |
| `RUNBOOK.md` | Backup, **restore drill**, rollback, secret rotation (five secrets), disk monitoring, proxy expansion, Hermes upgrade, degraded-mode decision tree | S9 |

▶ **Testing-document naming.** Existing files are `testing/phase-NN-testing.md`. New ones are named
by sprint, and the [README](README.md) carries the mapping. Renaming eight existing files to match
would churn every cross-reference in the set to buy naming symmetry — ▶ the mapping table is cheaper
and loses nothing.

---

## 8. New anti-patterns for [10 §6](10-implementation-roadmap.md)

| Anti-pattern | Tempting because | Rule |
|---|---|---|
| **Downloading a post before deciding to reject it** | The listing page has everything | Title, author and timestamp settle most rejections. 190 KB to discover a job advert is the old design's central inefficiency |
| **Treating a short RSS feed as "nothing new"** | It looks the same as an idle poll | It may be watermark overflow. Compare the feed's oldest item against `last_seen_utc` and **raise an error** |
| **Health-checking a proxy against a neutral endpoint and calling it healthy** | ipify returns 200 | A proxy can be reachable and still soft-blocked by the target. Measure **target acceptance** from real traffic |
| **Proxying the customer's own website** | The proxy layer is right there | Ten rotating datacenter IPs hitting a customer's site looks like an attack. That fetch is direct |
| **Inheriting a framework's model-invoking defaults** | They are off the critical path | `title_generation`, `approvals: smart`, memory review and skill auto-creation are four unbudgeted call paths. Audit the effective config (AD-31) |

---

## 9. Update sequence

| Sprint | Documents touched |
|---|---|
| **S0** | **New** `SPRINT-0-MEASUREMENTS.md`. Correct [02 §6.2](02-research-findings.md) prices; record the provider decision |
| **S1** | [10](10-implementation-roadmap.md) §1/§1.4/§5/§6, [13](13-phase-03.md), [README](README.md) |
| **S2** | [03](03-architecture.md), [05](05-database-plan.md), [07](07-scraping-pipeline.md), [08](08-proxy-service.md), [04](04-system-design.md) §5/§5a, [06c](06c-local-first-pipeline.md), [09](09-dashboard-plan.md), [16](16-phase-06.md), [24](24-cost-optimization.md), [00](00-current-state.md), [02](02-research-findings.md); **diagrams** [03 §2](03-architecture.md), [03 §5](03-architecture.md), [05 §6](05-database-plan.md), [07-new](07-scraping-pipeline.md), [08-new](08-proxy-service.md), [09 §2](09-dashboard-plan.md); C6 |
| **S3** | [16](16-phase-06.md), [06c](06c-local-first-pipeline.md) §3/§6/§8, [05](05-database-plan.md); diagram [06c §1.2](06c-local-first-pipeline.md) |
| **S4** | [14](14-phase-04.md) (**C5**), [06d](06d-ai-budget-and-scale.md) (**C4**), [06e](06e-business-knowledge-base.md), [06b](06b-deepseek-optimization.md) |
| **S5** | [15](15-phase-05.md) |
| **S6** | [17](17-phase-07.md) (**C3**), [09 §3.8](09-dashboard-plan.md) (**C1, C2**), [04 §9a](04-system-design.md), [06a](06a-ai-service-layer.md), [06d](06d-ai-budget-and-scale.md) |
| **S7** | [21](21-hermes-architecture.md) §4/§8/§12/§13, [22](22-hermes-skills.md), [23](23-hermes-memory-and-knowledge.md) §5, [24](24-cost-optimization.md), [04 §12](04-system-design.md); **new** `HERMES-SETUP.md`, `HERMES-SEAM.md` |
| **S8** | [18](18-phase-08.md), [06g](06g-explainability-and-quality.md) (**C3**), [06i](06i-feedback-and-memory.md) |
| **S9** | **New** `RUNBOOK.md`; diagram [21 §8.1](21-hermes-architecture.md); [10 §10](10-implementation-roadmap.md) checklist; [README](README.md) final pass |
| **Immediately** | Supersession headers on [25](25-hermes-roadmap.md) and [26](26-documentation-plan.md) — before anyone reads them as current |

---

## 10. Summary

| | Count |
|---|---:|
| Documents created this pass | **6** (27–32) |
| Documents superseded | **2** ([25](25-hermes-roadmap.md), [26](26-documentation-plan.md)) — retained with headers |
| Documents requiring update | **24** |
| — critical | 6 |
| — important | 12 |
| — minor | 10 *(overlapping)* |
| Documented contradictions found and assigned | **6** |
| New architecture decisions | **7** (AD-25…AD-31) |
| Existing decisions amended | **4** (AD-2, AD-10b, AD-19, and AD-1 clarified) |
| Decisions withdrawn | **2** (agent-tier tables; Docker deployment) |
| New documents | **5** + 10 sprint test suites |
| Diagrams changing | **8** |
| Diagrams deliberately unchanged | **3** |
| Migrations added by this review | **1** (`0005_discovery`) |
| Migrations removed by this review | **1** (`0005_agent_tier`, withdrawn) |

**Net migration count: unchanged.** ◐ The review added a discovery table and removed an agent table,
and the chain is still ten revisions with one head — which is a reasonable signal that the changes
were substitutions of better mechanisms rather than accumulation.
