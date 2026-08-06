# 02c — Final Architecture Review: Knowledge, Learning & Memory

> Research conducted 2026-07-30, ahead of implementation. Eleven topics, each ending in an
> **Adopt / Adopt-with-limits / Defer / Reject** decision with its reasoning.
>
> **Six of the eleven are partial or full rejections.** This pass deliberately looked for reasons
> *not* to add machinery. Companion documents: [02](02-research-findings.md),
> [02a](02a-competitor-analysis.md), [02b](02b-research-2026-07.md).

---

## 0. Headline: research found one correctness defect

Before the topic-by-topic review, the finding that justified this pass on its own.

**The learning loop as designed would degenerate.** The adaptive budget's `YieldCurve`
([06f §2.3](06f-adaptive-budget.md)) is fitted from `lead_labels` — but labels only exist for leads
the operator *sees*, and the operator only sees leads that were **admitted** to AI. The curve would
therefore be fitted exclusively on the region above the admission cut, learn that region's shape,
and re-confirm the gate that produced it. Each cycle narrows. Nothing in the design would notice,
because precision — measured only on admitted leads — would look fine or improve.

This is the textbook **degenerate feedback loop**: the model's own output determines the data it
learns from next, and the literature's named mitigations are *exploration*, *exposure-aware
modelling*, and *candidate-pool growth*.

**We already built the exploration channel and then discarded its output.** The holdout audit
([06c §6](06c-local-first-pipeline.md)) enriches 2% of *rejected* candidates — precisely the
random exploration of the un-admitted region the mitigation calls for. But `gate_audits` stores only
aggregate counts (`sampled`, `would_have_qualified`); the individual audited items never become
visible leads, so they can never be labelled, so they contribute **nothing** to the curve.

**→ Fix (Adopt):** holdout-enriched items become **real, labellable leads**, flagged
`source='holdout_audit'`. Their labels feed the yield curve on equal footing with admitted leads.
The audit keeps its measurement role and gains its learning role. Full specification in
[06i §2.3](06i-feedback-and-memory.md).

The cost is a flag column and a UI badge. Without it, the system would get *worse* at finding leads
the longer it ran, while every dashboard metric said it was improving.

---

## 1. Knowledge Lifecycle Management

**What it is.** Whether stored facts expire, decay, or become stale, and what the system does when
they do.

**Production practice.** The consistent finding is that **staleness degrades silently**: latency
stays flat, retrieval works, standard metrics score well, right up until the system confidently
returns something that stopped being true months ago. A reported 60% of enterprise RAG failures
trace to freshness rather than retrieval quality. The named failure mode is that a system
*"assigns the same confidence to stale knowledge as to current knowledge, because from its
perspective all knowledge is equally present."* Mature systems therefore **measure staleness,
monitor it continuously, and make outdated information impossible to serve confidently.**

Some work proposes continuous **confidence decay** — Ebbinghaus-style exponential functions with
access reinforcement.

| | |
|---|---|
| Benefit | Prevents silent rot; makes age visible; stops old inferences masquerading as current |
| Drawback | Decay functions produce numbers nobody can interpret or verify |
| Complexity | Staleness flags: trivial. Decay curves: moderate, plus a permanent tuning burden |
| Cost | Zero (both are local arithmetic) |

**→ ADOPT: binary, per-section-type staleness with an explicit threshold.**
**→ REJECT: continuous confidence decay.**

An ICP does not become 3% less true each week. It is either still right or the business changed —
and *which* is knowable by checking the website fingerprint, not by extrapolating a curve. A decay
function would silently lower scores for no observable reason, which is the opposite of the
explainability this platform is built around. A `last_verified_at` per section plus a per-type
staleness threshold gives the same protection, is checkable, and can be rendered as *"personas last
verified 94 days ago"* — a sentence an operator can act on.

**→ REJECT: expiring Reddit discoveries.** A lead is a historical fact — *this person wrote this on
this date* — and does not become false. Its *actionability* decays, and that is already the
`recency` component of the score. Deleting old leads would destroy the evidence base that
calibration (§10) and pattern discovery (§7) are computed from. Leads and their analyses are
retained indefinitely; the retention policy purges `ai_calls` and `http_cache`, never evidence
([06i §4](06i-feedback-and-memory.md)).

