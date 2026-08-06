# 30 — AI Call Inventory

> **Part 8.** Every model-invoking path in the platform, re-evaluated: can it be made deterministic,
> cached, replaced, delayed, or skipped?
>
> Evidence labels: ✅ Verified · ◐ Inferred · ▶ Recommendation · ❓ Unknown.

---

## 0. The headline finding

Seventeen model-invoking paths exist. **Twelve were budgeted; five were not.**

The five unbudgeted paths are all Hermes defaults ([19 §"Auxiliary Models"](19-hermes-research.md),
[19 §7](19-hermes-research.md), [19 §4](19-hermes-research.md)), and one of them — the memory
background review — ◐ may fire **once per turn**, which would roughly double the agent tier's call
count against the [21 §6.5](21-hermes-architecture.md) estimate.

> **Three configuration lines remove most of it, and the total available saving is ~42% of projected
> platform AI spend.**

---

## 1. The complete inventory

| # | Call | Tier | Frequency | Budgeted? |
|---:|---|---|---|---|
| 1 | `analyze_business` — the 23-section BKB | Pipeline | 1 per site version | ✅ |
| 2 | `regenerate_section` | Pipeline | On demand | ✅ |
| 3 | `enrich_batch` — **Tier 1**, B=8 | Pipeline | **The volume path** | ✅ |
| 4 | Holdout audit | Pipeline | Folded into #3 | ✅ |
| 5 | **Tier 2** deep enrichment, un-batched | Pipeline | ≤25/run | ✅ |
| 6 | `suggest_outreach` | Pipeline | Lazy, per lead | ✅ |
| 7 | Golden-set replay | Pipeline | Per prompt/model change | ✅ |
| 8 | `test_connection` | Pipeline | Manual | ✅ |
| 9 | Operator conversation turn | Agent | ~180/mo | ✅ |
| 10 | Cron report turn | Agent | ~18/mo | ✅ |
| 11 | Delegated research turn | Agent | ~70/mo | ✅ |
| 12 | Outreach request turn | Agent | ~20/mo | ✅ |
| **13** | **`auxiliary.title_generation`** | Agent | **1 per session** | ❌ |
| **14** | **`auxiliary.compression`** | Agent | At 50% context | ❌ |
| **15** | **`approvals: smart` risk assessor** | Agent | Per risky command | ❌ |
| **16** | **Memory background review** | Agent | ❓ **per turn** | ❌ |
| **17** | **`skill_manage` auto-creation** | Agent | After complex tasks | ❌ |

---

## 2. The five unbudgeted paths

### 2.1 #13 — `auxiliary.title_generation` ✅

```yaml
auxiliary:
  title_generation:
    enabled: true        # ← DEFAULT
    language: ""
    timeout: 30
```

**Purpose:** generate a human-readable session title.
**Fires:** once per session. With `session_reset: {mode: idle, idle_minutes: 1440}` and a fresh
session per cron job, ◐ that is ~50 sessions/month.
**Value to us:** none. Sessions are identified by `run_id` and chat id, and no UI displays a session
title.

| | |
|---|---|
| Cacheable? | No |
| Replaceable? | **Yes — trivially.** A title is `f"{platform}:{chat}:{date}"` |
| Delayable? | Irrelevant |
| **Skippable?** | **✅ Yes. `enabled: false`** |
| ◐ Saving | **−50 calls/month**, ~$0.01 |

### 2.2 #14 — `auxiliary.compression` ✅

**Purpose:** summarise conversation history at 50% of the context limit.
**Fires:** rarely, given single-purpose turns — but when it fires it is a *large* call, summarising
the whole history.

| | |
|---|---|
| Cacheable? | No |
| Replaceable? | Partially — a session reset discards instead of summarising |
| Delayable? | Yes, by raising `threshold` |
| Skippable? | **No — keep it.** ▶ It is the safety valve that prevents a runaway session hitting the context limit |
| ▶ Action | Keep at `threshold: 0.50`. **Pin the compression model to v4-flash** so a fallback chain cannot silently route a large summarisation call to a costlier model |

### 2.3 #15 — `approvals: smart` ✅

> "**smart** (default): An auxiliary LLM assesses risk; low-risk commands auto-approve, dangerous ones
> auto-deny, uncertain cases escalate."

