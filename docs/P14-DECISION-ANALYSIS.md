# P14 — Decision Analysis

**Phase:** P14, `analyze_business` · **Written:** 2026-08-16
**Companion to:** [PHASE-14-COMPLETION-REPORT.md](PHASE-14-COMPLETION-REPORT.md) ·
[PHASE-14-HANDOVER.md](PHASE-14-HANDOVER.md)

> The reasoning behind **V-1**, the phase's stated dependency, and the five clarifications P14 files.
> Same role as [P11-DECISION-ANALYSIS.md](P11-DECISION-ANALYSIS.md) and
> [P12-DECISION-ANALYSIS.md](P12-DECISION-ANALYSIS.md): the completion report says *what*, this says
> *why*. (P13 recorded its four clarifications inline in
> [34 §P13](34-implementation-plan.md) instead; this returns to the P11/P12 shape, because V-1 needs
> more room than a plan-row note.)
>
> **None of the five is a [freeze §11](ARCHITECTURE_FREEZE.md) amendment**, and only one is a
> [§11.1](ARCHITECTURE_FREEZE.md) reconciliation candidate. No technology, table, decision or
> dependency changes; no migration is added; the chain stays at seven revisions of ten.
>
> **All five were settled before the first line of code**, which is the ordering
> [P12](P12-DECISION-ANALYSIS.md) records as load-bearing.

---

## V-1 — DeepSeek direct, with OpenRouter as failover

**Resolved 2026-08-16, before any provider code was touched.** This is
[34 §P14](34-implementation-plan.md)'s second dependency — *"Depends on P13, **P0 (V-1 provider
decision)**"* — and [PHASE-13-HANDOVER §8](PHASE-13-HANDOVER.md) flags it 🔴 as *"the one entry
condition that is not about P13"*.

### The decision was already made; V-1 was its evidence

[Freeze §5](ARCHITECTURE_FREEZE.md) fixes the technology row:

> | AI provider | **DeepSeek V4 Flash (direct), OpenRouter failover** | Vendor SDK |

[31 §3.3](31-execution-plan.md) V-1 reads *"DeepSeek direct vs OpenRouter — same 8-item enrichment on
both"*, and its own note says the quiet part out loud:

> ▶ [27 §6.1](27-architecture-review.md) recommends direct; **this is the evidence**.

So V-1 is a **validation of a frozen choice**, not an open selection between two candidates. That
distinction decides how P14 may treat it. [Lock §2](EXECUTION_MODE_LOCK.md) prohibits *"a new
technology evaluation or framework comparison"* outright, and [freeze §5](ARCHITECTURE_FREEZE.md) is
closed. **Producing a cost/latency/maintenance trade-off study would therefore be the one artefact
Execution Mode forbids** — and it would be a study whose conclusion the freeze has already recorded.

### ⚠️ Correction, 2026-08-16 — the key does not come from `.env`, and this section first said it did

An earlier draft of this section, and of the manual guide, framed the live measurement as **blocked**
because there is no `DEEPSEEK_API_KEY` in `.env`. **That was wrong**, and the codebase says so
directly: `src/ai/credentials.py:147` describes the environment variable as *"local-development
convenience"* and states that **"the Settings page remains the intended path."**

The key is entered at **`/settings/ai`**, validated against the provider *before* it is stored
(`set_key(..., validate=True)` — a rejected key is never persisted), and encrypted at rest under
**AD-12**. So the live 8-item verification is **not blocked by the absence of a file**; it is
available to any operator with a key and a browser, and
[`docs/testing/P14-testing.md`](testing/P14-testing.md) T5 now walks through exactly that: enter the
key, click **Validate & save**, click **Test connection** to confirm the response came from the real
provider, then run T5–T8.

What remains true is narrower and is the only claim this section now makes: **P14's automated suite
could not take the measurement**, because the suite runs offline by design (`block_network`,
[35 §2.3](35-testing-strategy.md) check 6) and no key is configured on this host. That is a statement
about the *test run*, not about the product.