Specification: [06h §2](06h-knowledge-lifecycle.md).

---

## 2. Evidence-Based Knowledge

**What it is.** Requiring every stored conclusion to reference the material it came from.

**Production practice.** Traceability work converges on connecting each output back to *"the data,
model versions, prompts, outputs, access events and approvals"* so that the path can be
reconstructed. In knowledge bases specifically, the failure mode is unattributed assertions that
become indistinguishable from sourced facts once written.

**→ ADOPT: already the design, with one gap closed — evidence gains a source type.**

`bkb_evidence` already stores verbatim spans validated as literal substrings
([05 §5.1a](05-database-plan.md)). What it assumes is that evidence is always a *website* span. Once
knowledge can also arrive from Reddit or an operator (§3), that assumption breaks.

```
source_type: website | reddit_post | reddit_comment | operator | ai_inference
```

**The answer to "should unsupported AI assumptions ever become permanent?" is: no — but they should
be storable.** Refusing to store inference would gut the knowledge base, because much of an ICP is
legitimately inferred rather than quoted. The correct treatment is three rules:

1. `ai_inference` is a **first-class, visibly-marked** evidence type, never a silent default.
2. A claim whose only evidence is `ai_inference` **can never be auto-promoted** to confirmed status,
   and renders with a distinct marker.
3. Any claim can be promoted by an operator, which changes its evidence to `operator` and records
   who and when.

This makes the distinction between *observed* and *inferred* a property of the data rather than of
whoever remembers it. Specification: [06h §3](06h-knowledge-lifecycle.md).

---

## 3. Business Knowledge Evolution

**What it is.** Whether the knowledge base should learn from months of Reddit monitoring rather than
remaining what the website said on day one.

**Production practice.** Voice-of-customer analytics is the mature analogue: systems that
*"auto-discover topics from open-text responses and organise them into a hierarchy that evolves as
new feedback arrives."* The consistently reported timeline is that **a reliable picture of recurring
themes develops over four to six weeks** of meaningful volume — not from individual observations.

**→ ADOPT, as a widening of the existing `bkb_suggestions` mechanism — not a new subsystem.**

The mechanism already exists ([06e §7](06e-business-knowledge-base.md)) for competitor aliases and
pain phrasings. Research supports extending it to the full set: new terminology, new competitors,
new customer language, new objections, new buying signals.

**The constraint that makes this safe: only aggregate patterns propose, never single observations.**
One Reddit post mentioning a competitor must not become business knowledge. A suggestion is raised
only when the same pattern appears **≥3 times, in ≥2 distinct dedup groups, within one project**.

The dedup requirement is not incidental: without it, a single viral thread and its forty reposts
would manufacture a pattern by itself. The threshold is deliberately unreachable on small projects —
a project with 40 total leads will never raise a suggestion, and **that is correct behaviour, not a
defect.** Knowledge accretion is a property of sustained use.

**→ REJECT: automatic application** (unchanged from [06e §7](06e-business-knowledge-base.md)).
**→ ADOPT: a write-path guard against regeneration deleting learned knowledge** — see §5.

Specification: [06h §4](06h-knowledge-lifecycle.md).

---

## 4. Human Feedback Learning

**What it is.** Using operator actions — useful / ignore / false positive / wrong persona — to
improve future results without training a model.

**Production practice.** Agent-in-the-loop frameworks using pairwise preferences, adoption signals
and relevance ratings report meaningful retrieval and precision gains while *reducing* retraining
frequency. Separately, the learning-to-rank literature is emphatic that **implicit feedback is
biased** — position bias most strongly — and that correcting it requires either propensity weighting
or high query repetition.

**→ ADOPT: feedback influences ranking weights, calibration, and knowledge suggestions.**
**→ ADOPT: the degeneracy fix in §0 — without it the rest is counterproductive.**
**→ REJECT: a learned ranker, online training, or propensity-weighted LTR.**