**Fires:** before a risky terminal command. ◐ Moot today because [AD-23](21-hermes-architecture.md)
disables the terminal toolset — but the default remains configured, so re-enabling any tool would
silently reintroduce a model call per invocation.

| | |
|---|---|
| **Skippable?** | **✅ `approvals: mode: off`** — there are no commands to approve |
| ▶ Note | Set it explicitly rather than relying on the toolset being disabled. Two guards, one of which is a config line |

### 2.4 #16 — Memory background review ✅ — **the one that matters**

> "**Background review:** The system includes a self-improvement review running after turns that can
> automatically update memory, controlled by `display.memory_notifications` settings."

❓ **The documentation does not state the frequency.** "After turns" reads as *every* turn.

◐ If it is per-turn, the agent tier's call count is **~2× the [21 §6.5](21-hermes-architecture.md)
estimate** — 288 budgeted turns become ~576 actual calls, and the ~$0.43/month becomes ~$0.80.

| | |
|---|---|
| Purpose | Decide whether anything from the turn belongs in `MEMORY.md` |
| Cacheable? | No |
| Replaceable? | **Yes.** The operator can say *"remember X"*, and the `memory` tool is directly callable |
| Delayable? | ▶ **Yes, and this is the right answer** — a nightly review rather than a per-turn one |
| Skippable? | ◐ Probably, via `memory.write_approval: true` + `display.memory_notifications` |
| ▶ Action | **Sprint 0 measures the frequency (M-11).** If per-turn, disable it. [23 §3.1](23-hermes-memory-and-knowledge.md) budgets ≤1,200 characters of memory that changes perhaps weekly — paying a model call per turn to maintain it is the single worst trade in the design |
| ◐ Saving | **Up to −288 calls/month, ~−$0.20** — potentially 45% of the agent tier |

### 2.5 #17 — `skill_manage` auto-creation ✅

> "After completing a complex task (5+ tool calls) successfully… the agent automatically creates
> skills."

[20 §3.3](20-hermes-vs-current.md) already sets `skills.write_approval: true`, so nothing is
*applied* without review. **But the deciding turn still costs tokens**, and the skill-writing turn is
long — it authors a whole `SKILL.md`.

| | |
|---|---|
| Skippable? | ◐ Largely, by keeping tasks under the 5-tool-call trigger |
| ▶ Action | Keep `write_approval: true`; ◐ our turns are 1–3 tool calls, so the trigger should rarely fire. **Measure in Sprint 0 (M-12)**; if it fires anyway, the skill set is authored by us and auto-creation can be disabled outright |

### 2.6 The general lesson ▶

All five are *framework defaults*, not decisions anyone made. A framework built for open-ended
assistant work optimises for pleasantness — a nice session title, memory that maintains itself,
skills that appear when useful. Every one of those is a model call, and none appears in a budget
because none appears in the code we wrote.

▶ **Sprint 0 must diff the effective Hermes config against its documented defaults and enumerate
every model-invoking path found**, not just the ones the design intended to use. This is a general
practice for adopting any agent framework under a metered budget.

---

## 2.7 The corrected configuration

```yaml
# ~/.hermes/config.yaml — the AI-cost-relevant block
model:
  default: deepseek-v4-flash        # NOT v4-pro (the DeepSeek guide's default) — D30
  provider: deepseek

auxiliary:
  title_generation:
    enabled: false                  # #13 — no consumer
  compression:
    provider: deepseek              # #14 — pinned; no fallback to a costlier model
    model: deepseek-v4-flash

compression:
  enabled: true
  threshold: 0.50                   # safety valve only
  micro_compact: false              # invalidates prefix cache every turn

approvals:
  mode: off                         # #15 — no terminal, nothing to approve

memory:
  write_approval: true              # #16/#17 — staged, reviewable
  memory_enabled: true

skills:
  write_approval: true              # #17

agent:
  max_turns: 12                     # NOT the default 500 — see §5
  reasoning_effort: low             # our tasks are retrieval and narration
  disabled_toolsets: [terminal, file, browser, code, web, media, x_search, image_gen, tts, voice]
```

▶ **`max_turns: 12` is the most important line.** The default of 500 means a looping agent can spend
until a context limit stops it. Our longest legitimate task — `run-diagnosis` — is 3 turns. Twelve is
four times the worst real case and bounds a runaway to roughly $0.02 instead of $0.80.

