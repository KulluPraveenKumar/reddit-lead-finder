# 06h — Knowledge Lifecycle, Evidence & Evolution

> How the Business Knowledge Base ages, what it is allowed to learn, and what protects it from
> forgetting. Extends [06e](06e-business-knowledge-base.md); decisions and research basis in
> [02c §1–3, §5–7](02c-research-final-review.md).

---

## 1. The governing idea

A knowledge base that never changes is a snapshot. A knowledge base that changes freely is a rumour.

The whole of this document is one distinction:

| | Rule |
|---|---|
| **Knowledge accretes** | New observations *add* to the BKB and are attributed to their source |
| **Knowledge is never silently overwritten** | Regeneration replaces only what it originally wrote |
| **Knowledge is never silently trusted** | Every claim carries an evidence type; inference is marked as inference |
| **Knowledge ages visibly** | Sections carry a verification date and a staleness state, not a decaying number |

Three of the four are enforced by the **write path**, not by operator diligence. That is deliberate:
a rule that depends on someone reading a warning is a rule that will be broken.

---

## 2. Staleness — visible age, not decaying confidence

### 2.1 The decision, and what it rejects

Research on knowledge freshness is unambiguous that **staleness degrades silently** — the system
keeps answering confidently while its facts rot ([02c §1](02c-research-final-review.md)). It is
equally clear that this must be *measured*, not inferred.

Some of that literature proposes continuous confidence decay. **We reject it.**

> An ICP does not become 3% less true each week. It is either still right, or the business changed —
> and *which* of those is true is knowable by checking the website fingerprint, not by extrapolating
> a curve.

A decay function would lower scores for no observable reason, and would be unexplainable in a
platform whose central claim is that every number can be traced to its cause. Binary staleness with
a per-type threshold gives the same protection and renders as a sentence an operator can act on.

### 2.2 The model

Two columns on `bkb_sections`:

```
last_verified_at   DATETIME   -- last regenerated, or last operator-confirmed
staleness_days     INTEGER    -- threshold for THIS section type (NULL = never stales)
```

`staleness_days` is per section type, not global, because the underlying truths change at very
different rates (§5). Derived state, computed rather than stored:

| State | Condition | Rendering |
|---|---|---|
| `fresh` | age < threshold | no marker |
| `ageing` | age ≥ 0.75 × threshold | subtle marker |
| `stale` | age ≥ threshold | amber badge + a suggested action |

**Staleness never alters a score.** It is an operator-facing signal about *knowledge*, not a
modifier on a lead. Coupling the two would reintroduce decay through the back door and make the
score depend on the wall clock, which would break reproducibility ([06i §5](06i-feedback-and-memory.md)).

### 2.3 What does not stale

**Leads and their analyses are retained indefinitely.** A lead is a historical fact — *this person
wrote this on this date* — and does not become false. Its *actionability* decays, and that is already
the `recency` component of the confidence score ([04 §9](04-system-design.md)).

Deleting old leads would destroy the substrate that confidence calibration and pattern discovery are
computed from — the two mechanisms that make the platform improve over months. Retention purges
`ai_calls` and `http_cache`; it never purges evidence ([06i §4](06i-feedback-and-memory.md)).

---

## 3. The evidence model

### 3.1 Evidence gains a source type

`bkb_evidence` already stores verbatim spans validated as literal substrings
([05 §5.1a](05-database-plan.md)). That design assumed evidence always came from a *website*. Once
knowledge can also arrive from Reddit or an operator (§4), the assumption breaks.

```
source_type:  website | reddit_post | reddit_comment | operator | ai_inference
```

| Type | Carries a verbatim span? | Validated how |
|---|---|---|
| `website` | Yes | Literal substring of the snapshot text |
| `reddit_post` / `reddit_comment` | Yes | Literal substring of the stored post/comment body |
| `operator` | No | The operator *is* the authority; records who and when |
| `ai_inference` | **No** | Nothing to validate — and that is the point |

### 3.2 Should unsupported AI assumptions ever become permanent?