The rejection is arithmetic, not preference. The yield curve does not activate below 200 labels
([06f §2.3](06f-adaptive-budget.md)). An internal team labelling on the order of tens of leads a week
reaches 200 in a matter of months. A learned ranking model needs at least an order of magnitude more
than that to beat hand-set weights, and propensity-weighted LTR assumes repeated queries we do not
have. **We would be fitting a model on a few hundred points to replace eleven interpretable weights
— trading the explainability this platform is built around for a near-certain overfit.**

Deterministic weights, adjusted by an operator who can see the breakdown, plus isotonic calibration,
is the correct ceiling for this data volume. This remains true even if usage grows tenfold.

**→ ADOPT: label *reasons*, not just labels.** `wrong_persona` and `wrong_pain_point` are worth more
than an undifferentiated rejection: a persona repeatedly mis-matched is evidence the *persona
definition* is wrong, which feeds §3 rather than merely lowering a score.

Specification: [06i §2](06i-feedback-and-memory.md).

---

## 5. Knowledge Freshness

**What it is.** Whether different knowledge types deserve different refresh strategies.

**→ ADOPT: per-section-type refresh policy, event-triggered wherever possible.**

The current plan has one regeneration path (full, or per-section manual). Research on freshness
management supports differentiating by **how fast the underlying truth changes**, and prefers
change-detection triggers over calendar schedules — a calendar refresh spends money re-deriving
unchanged facts.

| Group | Sections | Refresh |
|---|---|---|
| **A — Identity** | overview, products, features, pricing, industry, target market | **On website change only** (fingerprint, already implemented). No calendar refresh. |
| **B — Buyer model** | ICPs, personas, pains, JTBD, value props | On website change, **plus a quarterly staleness prompt**. These are inferences and drift with the business — but regeneration is *proposed*, never automatic. |
| **C — Competitive & linguistic** | competitors, alternatives, customer language, Reddit terminology, search intent, buying signals, objections | **Continuous accretion via suggestions (§3).** Periodic regeneration from the website is *wrong* here. |
| **D — Activation** | outreach angles, content themes, SEO/GEO entities, negative signals | On demand |
| — | Subreddit statistics | Per run (live validation, already the case) |

**Group C carries the most likely real bug in the entire plan.** Regenerating `customer_language` or
`competitor_references` from the website would **delete months of Reddit-learned knowledge** — the
platform's most valuable accumulated asset — and the operator would probably not notice, because the
section would still look populated.

A UI warning is not sufficient; someone clicks through it, or a job calls the handler directly.

**→ ADOPT: make merge-not-replace a property of the write path.** Every content row carries an
`origin` (`website` | `reddit_learned` | `operator`), and **regeneration replaces only
`origin='website'` rows.** `bkb_entity_aliases.source` already has exactly this shape
([05 §5.1a](05-database-plan.md)); this generalises the pattern it established. Data loss then
becomes structurally impossible rather than procedurally discouraged.

Specification: [06h §5](06h-knowledge-lifecycle.md).

---

## 6. Entity Resolution

**→ UNCHANGED — the four-tier resolver ([06e §4](06e-business-knowledge-base.md)) remains correct.**
Re-reviewed against production entity-resolution practice (canonicalise → block → match, cheap
deterministic tiers first); the design already matches it. Nothing to change.

**→ ADOPT one small addition: entity lifecycle status.** Entities drift in ways aliases do not
capture — a competitor renames, gets acquired, or exits. A `status` of
`active | merged_into | retired` (with `merged_into_id`) means a renamed competitor's aliases keep
resolving to the surviving entity, and historical leads that matched the old name stay explainable
instead of pointing at a vanished slug.

Two columns. It prevents a class of "this lead references an entity that no longer exists" bugs that
would otherwise surface a year in, when they are hardest to reason about.

---

## 7. Pattern Discovery

**What it is.** Turning recurring Reddit observations — repeated pains, objections, feature
requests, buying triggers, language — into reusable knowledge.

**→ ADOPT, narrowly: as a SQL aggregation over data we already store, feeding §3.**
**→ REJECT: topic modelling, clustering, or any separate analytics subsystem.**