---

## 3. The twelve budgeted calls, re-evaluated

### 3.1 `analyze_business` — the BKB

| | |
|---|---|
| **Purpose** | Website text + local signals → 23 typed BKB sections |
| **Input** | ≤40 KB cleaned text + locally extracted signals (competitors, pricing, tech, schema.org) |
| **Output** | ~7,000 tokens of validated JSON |
| **Cacheable?** | ✅ **Already, twice** — L1 fingerprint (7 d) and L2 profile cache (permanent) |
| **Replaceable?** | ❌ No. This is genuine reasoning over prose |
| **Delayable?** | ❌ Everything downstream reads it |
| **Skippable?** | ❌ |
| ▶ Opportunity | ◐ Sections 21–22 (`seo_entities`, `geo_entities`) are largely *extractable* — headings, schema.org, nav taxonomy. **But splitting them out would cost a second call.** Keep consolidated. **No change** |

### 3.2 `regenerate_section`

| | |
|---|---|
| **Purpose** | Regenerate one BKB section |
| **Cacheable?** | ✅ On `(section, context_hash, prompt_version)` |
| **Delayable?** | ✅ Operator-initiated |
| **Skippable?** | ✅ Entirely optional |
| ▶ Opportunity | **Defer the UI to a later sprint.** The capability must exist for [06 §3.4](06-ai-pipeline.md)'s per-section-failure story, but a *manual regenerate button* can wait. **Saving: 0 runtime calls; removes scope** |

### 3.3 `enrich_batch` — Tier 1, the volume path

| | |
|---|---|
| **Purpose** | 8 items → 8 `LeadAnalysis` objects: categoricals, slugs, evidence spans |
| **Input** | Frozen ~3,500-token prefix + 8 × (title + truncated body + comment digest) |
| **Output** | ~250 tokens/item |
| **Cacheable?** | ✅ **Four ways** — response cache, content-hash dedup, dedup-group fan-out, incremental `already_analyzed` |
| **Replaceable?** | ❌ **No, and this is the boundary.** Everything replaceable was already replaced: keyword matching, competitor resolution, recency, engagement, dedup, and the final score are all deterministic. What remains is *reading a post and deciding what kind of thing it is* |
| **Delayable?** | ✅ Already — enrichment runs after scraping and is off the user's critical path |
| **Skippable?** | ✅ Per item, by the adaptive gate — but **the gate is not a cost dial** ([C1](24-cost-optimization.md)) |
| ▶ Opportunity | **None that does not cost quality.** ◐ This call is the irreducible core |

### 3.4 Holdout audit

| | |
|---|---|
| **Cacheable?** | ✅ Same mechanisms |
| **Skippable?** | ❌ **Never.** It is the only evidence that filtering is honest ([AD-10b](03-architecture.md)) |
| ▶ Opportunity | ▶ **Expand it, at a small cost.** [28 §9 D6](28-discovery-redesign.md) adds a *metadata-triage* rejection stage; a new gate inherits the obligation to be audited. **+1 call/run** |

### 3.5 Tier 2 deep enrichment

| | |
|---|---|
| **Purpose** | Un-batched, full-context analysis of leads ≥80 |
| **Cacheable?** | ✅ On `(content_hash, prompt_version)` |
| **Replaceable?** | ◐ Partially — it enriches *presentation*, never the score ([06i §3.4](06i-feedback-and-memory.md)) |
| **Delayable?** | ✅ **Yes — to the moment the operator opens the lead** |
| **Skippable?** | ✅ Entirely |
| ▶ **Opportunity** | ▶ **Ship it lazy, not eager.** The current design escalates automatically at `confidence ≥ 80`, capped at 25/run. But most leads are never opened — [06a §1](06a-ai-service-layer.md) makes exactly this argument for `suggest_outreach`: *"it costs nothing for the 95% of leads nobody opens."* The same reasoning applies and was not applied. **Saving: ~25 calls/run → ~2, ≈ −$0.02/run** |

### 3.6 `suggest_outreach`