**No — but they must be storable.**

Refusing to store inference would gut the knowledge base. Much of an ICP is legitimately inferred: a
site rarely states *"our buyer is a Series-A growth lead with an attribution problem."* A model
concluding that from the copy is doing useful work.

The danger is not that inference exists. It is that inference becomes **indistinguishable from
observation** once it is written down. Three rules prevent that:

1. **`ai_inference` is first-class and visibly marked** — never a silent default. A claim with no
   evidence row at all is a bug; a claim with `ai_inference` evidence is honest.
2. **A claim whose only evidence is `ai_inference` can never be auto-promoted.** Not by a
   suggestion, not by repetition, not by a later run agreeing with it. A model agreeing with itself
   is not corroboration.
3. **An operator can promote anything**, which writes an `operator` evidence row recording who and
   when. Human judgement is the only thing that converts inference into a confirmed fact.

The result: *observed* versus *inferred* is a property of the data, not of whoever remembers the
provenance.

### 3.3 What this makes possible

The lead detail already links every matched slug back to its BKB section
([06g §3](06g-explainability-and-quality.md)). With typed evidence, that chain gains its final link:

```
Reddit post  →  matched pain `attribution-gap`
                  └─ defined in BKB §pain_points  (v3, verified 12 days ago)
                       ├─ website   "stop guessing which channel drove the deal"   acme.com/
                       ├─ reddit    "our attribution is a mess"        r/SaaS · 3 leads
                       └─ operator  confirmed 2026-06-14
```

An operator can see not just *what* matched but *why the system believes that pain exists at all*,
and whether that belief came from the site, from Reddit, from a human, or from a model's guess.

---

## 4. Knowledge evolution — what Reddit teaches the knowledge base

### 4.1 Scope

The `bkb_suggestions` mechanism already exists ([06e §7](06e-business-knowledge-base.md)) for
competitor aliases and pain phrasings. This widens it to the full set — **the same machinery, more
inputs**, not a new subsystem:

| Discovery | Proposes | Target |
|---|---|---|
| Unregistered competitor alias | New alias | `bkb_entity_aliases` |
| Unknown competitor named repeatedly | New entity | `bkb_entities` |
| Recurring phrasing absent from `how_people_phrase_it` | New phrasing | `pain_points` |
| Recurring vocabulary in high-scoring leads | New term | `customer_language` / `reddit_terminology` |
| Recurring objection | New objection | `common_objections` |
| Recurring pre-purchase phrasing | New signal example | `intent_signals` |
| Persona repeatedly labelled `wrong_persona` | Review the persona | `personas` (flag, not edit) |

### 4.2 The threshold that makes this safe

**Only aggregate patterns propose. Single observations never do.**

```
≥ 3 occurrences,  in ≥ 2 distinct dedup groups,  within one project
```

**The dedup-group requirement is not incidental.** Without it, one viral thread and its forty
reposts would manufacture a pattern by itself — and our own near-duplicate grouping
([06c §4](06c-local-first-pipeline.md)) already knows those forty are one discussion. Counting raw
occurrences would let the loudest thread rewrite the knowledge base.

The threshold is deliberately unreachable at low volume. **A project with 40 total leads will never
raise a suggestion, and that is correct behaviour, not a defect** — knowledge accretion is a property
of sustained use, and the voice-of-customer research puts a reliable thematic picture at four to six
weeks of real volume ([02c §3](02c-research-final-review.md)). A system that proposed knowledge on
day two would be proposing noise.

### 4.3 Nothing auto-applies

Unchanged from [06e §7](06e-business-knowledge-base.md) and restated because it now governs far more:

- Suggestions are written with `status='pending'` and their supporting evidence
- The Knowledge Suggestions panel shows the proposal, the count, and the contributing leads
- Acceptance is the **only** write path into the BKB from Reddit
- An accepted suggestion writes rows with `origin='reddit_learned'` and a `reddit_post` /
  `reddit_comment` evidence row

Automatic self-modification would let one mis-scored lead poison the knowledge base, and the error
would compound invisibly with every subsequent run that matched against the poisoned term.