The rejection is the interesting half. Voice-of-customer platforms run topic modelling because their
input is unstructured free text with no labels. **Ours is already labelled**: every `lead_analysis`
row carries `matched_pain_slugs`, `matched_signal_slugs`, `persona_slug`, and `competitor_mentions`,
all reconciled against closed sets ([02b §20](02b-research-2026-07.md)). Discovering that
`attribution-gap` recurs is therefore a `GROUP BY`, not a machine-learning problem.

Building a clustering layer here would be re-deriving structure we deliberately paid a model to
produce, and would introduce an unsupervised component whose output nobody could explain — in a
platform whose central claim is that every conclusion is explainable.

Pattern discovery is: a nightly aggregation, a `patterns` table, a read-only *"what Reddit is telling
us"* view, and a feed into `bkb_suggestions`. **Zero AI cost.**

Specification: [06h §6](06h-knowledge-lifecycle.md).

---

## 8. Progressive Enrichment

**What it is.** Staged pipelines where cheap processing runs first and expensive processing runs
only where it is warranted.

**Production practice.** LLM cascades are well-established: *"a tiered cascade, trying the cheapest
routing method first and escalating to a more expensive one only when the cheap method cannot decide
confidently."* FrugalGPT-style results report **up to 90% inference cost reduction** at comparable
output quality.

**→ Already adopted, and it is the backbone of the design.** Hard filters → pre-score → adaptive gate
→ batched enrichment is exactly this cascade ([06c](06c-local-first-pipeline.md)). The research
confirms the existing architecture rather than changing it.

**→ ADOPT one addition: a second AI tier for the top slice.**

The gap is that after the gate, enrichment is *uniform* — every admitted item gets the same batched
B=8 treatment. But our own research established that **batching measurably degrades per-item quality
through attention dilution** ([02 §6.8](02-research-findings.md)). The highest-value leads are
therefore analysed at the *lowest* per-item quality the pipeline offers, which is backwards.

- **Tier 1** — batched B=8, classification and slug matching. All admitted items.
- **Tier 2** — single-item, full BKB context, richer output. Only leads above a confidence threshold
  or explicitly requested, **budgeted separately and capped.**

Tier 2 is cheap precisely because it is rare: on a 1,000-post run the top slice is tens of items, so
un-batched treatment costs cents. The justification is quality, not cost — and it uses a mechanism
(the cascade) already proven in the design.

Specification: [06i §3](06i-feedback-and-memory.md).

---

## 9. Decision Provenance

**What it is.** Being able to reconstruct, later, exactly why something was recommended.

**Production practice.** Lineage work stresses connecting an output to *"the system, model, data,
policy, human review"* and reconstructing state at any past point. The heavyweight end —
cryptographic sealing, tamper-evident ledgers, event replay — comes from regulated decision-making
about people.

**→ ADOPT: version pinning on every analysis row. This is the highest value-per-byte item in the
review.**
**→ REJECT: event sourcing, immutable ledgers, cryptographic sealing.**

Those exist to satisfy auditors of decisions with legal consequences. We rank Reddit threads for an
internal marketing team. The architectural cost is large and permanent; the benefit here is zero.
Recorded explicitly so it is not revisited as a "best practice."

The lightweight version delivers nearly all the value. `lead_analysis` already records `provider`,
`model`, `prompt_version`, `raw_json`, and `content_hash`. What is missing is what the *rest* of the
system looked like:

| Add | Why |
|---|---|
| `bkb_id` | Which knowledge base version produced the matched slugs |
| `weights_version` | Which score weights were in force |
| `ruleset_version` | Which rule engine and negative vocabulary applied |

**This closes an acceptance criterion that is currently unsatisfiable.** Phase-8 AC28 asserts that a
lead's entity links "resolve to the pinned version, not a dangling ref" — but nothing in
`lead_analysis` pins a BKB today, so after one regeneration the links resolve to *current* knowledge,
silently. Three columns make every historical decision reconstructible and make AC28 true.

Specification: [06i §5](06i-feedback-and-memory.md).

---

## 10. Confidence Calibration

**→ UNCHANGED — the existing approach is what the research recommends.**

ECE (10 bins) and Brier as the measures, isotonic regression as the monotonic correction, applied at
**display time only** so ranking is never altered, with `insufficient_data` below 100 labels
([06g §4.2](06g-explainability-and-quality.md)). Research on calibration from historical feedback
describes this design. Explicitly re-confirmed; no change.

