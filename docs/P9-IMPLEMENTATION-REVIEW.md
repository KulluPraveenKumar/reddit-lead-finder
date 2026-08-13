# P9 IMPLEMENTATION REVIEW — Rule engine

**Written:** 2026-08-13 · **Phase:** P9 (frozen numbering) · **Revision:** none — P9 adds no migration · **Days / Risk:** 2 · Low
**Status:** review only. **No production code has been written. No configuration has been changed.**

> ⚠️ **P9 is `src/rules/` and nothing else.** It is **not** `docs/16-phase-06.md` ("Scrape Execution,
> Comments & Local Pipeline"), which bundles the rule engine, the three-tier dedup cascade, entity
> resolution and the deterministic pre-score into one phase against migration `0007`. That document
> belongs to the **superseded eight-phase numbering** ([lock §2.1](EXECUTION_MODE_LOCK.md)) and maps
> to **P9, P10, P11 and P15**. `docs/10-implementation-roadmap.md` carries the same superseded
> bundling. `docs/testing/phase-06-testing.md` is their companion and is likewise historical:
> **read-only, never extended.**
>
> Reading either as P9's specification would build three phases at once, author a migration P9 does
> not own, and implement `EntityRegistry` six phases early.

**P9's actual content**, per [34 §P9](34-implementation-plan.md): five modules under `src/rules/` —
keyword tiers, negative terms, structural noise regexes, author heuristics, and competitor matching
behind an interface whose implementation does not arrive until P15. **No migration. No table. No
route. No handler change.**

---

## 0. Verdict up front

**P9 must not be implemented as currently documented.** Two findings are blocking. Neither is a
documentation nit: the first is an architecture-rule violation that the phase's own acceptance
criterion would report as **passing**, and the second is a scope claim P9 cannot satisfy because the
work belongs to a phase ten steps later.

| | Finding | Severity |
|---|---|---|
| **F1** | The natural implementation makes `src/rules/` import `src.ai.gate` for its return type — **violating R3 / fence 2** — and the fence that would catch it **does not exist**, because no test enforces fence 2 over `src/rules/` | 🔴 **BLOCKING** |
| **F2** | *"11 rejection reasons implemented and counted"* is **P19's deliverable, verbatim**. P9's own five tasks produce **four** of the eleven, and P9 has no store to count into (DB: None) | 🔴 **BLOCKING** |
| **F3** | **Two rejection vocabularies already ship and disagree.** `src/discovery/triage.py` counts nine reasons into `run_events` today; `src/ai/gate.py` declares a different eleven. P9 would be the third | 🟠 Must resolve |
| **F4** | **`pipeline.rules_enabled: false` has nothing to disable.** No `pipeline:` block exists in `config.yaml`, and P9's Files row wires no call site. The documented rollback is currently unexecutable — and [lock §4](EXECUTION_MODE_LOCK.md) requires the rollback be *executed*, not documented | 🟠 Must resolve |
| **F5** | **`rules/competitors.py` can never fire in production during P9.** Its only data source is the `EntityRegistry` (P15) or a BKB `projects` row (`0007`, P12). P9's Config row names no competitor key | 🟠 Must resolve |
| **F6** | **`_triage_config` reads `config["keywords"]` as a list when it is a dict** — measured this session: `TriageConfig.keywords` is `('high_intent', 'medium_intent')`. P6's keyword matching has never matched a keyword | 🟠 Pre-existing defect, found here |
| **F7** | Keyword **tiers** are specified as high/medium/low ([06c §3.1](06c-local-first-pipeline.md)); `config.yaml` ships **two** tiers and P9's Config row adds none | 🟡 Decide |
| **F8** | `rules/subreddits.py` is in [06c §2](06c-local-first-pipeline.md)'s module table and in **neither** [34 §P9](34-implementation-plan.md)'s Files row nor [03 §2](03-architecture.md)'s module map | 🟡 Record |
| **F9** | Rollback flag naming disagrees across documents: `pipeline.rules_enabled` ([34 §P9](34-implementation-plan.md)) vs `pipeline.local_qualification` ([31 Sprint 3](31-execution-plan.md)) | 🟡 Wording |
| **F10** | [34](34-implementation-plan.md)'s header says *"31 phases across 10 stages"*; the index lists **P0–P30 = 31 phases**. The operator's brief calls it *"the 34-phase roadmap"* — **34 is the document number, not a phase count** | ℹ️ Reported |
| **F11** | The working tree is **not clean**. `config.yaml` carries P7's live Telegram settings including a **real chat id** | ⚠️ Pre-flight |
| **F12** | P9's three config keys already have a **different documented home and a default**: [06b](06b-deepseek-optimization.md) specifies them as `ai.prefilter.{min_chars: 80, skip_deleted_authors, skip_bot_authors}`. `min_chars` there measures a **body**, which P9's rules never see | 🟠 Must resolve |

Nothing below is worked around. F1–F5 are analysed as decisions in
[P9-DECISION-ANALYSIS.md](P9-DECISION-ANALYSIS.md).

---

## 1. Authority ranking

When two documents disagree, the higher row wins.

| # | Authority | Scope | Why it ranks here |
|---|---|---|---|
| **1** | [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) | **§2 R3** (fence 2), R10, R11, R20; §4.1 the frozen chain; §11 amendments; §11.1 reconciliations | Self-declared binding constraint set. **R3 is the rule F1 breaks** |
| **2** | [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) | §2.1 the two numberings; §3 workflow; §4 discipline incl. *rollback executed*; §5 hygiene; §8 deferral | Governs *how* the phase executes |
| **3** | [34 §P9](34-implementation-plan.md) + [34 §1.2](34-implementation-plan.md) | Objective, Deliverables, Files, DB, Config, Depends on, 5 Tasks, Acceptance, Metrics, Rollback, Docs | *"The definitive execution guide"*. Its Files row is *"a guide, not a contract"* ([34 §1.1](34-implementation-plan.md)) |
| **4** | [35](35-testing-strategy.md) | §2 the gate; §2.3 the four non-negotiables; §2.4 mutation discipline | The named testing gate |
| **5** | [PHASE-08-HANDOVER.md](PHASE-08-HANDOVER.md) | Entry conditions, traps T1–T7, blockers, §8 the flakes | Execution record of the immediate predecessor |
| **6** | [06c §2, §3.1, §3.2](06c-local-first-pipeline.md) | **Module placement and algorithm detail only** | Design detail. Its §3.2 reason table is **P19's specification**, not P9's (F2) |
| **7** | [03 §2](03-architecture.md) | The module map | Consistent with 34 on the five modules; adds nothing binding |
| **⛔** | `16-phase-06.md`, `testing/phase-06-testing.md`, `10-implementation-roadmap.md` | — | **Superseded / historical** ([lock §2.1](EXECUTION_MODE_LOCK.md)) |

> **The supersession is explicit, not inferred.** [lock §2.1](EXECUTION_MODE_LOCK.md) states it in
> terms: *"**P0–P30** is the frozen plan ([34](34-implementation-plan.md)) and is the only active
> scheme. **'Phase 01'–'Phase 08'** … is the **superseded** scheme"*, and
> [progress/P08-COMPLETE.md §6](progress/P08-COMPLETE.md) applies the same ruling to `18-phase-08.md`.
> `docs/10-implementation-roadmap.md` is not named in that clause but is governed by it: it is the
> roadmap for the eight-phase scheme, it assigns the rule engine to old-Phase-6 with migration
> `0007`, and [lock §2](EXECUTION_MODE_LOCK.md) states *"[34](34-implementation-plan.md) is the plan.
> There is no other."*

### 1.1 The P9 specification matches the current roadmap — with two exceptions

Checked field by field against [34 §P9](34-implementation-plan.md), all thirteen fields, and against
[freeze §4.1](ARCHITECTURE_FREEZE.md):

| Field | Consistent? | Note |
|---|---|---|
| Objective | ✅ | |
| Deliverables | ✅ | Matches [03 §2](03-architecture.md)'s five-module list exactly |
| Files | ✅ | Five `+` files, no `~`. See §3.4 — the Config row implies a sixth |
| **DB** | ✅ | **None.** No revision between `0006` (P8) and `0007` (P12) — [freeze §4.1](ARCHITECTURE_FREEZE.md) confirms; P9 adds no migration and the chain stays at ten |
| Config | ⚠️ | Three keys. Insufficient for tasks 1 and 4 — F5, F7 |
| Depends on | ✅ | P8, which is complete, pushed, CI-green and manually accepted |
| Tasks | ✅ | Five, internally coherent |
| **Acceptance** | 🔴 | *"11 rejection reasons"* is P19's — **F2** |
| Metrics | ⚠️ | *"100% branch coverage on rejection reasons"* inherits F2's ambiguity |
| Time / Risk | ✅ | 2 days · Low. Concur — pure functions, no I/O, no schema |
| **Rollback** | 🟠 | Unexecutable as written — **F4** |
| Docs | ✅ | [06c §2](06c-local-first-pipeline.md) — P9 owns the module-table repair (F8) |

---

## 2. Blocking findings

### 2.1 🔴 F1 — `src/rules/` cannot return a `GateDecision`, and the fence that says so does not exist

`src/ai/gate.py` already ships. It defines the rule plugin interface P9's modules are the obvious
implementations of:

```python
class PreAIGate:
    def __init__(self, rules: list[Any] | None = None):
        self.rules = rules or []

    def evaluate(self, item: Any) -> GateDecision:
        for rule in self.rules:
            decision = rule(item)
            if decision is not None and not decision.admitted:
```

A rule is `Callable[[item], GateDecision | None]`. The shortest path from [34 §P9](34-implementation-plan.md)
task 5 — *"every rejection returns a counted reason string"* — to a working gate is for
`src/rules/structural.py` to `from src.ai.gate import GateDecision, RejectionReason` and return one.

**That import violates R3**, which [freeze §2](ARCHITECTURE_FREEZE.md) states without qualification:

> **R3** — `rules/`, `dedupe/`, `scoring/`, `knowledge/`, `feedback/`, `discovery/policy.py` **never
> import `src.ai`** · Enforced by *Grep fence 2*

**And fence 2 does not exist over `src/rules/`.** Verified this session against
`tests/test_boundaries.py`: the file contains 40 tests; the only AI-import fence is
`test_discovery_makes_no_ai_calls`, scoped to `src/discovery/`. [35 §2.1](35-testing-strategy.md)
check 9 specifies fence 2 over six paths —
`src/rules/ src/dedupe/ src/scoring/ src/knowledge/ src/feedback/ src/discovery/policy.py` — and
**five of the six do not exist yet**, so the check has been passing over an empty set for eight
phases. [PHASE-08-HANDOVER §6](PHASE-08-HANDOVER.md) records *"Grep fences 4 of 4, unchanged"*, which
is true of what is implemented and silent about what is specified.

**P9 is the phase that creates the first of those five paths.** So on P9's watch fence 2 stops being
vacuous — or would, if it were written. Today it is not, and the phase's single **bold** acceptance
criterion is the manual `grep` form, which a reviewer runs once and nobody runs again.

This is the same defect class as P4's fence 4 and P7's fence 3, both of which
`tests/test_boundaries.py` documents in its own comments: *"``docs/12`` §14 had also ticked [it] as
delivered while it was absent, and which failed on seven identifiers the moment it was written."*
The precedent for the fix is equally established — P6's G1 and P5's F3, quoted in the same file:
*"a fence that walks whatever files are there passes vacuously if the file it was written for is
deleted."*

**Consequence if unresolved:** `src/rules/` ships importing `src.ai`, every gate reports green, and
the boundary that carries [06c](06c-local-first-pipeline.md)'s entire 95%-cost argument is breached
in the first module that was supposed to prove it. See [D1](P9-DECISION-ANALYSIS.md).

### 2.2 🔴 F2 — The eleven rejection reasons are P19's deliverable, and P9's tasks produce four

[34 §P9](34-implementation-plan.md) Acceptance: *"**11 rejection reasons implemented and counted**"*.

[34 §P19](34-implementation-plan.md) Deliverables: *"`PreAIGate` with **11 counted reasons**;
`AdaptiveBudget` …"*.

Both cannot be true. Taking [06c §3.2](06c-local-first-pipeline.md)'s table — the source of the
number — and assigning each reason to the phase that can produce it:

| # | Reason | Produced by | Owning phase |
|---:|---|---|---|
| 1 | `already_analyzed` | `(content_hash, prompt_version)` cache lookup | **P19** (gate) / P20 |
| 2 | `duplicate_exact` | sha256 content hash | **P10** — dedup cascade |
| 3 | `duplicate_near` | MinHash Jaccard ≥ 0.85 | **P10** |
| 4 | `negative_term` | project negative vocabulary | ✅ **P9** — task 1 |
| 5 | `structural_noise` | hiring / giveaway / megathread / AMA regex | ✅ **P9** — task 2 |
| 6 | `too_short` | `len(text) < min_chars` | ✅ **P9** — `rules.min_chars` |
| 7 | `bot_or_deleted` | `[deleted]`, AutoModerator, `*Bot` | ✅ **P9** — task 3 |
| 8 | `out_of_window` | run time window | **P6** (ships today, in `triage.py`) |
| 9 | `downvoted` | comment score < 0 | **P11** — comments do not exist until then |
| 10 | `below_prescore` | pre-score under the admission threshold | **P11** (score) + **P19** (threshold) |
| 11 | `budget_exhausted` | run's AI budget consumed | **P19** — `AdaptiveBudget` |

**P9 can implement four: 4, 5, 6, 7.** Not one of the other seven is reachable from P9's five tasks,
and three of them require tables that do not exist until `0009`.

**"Counted" is the second half of the problem.** P9's **DB** row is `None`. There is no `prescores`
write, no `run_events` write, no counter store. `GateReport` — the thing that counts — lives in
`src/ai/gate.py` and is therefore across the R3 boundary from `src/rules/` (F1). A rule engine can
*return* a reason; only a caller can *count* one, and P9 wires no caller (F4).

**Consequence if unresolved:** P9 either overreaches into P10, P11 and P19 — building a dedup hash,
a pre-score and a budget ten phases early, against [lock §3](EXECUTION_MODE_LOCK.md) step 4 — or it
ships an acceptance criterion that is quietly reinterpreted, which is exactly the *"ticked as
delivered while it was absent"* pattern this codebase has now recorded three times. See
[D2](P9-DECISION-ANALYSIS.md).

---

## 3. Non-blocking findings

### 3.1 🟠 F3 — Two rejection vocabularies already ship, and they disagree

| | `src/discovery/triage.py` (P6, **live, writing to `run_events` today**) | `src/ai/gate.py` (P1, **declared, no writer**) |
|---|---|---|
| Count | 9 | 11 |
| Bot rejection | `bot_author` | `bot_or_deleted` |
| Structural | **five separate reasons** — `hiring`, `giveaway`, `megathread`, `ama`, `engagement_bait` | **one** — `structural_noise` |
| Missing title | `no_title` | *(absent)* |
| Shared, identical | `out_of_window`, `negative_term` | same |

`handle_discover` counts triage's vocabulary into `run_events` (`discover.py:139–188`) and it is
rendered on the run page. `RejectionReason.ALL` is rendered by nothing.

The `gate.py` docstring states the intent plainly: *"The eleven reasons are fixed here rather than in
Phase 6 so the counters, the UI, and the holdout audit all agree on the vocabulary from the start."*
**They do not agree.** P6 shipped a second vocabulary without reconciling.

**P9 is where a third would appear**, and where the choice is cheapest to make: `src/rules/` has no
callers yet, so its vocabulary can be chosen freely today and cannot be chosen freely once P10 and
P11 depend on it. Note also that the `structural_noise` collapse is lossy in the direction that
matters — [AD-10b](ARCHITECTURE_FREEZE.md) requires aggressive filters be *measured*, and "5–12%
rejected as structural noise" is not a measurement an operator can act on, whereas "8% megathread,
1% hiring" is. See [D3](P9-DECISION-ANALYSIS.md).

### 3.2 🟠 F4 — The documented rollback has nothing to switch off

[34 §P9](34-implementation-plan.md) Rollback: `pipeline.rules_enabled: false`.

Measured this session: `config.yaml` has **fourteen** top-level blocks — `subreddits`, `keywords`,
`scoring`, `schedule`, `dashboard`, `ai`, `pricing`, `logging`, `worker`, `orchestration`,
`discovery`, `network`, `proxy`, `notify`. **There is no `pipeline:` block**, and `grep -rn
"rules_enabled" src/` returns nothing.

P9's Files row lists five new files under `src/rules/` and marks **no existing module `~`**. Contrast
[34 §P7](34-implementation-plan.md), whose Files row explicitly carries
`src/orchestration/handlers/*.py ~` and `config.yaml ~`. On the plan as written, **P9 has no
consumer**, so a flag that disables it disables nothing.

[lock §4](EXECUTION_MODE_LOCK.md) makes this concrete rather than academic: *"Rollback **executed and
verified**, not merely documented"* is a line on the phase-completion checklist. A flag with no
reader cannot be executed and cannot be verified.

**This is the decision that sets the whole phase's shape** — stage count, mutation targets, and
whether P9 is rollback-able at all. See [D4](P9-DECISION-ANALYSIS.md); three options are laid out
there and the recommendation is that `src/rules/` reads the flag itself, so a disabled ruleset
admits everything and the rollback is provable inside P9's own boundary.

### 3.3 🟠 F5 — The competitor rule has no data source until P15, and P9's Config row adds none

[34 §P9](34-implementation-plan.md) task 4: *"Competitor matching **via the entity registry
interface** (stub until P15; dictionary fallback)"*.
Acceptance: *"a post using only a competitor alias matches"*.

The `EntityRegistry` is [34 §P15](34-implementation-plan.md)'s deliverable — six phases out — and its
data comes from `bkb_entities` / `bkb_entity_aliases`, created by `0007` in **P12**. The alternative
source, *"a dictionary from the business profile"* ([06c §2](06c-local-first-pipeline.md)), reads
`projects` — also `0007`.

P9's Config row is `rules.{min_chars,skip_deleted_authors,skip_bot_authors}`. **No competitor key.**

So the rule is fully testable against an injected double and **entirely inert in production** for
three phases. That is defensible — it is precisely why the task says *"stub until P15"* — but it must
be **stated**, not discovered. The failure mode is the one [DI17](DEFERRED-IMPROVEMENTS.md) already
names for `handle_maintenance`: *"exists, nothing calls it on a timer yet"*, and the one P6's
`density_threshold` note names: *"a key nothing reads is a documented capability that does not
exist."* A competitor rule that silently matches nothing looks identical to a business with no
competitors.

**Recommendation:** ship the Protocol plus a `DictionaryEntityRegistry` fallback, ship a test that
proves the alias path with an injected registry, ship **no** config key, and add an existence-style
guard asserting the production wiring is absent — so P15 must delete a test to wire it, rather than
discovering the rule was dead. See [D5](P9-DECISION-ANALYSIS.md).

### 3.4 🟠 F6 — P6's keyword matching has never matched a keyword

`src/orchestration/handlers/discover.py:467`:

```python
def _triage_config(config: dict[str, Any]) -> TriageConfig:
    discovery = (config or {}).get("discovery", {}) or {}
    keywords = tuple(str(k) for k in (config or {}).get("keywords", []) or [])
```

`config["keywords"]` is a **mapping**, not a sequence. Measured this session against the shipped
`config.yaml`:

```
type(config['keywords'])  →  <class 'dict'>
tuple(str(k) for k in ...) →  ('high_intent', 'medium_intent')
```

`TriageConfig.keywords` is therefore the two **tier names**, and `triage()`'s
`hits = [kw for kw in cfg.keywords if kw.lower() in lowered]` matches a title only if it literally
contains the string `high_intent`. `components["keyword_hits"]` is empty on every real post and the
provisional score `min(len(hits), 5) * 20` is **always 0.0** — which is also why nothing downstream
noticed: nothing consumes that score yet, and P11 is the first phase that would.

**This is P6's defect, found in P9's review.** P9 does not own `discover.py` and fixing it there is
outside the Files row and outside [lock §8](EXECUTION_MODE_LOCK.md)'s four conditions for a
mid-phase improvement — it changes shipped behaviour on a path P9 is additive to, the same reasoning
that deferred [DI13](DEFERRED-IMPROVEMENTS.md) and [DI14](DEFERRED-IMPROVEMENTS.md).

**But P9 must not reproduce it.** `rules/keywords.py` reads the same `keywords:` block, and the
correct shape is the dict. Recommend: register as **DI24** with the trigger *"P11, which is the first
consumer of a triage score"*, and add a P9 test asserting `rules/keywords.py` reads the tiered
mapping — a test that would have failed against `_triage_config`.

> **Number corrected.** An earlier draft of this section proposed DI23 for this finding. The operator
> approved [D3](P9-DECISION-ANALYSIS.md) with **DI23 assigned to the rejection-vocabulary
> convergence**, so this one is **DI24**. Recorded rather than silently edited — two documents
> disagreeing on an identifier is the pattern [freeze §11.1](ARCHITECTURE_FREEZE.md) exists for, and
> this repository has now hit it three times.

### 3.5 🟡 F7 — Three keyword tiers are specified; two ship

[06c §3.1](06c-local-first-pipeline.md): `"keyword_tier": TIER_VALUE[item.matched_keyword_tier]  # high/med/low`.
`config.yaml` ships `keywords.high_intent` and `keywords.medium_intent`. There is no `low_intent`,
and [34 §P9](34-implementation-plan.md)'s Config row adds no keyword key at all.

`src/scoring.py::LeadScorer` — the legacy scorer, still live and pinned by the R20 fingerprint —
reads exactly these two and tags matches `[HIGH]` / `[MED]`.

Three readings are available and P9 must pick one deliberately: two tiers with `low` reserved; three
tiers with an empty third shipped in `config.yaml`; or `TIER_VALUE` keyed on whatever tiers the
mapping contains, which is the only one that cannot go stale. **Recommend the third.** Whichever is
chosen, do **not** alter the two existing tier lists — `LeadScorer` reads them and R20 pins the
resulting `intent_score` fingerprint over 459 rows.

### 3.6 🟡 F8 — `rules/subreddits.py` is in one document and two module maps disagree

[06c §2](06c-local-first-pipeline.md)'s table: *"Subreddit filtering | set membership |
`rules/subreddits.py`"*.

It appears in **neither** [34 §P9](34-implementation-plan.md)'s Files row (five modules) nor
[03 §2](03-architecture.md)'s map (*"src/rules/ keywords · negatives · structural · competitors ·
authors"*). [03 §2](03-architecture.md) instead places subreddit work in `src/discovery/`
(*"subreddit candidate generation + validation + rank"*), which is [34 §P17](34-implementation-plan.md)'s.

**Do not create it.** P9's **Docs** field already makes P9 the owner of [06c §2](06c-local-first-pipeline.md),
so the disposition is a one-row repair in that table pointing subreddit filtering at `src/discovery/`
— the same reconciliation pattern P8 used for [05 §7](05-database-plan.md).

Note also that [06c §2](06c-local-first-pipeline.md) attributes *"negative-term filtering"* to
`rules/keywords.py`, which is why [34 §P9](34-implementation-plan.md)'s Files row has no
`negatives.py` while [03 §2](03-architecture.md)'s prose lists "negatives" as a concern. Those two
are consistent; only `subreddits.py` is orphaned.

### 3.7 🟡 F9 — The rollback flag has two names

[34 §P9](34-implementation-plan.md): `pipeline.rules_enabled: false`.
[31 Sprint 3](31-execution-plan.md): `pipeline.local_qualification: false` — one flag for the rule
engine, dedup and pre-score together, matching the superseded bundling.
[34 §P11](34-implementation-plan.md): `pipeline.prescore_enabled: false`.

34 wins on the authority ranking, and its per-phase flags are the better design: a phase whose
rollback is shared with two unbuilt phases cannot be rolled back independently, which
[34 §1](34-implementation-plan.md) requires of every phase. Record; no action beyond using 34's name.

### 3.8 🟠 F12 — The same three config keys are already specified elsewhere, under a different block, with a default

[34 §P9](34-implementation-plan.md) Config: `rules.{min_chars,skip_deleted_authors,skip_bot_authors}`.

[06b](06b-deepseek-optimization.md)'s configuration listing, lines 453–456:

```yaml
  prefilter:
    min_chars: 80
    skip_deleted_authors: true
    skip_bot_authors: true
```

**The same three keys, in the same order** — nested under `ai:`, as `ai.prefilter.*`, with the only
default value that appears in any document.

Three separable questions:

1. **Which block?** `rules:` (34) or `ai.prefilter:` (06b). **34 wins on the authority ranking**, and
   independently on the merits: putting the rule engine's configuration under `ai:` invites exactly
   the coupling **R3** forbids, and a reader wiring `rules/keywords.py` to an `ai.*` key is one step
   from importing `src.ai` to read it (F1). Adopt `rules:` as a top-level block and record 06b's
   listing as a [freeze §11.1](ARCHITECTURE_FREEZE.md)-style reconciliation.
2. **What is `min_chars`'s default?** 34 gives none; **80** is the only number in the corpus. Adopt
   it, and cite 06b as the source rather than inventing a value.
3. **⚠️ Which text does it measure?** 06b's context is a **prefilter immediately before an AI call**,
   i.e. after a body has been fetched — so `min_chars: 80` is a **body** length, and 06c §3.2 agrees
   (`len(text) < min_chars`). **P9's rules never see a body.** [34 §P9](34-implementation-plan.md)'s
   five tasks are title-, author- and keyword-shaped; the body arrives with P11's comment and
   full-scoring work.

Question 3 changes A1's number and is therefore part of the blocking decision, not a footnote: P9
either ships a text-agnostic `is_too_short(text, min_chars)` predicate whose production binding is
P11's — **four reasons implemented, three of them wired** — or defers `too_short` entirely and ships
**three**. Folded into [D2](P9-DECISION-ANALYSIS.md).

### 3.9 ℹ️ F10 — "34-phase roadmap" is a document number, not a phase count

[34](34-implementation-plan.md)'s header reads *"31 phases across 10 stages, 83 engineer-days"* and
its index lists **P0 through P30 — 31 phases** across stages A–J. The brief's phrase *"the current
34-phase roadmap"* refers to `docs/34-implementation-plan.md`. Confirmed that document is the current
one and P9 is its ninth numbered phase. No action; recorded so the count is not propagated.

---

## 4. Dependency and predecessor verification

### 4.1 Phase dependencies

| | |
|---|---|
| **Depends on** | **P8** — complete, pushed, CI-green, manually accepted by the operator |
| P8's deliverable P9 uses | **None.** P8 created four empty tables and four `leads` columns; P9 writes to no table |
| Forward dependants | **P10** (dedup cascade, `Depends on: P9`), then P11, then P19 |
| Blocked by P9 | Nothing else. P10 is the only phase naming P9 in its Depends-on row |

**P9 is the first phase since P0 whose dependency on its predecessor is purely procedural.** It uses
nothing P8 built. That is worth stating because it means P9 is unusually safe to get wrong in one
direction — no migration, no live data, no schema — and unusually expensive to get wrong in the
other, because P10, P11 and P19 all consume its vocabulary and its return type (F1, F2, F3).

### 4.2 The P8 handover's entry conditions, checked

| Condition | State |
|---|---|
| `docs/testing/P08-testing.md` sign-off table signed | ⚠️ **Operator's.** The brief records manual acceptance; the table's checkboxes are the artefact. **No tag until signed** — [lock §6.2](EXECUTION_MODE_LOCK.md) |
| §3 read — the four rebuilds and P12's `NOT NULL` decision | ✅ Read. **P12's, not P9's** — P9 authors no migration |
| §4 T1 read — `confidence_score` does not unblock `lead.high_confidence` | ✅ Read. `test_min_confidence_alert_was_not_shipped` must stay green through P9; P9 touches nothing near it |
| §4 T2 read — the `dedup_members` invariant is P10's | ✅ Read. [DI22](DEFERRED-IMPROVEMENTS.md) |
| [34 §P9](34-implementation-plan.md) read — all thirteen fields | ✅ §1.1 above, field by field |
| [freeze §4.1](ARCHITECTURE_FREEZE.md) read — `0007` is `projects_and_knowledge_base` | ✅ P9 adds no revision; the chain stays at ten |
| `phase-manager` skill loaded before the first edit under `src/` | ⏳ Stage 0 of the checklist |
| Full suite green before the first change — **1148 passed, 2 skipped** | ⏳ §4.3 — **blocked on F11** |
| `git status` clean · `alembic heads` = one `0006` · `check_schema.py` 51/51 | ⚠️ Two of three — §4.3 |
| `gh run list`: P8 green on `origin/main` | ✅ Verified |
| M7 backup before any `alembic upgrade` | ➖ **N/A.** P9 runs no upgrade against the live database |

### 4.3 Baseline — measured 2026-08-13, this session, on `main` @ `1ef3bba`

| Check | Result |
|---|---|
| `git rev-parse HEAD` | `1ef3bbaf1a0310a5181c2e0e506100553cfd1cd7` |
| `git rev-parse origin/main` | `1ef3bbaf1a0310a5181c2e0e506100553cfd1cd7` — **identical** |
| `gh run list` | P8 head commit → **success**, 2m45s |
| `alembic heads` | `0006_content_and_dedup (head)` — **one head** |
| `scripts/check_schema.py` | **OK — all 51 checks passed** |
| `ruff check .` | **All checks passed!** |
| `ruff format --check .` | **127 files already formatted** |
| **`git status --porcelain`** | 🔴 **` M config.yaml`** — see F11 |
| **Full suite** *(on the dirty tree)* | **2 failed, 1146 passed, 2 skipped** in 362 s — **both failures attributable to F11**, and `1146 + 2 = 1148`, reconciling exactly with P8's recorded baseline |

### 4.4 ⚠️ F11 — The working tree is not clean, and it is the same file for the same reason

The brief states *"Working tree is clean."* It is not:

```
 M config.yaml
```

Three hunks, all in the `notify:` block, all left by P7's live Telegram verification:

| Key | Committed | Working tree |
|---|---|---|
| `notify.enabled` | `false` | `true` |
| `notify.transport` | `'null'` | `bot_api` |
| `notify.telegram_chat_id` | `''` | **a real chat id** |

**This is a known, recurring pre-flight item, not a new defect.**
[P8-IMPLEMENTATION-CHECKLIST step 0.2](P8-IMPLEMENTATION-CHECKLIST.md) documents the identical state
and its remedy: *"`git checkout -- config.yaml` — and **never commit it**, which is what **R15**
exists to prevent."* It also recorded the measurement at that time: **three** tests failing with the
live config, zero attributable once reverted.

**Re-measured this session — it is now two, not three:**

```
FAILED tests/test_boundaries.py::test_the_notify_config_block_ships_and_defaults_to_off
FAILED tests/test_notify_policy.py::test_the_shipped_config_block_builds_the_transport_it_names
2 failed, 1146 passed, 2 skipped in 362.37s
```

Both assert the shipped default is off; both fail on `enabled=True, transport='bot_api'` and a
populated `telegram_chat_id`. The third has since been fixed by P7's `06cdf11` (*"the test that
depended on `TELEGRAM_BOT_TOKEN` being absent"*). **`1146 + 2 = 1148`**, which reconciles exactly with
[PHASE-08-HANDOVER §6](PHASE-08-HANDOVER.md)'s recorded baseline of *1148 passed, 2 skipped* — so the
suite is green on a clean tree and **no third flake fired on this run.**

Two consequences for P9 specifically:

1. **The baseline suite figure cannot be compared to 1148 until it is reverted.** The number recorded
   in §4.3 is measured on the dirty tree and is expected to carry those three failures.
2. **P9 edits `config.yaml`** — it is the only phase artefact the Config row requires. Staging that
   file while these hunks are present risks committing a **real chat identifier to a public
   repository**, which is an R15 violation and, per [lock §5.2](EXECUTION_MODE_LOCK.md), *"not fixed
   by a later commit — it is fixed by rotating the credential."* P8 never touched `config.yaml`, so
   P9 is the first phase since P7 where this dirt sits in the blast radius.

**Recommendation:** revert before Stage 0, and add an explicit hygiene step to P9's checklist that
re-runs `git diff --cached` against the H1/H2 patterns immediately before the `config.yaml` commit —
not only at the end of the phase. The recurrence rate is now two phases out of two that checked.

---

## 5. Acceptance criteria

### 5.1 P9-specific — [34 §P9](34-implementation-plan.md), as reconciled above

| # | Criterion | Verdict | How it is proved |
|---:|---|---|---|
| A1 | 11 rejection reasons implemented and counted | 🔴 **Replace** — F2. P9 implements **four**; counting is P19's | Test asserting `rules.REASONS` is exactly the four, and a test asserting the four are a **subset of** `RejectionReason.ALL` |
| A2 | **`grep -rn "import.*src\.ai" src/rules/` returns nothing** *(bold)* | ✅ Keep, and **promote to a test** — F1 | New `test_the_rules_package_is_inside_the_ai_fence` + a package-existence guard, following `test_the_notify_package_exists` |
| A3 | A post using only a competitor alias matches | ✅ Keep — scope it to an injected registry double, F5 | Fixture post containing only an alias; assert the competitor signal fires and the canonical name is returned |
| A4 | Negative terms are case- and punctuation-insensitive | ✅ Keep | Parametrised: `Foo-Bar`, `foo bar`, `FOO.BAR`, `foobar`; and a **negative** case proving the normaliser does not over-match |
| A5 | Property test: no input crashes | ✅ Keep, and **strengthen** | `None`, `""`, 100 kB body, lone surrogates, RTL marks, ReDoS-shaped input. See §7 |
| A6 | Rule evaluation < 1 ms/item *(Metrics)* | ⚠️ Keep, **restate as CPU time** — [DI18](DEFERRED-IMPROVEMENTS.md) | `time.process_time()` over ≥1,000 items with headroom, **not** wall clock. See §9 R3 |
| A7 | 100% branch coverage on rejection reasons *(Metrics)* | ✅ Keep, scoped to the four | `--cov=src/rules --cov-branch`; **≥85%** applies only to `src/{ai,net,scoring,knowledge}` — `src/rules/` takes the ≥70% floor, and 100% branch on the reason paths is the stricter, phase-specific bar |
| A8 | Rollback `pipeline.rules_enabled: false` **executed** | 🟠 **Blocked on D4** — F4 | Whatever D4 settles, the rollback must be *run*, not described — [lock §4](EXECUTION_MODE_LOCK.md) |

### 5.2 Universal — [34 §1.2](34-implementation-plan.md)

| Criterion | P9 exposure |
|---|---|
| `ruff check` / `ruff format --check` | Low — five new files, formatted on write |
| `pytest` passes; no live network | Low — `src/rules/` opens no socket and no file |
| Coverage ≥70% on new modules | **≥70%** for `src/rules/`; the ≥85% tier does not name it. Target 100% branch on reason paths anyway (A7) |
| **All four grep fences (R2–R5)** | 🔴 **This is F1.** Fence 2 gains its first real subject in this phase and is currently unwritten |
| Migration round-trip on a copy | ➖ **N/A** — no revision. Run it anyway as a regression: `0006 → 0005 → 0006` must still pass untouched |
| **Legacy contract** — 459 leads, `intent_score` fingerprint, byte-identical `GET /`, 13 CSV columns, 17 endpoints | Low, but **not zero** — F7. Touching `keywords.high_intent` / `medium_intent` would move `LeadScorer`'s output and break the fingerprint. **Do not edit those two lists** |
| Manual guide generated and executed | `docs/testing/P09-testing.md`. Hard for a non-developer: P9 has no page and no observable output. See §8 |
| Documentation edits landed | [06c §2](06c-local-first-pipeline.md) module table — F8 |

---

## 6. Boundary verification

### 6.1 The four fences, as they stand today

| Fence | Rule | Implemented? | P9's effect |
|---|---|---|---|
| **1** | No vendor coupling outside `src/ai/providers/` | ✅ AST-based, `test_no_vendor_coupling_outside_providers` | None |
| **2** | `rules/ dedupe/ scoring/ knowledge/ feedback/ discovery/policy.py` never import `src.ai` | 🔴 **Partial.** Only `src/discovery/` is covered, by `test_discovery_makes_no_ai_calls`. **Five of six specified paths do not exist**; `src/rules/` is the first to arrive | **P9 must write it** — F1 |
| **3** | `src/` never imports Hermes | ✅ `test_the_platform_never_imports_hermes`, scoped to all of `src/` — **automatically covers `src/rules/` the moment it exists** | Passive coverage; assert it in Stage 1 |
| **4** | No Reddit identifier in `src/net/` | ✅ AST-based | None |

> **Fence 3 is the model.** It walks all of `src/` and counts its own inputs
> (`assert scanned > 0, "fence 3 scanned no files"`). Fence 2 for `src/rules/` should be written the
> same way, with the package-existence guard `test_the_notify_package_exists` establishes as the
> house pattern — otherwise deleting `src/rules/` would silently reduce the fence to a no-op, which
> is P5's F3 for the fourth time.

### 6.2 The boundary P9 actually has

`src/rules/` must be reachable **from** `src.ai` and must not reach **into** it. The dependency
arrow points one way, and P9 is where it is first drawn:

```
   src/ai/gate.py  ──imports──►  src/rules/            ✅ legal, and the intended direction
   src/rules/      ──imports──►  src/ai/gate.py        🔴 R3 violation (F1)
```

The practical consequence: **`src/rules/` owns its own return type.** It cannot return
`GateDecision`, cannot reference `RejectionReason`, and cannot import `GateReport` to count into. It
returns a neutral value — a reason string, or a small frozen dataclass defined in `src/rules/` — and
the adapter that turns it into a `GateDecision` lives on the `src.ai` side, where the import is
legal. That adapter is **P19's**, not P9's ([34 §P19](34-implementation-plan.md) Files row:
`src/ai/gate.py ~`).

P9 should therefore ship a test that fails if `src/ai/gate.py` is modified to construct rules
itself — or, more cheaply and more honestly, simply not touch `src/ai/gate.py` at all and say so in
the handover. See [D1](P9-DECISION-ANALYSIS.md).

---

## 7. Testing strategy

### 7.1 Shape

`src/rules/` is the most testable code in this project: five pure modules, no session, no clock
except one injectable `now`, no network, no filesystem. Everything is testable from literals, which
is the reason [06c §2](06c-local-first-pipeline.md) puts these tasks in deterministic code in the
first place.

| Layer | What | Where |
|---|---|---|
| **Fence** | Fence 2 over `src/rules/` + package existence | `tests/test_boundaries.py` ~ |
| **Unit** | Per module: keywords (tiers, density, negatives), structural (five patterns × match/near-miss), authors (`[deleted]`, AutoModerator, `*Bot` suffix, allowlist), competitors (canonical, alias, misspelling, no-registry) | `tests/test_rules_*.py` + |
| **Property** | A5 — no input crashes, over generated and adversarial inputs | `tests/test_rules_properties.py` + |
| **Vocabulary** | `REASONS` is exactly the four; the four are a subset of `RejectionReason.ALL`; no reason string is invented at a call site | `tests/test_rules_vocabulary.py` + |
| **Performance** | A6 — CPU time per item, not wall clock | with the unit tests |
| **Regression** | Legacy contract, migration round-trip, full suite | existing |

### 7.2 The tests that matter more than they look

- **A near-miss for every structural pattern.** `\bhiring\b` must reject *"[HIRING] Senior dev"* and
  **admit** *"our hiring process is broken and I need a tool"* — which is a textbook lead and the
  exact false positive this rule generates. Ship the negative case beside every positive one; a
  regex fence tested only on its matches is untested.
- **Punctuation-insensitivity has two failure directions.** A4 as written only tests that
  `Foo-Bar` matches `foo bar`. The normaliser must also **not** make `notion` match `no tion` or
  `cat` match `c a t`. Half of A4 is missing from the criterion.
- **`*Bot` is a suffix rule with a well-known collision.** `Botany_Nerd`, `robotics_guy`,
  `Abbott` — the shipped `BOT_AUTHORS` set in `triage.py` is an exact-match frozenset for precisely
  this reason. A P9 suffix rule must be anchored and case-folded, and must ship its false-positive
  fixtures.
- **ReDoS.** Five compiled patterns applied to attacker-supplied post bodies. A5's *"no input
  crashes"* should be read to include *"no input hangs"*: assert bounded CPU time on a pathological
  input, since a catastrophic backtrack does not raise, it stalls the worker.

### 7.3 Mutation strategy

[35 §2.4](35-testing-strategy.md) requires mutation for *"every criterion marked **bold** in
[34](34-implementation-plan.md), and every check in §2.3."* **P9 has exactly one bold criterion** —
the fence. That is a thin literal minimum for a phase whose entire product is branch logic, and P8's
result argues against taking the minimum: **14 designed, 12 detected, 2 proven equivalent, and
[PHASE-08-HANDOVER §4 T5](PHASE-08-HANDOVER.md) records that every survivor was informative — one
was a masked assertion, a real test defect.**

Proposed set — **16 mutations**, each with the test that must die:

| # | Mutation | Must be caught by |
|---:|---|---|
| M1 | Add `from src.ai.gate import GateDecision` to `src/rules/structural.py` | Fence 2 (F1's whole point) |
| M2 | Delete `src/rules/__init__.py` | Package-existence guard |
| M3 | Make the fence's file walk return `[]` | `assert scanned > 0` |
| M4 | Drop one of the five structural patterns | That pattern's positive test |
| M5 | Remove `re.IGNORECASE` from the structural patterns | Case-variant test |
| M6 | Widen `\bhiring\b` to `hiring` | The *"our hiring process is broken"* near-miss |
| M7 | Anchor `^\[hiring\]` only, dropping the `\bhiring\b` alternative | `[HIRING]`-elsewhere test |
| M8 | Negative-term compare without casefolding | A4 case test |
| M9 | Negative-term compare without punctuation normalisation | A4 punctuation test |
| M10 | Over-normalise — strip all whitespace before comparing | The A4 **over-match** guard (§7.2) |
| M11 | `min_chars` boundary `<` → `<=` | An exactly-`min_chars` fixture |
| M12 | Ignore `rules.skip_bot_authors: false` | The flag-respected test |
| M13 | `*Bot` suffix match without anchoring | `Botany_Nerd` false-positive fixture |
| M14 | Competitor match on canonical name only, ignoring aliases | A3 |
| M15 | Return a reason string not in `REASONS` | Vocabulary test |
| M16 | `rules_enabled: false` still rejects | The rollback test (**subject to D4**) |

Mutations M1–M3 are the ones that would have caught F1 and are why the fence lands in **Stage 1,
before the modules it constrains** — the P8 pattern, which
[P8-IMPLEMENTATION-CHECKLIST](P8-IMPLEMENTATION-CHECKLIST.md) records as *"the guard that would have
caught F1, before the migration it constrains"*, and which
[progress/P08-COMPLETE.md §2](progress/P08-COMPLETE.md) calls *"the phase's real product"*.

**A survivor is diagnosed, never absorbed.** If a mutation survives and the fix crosses a stage
boundary, work stops and the operator decides — [lock §3](EXECUTION_MODE_LOCK.md) step 6: *"Root
cause fixed, never an assertion weakened."*

---

## 8. The manual guide problem

Every phase must produce `docs/testing/P09-testing.md`, and [35 §1](35-testing-strategy.md) requires
it be executable **by a non-developer**: *"If a step cannot be verified without reading code, the
step is wrong."*

**P9 has no page, no endpoint, no log line, no database row and no CLI command.** It is a library
with no callers. This is the hardest manual guide in the project so far, and the difficulty is real
rather than a documentation problem — it is F4 wearing a different hat.

Three honest options, in preference order:

1. **A tiny `python -m` demo entry point** that takes a title and prints the verdict and reason. A
   non-developer types a hiring title and sees `reject · structural_noise`. Costs one small module
   outside the Files row (which is *"a guide, not a contract"*, and P5 and P6 both took this
   latitude — see `triage.py`'s own file-row note).
2. **Config-driven observation** — if D4 lands the flag inside `src/rules/`, the tester flips
   `pipeline.rules_enabled` and re-runs the demo, which makes the **rollback** manually verifiable
   too. This is option 1 plus the thing [lock §4](EXECUTION_MODE_LOCK.md) already requires.
3. **A guide of pytest invocations with expected counts.** Honest but weak, and it fails
   [35 §1](35-testing-strategy.md)'s own test of a good step. Note
   [DI19](DEFERRED-IMPROVEMENTS.md): `pyproject.toml` sets `addopts = "-q --strict-markers"`, so
   **never write `-q` in a guide step whose expected output is a count** — it becomes `-qq` and
   suppresses the summary line entirely.

**Recommend option 2**, which resolves F4 and the guide together. It is folded into
[D4](P9-DECISION-ANALYSIS.md) rather than decided separately.

---

## 9. Risk assessment

| | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | `src/rules/` imports `src.ai` and every gate stays green | **High** — it is the shortest path to a working gate | **Critical** — breaches the boundary carrying the 95% cost argument | F1 / D1. Fence in **Stage 1**, before the modules |
| **R2** | P9 builds P10/P11/P19 work chasing "11 reasons" | **High** if F2 is left unreconciled | High — [lock §3](EXECUTION_MODE_LOCK.md) step 4, and three phases done badly instead of one well | F2 / D2, decided before Stage 1 |
| **R3** | The `< 1 ms/item` metric becomes a fourth flaky test | **Medium** | Medium — [PHASE-08-HANDOVER §8](PHASE-08-HANDOVER.md): five occurrences in one phase, and the real cost is training the team to read red as *"probably the flake"* | CPU time with headroom, never wall clock. [DI18](DEFERRED-IMPROVEMENTS.md) |
| **R4** | A third rejection vocabulary is created | **Medium-High** — it is the default outcome of not deciding | Medium — P10, P11 and P19 inherit it and the run page shows two schemes | F3 / D3 |
| **R5** | `config.yaml`'s live chat id reaches a public commit | **Low**, but **irreversible** | **Critical** — R15; requires credential rotation | F11. Revert at Stage 0; re-check `git diff --cached` at the config commit specifically |
| **R6** | A structural regex over-matches and silently discards real leads | **Medium** | High and **invisible** — [AD-10b](ARCHITECTURE_FREEZE.md); the holdout that would catch it is P11's | Near-miss fixture for every pattern (§7.2); reasons kept granular (F3/D3) so the funnel is readable |
| **R7** | Three known flaky tests cost a re-run per stage | **High** — 5 occurrences in P8 | Low each, corrosive cumulatively | **D8 is still open.** [PHASE-08-HANDOVER §8](PHASE-08-HANDOVER.md) asks P9 to register all three or fix them. See §10 |
| **R8** | The competitor rule ships inert and nobody notices until P15 | **Medium** | Medium | F5 / D5 — a guard that P15 must delete to wire it |
| **R9** | ReDoS on an attacker-supplied body stalls the worker | **Low** | Medium | Bounded-CPU assertion in the property tests (§7.2) |

---

## 10. Obligations P9 inherits and does not create

[PHASE-08-HANDOVER §7 and §8](PHASE-08-HANDOVER.md) hand P9 three items that are not P9 scope but are
P9's to dispose of:

| | Item | Disposition recommended |
|---|---|---|
| **D8** | The flaky-test decision — three tests, five occurrences in P8, **one registered nowhere** | **Settle it in P9.** [DI18](DEFERRED-IMPROVEMENTS.md) covers `test_parse_speed_stays_inside_the_budget`; DI20 is *reserved* for `test_does_not_write_to_the_database_it_checks` and never filled; `test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs` is in no register at all. P9 has a wall-clock metric of its own (A6/R3), so it is the phase with the strongest reason to fix rather than register. **Blocking decision — see [D6](P9-DECISION-ANALYSIS.md)** |
| **L4** | P7's undelivered notification retry | **Not P9's.** Still an open P7 obligation with no owner. Re-state in P9's handover so it does not decay into silence |
| **O2** | `mypy` — 193 errors in 23 files, deferred by D6 in P8 | **Re-defer.** But note `src/rules/` is new code: ship it **clean under `mypy --ignore-missing-imports`** so the debt does not grow, even though the gate does not check it |
| **DI15** | An eighth job type shipped unreconciled | **Does not fire.** P9 adds no job type. Trigger passes to P11 |
| **DI22** | The `dedup_members` invariant | **P10's.** Untouched |

---

## 11. Assumptions this review makes explicit

| | Assumption | If wrong |
|---|---|---|
| **A-1** | **P9 is library-only: it ships `src/rules/` plus its config block, and wires no call site.** Evidence: Files row has five `+` and no `~`; DB is None; funnel counters are [34 §P11](34-implementation-plan.md) task 2; gate composition is [34 §P19](34-implementation-plan.md) | The phase gains a sixth stage and `discover.py` or `gate.py` enters the blast radius. **Decided by [D4](P9-DECISION-ANALYSIS.md)** |
| **A-2** | `src/discovery/triage.py` is **not refactored** onto `src/rules/`. It is P6's, it is live on real data, its metadata-only scope is deliberate and documented in its own docstring, and it is outside P9's Files row | Convergence work lands in P9 unbudgeted and P6's shipped behaviour changes. Registered as a DI for P11 instead — **[D3](P9-DECISION-ANALYSIS.md)** |
| **A-3** | P9 writes no migration, and `alembic heads` stays `0006` throughout | The frozen chain gains an eleventh revision, which needs a [freeze §11](ARCHITECTURE_FREEZE.md) amendment |
| **A-4** | The four reason strings P9 produces are drawn from `RejectionReason.ALL`'s spelling, even though `src/rules/` may not import it | Two vocabularies diverge further, F3 worsens |
| **A-5** | `src/rules/` takes the **≥70%** coverage floor; the ≥85% tier names `src/{ai,net,scoring,knowledge}` and not `src/rules/` | The bar rises; 100% branch on reason paths (A7) clears it anyway |
| **A-6** | The existing `keywords.high_intent` / `medium_intent` lists are **read, never edited** — `LeadScorer` consumes them and R20 pins the resulting fingerprint over 459 rows | The legacy contract breaks and the phase fails gate check 13 |

---

## 12. Scope — what P9 does **not** do

Stated because every item below is something a reader of the acceptance criteria could reasonably
think P9 owns:

- **No migration, no table, no column.** The chain stays at `0006`.
- **No dedup.** `duplicate_exact` / `duplicate_near` are P10's, and the tables P8 built stay empty.
- **No pre-score.** The nine-component score, `below_prescore`, and the funnel counters are P11's.
- **No `PreAIGate` composition, and no edit to `src/ai/gate.py`.** P19's Files row owns that file.
- **No adaptive budget, no knee, no `budget_exhausted`.** P19.
- **No `EntityRegistry`.** P15. P9 ships the interface and a dictionary fallback only.
- **No route, no template, no funnel rendering.** P11 and P16.
- **No holdout audit.** R11's obligation for metadata triage is P11's; P9's rules feed no gate yet.
- **No change to `src/discovery/triage.py`** — A-2.
- **No fix to `_triage_config`** — F6; registered, not fixed.

---

## 13. Verdict

**Do not begin implementation.** Six decisions need the operator, two of them blocking:

| | Decision | Severity |
|---|---|---|
| **D1** | The return type of a rule, and whether fence 2 is written in Stage 1 | 🔴 **BLOCKING** |
| **D2** | The rejection-reason count P9 actually ships, and what "counted" means with `DB: None` | 🔴 **BLOCKING** |
| **D3** | Which rejection vocabulary P9 adopts, and what happens to triage's nine | 🟠 Needs assent |
| **D4** | Whether `pipeline.rules_enabled` is shipped, deferred, or read by `src/rules/` itself — and with it the manual guide | 🟠 Needs assent |
| **D5** | The competitor rule's data source and its inert-in-production guard | 🟠 Needs assent |
| **D6** | The flaky tests — D8, still open from P8, now on its second inherited phase | 🟠 Needs assent |

Each is analysed with options and a recommendation in
[P9-DECISION-ANALYSIS.md](P9-DECISION-ANALYSIS.md).

**`docs/P9-IMPLEMENTATION-CHECKLIST.md` and `docs/testing/P09-testing.md` are deliberately not
written yet.** Their content depends on D1, D2 and D4 — the return type, the criterion count, and
whether P9 has a rollback at all — and a staged plan authored against unapproved decisions is a plan
for a phase nobody agreed to. They follow immediately once those three are settled in writing.

**And before any of that: revert `config.yaml`** (F11). It is the one item that can cause
irreversible harm, and it takes one command.
