# 26 — Documentation Plan

> ⚠️ **SUPERSEDED by [32 — Documentation Consistency Plan](32-documentation-consistency.md)
> (2026-08-05).**
>
> Most of the update list below survives. **Withdrawn:** every row concerning migration
> `0010_agent_tier` / `0005_agent_tier` and the revision renumbering — the agent tier adds no tables
> ([27 §5](27-architecture-review.md), AD-29). The §2.2 row instructing [14](14-phase-04.md)–[18](18-phase-08.md)
> to renumber their revisions is likewise withdrawn; revisions are authored in **sprint order**
> instead ([31 §5](31-execution-plan.md)).
>
> [32](32-documentation-consistency.md) also adds what this document lacked: a consistency ledger for
> six documented contradictions, seven new architecture decisions (AD-25…AD-31), and the supersession
> policy applied to this document itself.

> **Step 12.** Exactly which documents in `docs/` must change, which become obsolete, which are new,
> which diagrams are affected, and which implementation guides need revision.
>
> **No existing document has been modified.** This document is the proposal; the edits land with the
> phase that makes them true. Editing a phase document before its phase runs produces documentation
> that describes an intention rather than a system, which is the failure mode this whole doc set has
> so far avoided.

---

## 1. What was created in this pass

| Doc | Covers | Brief step |
|---|---|---|
| [19 — Hermes Research](19-hermes-research.md) | 40 topics, evidence-classed, 8 gaps left as gaps | 2 |
| [20 — Current vs. Hermes](20-hermes-vs-current.md) | 31 subsystems, dispositions, risks, effort | 3 |
| [21 — Hermes Architecture](21-hermes-architecture.md) | Redesign, AD-20…AD-24, agent strategy, 4 agent definitions | 4, 5, 6 |
| [22 — Skill Design](22-hermes-skills.md) | 13 skills; 10 of the brief's examples adjudicated out | 7 |
| [23 — Memory & Knowledge](23-hermes-memory-and-knowledge.md) | Allocation rule, fifth memory class, knowledge organisation | 8, 9 |
| [24 — Cost Optimization](24-cost-optimization.md) | Two target definitions, 11 filter layers, 4 new layers, 5th ceiling | 10 |
| [25 — Updated Roadmap](25-hermes-roadmap.md) | Every phase reviewed; H1–H4 added; production path | 11 |
| **26 — Documentation Plan** | This document | 12 |

---

## 2. Documents that MUST be updated

Ordered by how load-bearing the change is. **"When" names the phase that makes the edit true.**

### 2.1 Critical — the change alters an architectural invariant

| Doc | Change | When |
|---|---|---|
| **[03 — Architecture](03-architecture.md)** | **Add AD-20…AD-24** ([21 §1](21-hermes-architecture.md)). **Extend §2's dependency rule with a fourth grep fence**: `grep -rn "import.*hermes" src/` → 0. **Add the control plane to the §2 layer diagram** as a tier *above* presentation, connected only by HTTP. Add `src/notify/` and `src/dashboard/routes_agent.py` to §3. Add a "two containers" row to §9 evolution paths | H1 |
| **[05 — Database Plan](05-database-plan.md)** | **Rewrite the §7 sequence table for the renumbering** ([21 §13.1](21-hermes-architecture.md)): new `0005_agent_tier`; unshipped `0005`–`0009` become `0006`–`0010`. Add `agent_events` + `notification_log` to §5 DDL, the §6 ERD and the §10 retention table. Add `agent_events.project_id` to the §7.1 deferred-FK table. **State in §7 that renumbering *unshipped* revisions is permitted and why** — the rule protects a deployed database, and only `0001`–`0003` are applied | H1 |
| **[06i — Feedback, Memory & Provenance](06i-feedback-and-memory.md)** | **Add the fifth memory class** ([23 §5](23-hermes-memory-and-knowledge.md)) to §4.1, with its lifetime and its "if lost" column. **Add the parallel enforceable rule** to §4.2 — deleting agent memory changes no score, no BKB section, no run outcome. Add the assertion to §8 | H1 |
| **[10 — Implementation Roadmap](10-implementation-roadmap.md)** | **§1 phase table gains H1–H4** in execution order. **New §1.3 — "What the Hermes adoption changed"**, in the same shape as §1.1 and §1.2: what was reversed, what was confirmed, and why the agent-framework rejection in [02b §2](02b-research-2026-07.md) survives in modified form. **§5 gains HR1–HR10** ([20 §5](20-hermes-vs-current.md)). §6 gains four anti-patterns (below). §10 checklist gains an agent-tier section | H1, extended each phase |
| **[04 — System Design](04-system-design.md)** | **New §12 — the agent seam**: the 17 tools, auth, error shapes, the `untrusted_content` envelope. **§11 observability gains** `agent_events`, the webhook ingest path, and `hermes_gateway_alive`. §2.4 job-type table gains nothing — cron *triggers* jobs, it does not add types | H2 |

