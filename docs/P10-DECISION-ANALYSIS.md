# P10 — Decision Analysis

**Phase:** P10, the dedup cascade (`src/dedupe/`) · **Written:** 2026-08-14
**Governs:** [34 §P10](34-implementation-plan.md), under
[ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md) and [EXECUTION_MODE_LOCK](EXECUTION_MODE_LOCK.md)

> Nine decisions were required, because nine questions in [34 §P10](34-implementation-plan.md) could
> not be answered from the phase's own row. Each is recorded here with what was measured, what was
> decided, and what was rejected — the form [P9-DECISION-ANALYSIS.md](P9-DECISION-ANALYSIS.md)
> established.
>
> **Six were put to the operator and answered before implementation began.** D6 is the one small
> improvement taken under [lock §8](EXECUTION_MODE_LOCK.md), and it is recorded rather than taken
> silently.
>
> **D10 is different: it was forced by a measurement *after* the code was written.** Mutation testing
> found the cascade grouping by single linkage — a real defect, not a missing test — and it is
> recorded last because that is when it was found.

---

## D1 — `choose_representative` cannot rank by a pre-score, because there is no pre-score

**The conflict.** [06c §4.3](06c-local-first-pipeline.md) specifies

```python
def choose_representative(group: list[Item]) -> Item:
    return max(group, key=lambda i: (i.prescore.total, i.score or 0, i.created_utc))
```

and [34 §P10](34-implementation-plan.md)'s Acceptance row asks that **a group of N yields N distinct
pre-scores**. But `src/scoring/prescore.py` is [34 §P11](34-implementation-plan.md)'s **Files** row,
and **P11 depends on P10**. Verified 2026-08-14: `grep -rn "prescore" src/` finds the `prescores`
table, its repository and P6's decision *not* to write to it — and no scorer. There is nothing to
rank by and nothing to count.

This is the same shape as P9's *"11 rejection reasons implemented and counted"*: an acceptance line
naming an artefact a later phase owns.

**Decided.** `DedupItem.rank` carries the pre-score, defaults to `None`, and the ordering falls back
to `(score, created_utc, row_id)`. P11 fills `rank` in without a signature change.

P10 proves the **checkable half** of the N-distinct claim — that grouping preserves N distinct
members and **mutates no per-item score field** (`test_a_group_of_n_keeps_n_members_and_n_identities`,
`test_grouping_mutates_no_per_item_score`). The N-distinct-pre-scores assertion moves to P11 with the
pre-scores that make it verifiable. Recorded as a [freeze §11.1](ARCHITECTURE_FREEZE.md)
reconciliation.

**Rejected — building a minimal pre-score inside P10.** It would satisfy the line literally and
create a second scoring implementation for P11 to reconcile or delete, in `src/scoring/`, outside
P10's Files row.

**Why it matters.** [06c §4.4](06c-local-first-pipeline.md) is explicit that collapsing the scores
alongside the grouping is a *silent quality regression*: three identical numbers for three
different-value leads, and the operator correctly stops trusting the ranking. P10's job is to make
that impossible, not to compute the numbers.

---

## D2 — the semantic tier ships a real path, in memory, that no-ops when absent

**The conflict.** [34 §P10](34-implementation-plan.md) task 3 asks for *"Model2Vec + `sqlite-vec`,
cosine ≥ 0.88, **no-op when unavailable**"*. But P10's **DB** row is *"None (tables from P8)"*, the
vector tables (`bkb_embeddings`, `bkb_embedding_meta`) arrive in `0007` with **P12**, and
[freeze §4.1](ARCHITECTURE_FREEZE.md) permits no eleventh revision. Separately, P0 measured both
`model2vec` and `sqlite_vec` as **not installed**
([SPRINT-0-MEASUREMENTS §3.1](SPRINT-0-MEASUREMENTS.md)) and deliberately did not install them.

**Decided.** `src/dedupe/semantic.py` genuinely reads `dedup.semantic_threshold` and genuinely works
when the library is present, comparing cosine similarity **in memory within the run**. It stores
nothing and needs no table. When the import fails it contributes nothing and logs once per process.
`requirements.txt` gains an **optional, commented** block.

**Rejected — a stub behind the config key.** That is precisely P6's `density_threshold` and P7's
`notify.min_confidence_alert`: *a key nothing reads is a documented capability that does not exist.*

**Rejected — hard dependencies.** Then CI would never exercise the degraded path, which is the exact
case [AD-16](03-architecture.md) and the acceptance criterion *"with the semantic layer disabled the
same run produces the identical lead set"* exist to protect. Keeping them optional means the
**unavailable arm is the one that runs on every gate**, which is the arm that will actually be hit
in production.