### Why the automated measurement could not be taken here

[SPRINT-0-MEASUREMENTS §B1](SPRINT-0-MEASUREMENTS.md) deferred V-1 for exactly one reason:

> | **B1** | **No `DEEPSEEK_API_KEY` / `TELEGRAM_BOT_TOKEN`** | Track B (12 measurements) and V-1
> deferred | Add both to `.env`. **Does not block P1–P22.** |

and §278 lists the blast radius:

> | **`DEEPSEEK_API_KEY` absent from `.env`** | M-1, M-2, M-3, M-4, M-6, M-11, M-12 and V-1 — every
> token, cost and behaviour measurement |

**Re-measured on this host, 2026-08-16.** No DeepSeek or OpenRouter credential is configured by
**either** route — `.env` carries only `APP_SECRET_KEY` and `TELEGRAM_BOT_TOKEN`, and the `settings`
table holds no stored key (`API keys stored in cleartext: 0`, and no encrypted one either).

⚠️ **Read B1 as written, though: it says *"Add both to `.env`"*, and for the DeepSeek key that
instruction is out of step with the shipped product** — `credentials.py` treats the environment
variable as a development fallback and names the Settings page as the intended path. B1 is a P0
document and correcting it is not P14's to do; the discrepancy is recorded here so the next reader
does not repeat the mistake this section made.

So the automated suite could not take the measurement, and **B1 remains open** — but the *operator*
can close it at any time through the UI, without touching a file. [31 §109](31-execution-plan.md)'s
*"V-1 deferred with Track B"* stands only until someone runs the manual guide with a real key.

### What P14 does instead

**P14 proceeds on the frozen §5 row and adds no provider code.** This is cheap because the work V-1
would have gated is *already shipped*: `src/ai/providers/` has carried `deepseek.py`,
`openrouter.py`, `openai.py`, `openai_compatible.py`, a `registry.py` and a `router.py` since **P4**,
and `AIService.__init__` already reads `ai.provider` with `ai.fallbacks` behind a `HealthRegistry`
circuit breaker. **P14 writes no provider, selects no provider, and changes no default.** It calls
`AIService`, which is [R2](ARCHITECTURE_FREEZE.md)'s only permitted path.

The consequence for this phase's acceptance is stated rather than hidden:

- **In the automated suite, cost `< $0.05` and the `ai_calls` count are verified against
  `FakeProvider` and the shipped price tables.** That proves the **control flow** — the lenient
  envelope validates in one attempt, the repair ladder is not entered, one row is written — and the
  **accounting arithmetic and display path**. It does **not** prove that a real DeepSeek response
  validates on the first attempt, and the token counts are fictional, so it is **not an invoice**.
- **Those two gaps are closed by the manual guide, not by another test.**
  [`testing/P14-testing.md`](testing/P14-testing.md) **T5–T8** are marked `[needs key]` and walk the
  operator through entering the key at `/settings/ai`, confirming with **Test connection** that the
  answer came from the real provider, and then re-checking the one-call and cost criteria against it.
  The sign-off table carries an explicit *"Did you enter a DeepSeek API key on the Settings page?"*
  box, so a skip is **recorded rather than silent**.
- **Running T5–T8 with a real key is what closes B1 and V-1**, and it needs no code change:
  `provider_comparison()` and the `ai_calls` ledger already record everything V-1 asks for — latency,
  reported cost and `prompt_cache_hit_tokens`.

### What was rejected

| Rejected | Why |
|---|---|
| Write the cost/latency/maintenance comparison from published price tables | It is a *technology evaluation*, prohibited by [lock §2](EXECUTION_MODE_LOCK.md), and substituting arithmetic over vendor pages for the live 8-item run V-1 specifies would put a **measurement-shaped document with no measurement in it** into a repository whose whole amendment path turns on that distinction |
| Buy a key and run V-1 inside P14 | Spending the operator's money is the operator's call, and V-1 is a **P0** item ([31 §3.3](31-execution-plan.md)), not a P14 deliverable. P14 does not absorb another phase's work |
| Switch the primary to OpenRouter for convenience | [Freeze §5](ARCHITECTURE_FREEZE.md) is closed, and changing it needs a **failed measurement** — the one thing unavailable here |
| Declare V-1 "answered" because the freeze answers it | It is answered *as a decision* and unanswered *as a measurement*, and saying so is the difference between a record and a claim. Both halves are stated above |