**The [03](03-architecture.md) edit is the one that matters most.** Its §2 dependency rule and the
three greps beneath it are what have kept this architecture honest through three research passes. A
fourth plane arriving without a fourth fence would be the single most likely way for the boundary in
[21 §1](21-hermes-architecture.md) to erode — not by decision, but by someone importing a convenient
helper.

### 2.2 Important — the change alters a specified behaviour

| Doc | Change | When |
|---|---|---|
| **[13 — Phase 03](13-phase-03.md)** | §2.1 remove per-project scheduling → deferred to H2. §2.2 out-of-scope note. §9 add the notification hook inside the state-transition transaction. §13 add AC16 | Now (before P3) |
| **[15 — Phase 05](15-phase-05.md)** | §7 gate UIs gain the Telegram card. §13 add AC17–AC18. Note that *approving* from Telegram is H2 | Before P5 |
| **[16 — Phase 06](16-phase-06.md)** | §9.2 comment candidates ordered by **pre-score**, not `intent_score`. §13 add AC23 | Before P6 |
| **[17 — Phase 07](17-phase-07.md)** | §2.1 add cross-project negative-result reuse and label-reason rule proposals. **§5 add `lead_analysis.reused_cross_project`** and the `bkb_id IS NULL` rule ([24 §4.2](24-cost-optimization.md)). **§13 AC29 amended** — pinning is required *unless* `reused_cross_project = 1`. §11 add the reuse risk. §13 add AC32–AC34 | Before P7 |
| **[14](14-phase-04.md), [15](15-phase-05.md), [16](16-phase-06.md), [17](17-phase-07.md), [18](18-phase-08.md)** | **Revision numbers only** — `0005`→`0006`, `0006`→`0007`, `0007`→`0008`, `0008`→`0009`, `0009`→`0010` (§2.1 [05](05-database-plan.md) row). Content unchanged; §5 headings, §13 AC references and the intra-revision ordering notes all carry the number | H1 |
| **[18 — Phase 08](18-phase-08.md)** | **Split**: §9.5 security review and the deployment/runbook items move to H4. Retention gains the fifth class. `/health/quality` gains an Agent tier row. §13 add AC34–AC35, remove AC13 | Before P8 |
| **[09 — Dashboard Plan](09-dashboard-plan.md)** | §2 IA gains `/health/agent` (or an Agent band on `/health/ai`). §4.2 gains the `/api/agent/*` table. **New §8 — Telegram as a surface**, stating the division: Telegram carries decisions, the dashboard carries deliberation ([21 §7.2](21-hermes-architecture.md)) | H2 |
| **[06d — AI Budget & Scale](06d-ai-budget-and-scale.md)** | **§2 gains an agent-tier row.** §2.4 monthly cost becomes **$0.59, not $0.16** — and says plainly that Hermes multiplies spend ~3.7×. §4 gains the fifth ceiling. §5 gains C1–C13 from [24 §8](24-cost-optimization.md) | H1 |
| **[06c — Local-First Pipeline](06c-local-first-pipeline.md)** | §2 "what never touches AI" gains **notification rendering** and **event classification**. §3.2 gate-reason table gains the [24 §4](24-cost-optimization.md) layers. §8 worked example re-derived with the new layers | H2, P6 |
| **[README](README.md)** | Index gains 19–26. **The nine-things list gains a tenth**: *the agent tier is bounded, separately funded, and cannot silence its own alerts*. The efficiency table gains an agent-tier line so the headline number is not quoted without it | H1 |