| | |
|---|---|
| **Purpose** | A draft outreach message for one lead |
| **Input** | Lead + analysis + BKB `outreach_angles` |
| **Cacheable?** | ✅ Permanently |
| **Delayable?** | ✅ Already lazy |
| **Replaceable?** | ▶ **Partially — and this is the best deterministic-replacement candidate in the inventory** |

▶ BKB section 19 already stores `outreach_angles` **per (persona × pain)**
([06e §2](06e-business-knowledge-base.md)), and [06g §3](06g-explainability-and-quality.md) already
describes the lead detail pulling it *"by `(persona × pain)` — a retrieval, not a generation."*

So a **deterministic first draft** is available at $0.00:

```
angle   = bkb.outreach_angles[(lead.persona_slug, lead.pain_point_slug)]
evidence= lead.evidence_quote                      # verbatim, already validated
draft   = template.render(angle=angle, evidence=evidence, subreddit=lead.subreddit)
```

▶ **Recommendation: render the template first; call the model only when the operator asks to improve
it.** ◐ Expected effect: the model runs on perhaps a quarter of draft requests. **Saving ≈ −15
calls/month, ~−$0.02** — and it makes the common path instant.

**The honest trade-off:** a template draft is more generic than a generated one. It is also
reproducible, free, and traceable to a BKB section — and since a human edits it before sending
regardless, genericness costs less here than anywhere else in the system.

### 3.7 Golden-set replay

| | |
|---|---|
| **Skippable?** | ❌ **Never.** It is the blocking release gate ([06g §5](06g-explainability-and-quality.md)) |
| **Delayable?** | ✅ Runs on prompt/model change, not per run |
| ▶ Opportunity | ▶ Cache golden results per `(prompt_version, model, batch_size)` so a re-run of an unchanged pair is free. **Saving: ~13 calls per redundant execution** |

### 3.8 `test_connection`

1-token completion, ~$0.0000005, manual. **No change.**

### 3.9 Agent turns #9–#12

Covered in [24 §5.2](24-cost-optimization.md). The material additions from this review:

| ▶ Change | Effect |
|---|---|
| `max_turns: 12` | Bounds a runaway from ~$0.80 to ~$0.02 |
| `reasoning_effort: low` | ◐ Retrieval and narration do not need high effort; output tokens fall |
| Ship 5 seam tools, not 17 | ◐ Fewer tool schemas per turn — the dominant fixed cost ([19 §3](19-hermes-research.md), L7) |
| Ship 3 skills, not 13 | Level-0 metadata is paid every turn ([19 §6](19-hermes-research.md)) |

---

## 4. What was already made deterministic — the precedent

▶ Worth recording, because it is the strongest evidence that the remaining calls are irreducible.
Each of these *was* a model call in an earlier draft:

| Task | Was | Now | Saving |
|---|---|---|---|
| Keyword generation per subreddit | 12 calls | **Set intersection** of the keyword pool with the subreddit's description vocabulary ([06 §3.3](06-ai-pipeline.md)) | **−12 calls/project** |
| Six staged generation calls | 6 calls | **1 consolidated call** | **−5 calls/project** |
| `summarize_opportunity` | 1 call/lead | A **field** of `LeadAnalysis` | **−1 call/lead** |
| The confidence score | 1 call/lead | **Weighted arithmetic** ([AD-11](03-architecture.md)) | −1 call/lead + reproducibility |
| `confidence_reasoning` | Would have been generated | **Rendered from stored components** ([AD-15](03-architecture.md)) | −1 call/lead |
| Competitor detection | Implicit in the prompt | **4-tier alias resolution** ([06e §4](06e-business-knowledge-base.md)) | Removes work from every prompt |
| Pattern discovery | Would have been clustering | **A nightly `GROUP BY`** ([06h §6](06h-knowledge-lifecycle.md)) | **−100% of an analytics subsystem** |
| Subreddit ranking | Could have been a model | **A weighted formula** ([15 §9.3](15-phase-05.md)) | −1 call/run |
| Admission count | Could have been a model | **Kneedle + floor + clamps** ([06f](06f-adaptive-budget.md)) | −1 call/run |

◐ **Nine deterministic replacements have already been made.** The four remaining candidates found by
this review (§2.1, §2.4, §3.5, §3.6) are smaller because the large ones are done — which is the
expected shape of a system that took the local-first principle seriously from the start.

---

## 5. Savings summary