**→ DEFER: segmented calibration** (per intent category or subreddit tier). Justified only above
~500 total labels *and* ≥200 within a segment; below that, segmenting fits noise. Deferred with the
threshold named rather than left as a vague future idea.

One caution recorded for whoever implements it: segmenting **fragments the ECE denominator**, so the
global ECE and the per-segment ECEs will not reconcile. Someone will try to add them up.

---

## 11. Memory Architecture

**What it is.** Whether long-lived knowledge should be separated from transient data.

**→ ADOPT: four memory classes with different lifetimes — logically separated, physically one
SQLite file.**
**→ REJECT: separate databases, separate services, event sourcing.**

Nothing at our scale justifies a second datastore, and every one added is a new backup story, a new
consistency problem, and a new failure mode. The valuable part of the idea is not physical
separation but **stated lifetime and retention rules**, which prevent the slow drift where an
operational table quietly becomes load-bearing for scoring.

| Class | Contents | Lifetime |
|---|---|---|
| **Durable knowledge** | BKB, sections, entities, aliases, links, patterns, calibration maps | Never auto-purged; backed up; survives everything |
| **Evidence** | leads, comments, `lead_analysis`, `bkb_evidence`, `lead_labels` | Never auto-purged — the substrate for calibration and patterns |
| **Operational** | runs, jobs, `ai_calls`, `ai_budgets`, `gate_audits`, metrics | Purged on a retention schedule, **after** aggregation |
| **Disposable cache** | `ai_cache`, `http_cache` | Deletable at any moment |

**The rule that makes this enforceable rather than aspirational:** *deleting every row in the
disposable class must not change any lead's score.* That is a single acceptance criterion, and it
prevents cache from ever becoming state — which is how caches turn into undocumented databases.

Specification: [06i §4](06i-feedback-and-memory.md).

---

## 12. What stays correct — explicitly

The user asked for this, and it is most of the plan. Re-reviewed this pass and **unchanged**:

| Decision | Status |
|---|---|
| `old.reddit.com` HTML scraping, no API / OAuth / PRAW | Correct — and the strategic basis is unchanged |
| Local-first funnel; AI as last enrichment step | **Confirmed by the cascade research** (§8) |
| Adaptive budget: knee + floor + marginal + clamps | Correct — one input defect fixed (§0), mechanism unchanged |
| Hybrid confidence: AI emits categoricals, Python computes the score | Correct |
| Explainability faithful by construction | Correct — extended, not revised (§9) |
| Four-tier entity resolution | Correct (§6) |
| ECE / Brier / isotonic at display time | Correct (§10) |
| Holdout audit at 2% of rejects | Correct — and now **doing a second job** it was always structurally capable of (§0) |
| 23-section BKB, typed sections, `NULL`-payload rule for the three overlapping keys | Correct |
| Local semantic layer (Model2Vec + `sqlite-vec`), optional and degrading | Correct |
| One consolidated `analyze_business()` call | Correct |
| Batch size as a measured ceiling, B=8 default | Correct — and it is *why* Tier 2 exists (§8) |
| Suggestions propose, operators dispose | Correct — **generalised** to all knowledge types (§3) |
| **Rejected:** agent frameworks, vector DBs, graph DBs, RAG over raw text, LLM-as-judge, microservices | All still rejected |

Eight phases, nine migrations, one head. **This review adds no phase and no migration.**

---

## 13. Competitor architecture comparison

Re-reviewed 2026-07-30, this time for knowledge flow rather than features.

### Tydal

| | |
|---|---|
| Knowledge model | *"You describe your product once, then Tydal continuously finds threads."* A **stored product description** — persistent, but flat text, not a structured model |
| Orchestration | Three stages: continuous background scan → per-thread scoring at discovery → **per-action generation** priced separately (0.1 credits/comment) |
| Long-term memory | Account state and DM conversation history. **No evidence of learning from outcomes** |
| Repeated work | Per-thread intent scoring at discovery time, on every scan, for every thread |
| Assumption | The business description is a static input; intelligence lives in the scanning frequency |

### RedShip