### 2.3 Minor — factual corrections and additions

| Doc | Change | When |
|---|---|---|
| [06a](06a-ai-service-layer.md) | §1 note: `suggest_outreach()` is now also reached via the seam, still lazily, still cached, still `AIService`-only | H3 |
| [06b](06b-deepseek-optimization.md) | §9 config gains the agent-tier block. Note that **Hermes' `prompt_caching` is Anthropic-shaped and does not apply to DeepSeek** ([19 §26.2](19-hermes-research.md)) | H1 |
| [06e](06e-business-knowledge-base.md) | §10 gains a fifth advantage: the BKB is conversationally queryable without duplication ([23 §4.2](23-hermes-memory-and-knowledge.md)) | H3 |
| [06g](06g-explainability-and-quality.md) | §5 cadence table gains agent-tier metrics. §7 red-metric responses gain agent budget exhaustion | H3 |
| [06h](06h-knowledge-lifecycle.md) | §4.3 restate: the agent proposes nothing. The BKB write path is unchanged and the seam is read-only | H2 |
| [08](08-proxy-service.md) | §10 reuse table gains a row: the agent tier does **not** use the proxy pool — it talks to localhost only | H2 |
| [01](01-product-vision.md) | §5 non-goals: **amend** the reply-drafting line to *"drafting for a human to send is in scope; posting, commenting and DMing are permanent non-goals"*. §2 flow gains the Telegram gate path | H3 |
| [00](00-current-state.md) | §7 dependency posture: no new Python packages for the platform; Hermes is a separate container, not a dependency | H1 |

**The [01](01-product-vision.md) amendment is the only place in the doc set where a stated non-goal
changes**, and it must be written precisely. The document currently says *"Posting, commenting, or
DMing on Reddit"* is not built, and [02a §7](02a-competitor-analysis.md) says *"Reply drafting — the
lead's `suggested_outreach_angle` is a hint for a human, not a draft to send."*

Your decision moves drafting in and leaves sending out. The amended text must make the distinction
structural rather than aspirational: **the platform has no Reddit write path, so a draft cannot
become a post.** Anything softer invites the line to be crossed later by someone who reads it as a
preference.

---

## 3. Documents that become obsolete

**None.** Every document in `docs/` remains accurate for the data plane, which Hermes does not
change.

Three come close and are worth naming, because "close to obsolete" is where silent rot begins:

| Doc | Why it survives |
|---|---|
| [02b §2](02b-research-2026-07.md) — *"Reject agent frameworks"* | **Survives in modified form, and the modification must be written into the document rather than left to the reader.** Its reasoning — deterministic orchestration beats model-driven orchestration when the steps are known — is still correct and is *why* [21 §1](21-hermes-architecture.md) keeps Hermes out of the pipeline. What changed is scope: the rejection now covers *orchestration*, not *the operator surface*. Add a dated note pointing to [21 §1](21-hermes-architecture.md) |
| [02c §12](02c-research-final-review.md) — *"Rejected: agent frameworks … all still rejected"* | Same treatment, same pointer |
| [13 §2.1](13-phase-03.md) — scheduler in Phase 3 | Superseded by H2, not obsolete: the `maintenance` job stays in Phase 3 |

> **A rejection that is later partly reversed must be edited at its source, with the reversal and its
> reason stated in place.** Leaving it to be discovered as a contradiction is how a documentation set
> stops being trusted — and this one has, three times, corrected its own reversals at source rather
> than annotating them ([02b closing table](02b-research-2026-07.md),
> [10 §1.1](10-implementation-roadmap.md)). The same standard applies here.