---

## 5. Freshness policy — different knowledge, different rules

### 5.1 The policy

Refresh cadence follows **how fast the underlying truth changes**, and the trigger is
change-detection wherever possible. A calendar refresh spends money re-deriving facts that did not
move.

| Group | Sections | Refresh trigger | `staleness_days` |
|---|---|---|---:|
| **A — Identity** | overview, products, features, pricing, industry, target market | **Website fingerprint change only** | 180 |
| **B — Buyer model** | ICPs, personas, pains, JTBD, value propositions | Website change; **plus a staleness prompt** | 90 |
| **C — Competitive & linguistic** | competitors, alternatives, customer language, Reddit terminology, search intent, buying signals, objections | **Accretion via §4** — not periodic regeneration | *never stales* |
| **D — Activation** | outreach angles, content themes, SEO/GEO entities, negative signals | On demand | 180 |

Subreddit statistics are validated live on every run and are not BKB state at all.

**Group C never stales by design.** A knowledge type that is continuously accreting from real
observations is *getting fresher*, not older; showing it an age badge would invite exactly the
regeneration §5.2 exists to prevent.

**Group B is prompted, never automatic.** These are inferences that drift with the business, so age
is genuinely informative — but regenerating an ICP silently, months after an operator hand-tuned it,
would be the same class of data loss as §5.2. The system says *"personas were last verified 94 days
ago — review?"* and stops.

### 5.2 The write-path guard — the most important rule in this document

**Regenerating a Group-C section from the website would delete months of Reddit-learned knowledge**,
and the operator would probably not notice, because the section would still look populated. This is
the most likely real bug in the plan.

A UI warning is not sufficient. Someone clicks through it, or a job calls the handler directly.

**→ Merge-not-replace is a property of the write path.** Every content row carries an origin:

```
origin:  website | reddit_learned | operator
```

```python
def regenerate_section(key, new_rows):
    """Regeneration replaces ONLY what regeneration originally wrote."""
    delete_rows(key, origin="website")          # the model's previous output
    insert_rows(key, new_rows, origin="website")
    # reddit_learned and operator rows are NEVER touched.
```

`bkb_entity_aliases.source` already has exactly this shape ([05 §5.1a](05-database-plan.md)); this
generalises the pattern it established rather than inventing one.

**One detail the guard leaves open, settled here:** when a regeneration supersedes the `bkb` row,
`reddit_learned` and `operator` rows are **re-pointed to the new `bkb_id`**, not left attached to the
superseded version. That is the single exception to "regeneration never touches non-`website` rows",
and it is a pointer update rather than a content change — the row's text, origin and evidence are
untouched. Without it, learned knowledge would detach from the current BKB on the first regeneration
and silently stop being matched against, which is the same data loss the guard exists to prevent,
arriving by a quieter route.

Data loss then becomes **structurally impossible** rather than procedurally discouraged, and the
guarantee is testable in one assertion: *regenerate every section twice and confirm no
`reddit_learned` or `operator` row is lost.*

### 5.3 What refresh costs

| Event | AI calls | Cost |
|---|---:|---:|
| Website fingerprint unchanged | **0** | **$0.00** |
| Group A change detected | 1 (affected sections) | ~$0.002 |
| Group B staleness prompt accepted | 1 | ~$0.002 |
| Group C accretion | **0** — it is a `GROUP BY` (§6) | **$0.00** |
| Group D on demand | 1 | ~$0.001 |

The knowledge base gets better continuously and the dominant path costs nothing, because the
accreting knowledge type is the one that requires no model at all.

---

## 6. Pattern discovery — a `GROUP BY`, not a model

### 6.1 Why there is no clustering here

Voice-of-customer platforms run topic modelling because their input is unstructured free text with
no labels. **Ours is already labelled.** Every `lead_analysis` row carries `matched_pain_slugs`,
`matched_signal_slugs`, `persona_slug`, and `competitor_mentions` — reconciled against closed sets
because we specifically paid a model to produce structure ([02b §20](02b-research-2026-07.md)).