| # | Change | Class | ◐ Calls/month | ◐ $/month |
|---|---|---|---:|---:|
| 1 | `title_generation: false` | Config | **−50** | −$0.010 |
| 2 | Memory background review disabled *(if per-turn — M-11)* | Config | **−288** | **−$0.200** |
| 3 | `approvals: off` | Config | −0 | −$0.000 |
| 4 | `max_turns: 12` | Config | 0 expected; bounds the tail | risk only |
| 5 | Deterministic outreach template first | Code | −15 | −$0.020 |
| 6 | Tier 2 lazy instead of eager | Code | −23/run ≈ **−23** | −$0.020 |
| 7 | Golden-set result caching | Code | −13 per redundant run | −$0.014 |
| 8 | 5 tools / 3 skills at first delivery | Scope | 0 calls; ◐ **−30–50% tokens per turn** | −$0.060 |
| 9 | **Stage-3 holdout audit** (D6) | Code | **+30** | **+$0.030** |
| | **Net** | | **≈ −379** | **≈ −$0.294** |

| | Before | After |
|---|---:|---:|
| Platform AI spend/month ([24 §7](24-cost-optimization.md)) | $0.59 | **≈ $0.34** ◐ |
| Of which pipeline | $0.16 | $0.12 |
| Of which agent tier | $0.43 | $0.22 |
| **Reduction** | — | **≈ 42%** |

**Item 9 is an increase, and it is the most important line in the table.** [28](28-discovery-redesign.md)
moves a rejection decision earlier — to title-and-snippet triage, before a body is ever fetched. A
new gate that is not audited is exactly what [AD-10b](03-architecture.md) forbids: *"a gate that
silently discards a good lead is worse than no gate."* Thirty extra calls a month, at three cents, is
the price of knowing the redesign did not cost quality. ▶ Any version of this plan that drops item 9
to improve the headline number should be rejected.

---

## 6. Deterministic-replacement candidates rejected ▶

Stated so they are not re-proposed.

| Candidate | Why not |
|---|---|
| Replace `enrich_batch` with a classifier | Needs labelled training data we do not have; forfeits explainability and closed-set slug grounding; [02c §4](02c-research-final-review.md)'s arithmetic against learned rankers applies unchanged |
| Replace intent staging with regex | Tried implicitly by every competitor. *"we're actively looking to replace Segment this quarter"* and *"we use Segment"* differ by intent, not by vocabulary |
| Skip the BKB and template the ICP | The BKB **is** the platform's differentiator ([02a §5](02a-competitor-analysis.md)) |
| Local LLM to avoid API cost | ◐ A $5 VPS cannot run a useful model; a GPU host costs more per month than the entire API bill |
| Drop the holdout audit | Removes the only evidence that filtering is honest |
| Drop discovery channel 1 (model-proposed subreddits) | It is folded into `analyze_business` and costs **no separate call** ([06 §3.2](06-ai-pipeline.md)). Removing it saves nothing and loses recall |

---

## 7. Acceptance criteria

- [ ] **AI-AC1** — Sprint 0 enumerates **every** model-invoking path in the effective Hermes config, including auxiliary paths, with a measured per-path frequency
- [ ] **AI-AC2** — `title_generation` disabled; a session produces **zero** title-generation calls
- [ ] **AI-AC3** — Memory background-review frequency measured (M-11); if per-turn, disabled and re-measured
- [ ] **AI-AC4** — `max_turns: 12`; a deliberately looping fixture terminates at 12 and costs under $0.03
- [ ] **AI-AC5** — An outreach request renders a **deterministic template** with zero model calls; the model runs only on an explicit improve request
- [ ] **AI-AC6** — Tier 2 fires **on lead open**, not on enrichment; a run with no opened leads makes zero Tier-2 calls
- [ ] **AI-AC7** — A golden-set re-run at an unchanged `(prompt_version, model, batch_size)` makes zero calls
- [ ] **AI-AC8** — Stage-3 metadata-triage holdout audit runs and publishes its miss rate
- [ ] **AI-AC9** — `ai_calls` distinguishes `stage='agent.%'` from pipeline stages, and the efficiency metric excludes agent rows ([27 §5.1](27-architecture-review.md))
- [ ] **AI-AC10** — Measured monthly spend is within ±25% of $0.34