---

## 4. New documents to create

| Doc | Purpose | When |
|---|---|---|
| `HERMES-SETUP.md` | Install, profile creation, `config.yaml` walkthrough, Telegram bot registration, pairing, verification. The operator-facing counterpart to this design set | H1 |
| `HERMES-MEASUREMENTS.md` | The ten M-1…M-10 results ([25 §4.1](25-hermes-roadmap.md)), dated, with the method for each. **This is the document that closes the research gaps in [19 §41](19-hermes-research.md)** — including the two go/no-gos, M-5 (does a notification cost tokens?) and M-9 (is `hermes send` reachable across a container boundary?) | H1 |
| `HERMES-SEAM.md` | The 17 tools: signature, route, auth, error shapes, `untrusted_content` envelope. The contract both planes are tested against | H2 |
| `RUNBOOK.md` | Already planned in Phase 8; now covers two containers: backup/restore, rollback, key rotation (both keys), proxy expansion, Hermes upgrade, gateway recovery, governor tuning | H4 |
| `testing/phase-h1-testing.md` … `phase-h4-testing.md` | Part A / Part B in the established house format | Each H phase |

**`HERMES-MEASUREMENTS.md` is the most valuable of the five**, and it is the only one whose absence
would leave a real defect in this design set. [19](19-hermes-research.md) is honest about eight gaps;
[24 §5.2](24-cost-optimization.md) makes an inference about toolset pruning saving 30–60% of
system-prompt tokens; [22 §8](22-hermes-skills.md) defers a Level-0 ceiling to a measurement. Those
are promissory notes, and this document is where they are paid.

---

## 5. Diagrams to change

| Diagram | Change | When |
|---|---|---|
| **[03 §2](03-architecture.md) — layer diagram** | Add the control plane as a box *above* presentation, connected by a single labelled HTTP arrow. **The arrow points one way.** Add `src/notify/` to infrastructure | H1 |
| **[03 §5](03-architecture.md) — data flow of one run** | Add the notification emissions at `gate.reached` and `run.complete`, marked **$0.00**; add the Telegram approval path re-entering at `approve_subreddits` | H2 |
| **[05 §6](05-database-plan.md) — ERD** | Add `agent_events` (→ `runs`, `projects`) and `notification_log` (→ `runs`) | H1 |
| **[06 §1](06-ai-pipeline.md) — pipeline map** | No change. **This is the point** — the enrichment pipeline is untouched by Hermes, and the diagram staying identical is the visual proof of [AD-21](21-hermes-architecture.md) | — |
| **[06c §1.2](06c-local-first-pipeline.md) — Reddit enrichment funnel** | Add the [24 §4](24-cost-optimization.md) layers to the local block; annotate every stage **$0.00** | P6 |
| **[04 §9](04-system-design.md) / [06a §10](06a-ai-service-layer.md) — hybrid confidence** | No change. The AI still never produces the score | — |
| **[09 §2](09-dashboard-plan.md) — information architecture** | Add Telegram as a second surface with its division of labour | H2 |
| **New — [21 §2](21-hermes-architecture.md) two-plane diagram** | Becomes the canonical system diagram; [03 §2](03-architecture.md) references it | H1 |
| **New — [21 §8.1](21-hermes-architecture.md) deployment topology** | Two containers, volumes, Caddy. Referenced by `RUNBOOK.md` | H4 |

**The two "no change" rows are deliberate entries, not omissions.** A reader comparing before and
after should be able to see at a glance that the enrichment pipeline and the scoring engine are
untouched. Diagrams that do not change are evidence about the boundary.

---

## 6. Implementation guides needing revision

