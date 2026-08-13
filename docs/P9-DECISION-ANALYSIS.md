# P9 DECISION ANALYSIS — Rule engine

**Written:** 2026-08-13 · **Phase:** P9 (frozen numbering) · **Status:** awaiting operator decisions
**Companion to** [P9-IMPLEMENTATION-REVIEW.md](P9-IMPLEMENTATION-REVIEW.md), which states the findings
these decisions resolve.

> **Nothing here has been implemented.** No file under `src/` has been created or modified, no
> configuration key has been added, and `config.yaml` has not been touched by this session.
>
> Six decisions. **D1, D2 and D4 are blocking** — the implementation checklist cannot pass Stage 0
> without them. D3, D5 and D6 need assent but do not gate the first commit.

| | Decision | Severity | Recommendation |
|---|---|---|---|
| [**D1**](#d1) | What a rule returns, and when fence 2 is written | 🔴 **BLOCKING** | **Option B** — a neutral type owned by `src/rules/`; fence in Stage 1 |
| [**D2**](#d2) | How many rejection reasons P9 ships, and what "counted" means | 🔴 **BLOCKING** | **Option B** — four implemented, three wired; counting is P19's |
| [**D3**](#d3) | Which rejection vocabulary, given two already exist | 🟠 Needs assent | **Option A** — `RejectionReason` spelling + a `detail` string |
| [**D4**](#d4) | `pipeline.rules_enabled` — ship, defer, or self-read | 🔴 **BLOCKING** | **Option C** — `src/rules/` reads its own flag |
| [**D5**](#d5) | The competitor rule's data source while P15 is unbuilt | 🟠 Needs assent | **Option A** — Protocol + dictionary fallback + an inertness guard |
| [**D6**](#d6) | The flaky tests — D8, inherited from P8 and still open | 🟠 Needs assent | **Option B** — fix two, register the third |

Plus one item that needs no decision, only an action: **[revert `config.yaml`](#preflight)**.

---

<a id="d1"></a>
## D1 — What a rule returns, and when fence 2 is written

### 🔴 BLOCKING

Resolves [review F1](P9-IMPLEMENTATION-REVIEW.md). This decision determines whether P9 breaches
**R3**, the rule that carries [06c](06c-local-first-pipeline.md)'s entire cost argument.

### What is actually at stake

`src/ai/gate.py` already ships a rule plugin interface: `PreAIGate.__init__(rules)` calls each rule
and reads `decision.admitted`. A rule is `Callable[[item], GateDecision | None]`. The shortest path
from [34 §P9](34-implementation-plan.md) task 5 to a working gate is for `src/rules/structural.py` to
import `GateDecision` and `RejectionReason` and return one.

That import is an **R3 violation**, and the fence that would catch it does not exist:
`tests/test_boundaries.py` implements fences 1, 3 and 4, and implements fence 2 **only over
`src/discovery/`**. [35 §2.1](35-testing-strategy.md) check 9 specifies six paths; five have never
existed, so the check has passed over an empty set for eight phases.

**P9 creates the first of those five.** The vacuous pass ends on this phase's watch — or would, if
anyone had written the test.

The cost of getting this wrong is not caught later. P10, P11 and P19 all consume `src/rules/`'s
return type. Once three phases import it, changing it is a refactor across four packages.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | `src/rules/` returns `GateDecision` from `src/ai/gate.py` | ❌ **R3 violation.** Ships green, breaches the only mechanical enforcement the architecture has. Not viable |
| **B** | `src/rules/` defines its own frozen result type and returns it; the adapter to `GateDecision` lives on the `src.ai` side (P19) | ✅ R3 holds; the dependency arrow points `src/ai/ → src/rules/`, which is legal and is the direction [03 §2](03-architecture.md) draws |
| **C** | Move `GateDecision` / `RejectionReason` into a new neutral package both may import | ❌ A new top-level package is not in any Files row, not in [03 §2](03-architecture.md)'s map, and needs a [freeze §11](ARCHITECTURE_FREEZE.md) amendment for a problem Option B solves for free |
| **D** | Rules return a bare `str | None` reason | ⚠️ Works and is R3-clean, but loses the `detail` that [D3](#d3) needs and that `GateDecision.detail` already exists to carry |

### ✅ Recommendation — **Option B**

`src/rules/__init__.py` defines:

```python
@dataclass(frozen=True)
class RuleResult:
    """A deterministic judgement, and why. Deliberately NOT GateDecision.

    R3 forbids src/rules/ importing src.ai, and GateDecision lives in
    src/ai/gate.py. The adapter is P19's, on the side of the boundary where
    the import is legal.
    """
    rejected: bool
    reason: str | None = None
    detail: str | None = None
```

`reason` is drawn from `RejectionReason.ALL`'s spelling **without importing it** ([D3](#d3)); a test
asserts the two agree, and that test lives in `tests/`, which may import both sides.

**And the fence is written in Stage 1, before the modules it constrains.** This is the P8 pattern
exactly — [P8-IMPLEMENTATION-CHECKLIST](P8-IMPLEMENTATION-CHECKLIST.md) Stage 1 is *"the guard that
would have caught F1, before the migration it constrains"*, and
[progress/P08-COMPLETE.md §2](progress/P08-COMPLETE.md) calls that guard *"the phase's real product"*.
Three tests:

1. `test_the_rules_package_is_inside_the_ai_fence` — AST import walk over `src/rules/`, using the
   existing `_imported_modules` helper, which already resolves relative imports so
   `from ..ai import gate` cannot slip past.
2. `test_the_rules_package_exists` — the guard that stops (1) becoming a no-op over an empty
   directory. P5's F3, P6's G1, and `test_the_notify_package_exists` are the established precedent.
3. `assert scanned > 0` inside (1) — fence 3's own idiom, in its own words: *"a fence that walked
   nothing would report no violations while checking nothing."*

**Also fix the specification while here.** [35 §2.1](35-testing-strategy.md) check 9 names six paths
of which five do not exist. P9 should not silently leave that. Recommend a note in that row recording
which paths are live and which phase creates each — `src/dedupe/` P10, `src/scoring/` P11,
`src/knowledge/` P15, `src/feedback/` P19 — so the next phase inherits a fence that says what it
covers rather than one that looks complete.

---

<a id="d2"></a>
## D2 — How many rejection reasons P9 ships, and what "counted" means

### 🔴 BLOCKING

Resolves [review F2](P9-IMPLEMENTATION-REVIEW.md) and question 3 of
[F12](P9-IMPLEMENTATION-REVIEW.md).

### What is actually at stake

[34 §P9](34-implementation-plan.md) Acceptance: *"**11 rejection reasons implemented and counted**"*.
[34 §P19](34-implementation-plan.md) Deliverables: *"`PreAIGate` with **11 counted reasons**"*.

The same eleven, claimed by two phases. Mapping [06c §3.2](06c-local-first-pipeline.md)'s table to
the phase that can produce each ([review §2.2](P9-IMPLEMENTATION-REVIEW.md) has the full table), P9's
five tasks reach **four**: `negative_term`, `structural_noise`, `too_short`, `bot_or_deleted`. The
other seven need a content hash (P10), a MinHash index (P10), comments (P11), a pre-score (P11), a
response cache (P19/P20), or an `ai_budgets` row (`0009`, P19).

**"Counted" is the harder half.** P9's DB row is `None`. `GateReport` — the object that counts — is
in `src/ai/gate.py`, across the R3 boundary ([D1](#d1)). P9 wires no caller ([D4](#d4)). A pure
function can *return* a reason; only a caller can *count* one.

**And `too_short` is not cleanly P9's either.** [06b](06b-deepseek-optimization.md) places
`min_chars: 80` in a prefilter that runs immediately before an AI call — after a body exists — and
[06c §3.2](06c-local-first-pipeline.md) writes it `len(text) < min_chars`. P9's rules see titles,
authors and keywords; the body arrives with P11.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | Implement all eleven in P9 | ❌ Builds P10, P11 and P19 in P9. Violates [lock §3](EXECUTION_MODE_LOCK.md) step 4 (*"Implement ONE phase only"*) and needs tables that do not exist until `0009` |
| **B** | Implement **four** predicates; **three** wired to data P9 can see; counting deferred to P19 | ✅ Honest, matches the five tasks exactly, leaves P19's deliverable intact |
| **C** | Implement **three**, defer `too_short` to P11 with its config key | ⚠️ Also honest, but throws away a predicate that is four lines and fully testable, and orphans `rules.min_chars`, which is in P9's Config row |
| **D** | Keep "11" and reinterpret it as "the vocabulary is complete" | ❌ This is the *"ticked as delivered while it was absent"* pattern the codebase has now recorded three times (fence 3, fence 4, F6) |

### ✅ Recommendation — **Option B**

Replace acceptance criterion A1 with, in P9's own words:

> **Four rejection predicates are implemented and unit-tested — `negative_term`, `structural_noise`,
> `too_short`, `bot_or_deleted` — each returning a reason string drawn from
> `RejectionReason.ALL`'s spelling. Three (`negative_term`, `structural_noise`, `bot_or_deleted`)
> operate on data P9's callers already have; `too_short` is text-agnostic and its production binding
> is P11's, when a body first exists. Counting these reasons into a report is P19's
> (`GateReport`), and P9 asserts only that its vocabulary is a strict subset of P19's.**

Ship `is_too_short(text: str, min_chars: int) -> bool` as a pure predicate with `rules.min_chars: 80`
(06b's value, cited rather than invented — [F12](P9-IMPLEMENTATION-REVIEW.md)), and **state in the
handover that nothing binds it to a body until P11.** That is the [DI17](DEFERRED-IMPROVEMENTS.md)
*"exists, nothing calls it on a timer yet"* shape, and the fix for it is to say so, not to hide it.

**And record the reconciliation.** [34 §P9](34-implementation-plan.md)'s acceptance row and
[34 §P19](34-implementation-plan.md)'s deliverables row cannot both stand. P9 owns the repair of its
own row; P19's is left alone, since it is the one that is correct.

---

<a id="d3"></a>
## D3 — Which rejection vocabulary, given two already ship and disagree

### 🟠 Needs assent

Resolves [review F3](P9-IMPLEMENTATION-REVIEW.md).

### What is actually at stake

| | `src/discovery/triage.py` (P6) | `src/ai/gate.py` (P1) |
|---|---|---|
| Status | **Live.** Counts into `run_events`, rendered on the run page | **Declared.** No writer, rendered by nothing |
| Count | 9 | 11 |
| Bot | `bot_author` | `bot_or_deleted` |
| Structural | five reasons — `hiring`, `giveaway`, `megathread`, `ama`, `engagement_bait` | one — `structural_noise` |
| Extra | `no_title` | — |

`gate.py`'s docstring claims the eleven were fixed early *"so the counters, the UI, and the holdout
audit all agree on the vocabulary from the start."* They do not. P6 shipped a second set without
reconciling.

**P9 is where a third appears by default**, and it is the last cheap moment to decide: `src/rules/`
has no callers today and three dependants tomorrow.

The genuine tension: [AD-10b](ARCHITECTURE_FREEZE.md) requires aggressive filters be *measured*, and
*"5–12% rejected as structural noise"* is not something an operator can act on, whereas *"8%
megathread, 1% hiring"* is. Granularity has real value. But `RejectionReason.ALL` is the vocabulary
`GateReport.to_dict()` renders and the holdout audit samples by, and five new top-level strings would
break both.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | `reason` from `RejectionReason.ALL`; the specific pattern in a **`detail`** field | ✅ Both properties. `GateDecision.detail` **already exists** for exactly this. Granularity is preserved and measurable; the counted vocabulary stays eleven |
| **B** | Five granular top-level reasons | ❌ Breaks `GateReport.to_dict()`'s fixed key set and the `NEVER_AUDITED` tuple; makes P9's vocabulary a superset of P19's, contradicting [D2](#d2)'s subset assertion |
| **C** | Adopt triage's nine | ❌ Adopts the vocabulary with no writer contract, and `no_title` is a metadata-only concern P9's rules do not have |
| **D** | Ship a third set and reconcile later | ❌ Three vocabularies. The problem this decision exists to prevent |

### ✅ Recommendation — **Option A**

`RuleResult(rejected=True, reason="structural_noise", detail="megathread")`. Eleven counted reasons,
unbounded granularity underneath, and `detail` is the field `GateDecision` already carries — so P19's
adapter is a field copy, not a translation.

**And triage's nine are not converged in P9.** `src/discovery/triage.py` is P6's, it is live on real
data, its metadata-only scope is deliberate and documented in its own docstring, and it is outside
P9's Files row. Rewiring it would change shipped behaviour on a path P9 is purely additive to — the
same reasoning that deferred [DI13](DEFERRED-IMPROVEMENTS.md) and [DI14](DEFERRED-IMPROVEMENTS.md).

**Register the convergence as DI23**, with the trigger: *"P11, which owns both the funnel counters
and the full-stage pre-score, and is therefore the first phase that must render both vocabularies on
one page."* The register runs DI1–DI19, DI21, DI22, with **DI20 reserved**
([DEFERRED-IMPROVEMENTS §1](DEFERRED-IMPROVEMENTS.md)) — and [D6](#d6) fills DI20 in the same phase,
so P9 lands **three**: DI20 (the WAL/mtime race), **DI23** (this convergence), and **DI24**
([review F6](P9-IMPLEMENTATION-REVIEW.md), `_triage_config`'s keyword shape).

---

<a id="d4"></a>
## D4 — `pipeline.rules_enabled`, and with it the manual guide

### 🔴 BLOCKING

Resolves [review F4](P9-IMPLEMENTATION-REVIEW.md) and [review §8](P9-IMPLEMENTATION-REVIEW.md). This
decision sets the phase's shape: stage count, mutation targets, and whether P9 is rollback-able.

### What is actually at stake

[34 §P9](34-implementation-plan.md) Rollback: `pipeline.rules_enabled: false`. Measured this session:
`config.yaml` has fourteen top-level blocks and **`pipeline:` is not one of them**; `rules_enabled`
appears nowhere in `src/`. P9's Files row marks **no existing module `~`**, so nothing reads it.

[lock §4](EXECUTION_MODE_LOCK.md) makes this bite: *"Rollback **executed and verified**, not merely
documented"* is a completion-checklist line. A flag with no reader cannot be executed.

The same gap produces [review §8](P9-IMPLEMENTATION-REVIEW.md)'s problem: P9 has no page, no
endpoint, no log line and no row, so `docs/testing/P09-testing.md` has nothing a non-developer can
observe — and [35 §1](35-testing-strategy.md) requires that it does.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | Ship the key in `config.yaml`; nothing reads it | ❌ Precisely what P6's `density_threshold` note forbids: *"a key nothing reads is a documented capability that does not exist, so it is absent rather than ignored."* And `test_the_density_heuristic_was_not_reintroduced` exists to enforce that principle |
| **B** | Defer the flag to P11, the first real consumer | ⚠️ Honest, and P7 took this shape for `min_confidence_alert` (D2, fenced by a test). But it leaves P9 with **no executable rollback at all**, and no manual guide |
| **C** | **`src/rules/` reads the flag itself**: disabled → every rule returns "not rejected" | ✅ The rollback becomes real, executable and unit-testable **inside P9's own boundary**. The manual guide gets its observable: flip the flag, re-run, see the verdict change |
| **D** | Wire `src/discovery/triage.py` to `src/rules/` for a real call site | ❌ Changes P6's shipped behaviour, touches a module outside the Files row, and contradicts [D3](#d3)'s deferral of convergence |

### ✅ Recommendation — **Option C**

A `RuleEngine` (or a module-level `evaluate(item, cfg)`) reads `rules_enabled` from its own config
dataclass. Disabled, it admits everything and short-circuits before any regex runs.

This makes three things true at once that are otherwise each unsolved:

1. **The rollback is executed and verified** — [lock §4](EXECUTION_MODE_LOCK.md) satisfied, with a
   unit test and a mutation (M16) proving a disabled engine cannot reject.
2. **The manual guide has an observable.** Paired with a small `python -m src.rules` demo that prints
   `reject · structural_noise · megathread` for a typed title, a non-developer can flip the flag and
   watch the verdict change. That satisfies [35 §1](35-testing-strategy.md)'s *"verified without
   reading code"* test, which options A and B do not.
3. **The flag is honest** — it is read, on the same commit it is introduced.

**On the block name:** use `pipeline.rules_enabled` as [34 §P9](34-implementation-plan.md) writes it,
not [31](31-execution-plan.md)'s `pipeline.local_qualification`
([review F9](P9-IMPLEMENTATION-REVIEW.md)) — 34 wins on authority, and per-phase flags are required
by [34 §1](34-implementation-plan.md)'s *"independently mergeable"* clause. A new `pipeline:` block is
created holding one key; P11 and P10 add theirs beside it.

**On the demo module:** it is outside the Files row, which [34 §1.1](34-implementation-plan.md)
declares *"a guide, not a contract"*. P5 took this latitude for its `feed` CLI and P6 for
`triage.py`, whose docstring records the precedent explicitly. Keep it small, keep it read-only, and
have it import **nothing** from `src.ai` so it does not become the leak fence 2 was written for.

---

<a id="d5"></a>
## D5 — The competitor rule's data source while P15 is unbuilt

### 🟠 Needs assent

Resolves [review F5](P9-IMPLEMENTATION-REVIEW.md).

### What is actually at stake

[34 §P9](34-implementation-plan.md) task 4: *"Competitor matching via the entity registry interface
(stub until P15; dictionary fallback)"*. Acceptance: *"a post using only a competitor alias
matches"*.

`EntityRegistry` is [34 §P15](34-implementation-plan.md)'s, six phases out. Its data lives in
`bkb_entities` / `bkb_entity_aliases`, created by `0007` in **P12**. The documented alternative — *"a
dictionary from the business profile"* ([06c §2](06c-local-first-pipeline.md)) — reads `projects`,
also `0007`. **P9's Config row names no competitor key.**

So the rule is fully testable and **entirely inert in production** for three phases. That is
intended. The risk is that inert and broken look identical: a competitor rule that matches nothing is
indistinguishable from a business with no competitors, and nothing on any page would say which.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | Protocol + `DictionaryEntityRegistry` fallback + a test asserting no production wiring exists | ✅ Testable now, honest about being inert, and P15 must **delete a test** to wire it — so the wiring is a deliberate act, not a discovery |
| **B** | Add `rules.competitors: []` to `config.yaml` as a stopgap source | ⚠️ Gives the rule a real source, but invents a config key no document specifies, and creates a second competitor source P15 must then deprecate |
| **C** | Defer `competitors.py` to P15 entirely | ❌ Drops a named deliverable and a named Files-row module. [lock §4.1](EXECUTION_MODE_LOCK.md): *"Scaling a phase down is the operator's decision, never Claude's"* |

### ✅ Recommendation — **Option A**

```python
class EntityRegistry(Protocol):
    def resolve(self, text: str) -> list[str]: ...
```

`src/rules/competitors.py` takes one by injection and defaults to a `DictionaryEntityRegistry`
constructed from an explicit mapping. Acceptance A3 is proved against an injected double holding a
canonical name plus aliases, which is a stronger test than a config round-trip would be.

The inertness guard follows P7's `test_min_confidence_alert_was_not_shipped` pattern, which
[PHASE-08-HANDOVER §4 T1](PHASE-08-HANDOVER.md) explicitly warns must be *"delete[d] deliberately
when P21 ships the kind, [not] discover[ed] failing"*. Same shape here, and the handover must carry
the same warning naming **P15**.

---

<a id="d6"></a>
## D6 — The flaky tests: D8, inherited from P8 and still open

### 🟠 Needs assent

[PHASE-08-HANDOVER §8](PHASE-08-HANDOVER.md) hands this to P9 in terms: *"P9 should either register
all three or fix them."*

### What is actually at stake

**Five occurrences in P8, on unchanged code:**

| Test | Times in P8 | Registered? |
|---|---:|---|
| `test_parse_speed_stays_inside_the_budget` | 2 | ✅ [DI18](DEFERRED-IMPROVEMENTS.md) |
| `test_does_not_write_to_the_database_it_checks` | 2 | ⚠️ **DI20 is reserved and never filled** |
| `test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs` | 1 | ❌ **Nowhere** |

All three are wall-clock or filesystem-timing assertions. All three pass in isolation. Two
consecutive P8 gate runs failed on two *different* ones.

The handover states the real cost precisely: *"a phase with a 'green after every stage' rule is being
trained to read a red suite as 'probably the flake' — which is exactly the reflex that lets a real
regression through."*

**P9 has a specific reason to care beyond inheritance.** Its own metric — *"rule evaluation < 1
ms/item"* — is a timing assertion. Shipping it as wall clock adds a **fourth** flake to a suite that
already has three, in the phase that was asked to fix them.

This session's full run was clean on all three (2 failed, both attributable to `config.yaml`; 1146
passed). One clean run is not evidence of absence — DI18 records 3/3 passes in isolation for a test
that has failed four times under load.

### Options

| | Option | Consequence |
|---|---|---|
| **A** | Register all three, fix none | ⚠️ Discharges the handover's letter. Costs a re-run per stage and leaves the reflex intact |
| **B** | **Fix the two timing assertions; register the filesystem race** | ✅ The two timing tests have the same root cause and the same fix, which DI18 already specifies: *"a monotonic or CPU-time budget with headroom, **not** a raised threshold"*. The WAL/mtime race is a different and larger problem |
| **C** | Fix all three | ⚠️ The WAL/mtime race is a real investigation of unknown size, in `scripts/check_schema.py`, unrelated to P9. Scope risk against a 2-day phase |
| **D** | Defer again | ❌ Second inherited phase. A decision deferred twice is a decision made by default |

### ✅ Recommendation — **Option B**

- **Fix** `test_parse_speed_stays_inside_the_budget` and
  `test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs` — both to `time.process_time()` or
  `time.monotonic()` with stated headroom. **This is not weakening an assertion**
  ([lock §3](EXECUTION_MODE_LOCK.md) step 6): the parser is not slow, the machine is busy, and DI18
  names the raised-threshold shortcut as the wrong fix explicitly.
- **Register** `test_does_not_write_to_the_database_it_checks` as **DI20** — filling the number that
  [PHASE-07-HANDOVER §8](PHASE-07-HANDOVER.md) proposed and that
  [DEFERRED-IMPROVEMENTS §1](DEFERRED-IMPROVEMENTS.md) has been holding open across two phases.
  Trigger: *"a third occurrence, or one in CI."*
- **Apply the same rule to P9's own A6 metric** — CPU time, never wall clock. A fourth flake
  introduced by the phase asked to remove three would be its own indictment.

**Scope note, honestly:** these two fixes are outside P9's Files row. They qualify under
[lock §8](EXECUTION_MODE_LOCK.md) — the improvement relates directly to P9 (its own metric shares the
defect class), does not expand scope, does not redesign architecture, and is small. If the operator
disagrees, **Option A is a legitimate answer** and costs only re-runs. What is not legitimate is a
third deferral without a decision.

---

<a id="preflight"></a>
## ⚠️ Not a decision — an action required before Stage 0

`git status --porcelain` returns ` M config.yaml`. Three hunks in the `notify:` block, left by P7's
live Telegram verification: `enabled: false → true`, `transport: 'null' → bot_api`, and a **real chat
identifier** where the committed value is empty.

```powershell
git checkout -- config.yaml
```

**Leave `.env` alone** — it is git-ignored and the token is worth keeping.
[P8-IMPLEMENTATION-CHECKLIST step 0.2](P8-IMPLEMENTATION-CHECKLIST.md) gives the identical
instruction for the identical state; this is the second consecutive phase to find it.

Two reasons it matters more in P9 than it did in P8:

1. **The suite is red until it is reverted.** Measured this session: `2 failed, 1146 passed, 2
   skipped`, both failures asserting the shipped default is off. `1146 + 2 = 1148`, reconciling
   exactly with [PHASE-08-HANDOVER §6](PHASE-08-HANDOVER.md)'s baseline.
2. **P9 edits `config.yaml`** — it is the only phase artefact the Config row requires, and P8 never
   touched the file. Staging it with these hunks present would put a real chat identifier in a
   **public** commit. That is an **R15** violation, and [lock §5.2](EXECUTION_MODE_LOCK.md) is
   unambiguous about the remedy: *"not fixed by a later commit — it is fixed by rotating the
   credential."*

P9's checklist must therefore re-run the H1/H2 hygiene patterns against `git diff --cached`
**immediately before the `config.yaml` commit**, not only at the end of the phase.

---

## Summary — what is needed to start

| | Needed | From |
|---|---|---|
| 1 | `git checkout -- config.yaml` | **Action**, not a decision |
| 2 | **D1** — Option B (neutral `RuleResult`; fence 2 in Stage 1) | 🔴 Operator, in writing |
| 3 | **D2** — Option B (four predicates, three wired, counting is P19's; A1 rewritten) | 🔴 Operator, in writing |
| 4 | **D4** — Option C (`src/rules/` reads `pipeline.rules_enabled`; demo module for the guide) | 🔴 Operator, in writing |
| 5 | **D3** — Option A (`RejectionReason` spelling + `detail`; triage convergence → DI23) | 🟠 Assent |
| 6 | **D5** — Option A (Protocol + dictionary fallback + inertness guard) | 🟠 Assent |
| 7 | **D6** — Option B (fix two timing tests, register DI20) | 🟠 Assent |

**Once D1, D2 and D4 are settled**, `docs/P9-IMPLEMENTATION-CHECKLIST.md` and
`docs/testing/P09-testing.md` are written against the settled answers, and implementation begins at
Stage 0. **They are deliberately not written yet** — a checklist authored against unapproved
decisions is a plan for a phase nobody agreed to.