**Consequence, handled.** The *installed* arm would then ship untested. It is covered by injecting a
stub `model2vec` into `sys.modules` — not by installing the package, because
`StaticModel.from_pretrained` **downloads weights** and [35 §2.1](35-testing-strategy.md) check 6
blocks the socket for the whole suite.

---

## D3 — `src/dedupe/` owns its two reason constants

**The conflict.** [PHASE-09-HANDOVER §3.3](PHASE-09-HANDOVER.md) instructs P10: *"Your two reasons
are `duplicate_exact` and `duplicate_near` … Extend `REASONS` and the subset test together."*
`REASONS` lives in `src/rules/__init__.py`, which is **outside** [34 §P10](34-implementation-plan.md)'s
**Files** row — and [lock §3](EXECUTION_MODE_LOCK.md) step 4 is *"every file in the phase's Files
row, and nothing outside it"*.

**Decided.** `src/dedupe/` declares `DUPLICATE_EXACT` / `DUPLICATE_NEAR` and builds
`src.rules.RuleResult` directly. `tests/test_rules_vocabulary.py` — the one file permitted to import
both sides of the R3 boundary — asserts that **all six stay a subset of P19's eleven**, that the two
vocabularies do not overlap, and that the running total is six.

**The cost, paid explicitly.** `src.rules.reject`'s M15 guard validates against P9's four and would
refuse both of P10's, so `src.dedupe.duplicate()` reproduces it. Mutation **M36** is the removal of
that guard.

**Rejected — editing `src/rules/__init__.py` anyway.** Defensible, and it would be one shared
vocabulary with one guard. It was rejected because the Files row is the phase boundary and a
deliberate exception to it should be the operator's call, not a convenience taken mid-implementation.

---

## D4 — P10 is library-only; nothing calls the cascade

**The question.** [34 §P10](34-implementation-plan.md)'s **Files** row lists
`src/dedupe/{__init__,exact,minhash,semantic,groups}.py` and `requirements.txt` — no handler, no
orchestration module, no template. P9 shipped the same shape and
[PHASE-09-HANDOVER §1](PHASE-09-HANDOVER.md) recorded it: *"Nothing imports them. P9 built the
library; P10 is its first caller."*

**Decided.** P10 is a library. **P11 is its first caller.** Two acceptance criteria are therefore
evaluated as follows:

| Criterion | How P10 evaluates it |
|---|---|
| *"with the semantic layer disabled the same run produces the identical lead set"* | A constructed-run assertion over fixtures, comparing **whole sets** rather than counts |
| *"collapse rate > 8% on real data"* | An **offline** measurement over a read-only copy of the live database — see **D7** |

`python -m src.dedupe` is shipped outside the Files row for the same reason P9 shipped
`python -m src.rules`: [35 §1](35-testing-strategy.md) requires the manual guide to be executable by
a non-developer, and [34 §1.1](34-implementation-plan.md) calls the Files row *"a guide, not a
contract"*. P5's `feed` CLI and P6's `triage.py` are the earlier precedents.

---

## D5 — MinHash ships One-Permutation Hashing, because A5 was measured and the literal reading fails

**This is the phase's Medium risk, and it resolved into a decision rather than a number.**

[34 §P10](34-implementation-plan.md)'s Acceptance row: *"**MinHash indexes and queries 2,000 items in
< 2 s CPU** (assumption A5, measured)"*. P0 left A5 unmeasured. 2,000 is `max_items_per_run`
([freeze §6](ARCHITECTURE_FREEZE.md)) — the normal case, not the tail.

**Measured 2026-08-14, before any implementation was written.** Python 3.12.5, win32, fixed seed,
2,000 items:

| Signatures only | Classic 128 independent permutations | One-Permutation Hashing |
|---|---:|---:|
| 305-char docs / 176 shingles | **6.36 s** | **0.27 s** |
| 870-char docs / 315 shingles | **11.11 s** | **0.55 s** |
| Jaccard mean absolute error, 40 pairs | 0.0308 | **0.0279** |

End to end — shingling **plus** signing **plus** banding **plus** the query stage, which is what the
acceptance criterion actually names — the shipped implementation measures **0.59 s** and **0.87 s**.
The classic figures are already over budget before shingling or querying is counted at all.

**Decided.** Ship One-Permutation Hashing with densification. It produces the **same 128-slot
signature**, bands identically, and is estimated by the same equality-count rule; it measured *more*
accurate, not less. The saving is structural: one hash of a shingle both picks its slot and supplies
its value, so cost is O(shingles) rather than O(shingles × 128).