| Guide | Revision |
|---|---|
| [11 — Phase 01](11-phase-01.md) | **None.** Shipped and unchanged |
| [12 — Phase 02](12-phase-02.md) | **None.** Shipped and unchanged |
| [13 — Phase 03](13-phase-03.md) | §2.1, §2.2, §9, §13 (§2.2 above) |
| [14 — Phase 04](14-phase-04.md) | **Revision number only** (`0005`→`0006`). No content change |
| [15 — Phase 05](15-phase-05.md) | §7, §13 |
| [16 — Phase 06](16-phase-06.md) | §9.2, §13 |
| [17 — Phase 07](17-phase-07.md) | §2.1, §11, §13 |
| [18 — Phase 08](18-phase-08.md) | Split; §9.5 and deployment move to H4 |
| **New** | `19-phase-h1.md` … `22-phase-h4.md`? **No** — see §6.1 |

### 6.1 A numbering decision, stated so it is not re-litigated

The existing convention is `1N-phase-NN.md` (11–18) for implementation guides and `0N`/`0Nx` for
design documents. Documents 19–26 created in this pass are **design documents**, and they occupy the
next free numbers.

Creating `27-phase-h1.md` … `30-phase-h4.md` would collide conceptually with that: the reader would
have to know that 11–18 and 27–30 are the same kind of thing while 19–26 are not.

**→ Decision: the H-phase implementation guides are `phase-h1.md` … `phase-h4.md`, unnumbered**, and
the [README](README.md) execution table lists them in execution order alongside 11–18. Numbers order
documents; they do not classify them, and a numbering scheme that has to encode two orthogonal facts
will encode neither reliably.

---

## 7. README restructure

The [README](README.md) is the entry point and currently promises *"one Python process, one SQLite
file, one linear migration chain, and one AI boundary."* Three of those four remain true. The fourth
does not, and the sentence must change rather than be quietly left standing.

Proposed replacement for the closing paragraph:

> *The architecture is **two processes on one host**, one SQLite file, one linear migration chain,
> and **two AI boundaries — one for the pipeline, one for the operator agent, separately funded and
> separately capped.** Every piece of machinery beyond that had to argue for itself, and the record
> of what was rejected is in [02b](02b-research-2026-07.md), [02c](02c-research-final-review.md), and
> [20 §3.6](20-hermes-vs-current.md).*

Additional README changes:

| Section | Change |
|---|---|
| Index | Add a **Control plane** block: 19–26 |
| Execution table | Add H1–H4 in execution order ([25 §2](25-hermes-roadmap.md)) |
| "The efficiency architecture in one table" | Add an agent-tier line. **The 95%/98% headline must not be quoted without it** |
| "The nine things that matter most" | Add a tenth: *the agent tier is bounded, separately funded, and structurally unable to silence its own alerts* |
| Deliverable map | Add a Hermes section mapping the brief's twelve steps to 19–26 |
| "Empirical verification performed" | Add the H1 measurements once `HERMES-MEASUREMENTS.md` exists |

---

## 8. New anti-patterns for [10 §6](10-implementation-roadmap.md)

Written in the existing table's voice, because the value of that table is that it names the tempting
mistake alongside the rule.

| Anti-pattern | Tempting because | Rule |
|---|---|---|
| **Letting Hermes call a model for pipeline work** | *"The agent is right there and it already has a key"* | Enrichment goes through `AIService`. A Hermes turn cannot be prefix-stable, cannot be batched at B=8, and is not covered by the four pre-call ceilings |
| **Putting business knowledge in `MEMORY.md`** | *"The agent should just know our pain points"* | 2,200 characters, no versioning, no evidence, no `origin`. The BKB is reached through a tool |
| **Making a notification a skill** | *"Then it could word things nicely"* | `hermes send` costs $0.00; a skill costs a turn. Thirty free messages a month become thirty paid ones |
| **Wrapping a deterministic function in a skill** | *"It's the same logic, and it's more flexible"* | Dedup is a hash, filtering is set membership, scoring is arithmetic. A model in front of any of them forfeits reproducibility and costs money to be worse |
| **Adding an "approve all" button to Telegram** | *"The operator keeps asking for it"* | The gate exists because AI subreddit proposals are occasionally badly wrong. One-tap accept-all restores exactly the failure the gate prevents |
| **Importing anything from Hermes into `src/`** | *"Just this one helper"* | The dependency inverts and the data plane becomes reachable from the control plane. Grep-enforced |
| **Enabling micro-compaction** | *"Long sessions are getting expensive"* | It *"invalidates cached prefix tokens every turn"*. Compress instead, or reset the session |
| **Trusting an agent-quoted number** | *"It just told me the miss rate is 3%"* | Every figure comes from a tool result in the same turn. `SOUL.md` forbids recall and estimation; a quoted number without a tool call is a defect |