**Recommendation, with its evidence: DeepSeek V4 Flash direct as primary, OpenRouter as failover —
unchanged from the freeze, un-remeasured, and explicitly labelled as such.**

---

## D1 — the golden-set acceptance criterion is not satisfiable in P14

**Clarification. No technology, table or decision changes.**

### What the document asks for

[34 §P14](34-implementation-plan.md)'s Acceptance row ends: *"**golden-set comparison shows no
regression vs the staged baseline**"*.

### The measurement

Taken 2026-08-16 across `tests/`, `docs/` and `scripts/`:

```
Get-ChildItem -Recurse -Filter "*golden*" -Path tests,docs,scripts   →   (no matches)
tests/baseline/  →  api_contract.json · api_scrape_contract.json · db_fingerprint.json
                    export_baseline.csv · index_baseline.html · index_pre_ux.html
```

**There is no golden set, and there is no staged baseline to compare against.** Nor could there be:

1. [35 §185–189](35-testing-strategy.md) puts `golden_leads.jsonl` at **40 items (P20) → 100 items
   (P25)** — it is P20's artefact, six phases away.
2. [Freeze §4.1](ARCHITECTURE_FREEZE.md) creates `golden_items`, `golden_runs`, `golden` anything in
   **`0010`, with P25**. The head is `0007`.
3. A golden set for *this* stage would be a set of website→BKB pairs, and the phase that first
   produces a BKB is the one being written.

### The resolution

**[35 §6](35-testing-strategy.md)'s P14 row is the operative gate, and it does not name the golden
set.** It reads, in full:

> | **P14** | **Exactly 1 `ai_calls` row**; < $0.05; section isolation | See 23 sections render; cost
> chip shows one call |

Three criteria, all three built and all three tested. The golden-set clause is read as what it is —
a forward reference to **P20**'s regression harness, which is the first phase with both a golden set
and a prior BKB to regress against. P14 ships the thing that makes it possible later: a
**deterministic, fixture-driven `analyze_business` whose output is a pure function of
`(site_text, local_signals, prompt_version)`**, so a golden pair recorded now stays meaningful.

Inventing a golden set inside P14 was rejected on P10's precedent (its D7 entry in
[freeze §11.1](ARCHITECTURE_FREEZE.md)): a baseline generated by the code under test and then
asserted against measures nothing, and it would retire the question — which is worse than the gap,
the same reasoning by which [P8 shipped no test for DI22](DEFERRED-IMPROVEMENTS.md).

---

## D2 — P14 supplies `pain_phrase`'s data and does **not** wire the component

**Operator decision, taken 2026-08-16 before `src/knowledge/` existed.**

### The conflict

[PHASE-13-HANDOVER §6](PHASE-13-HANDOVER.md) says:

> | **P14** | `test_the_three_absent_pre_score_components_are_still_absent` | … When P14 writes
> `pain_points.phrases_json`, update it **with** `WEIGHTS` and `prescore()`; a seventh weight
> **rescales every stored total** |

while [34 §P14](34-implementation-plan.md)'s **Files** row names no file under `src/scoring/`:

> `src/ai/{service,schemas}.py` ~; `src/ai/prompts/business_intelligence.v1.md` ~;
> `src/knowledge/{bkb,sections}.py` +; `src/db/repositories/knowledge.py` +;
> `src/orchestration/handlers/website.py` +

Both cannot hold.

### What the constant actually says

`src/scoring/__init__.py:179`, shipped by P11:

```python
#: … Each entry now names the phase
#: that supplies the **data**, not the phase that supplies the column.
ABSENT_COMPONENTS: dict[str, str] = {
    "pain_phrase": "P14 — `pain_points.phrases_json` is written by analyze_business",
    ...
}
```

**The entry names P14 as the *data* supplier, and the docstring says in as many words that this is
not the same as the phase that wires it.** The handover's sentence is a warning that the three must
move *together* when they move — not an instruction that P14 must move them.

### Why wiring in P14 would be DI24

`projects` still has no writer; [PHASE-13-HANDOVER §3.5](PHASE-13-HANDOVER.md) confirms **P16** is
still the first one. So a `pain_phrase` component wired in P14 would read `project.pain_points` for
every real lead, find nothing, and contribute a structural zero until P16 — which is
[DI24](DEFERRED-IMPROVEMENTS.md) precisely, *"the nine-component score cannot have two components
structurally zero"*, and it is the defect
[P11's D1/D2](P11-DECISION-ANALYSIS.md) refused when it declined to ship the three at `0.0`. It is
also P6's `density_threshold` precedent: **a key nothing reads is a documented capability that does
not exist.**

And it would rescale twice. A seventh weight now and an eighth at P16 means **every stored pre-score
total is renormalised twice** ([PHASE-11-HANDOVER §4](PHASE-11-HANDOVER.md) T2), for no reading
gained in between.

### What ships

- P14 **writes** `pain_points.phrases_json` from `how_people_phrase_it`. The data is real and
  queryable from the moment the phase lands.
- `WEIGHTS` stays at **six** components. `prescore()` is untouched. No file under `src/scoring/` is
  edited except the one `ABSENT_COMPONENTS` value.
- **The `"P14"` prefix stays**, and the value gains a clause: *"the component waits for P16, when the
  first `projects` row makes it readable (D2)"*. `pain_phrase` and `subreddit_fit` then land in
  **one** rescale, at P16, instead of two.

### ⚠️ A correction made during validation, recorded rather than quietly fixed

The first implementation of this decision **re-pointed the label to `"P16"`**, and
`tests/test_schema_0007.py::test_the_three_absent_pre_score_components_are_still_absent` failed on
`assert ABSENT_COMPONENTS["pain_phrase"].startswith("P14")`.

**The test was right and the edit was wrong.** This dict's own docstring, shipped by P12, fixes the
convention: *"Each entry now names the phase that supplies the **data**, not the phase that supplies
the column."* Under that convention `pain_phrase` **is** P14's — `analyze_business` writes
`phrases_json`. Re-pointing it to P16 silently changed a shipped convention to record a fact the
value text could carry on its own.

So the prefix was restored and the clause added instead. **No test was weakened and P12's assertion
is untouched** — which is the outcome [lock §3](EXECUTION_MODE_LOCK.md) step 6 asks for: fix the root
cause, never the assertion. The root cause was the edit.

---

## D3 — DI33 is closed by telling the model what it did not see

**[DI33](DEFERRED-IMPROVEMENTS.md) names P14 as its owner: *"the first consumer … the phase that
learns whether `analyze_business` actually needs the markup signals on a cache hit"*.**

### The finding, restated

An L1 cache hit returns `extracted_text` and no markup, so `tech_markers`, `structured_data`,
`social_links` and `nav_taxonomy` come back `()` while `competitors` and `pricing` still work.
`SiteSignals.markup_seen` is `False` on that path. [PHASE-13-HANDOVER §4 T1](PHASE-13-HANDOVER.md)
states the danger in one sentence: *"four empty tuples with no explanation read identically to 'this
site has none of these'"*, and a consumer that cannot tell those apart **records "this company uses
no analytics" as a fact about the business.**

### The answer, now that a consumer exists

P14 is that consumer, and the answer is **no — `analyze_business` does not need the markup signals,
and it must not be told they were empty.**

The prompt's `local_signals` block is *facts, not questions*
([PHASE-13-HANDOVER §3.3](PHASE-13-HANDOVER.md), [06 §2.2](06-ai-pipeline.md)). So:

- when `markup_seen` is **True**, the four markup-derived keys are rendered as today;
- when `markup_seen` is **False**, the four keys are **omitted from the payload entirely** and a
  single line is rendered in their place: `"markup_not_observed": true`, with the prompt's Rules
  section gaining one clause telling the model that an omitted signal is *unobserved*, never
  *absent*, and must not be reported as a negative finding.

That is DI33's third option — *accept the degradation and mark it* — carried through to the
consumer, and it needs **no column, no migration, and no re-fetch**, so it defeats neither
[freeze §4.1](ARCHITECTURE_FREEZE.md) nor P13's **G2** (zero fetches on an L1 hit).

`test_a_cache_hit_reports_that_it_saw_no_markup` is **kept and extended**, per
[PHASE-13-HANDOVER §6](PHASE-13-HANDOVER.md)'s instruction not to simply delete it: it now also
asserts that the rendered prompt for a cache hit contains no `tech_markers` key and does contain
`markup_not_observed`, so signals silently going empty is still something a test notices.

**DI33 is closed.**

---

## D4 — "exactly one `ai_calls` row" is what makes per-section validation an *envelope* decision

**Clarification. It changes no document; it records why `src/ai/schemas.py` changes shape.**

Two of P14's acceptance criteria pull against each other on the current code:

> **Exactly one** `ai_calls` row with `stage='business_intelligence'` per analysis
> · a forced schema failure in one section leaves the other 22 persisted

`AIService._record_ai_call` writes **one row per attempt**, and `_execute`'s repair ladder retries on
any `output_model` validation failure. `BusinessKnowledgeOut` today types `buyer_personas`,
`pain_points`, `buying_signals` and `competitor_references` as lists of strict models with slug
validators — so **one malformed slug in one persona fails the whole envelope, sends a 23-section
response down the repair ladder, and writes a second and a third `ai_calls` row.** The two criteria
are then jointly unsatisfiable.

**The resolution is that validation happens in two places, not one.**

- **The envelope stays lenient.** `BusinessKnowledgeOut` keeps `extra="allow"` and every field
  defaulted, and the four typed lists become `list[dict]` at the envelope level. A well-formed JSON
  object therefore *always* validates, one attempt, **one `ai_calls` row**. The repair ladder is
  reserved for what it was built for — malformed or truncated JSON, which no per-section logic can
  rescue.
- **The sections are strict.** `src/knowledge/sections.py` validates each of the 23 independently
  against its typed model (`PersonaOut`, `PainPointOut`, `BuyingSignalOut`, `CompetitorOut` and the
  rest, all of which already exist in `src/ai/schemas.py` and are **kept, not replaced**). A section
  that fails is persisted with `status='incomplete'` and its validation error; the other 22 persist
  normally.

This is why `src/ai/schemas.py` is in the phase's **Files** row with a `~`. The strict models are
not weakened — they are **moved from the envelope to the section boundary**, which is where
per-section failure isolation requires them to be, and every one of them keeps its slug validator.

---

## D5 — the section models moved into `src/knowledge/`, because R3 requires it

**Found by the fence, during implementation, not during review.**

The first draft of `src/knowledge/sections.py` imported its 17 strict models from
`src/ai/schemas.py`. That is a **[R3](ARCHITECTURE_FREEZE.md) violation**: the rule reads
*"`rules/`, `dedupe/`, `scoring/`, **`knowledge/`**, `feedback/`, `discovery/policy.py` never import
`src.ai`"*, and `src/knowledge/` is one of grep fence 2's six paths.

### What ships

The models are **defined in `src/knowledge/sections.py`**. The four that P1 had put in
`src/ai/schemas.py` — `PersonaOut`, `PainPointOut`, `BuyingSignalOut`, `CompetitorOut` — **had no
importer anywhere** (verified by grep across the tree before the move), so they were **moved, not
copied**: one definition, not two.

This is the right home on the merits and not merely a way around the fence:

* **`src/ai/schemas.py` owns the envelope** — what a *provider response* may look like.
* **`src/knowledge/` owns the sections** — what the *knowledge base is*. A BKB whose definition
  lived in the AI layer would depend on the thing that happens to fill it, which is precisely the
  coupling R3 exists to prevent.

`AIService` is likewise **injected** into `bkb.analyze` rather than imported — the handler
constructs it on the other side of the fence. `SLUG_PATTERN` is the one thing genuinely duplicated
across the boundary, five lines of regex, and
`test_the_slug_pattern_agrees_across_the_fence` makes the two agreeing a test rather than a hope: a
pattern that drifted would produce a persona the enrichment path can never match, with nothing
failing.

### Two other things the fences caught before review did

1. **`test_no_wire_format_details_outside_ai`** rejected a `BKBSettings` dataclass reading the
   phase's one config key, on the grounds that *business logic must not know what the provider's
   wire knobs are*. It was right. The key is read by `AIService.analyze_business_call`; the
   knowledge layer passes no budget at all. **The Config row is still honoured** — the key ships,
   is read, and its default is asserted where it is read.
2. **Fence 2 was never extended to `src/knowledge/`.** `test_the_scoring_package_is_inside_the_ai_fence`
   says *"`src/knowledge/` is P15's"*, which was true when written — but **P14 is the phase that
   creates the package**, and a fence extended one phase after the package appears is a fence that
   was absent for exactly the change that introduced the risk. That is P4's and P7's recorded defect,
   a fence ticked as delivered while missing. P14 adds
   `test_the_knowledge_package_is_inside_the_ai_fence` and its existence guard. **Fence 2 now covers
   5 of 6**; `src/feedback/` is P19's.

---

## D6 — DI37, found by accident and deliberately not fixed here

While writing the handler tests, five of them took **21.6 seconds each**. The cause is not P14's
code: `AIService._record_ai_call` writes through its **own** session, so a caller holding an open
write transaction stalls that insert for the whole `busy_timeout` and then loses the row to the
`except Exception` that keeps recording from breaking the call it records.

The cost data is the loss that matters — `usage_today()` seeds the **daily cap** from `ai_calls`, so
a stage that lost its rows would under-report spend and the cap would be looser than it looks.

**P14 is immune by construction**: `bkb.analyze` makes its call **before** its first write, and
`test_the_model_call_happens_before_the_first_write` fails if a refactor reorders them. The general
fix is P4's recorder, shared by every stage, and both candidate shapes change what an `ai_calls` row
means on rollback — so it is [DI37](DEFERRED-IMPROVEMENTS.md), with the cheap half (log the dropped
row at WARNING rather than DEBUG) named in its trigger.

---

## Summary

| | Decision | Kind | Costs |
|---|---|---|---|
| **V-1** | DeepSeek direct, OpenRouter failover — frozen choice, **measurement still deferred under B1** | Dependency resolved | No key on this host; the live manual step is marked and skippable |
| **D1** | The golden-set criterion is P20's; [35 §6](35-testing-strategy.md)'s three-criterion row is the gate | Clarification | Stated, not silently dropped |
| **D2** | P14 supplies `pain_phrase` data; **P16** wires it | Operator decision | One `ABSENT_COMPONENTS` value gains a clause. **The `P14` prefix stays** — a first attempt to re-point it to `P16` broke P12's assertion and was reverted, not accommodated |
| **D3** | DI33 closed — omit unobserved signals and say so in the prompt | DI closed | One prompt clause, one dict branch |
| **D4** | Lenient envelope, strict sections | Clarification | `src/ai/schemas.py` changes shape, no model is weakened |
| **D5** | Section models live in `src/knowledge/`; fence 2 extended to it | **R3 compliance** | Four models moved; `SLUG_PATTERN` duplicated and pinned |
| **D6** | DI37 opened; P14 immune by call-before-write ordering | DI opened | One ordering test |

**No [freeze §11](ARCHITECTURE_FREEZE.md) amendment. No migration. No new table. No new
technology.** The chain stays at `0007`, seven revisions of ten.