**This is a reconciliation, not a [§11](ARCHITECTURE_FREEZE.md) amendment.** No technology, table,
decision or dependency changes — what changes is how a 128-component sketch is computed.
[06c §4.2](06c-local-first-pipeline.md) anticipated exactly this: *"Performance is a design target,
not a measured claim … this number is validated in testing rather than assumed here."*

**Rejected — `datasketch`.** Not in [freeze §5](ARCHITECTURE_FREEZE.md), and §12 closes the set. The
same reasoning by which P9 refused `hypothesis` for its property tests.

**Rejected — shipping classic 128 perms and amending A5 to ~6.4 s.** It would honour the wording
exactly and spend the amendment path to make the normal case 20× slower.

**A measured property, pinned rather than hidden.** A 128-slot sketch estimates Jaccard to roughly
±0.05, so a pair whose exact similarity sits inside that band of the threshold may fall on either
side of it. Measured: a pair at exactly **0.815** estimates **0.859** and therefore groups.
`test_near_the_threshold_the_sketch_and_exact_jaccard_can_disagree` pins it, because the alternative
is a future reader finding one such pair and "fixing" it by computing exact Jaccard over every
candidate — the O(n²) cost banding exists to avoid. The consequence is bounded and benign: a
borderline pair is grouped, one of the two is enriched, and **both keep their own score**.

---

## D6 — the content hash normalises title and body separately

**Taken under [lock §8](EXECUTION_MODE_LOCK.md)**, not put to the operator, and recorded here rather
than made silently.

[06c §4.1](06c-local-first-pipeline.md) writes `content_hash = sha256(normalise(title + "\n" + body))`.
`normalise` collapses whitespace, so the joining newline becomes a space — and under that literal
parenthesisation `("a b", "c")` and `("a", "b c")` produce **the same hash**. Two different posts
merge into one group and one of them is never enriched.

**Decided.** Normalise the parts, then join: `sha256(normalise(title) + "\n" + normalise(body))`. The
separator is a character `normalise` can no longer emit.

Same algorithm, same column, same tier, one parenthesis moved to close a collision — which satisfies
all four of [lock §8](EXECUTION_MODE_LOCK.md)'s conditions.
`test_a_title_body_boundary_shift_is_not_a_duplicate` is the assertion; mutation **M4** is the
reversion.

---

## D7 — the collapse-rate metric is not met, and cannot be met by this corpus

[34 §P10](34-implementation-plan.md)'s **Metrics** row asks for *"collapse rate > 8% on real data"*.

**Measured 2026-08-14** on a read-only copy of `data/leads.db` (488 leads):

| `jaccard_threshold` | Groups | Collapse |
|---|---:|---:|
| 0.95 | 20 | 4.51% |
| **0.85 — shipped** | **23** | **5.74%** |
| 0.80 · 0.75 · 0.70 · 0.60 | 23 | 5.74% |

Exact tier alone: 12 groups, **2.46%**. Adding MinHash: 23 groups, **5.74%**.

**Root cause — three findings, none of them under-detection.**

1. **The rate is flat from 0.85 down to 0.60.** Loosening the threshold finds **zero** additional
   duplicates. The corpus contains 5.74% duplicate content and no more, so this is not a tuning
   artefact.
2. **ID-level dedup has already been spent on this corpus.** All 488 `reddit_id` values are distinct
   — the column is `UNIQUE`. [28 §L3](28-discovery-redesign.md) estimates *"3–8% residual overlap"*
   for ID dedup, and that is the figure most plausibly behind the >8% target. It is removed before
   the cascade ever sees the data.
3. **The estimate is intra-run; the corpus is a 29-month archive.**
   [06c §3.2](06c-local-first-pipeline.md) gives `duplicate_exact` 3–8% and `duplicate_near` 8–20%,
   both explicitly *"this run"*. The live database holds **59 scrape runs across 4 subreddits, from
   2024-03-18 to 2026-08-13**. A cross-run archive dilutes intra-run duplication by construction.
   12.3% of leads also carry an empty body, giving tier 2 less to match on.

**Decided.** Record the measurement; reconcile the metric to the intra-run quantity it was always
about; defer the intra-run measurement to **P11**, the first phase with a live call site and funnel
counters. **No threshold was tuned to chase the number** — and the flatness above proves tuning
would not have reached it anyway.

**Rejected — amending the target to 5.74%.** It would bake a cross-run figure into a metric written
about a run, and spend the amendment path on a number P11 can still measure properly.

---

## D8 — DI22 is upheld in the write path, and no column was added

[DEFERRED-IMPROVEMENTS DI22](DEFERRED-IMPROVEMENTS.md) hands P10 an invariant the schema cannot
express: *"a lead or comment belongs to at most one group **per run**"*. `dedup_members` has no
`run_id`, the run is reachable only through `dedup_groups`, and SQLite cannot constrain uniqueness
across a join.