---

## 9. Update sequence

Documentation lands *with* the phase that makes it true, never before.

| Phase | Documents touched |
|---|---|
| **Before P3** | [13](13-phase-03.md) §2.1/§2.2/§9/§13 |
| **H1** | [03](03-architecture.md), [05](05-database-plan.md), [06i](06i-feedback-and-memory.md), [06d](06d-ai-budget-and-scale.md), [06b](06b-deepseek-optimization.md), [00](00-current-state.md), [10](10-implementation-roadmap.md) §1/§1.3/§5/§6/§10, [README](README.md); **new** `HERMES-SETUP.md`, `HERMES-MEASUREMENTS.md`, `testing/phase-h1-testing.md`; diagrams [03 §2](03-architecture.md), [05 §6](05-database-plan.md), [21 §2](21-hermes-architecture.md) |
| **Before P5** | [15](15-phase-05.md) §7/§13 |
| **H2** | [04](04-system-design.md) §11/new §12, [09](09-dashboard-plan.md) §2/§4.2/new §8, [06c](06c-local-first-pipeline.md) §2, [06h](06h-knowledge-lifecycle.md) §4.3, [08](08-proxy-service.md) §10, [02b §2](02b-research-2026-07.md) + [02c §12](02c-research-final-review.md) dated notes; **new** `HERMES-SEAM.md`, `testing/phase-h2-testing.md`; diagram [03 §5](03-architecture.md), [09 §2](09-dashboard-plan.md) |
| **Before P6** | [16](16-phase-06.md) §9.2/§13; diagram [06c §1.2](06c-local-first-pipeline.md) |
| **Before P7** | [17](17-phase-07.md) §2.1/§11/§13 |
| **H3** | [06a](06a-ai-service-layer.md) §1, [06e](06e-business-knowledge-base.md) §10, [06g](06g-explainability-and-quality.md) §5/§7, [01](01-product-vision.md) §2/§5; **new** `testing/phase-h3-testing.md` |
| **Before P8** | [18](18-phase-08.md) split |
| **H4** | **New** `RUNBOOK.md`, `testing/phase-h4-testing.md`; diagram [21 §8.1](21-hermes-architecture.md); [10 §10](10-implementation-roadmap.md) checklist completed; [README](README.md) final pass |

---

## 10. Summary

| | Count |
|---|---:|
| Documents created in this pass | **8** (19–26) |
| Existing documents requiring update | **19** |
| — critical (architectural invariant) | 5 |
| — important (specified behaviour) | 9 |
| — minor (factual) | 8 *(some overlap)* |
| Documents becoming obsolete | **0** |
| Rejections needing a dated in-place amendment | **2** ([02b §2](02b-research-2026-07.md), [02c §12](02c-research-final-review.md)) |
| Non-goals needing amendment | **1** ([01 §5](01-product-vision.md) — drafting in, sending out) |
| New documents | **9** (4 guides, 4 test suites, `RUNBOOK.md`) — plus `HERMES-SETUP.md` and `HERMES-MEASUREMENTS.md` |
| Diagrams changing | **6** |
| Diagrams deliberately unchanged | **2** — and that is the evidence the boundary held |
| Implementation guides revised | **5** of 8 |
| Implementation guides untouched | **3** (P1, P2, P4) |

**Zero obsolete documents is the finding worth ending on.** A framework adoption that invalidated a
third of the design set would have been a rewrite wearing an integration's clothes. Nineteen updates,
two amendments and eight new documents — against forty-four existing files, none discarded — is what
it looks like when a new tier attaches at the edges of an architecture that was drawn correctly the
first time.