Discovering that `attribution-gap` recurs is therefore an aggregation, not a machine-learning
problem. Building a clustering layer would be re-deriving structure we already bought, and would
insert an unsupervised component whose output nobody could explain — into a platform whose central
claim is that every conclusion is explainable.

### 6.2 What it is

A nightly SQL aggregation over `lead_analysis`, joined to `dedup_members` so that a group counts
once:

```sql
-- shape only; full DDL in 05 §5.4d
SELECT pattern_kind, pattern_key,
       COUNT(DISTINCT COALESCE(dm.group_id, 'lead:' || la.lead_id)) AS distinct_groups,
       COUNT(*) AS occurrences,
       AVG(l.confidence_score)                                      AS avg_confidence,
       MIN(la.created_at), MAX(la.created_at)
  FROM lead_analysis la ...
 GROUP BY pattern_kind, pattern_key;
```

Two outputs:

1. **A read-only "What Reddit is telling us" view** — recurring pains, objections, competitors,
   language and triggers, with trend over time and the leads behind each.
2. **A feed into `bkb_suggestions`** for patterns that clear the §4.2 threshold and are not already
   in the BKB.

**Zero AI cost.** It runs beside the nightly quality rollups
([06g §5](06g-explainability-and-quality.md)) and uses the same substrate.

### 6.3 Why this belongs here rather than as an analytics feature

Pattern discovery is not a reporting side-feature; it is **the sensing organ for §4**. Without it,
knowledge evolution has no input. Framing it as analytics would make it the first thing cut for
scope — and cutting it would quietly turn the knowledge base back into a static artefact, which is
precisely the competitor weakness the platform exists to avoid
([02c §13](02c-research-final-review.md)).

---

## 7. Entity lifecycle

Entities drift in ways aliases do not capture: a competitor renames, gets acquired, or exits.

```
bkb_entities.status:  active | merged_into | retired
bkb_entities.merged_into_id
```

| Status | Resolution behaviour |
|---|---|
| `active` | Normal |
| `merged_into` | Aliases resolve to the **surviving** entity; historical leads stay explainable |
| `retired` | No longer matched in new runs; historical references still render |

Two columns, and they prevent a class of *"this lead references an entity that no longer exists"*
bugs that would otherwise appear a year in, when they are hardest to reason about. Entities are
never hard-deleted — a deleted entity would silently break every historical explanation that
referenced it.

---

## 8. Schema additions

**No new migration.** Everything below lands in revisions that already exist in the plan
([05 §7](05-database-plan.md)); the chain stays linear at nine with one head.

| Revision | Addition |
|---|---|
| `0005` | `bkb_sections.last_verified_at`, `.staleness_days`, `.origin`<br>`bkb_evidence.source_type`, `.confirmed_by`, `.confirmed_at`<br>`bkb_entities.status`, `.merged_into_id`<br>`personas` / `pain_points` / `intent_signals` `.origin`<br>`bkb_suggestions.pattern_kind`, `.distinct_groups` |
| `0009` | `patterns` — the nightly aggregation output |

Full DDL in [05 §5.1c and §5.4d](05-database-plan.md).

---

## 9. Acceptance criteria

- Every `bkb_sections` row has `last_verified_at`; the derived state renders correctly at each threshold
- Staleness **never** alters a confidence score (asserted: advance the clock, re-score, scores identical)
- Every BKB claim has ≥1 `bkb_evidence` row; a claim with zero evidence rows fails validation
- `website`, `reddit_post`, and `reddit_comment` spans are literal substrings of their source
- A claim whose only evidence is `ai_inference` cannot be promoted by any automatic path
- **Regenerating every section twice loses no `reddit_learned` or `operator` row**
- A pattern occurring 3× within a single dedup group raises **no** suggestion
- A pattern occurring 3× across 2 dedup groups raises exactly **one** suggestion
- Pattern aggregation makes **zero** AI calls
- A `merged_into` entity's aliases resolve to the surviving entity; historical leads still explain