| | |
|---|---|
| Knowledge model | *"We read your site, work out what you actually sell, and turn that into the keywords worth watching."* Website analysis is **one-time onboarding**; the persisted artefact is a **keyword list** |
| Orchestration | Static keyword set → weekly scans → per-thread AI relevance rating |
| Long-term memory | **None found.** Zero references to tracking which leads were acted on |
| Repeated work | Per-thread relevance rating on every weekly scan; weekly SERP and AI-visibility scans |
| Assumption | Business understanding is a *compilation step* that produces keywords and is then discarded |

### The three architectural gaps

1. **Neither has a knowledge base — only Tydal has knowledge, and it is flat text.** RedShip
   compiles the website into keywords and throws the understanding away. Neither can answer *"what
   does this business's buyer actually sound like?"* six months in, because neither stored it.

2. **Neither closes the loop.** No feedback signal, no calibration, no measurement of what filtering
   discarded. Both are open-loop systems: they classify, present, and forget. **A user who marks
   fifty leads as irrelevant in RedShip changes nothing about the fifty-first.**

3. **Both re-derive per thread, per scan, forever.** With no persisted analysis keyed on content and
   no incremental processing, cost scales with *volume scanned*, not with *new information*. That is
   what forces per-credit pricing (Tydal) and hard keyword caps (RedShip) — and those caps then
   limit the product's intelligence for commercial rather than technical reasons.

### Where we are structurally stronger

| Dimension | Them | Us |
|---|---|---|
| Business model | Flat text or a keyword list | 23-section BKB, entity-resolved, evidenced |
| Learns from Reddit | ❌ | Suggestions from aggregate patterns (§3) |
| Learns from users | ❌ | Labels → calibration + yield curve + knowledge (§4) |
| Knowledge freshness | Static after onboarding | Per-type policy, change-triggered (§5) |
| Re-analysis cost | Full price, every scan | **$0.00** — content-hash keyed |
| Reconstruct a past decision | ❌ | Version-pinned (§9) |
| Knows what it discarded | ❌ | Gate miss rate, every run |

**The gap widens with time, which is the point.** At day one we are a better-instrumented version of
the same idea. At month six we have a knowledge base that has absorbed hundreds of real customer
phrasings, a calibrated confidence score, and measured filter quality — while both competitors are
running exactly the same query against exactly the same static keyword list they compiled on day one.

**What they do better, unchanged from [02a §5](02a-competitor-analysis.md):** Tydal closes the
discovery-to-engagement loop; both ship SERP and AI-visibility tracking; both are far simpler to
operate. The last is a real cost of everything above, and it is only defensible because this is an
internal platform.

---

## 14. Decision summary

| # | Topic | Decision |
|---|---|---|
| 0 | Yield-curve degeneracy | ✅ **Adopt fix** — holdout leads become labellable |
| 1 | Knowledge lifecycle | ⚠️ Adopt binary staleness · ⛔ Reject decay curves · ⛔ Reject expiring leads |
| 2 | Evidence-based knowledge | ✅ Adopt `source_type`; inference marked, never auto-promoted |
| 3 | Knowledge evolution | ⚠️ Adopt via existing suggestions, aggregate-only (≥3, ≥2 groups) |
| 4 | Human feedback | ⚠️ Adopt weights + calibration + reasons · ⛔ Reject learned ranker |
| 5 | Knowledge freshness | ✅ Adopt per-type policy + **origin-guarded regeneration** |
| 6 | Entity resolution | ✅ Unchanged · ➕ entity lifecycle status |
| 7 | Pattern discovery | ⚠️ Adopt as SQL aggregation · ⛔ Reject topic modelling |
| 8 | Progressive enrichment | ✅ Already adopted · ➕ Tier 2 for the top slice |
| 9 | Decision provenance | ⚠️ Adopt version pinning · ⛔ Reject event sourcing / ledgers |
| 10 | Confidence calibration | ✅ **Unchanged** · ⏸ Defer segmentation (≥500 / ≥200) |
| 11 | Memory architecture | ⚠️ Adopt four classes, one file · ⛔ Reject separate stores |

**One correctness fix, five narrow additions, six rejections, and a large amount confirmed
unchanged.** No new phase; no new migration.