**Decided.** The guarantee is **structural in the construction, then checked independently**:

| | |
|---|---|
| Construction | `_Clusters` holds a `key -> cluster` map; every tier consults it before claiming. A second claim is **never constructed**, not rejected after the fact |
| Check | `validate_membership()` asserts the property over finished groups, independent of the construction |
| Write path | `group_rows()` and `persist()` both refuse a result that fails the check |
| Property test | 40 random corpora built from a shared phrase pool, so overlaps arise in combinations nobody chose |

**No column was added.** DI22 records that adding `run_id` to `dedup_members` would be a
[freeze §11](ARCHITECTURE_FREEZE.md) question; P10 did not need it, so it was not asked.

**A related decision inside the same mechanism.** A later tier **extends** a group an earlier tier
opened rather than opening a second one — otherwise a post 95% similar to a member of an exact group
is stranded alone, and the operator sees two groups describing one discussion.

---

## D10 — grouping is **complete** linkage, and single linkage was a defect

**Not a decision taken up front. It was forced by a measurement, after the code was written.**

Mutation **M35** — replacing the cascade's `sim >= jaccard_threshold` with `sim >= 0.0` — **survived
the first full mutation run**. Probing why did not find a missing test; it found this:

`_Clusters.attach` joined a cluster on the strength of **one** match. That is single linkage, which
is transitive closure in disguise — `A~B` at 0.90 and `B~C` at 0.90 puts `A` and `C` in one group
however far apart they are. **Measured 2026-08-14 on a graded corpus: a 14-member group whose
furthest pair was 0.445 similar.**

Those two leads would then have **shared one AI analysis**. That is exactly the silent quality
regression [06c §4.4](06c-local-first-pipeline.md) exists to forbid, and
[06c §4.2](06c-local-first-pipeline.md) asks for *pairs above a threshold*, **not connected
components**. The module's own docstring claimed it avoided chaining while the code performed it.

**Decided.** Complete linkage: a member joins only if it reaches the threshold against **every**
member. One comparison per existing member, and a group is a handful of items. The same corpus's
lowest in-group pair afterwards is **0.852**. Mutations **M37**, **M38** and **M39** attack the three
places the rule could be lost.

**The fix needed two passes.** The first `admissible()` closed over `key` but was also called for the
*other* members being pulled in, so it checked the wrong item against the cluster and still admitted
a **0.781** pair — a guard that was, for half its call sites, checking nothing.

**Live data is unaffected:** collapse on the 488 real leads is 5.74% before and after, because that
corpus contains no chains. The defect would have surfaced on the first dense real run, which is
P11's.

---

## D9 — DI14 does not bite, and is not closed by accident

[PHASE-09-HANDOVER §4 T1](PHASE-09-HANDOVER.md) flags P10 as *"the first place that bites"* for
[DI14](DEFERRED-IMPROVEMENTS.md)'s permalink host split.

**Re-measured 2026-08-14:** the live database now holds **444 `old.reddit.com` / 42
`www.reddit.com` / 2 `i.redd.it`** across **488** rows. The register records 444/27 across 471; the
database has grown since.

**It does not bite.** The cascade is content-keyed throughout — tier 1 hashes title and body, tier 2
shingles them, tier 3 embeds them, and identity is the database primary key. `DedupItem` carries **no
`url` field**, and all 12 multi-member content-hash buckets on the live data formed with `url`
playing no part. Two rows for one post under two hostnames would hash identically and group, which is
the correct outcome and the opposite of the failure DI14 predicts.

`test_the_dedup_cascade_is_keyed_on_content_not_on_url` keeps that an architectural property rather
than an accident. **DI14 remains open on its own merits**, and P10 does not close it.

---

## What was deliberately not done

| | Why |
|---|---|
| **DI25** — `triage.py`'s bare `\bhiring\b` discarding real leads | P11's, and [PHASE-09-HANDOVER §4 T3](PHASE-09-HANDOVER.md) says explicitly that P10 *"should not fix it in passing"* |
| **DI23** — two rejection vocabularies that disagree | P11's, which is the first phase that must render both on one page |
| **DI24** — `_triage_config` reads a mapping as a list | P11's |
| **DI26** — `normalise` tears decomposed Unicode apart | P11 or P15. Note `src/dedupe/exact.normalise` is a **different function** with different requirements; it is not the one DI26 names |
| **DI20**, **DI27** | Their triggers (a fifth occurrence / a second occurrence) were not satisfied |
| Adding `run_id` to `dedup_members` | See **D8** |
| Tuning `jaccard_threshold` to reach the collapse metric | See **D7** — and it would not have worked |
