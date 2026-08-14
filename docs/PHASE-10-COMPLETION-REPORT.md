# Phase 10 — Completion Report · Dedup cascade

**Phase:** P10 (frozen numbering, [34 §P10](34-implementation-plan.md)) · **Date:** 2026-08-14
**Revision:** none — P10 adds no migration. `alembic heads` remains `0006_content_and_dedup`.

> Decisions and their measurements: [P10-DECISION-ANALYSIS.md](P10-DECISION-ANALYSIS.md).
> What the next phase inherits: [PHASE-10-HANDOVER.md](PHASE-10-HANDOVER.md).
> Where a lost session resumes: [progress/P10-COMPLETE.md](progress/P10-COMPLETE.md).

---

## 1. What was built

`src/dedupe/` — six modules that turn *"these look like the same conversation"* into a decision,
without touching a model, a table, or a per-item score.

| File | What it is |
|---|---|
| `__init__.py` | The two reason constants, `DedupSettings`, `DedupItem`, and the closed-vocabulary guard |
| `exact.py` | Tier 1 — normalisation and the SHA-256 content hash |
| `minhash.py` | Tier 2 — shingling, the 128-slot signature, LSH banding, the index |
| `semantic.py` | Tier 3 — optional Model2Vec cosine, a no-op when the library is absent |
| `groups.py` | The cascade, representative selection, the DI22 guarantee, and persistence |
| `__main__.py` | `python -m src.dedupe` — the only thing in this phase a person can look at |

**Nothing calls it.** [34 §P10](34-implementation-plan.md)'s Files row lists no handler and no
orchestration module; **P11 is its first caller**, exactly as P9 stood to P10.

### The correctness rule this phase exists to protect

[06c §4.4](06c-local-first-pipeline.md) — **group for analysis, score individually.** Three
near-identical threads have different authors, subreddits and ages, so they are worth different
amounts as leads. One shared analysis; three different confidence scores. Nothing in `src/dedupe/`
reads, writes or derives a per-item score, and `test_grouping_mutates_no_per_item_score` holds it.

---

## 2. Acceptance criteria

| [34 §P10](34-implementation-plan.md) | Evidence |
|---|---|
| Tier 3 groups paraphrase pairs sharing no 5-grams; tiers 1–2 do not | `test_tier_three_groups_paraphrases_that_share_no_five_grams` — asserts the fixture shares **zero** 5-grams, then that tiers 1–2 produce no group and tier 3 produces one |
| **With the semantic layer disabled the same run produces the identical lead set** *(bold)* | `test_disabling_tier_three_produces_the_identical_lead_set` — compares **whole sets**, not counts; plus `test_tier_three_configured_but_unavailable_is_a_clean_no_op`. Mutations M18–M21 |
| **A group of N yields N distinct pre-scores** *(bold)* | **Reconciled — D1.** `src/scoring/prescore.py` is P11's Files row and P11 depends on P10, so no pre-score exists. P10 proves the checkable half: `test_a_group_of_n_keeps_n_members_and_n_identities`, `test_grouping_mutates_no_per_item_score`. [freeze §11.1](ARCHITECTURE_FREEZE.md) |
| **MinHash indexes and queries 2,000 items in < 2 s CPU** *(bold)* | **Measured and met — 0.59 s / 0.87 s.** The literal *"128 perms"* reading measured **6.36 s / 11.11 s** and fails. `test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds`. D5, [freeze §11.1](ARCHITECTURE_FREEZE.md) |
| **No `src.ai` import** *(bold)* | `test_the_dedupe_package_is_inside_the_ai_fence` + `test_the_dedupe_package_exists`. Fence 2 now covers **3 of 6** paths |
| DI22 — at most one group per run | `test_no_item_belongs_to_two_groups`, `test_validate_membership_catches_a_hand_built_violation`, `test_persistence_refuses_a_result_that_violates_di22`, `test_tier_three_cannot_steal_a_member_from_an_earlier_tier`, and a 40-corpus property test. Mutations **M25** (the inner claim guard) and **M26** (the check itself) — **not** M24/M31, which survived as equivalents and therefore discharge nothing |

### Metrics

| Target | Measured |
|---|---|
| 2,000 items < 2 s | **0.59 s** (305-char) · **0.87 s** (870-char) ✅ |
| Collapse rate > 8% on real data | **5.74%** ❌ — **see §5** |
| 0 leads lost when tier 3 is off | **0** ✅ — asserted as set equality, not as a count |

---

## 3. Verification

| Check | Result |
|---|---|
| Full suite | **1640 passed, 2 skipped** in 287.45 s — one clean uninterrupted run (P9: 1380 / 2) |
| New tests | **+260** |
| `ruff check .` / `ruff format --check .` | Clean · 156 files |
| **Branch coverage, `src/dedupe/`** | **100%** — 533 statements, 186 branches, 0 missed |
| `alembic heads` | `0006_content_and_dedup` — one head, unchanged |
| `check_schema.py` | **51/51** — unchanged from P8 and P9 |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns |
| Grep fences | Fence 2 covers **3 of 6** specified paths, and says so |
| Offline guarantee | Held — tier 3's *installed* arm is tested by injecting a stub into `sys.modules`, never by downloading a model |
| Rollback | **Executed** — by flag, by config file, and by block deletion |

### A gate finding worth recording

**The A5 assertion fails under `--cov`, and that is the instrument, not the code.** Coverage's tracer
costs **3.0×** here: 0.59 s / 0.87 s bare against 1.76 s / 2.63 s instrumented. [35 §2.1](35-testing-strategy.md)
check 7 runs the whole suite under coverage, so the assertion would have gone red on a phase that
meets its budget comfortably.

The response was to **skip the timing assertion under a tracer and say so**, not to inflate the
budget — A5 is a claim about the CPU an operator's run will spend, and a budget padded to survive
instrumentation would stop being that claim. The criterion still fires on checks 4 and 5, which run
without coverage, and the code above the assertion executes either way so coverage is unaffected.

---

## 4. Mutation testing

Applied to every **bold** acceptance criterion, to the DI22 guarantee, and — after the first run —
to the complete-linkage rule that run exposed.

**39 designed · 36 detected · 3 survived · 0 hung · 0 not applied.**

| Group | Count | What they attack |
|---|---:|---|
| `exact.py` | 6 | emphasis spaced rather than deleted, whitespace deleted rather than collapsed, the edit-marker cut point and its anchoring, **D6's title/body boundary** |
| `minhash.py` | 10 | shingle width and emptiness, the empty-set sentinel, **min→max hashing**, densification and its donor, hard-coded banding, an inverted estimator, self-candidacy |
| `semantic.py` | 5 | unclamped cosine, the no-encoder guard, the threshold, the vector-count mismatch guard, `except Exception` narrowed to `ImportError` |
| `groups.py` | 17 | the representative tie-break, unknown-score handling, **four DI22 breaches**, raw-vs-normalised shingling, method precedence, per-member reason attribution, the threshold check, collapse arithmetic, **three complete-linkage breaches** |
| `__init__.py` | 1 | the closed-vocabulary guard (**D3's cost, paid**) |

### The three survivors are all provably equivalent

| | Why it cannot be detected |
|---|---|
| **M6** | **The deliberate control.** `x.append(k) if True else None` is semantically identical to `x.append(k)`. It is in the set precisely so that a run in which *everything* is "detected" is recognisable as broken — and it earned its place, see below |
| **M24** · **M31** | The `clusters.holds(...)` guards in tiers 2 and 3 are **redundant**: `_Clusters.attach()` opens with `if key in self._of: return`. Defence in depth. The load-bearing guard is the inner one, and **M25 attacks it and is detected** |

Three earlier designs were also equivalent and were **replaced rather than counted**: `.match` →
`.search` and removing `^` (the edit-marker rule is doubly anchored, so each alone changes nothing),
and `<= k` → `< k` on shingle width (at `len == k` the general path yields the same single shingle).

⚠️ **[PHASE-09-HANDOVER §4 T4](PHASE-09-HANDOVER.md) applied, and it fired twice.** A mutation
reporting *"anchor not found"* is not a pass: the driver requires each anchor to match **exactly
once** and reports a miss as its own outcome. Two anchors went stale when the complete-linkage
rewrite moved the code under them, were re-cut, and are now detected. **Zero mutations failed to
apply in the final run.**

**T4 gains a sibling: a driver without a timeout is worse than no driver.** The first run had none
and was killed after 30 minutes having reported nothing — and the cause was not a mutation but the
driver's own root-finding loop, which walked up from the scratchpad, never found `src/`, and spun at
the drive root where `Path("C:/").parent` is itself. The driver now has a 180 s per-mutation ceiling,
reports **HUNG** as a fourth outcome, and flushes each line to a file so a killed run still leaves a
record.

---

## 5. ❌ The one metric not met, and why

[34 §P10](34-implementation-plan.md)'s Metrics row asks for **collapse rate > 8% on real data**.
Measured on a read-only copy of `data/leads.db` (488 leads): **5.74%**.

**This was investigated rather than worked around, and it is not under-detection.**

| `jaccard_threshold` | Groups | Collapse |
|---|---:|---:|
| 0.95 | 20 | 4.51% |
| **0.85 — shipped** | **23** | **5.74%** |
| 0.80 · 0.75 · 0.70 · 0.60 | 23 | **5.74%** |

**Root cause, three findings:**

1. **Flat from 0.85 down to 0.60.** Loosening the threshold finds **zero** additional duplicates. The
   corpus holds 5.74% duplicate content and no more.
2. **ID-level dedup is already spent.** All 488 `reddit_id` values are distinct — the column is
   `UNIQUE`. [28 §L3](28-discovery-redesign.md)'s *"3–8% residual overlap"* for ID dedup, the figure
   most plausibly behind the >8% target, is removed before the cascade sees the data.
3. **The estimate is intra-run; the corpus is an archive.** [06c §3.2](06c-local-first-pipeline.md)
   gives `duplicate_exact` 3–8% and `duplicate_near` 8–20%, both explicitly *"this run"*. The live
   database holds **59 scrape runs across 4 subreddits, 2024-03-18 to 2026-08-13**, and 12.3% of its
   leads carry an empty body.

**Resolved as a reconciliation:** the metric is the intra-run quantity it was always about, and the
intra-run measurement belongs to **P11** — the first phase with a live call site and funnel counters.
P10 is library-only and structurally cannot make it. **No threshold was tuned to chase the number**,
and the flatness measurement proves tuning could not have reached it.
[freeze §11.1](ARCHITECTURE_FREEZE.md), [P10-DECISION-ANALYSIS §D7](P10-DECISION-ANALYSIS.md).

---

## 6. 🔴 The defect mutation testing found

**Mutation M35 — replacing the cascade's `sim >= jaccard_threshold` with `sim >= 0.0` — survived the
first full run.** Probing why did not find a missing test. It found a real defect.

`_Clusters.attach` joined a cluster on the strength of **one** match. That is **single linkage**, and
single linkage is transitive closure in disguise: `A~B` at 0.90 and `B~C` at 0.90 puts `A` and `C` in
one group however far apart they are. Measured on a graded corpus, 2026-08-14: **a 14-member group
whose furthest pair was 0.445 similar.**

The consequence is not cosmetic. Those two leads would have **shared one AI analysis** — which is
precisely the silent quality regression [06c §4.4](06c-local-first-pipeline.md) exists to forbid, and
[06c §4.2](06c-local-first-pipeline.md) asks for *pairs above a threshold*, not connected components.
The module's own docstring claimed it avoided chaining while the code performed it.

**Fixed as complete linkage:** a member joins only if it reaches the threshold against **every**
member. The cost is one comparison per existing member, and a group is a handful of items. After the
fix the same corpus's lowest in-group pair is **0.852**.

⚠️ **The fix needed two passes, and the second was found the same way.** The first version of
`admissible()` closed over `key` but was also called for the *other* members being pulled in — so it
checked the wrong item against the cluster and still let a **0.781** pair through. A complete-linkage
guard that was, for half its call sites, checking nothing.

**Live data is unaffected:** collapse on the 488 real leads is **5.74% before and after**, because
that corpus contains no chains. The defect would have appeared on the first dense real run — P11's.

### And a contaminated run, caught by the control

The first regression test written for this built three documents and let the LSH index find them.
**It failed on correct code**, because banding is *probabilistic* — a 0.906 pair shares a band only
~83% of the time at 8 bands of 16 rows, so the anchor did not reliably see both matches.

While it was red, the mutation run reported **39 of 39 detected** — including **M6, the deliberate
no-op control**. That is the only reason the contamination was visible: a control that gets detected
is a run that proves nothing. The linkage tests are now driven by a **fixed similarity table**, and
the corpus-level property is asserted separately by a test that holds whichever pairs banding offers.

---

## 7. Things found by testing, not by review

**1. Shingling raw text loses the reposts the tier exists to catch.** The first implementation fed
tier 2 the raw title and body. Measured: *"Which CRM should I use for my small startup team?"* against
the same sentence casefolded and without the question mark estimates **0.55** raw and **0.98**
normalised. At a 0.85 threshold the raw form misses a repost differing only in capitalisation — which
is the single most common way a repost differs. [06c §4.2](06c-local-first-pipeline.md) chooses
character n-grams *because* casing and punctuation *"vary far more than substance"*; shingling raw
text does the opposite of what that sentence asks for. Mutation M27.

**2. A near-duplicate of an already-grouped post was stranded alone.** Tier 2 originally skipped any
item an earlier tier had claimed, so a post 95% similar to a member of an exact group formed no group
at all — collapse lost for no reason, and two groups describing one discussion. Later tiers now
**extend** a group instead. Clusters are deliberately **not merged** when a match spans two of them:
that is transitive closure, which chains `A~B~C` into one group when `A` and `C` are 0.4 similar.

**3. An exact duplicate inside an extended group was being reported as *near*.** Once a group's
method upgrades to `minhash`, deriving every member's reason from the group would move real
`duplicate_exact` volume into the near bucket — and the two mean very different things to an operator
(a repost versus a separate conversation). The group is now described by its **loosest** evidence
while each member reports **how it joined**. Mutations M29, M30.

**4. A text-less item was being signed on the strength of a newline.** `_dedupe_text` returned
`"\n"` for a post with no title and no body, which shingles to one shingle — giving every body-less
post in a run the *same* signature. 12.3% of live leads have an empty body. Mutation M28.

**5. The A5 assertion measures the instrument under `--cov`.** §3 above.

**6. The densification mask was dead code with a wrong justification.** Mutation **M11** deleted a
per-slot XOR mask and survived. It survived because it was an *equivalent* mutation: **XOR with a
constant preserves equality** — `a ^ m == b ^ m` exactly when `a == b` — so it could never change the
agreement pattern `estimate_jaccard` counts. The docstring justified it as decorrelating borrowers,
which is simply false. **The honest response to an equivalent mutation over dead code is to delete
the code**, not to write a test that pins it, so the mask is gone.

**7. The manual guide's own T8 was wrong when written.** `-k dedupe` matches **2** of the 3 boundary
tests, because the third is named `dedup_cascade`. Found by executing the guide before publishing it
— the same class of error P9 had to correct after the fact in `defa9ca`, caught before shipping this
time.

---

## 8. Documentation landed

| Document | Change |
|---|---|
| [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) | **Four reconciliations** — A5/OPH, the N-distinct pre-scores, the collapse metric, and 06c's stale exclusion of the semantic tier. **No §11 amendment**: no technology, table, decision or dependency changes in any of them |
| [06c §4.2](06c-local-first-pipeline.md) | The *"No embedding model, no vector database"* paragraph struck as superseded by AD-16, with its objection answered; **new §4.2a** describes the tier that actually ships. §4.2's performance caution annotated with what measuring it changed |
| [06c §4.3](06c-local-first-pipeline.md) | The pre-score dependency recorded — `rank` is injected, and the N-distinct assertion moves to P11 |
| [34 §P10](34-implementation-plan.md) | A four-part reconciliation note, plus the record of which two files sit outside the Files row and why |
| [35 §2.1](35-testing-strategy.md) | Fence 2's table updated — `src/dedupe/` **enforced since P10**; P5's F3 now recorded **five** times; the `RejectionReason` temptation named |
| [35 §6](35-testing-strategy.md) | P10's row corrected — A5 annotated, the pre-score criterion struck through and replaced, the manual check made executable |
| [docs/README.md](README.md) | P10 execution row |
| `config.yaml` | The `dedup:` block, with both rollbacks and the A5 measurement documented inline |
| `requirements.txt` | **No required dependency added.** Tier 3's two libraries recorded as an explicitly optional block, with the reason they are not hard requirements |

---

## 9. Deferred Improvements

**No DI was closed, and none was created.**

| | |
|---|---|
| **DI22** | **Discharged as designed** — it asked P10 to uphold the invariant at application level, and P10 does. It is not "closed": the schema gap it describes is still real, and a future writer other than this cascade would reintroduce it |
| **DI14** | **Re-measured and left open.** The live split is now **444 `old.reddit.com` / 42 `www.reddit.com` / 2 `i.redd.it`** across **488** rows; the register records 444/27 across 471. It does **not** bite P10 — the cascade is content-keyed and `DedupItem` has no `url` field, held by `test_the_dedup_cascade_is_keyed_on_content_not_on_url` |
| **DI23 · DI24 · DI25 · DI26** | Untouched. P11's and P15's, and [PHASE-09-HANDOVER §4 T3](PHASE-09-HANDOVER.md) says explicitly that P10 must not fix DI25 in passing |
| **DI20 · DI27** | Triggers not satisfied — no fifth `check_schema` race, no second heartbeat failure, across this phase's runs |

---

## 10. What P10 deliberately did not do

| | Why |
|---|---|
| Add `run_id` to `dedup_members` | DI22 records it as a [freeze §11](ARCHITECTURE_FREEZE.md) question. P10 did not need it, so it was not asked |
| Add `datasketch` | [freeze §5](ARCHITECTURE_FREEZE.md) closes the technology set; §12 forbids introducing one. Same reasoning by which P9 refused `hypothesis` |
| Make `model2vec` / `sqlite-vec` required | CI would then never exercise the degraded path, which is the case AD-16 exists to protect |
| Create `src/db/repositories/dedupe.py` | Outside the Files row. P11 adds `repositories/comments.py` and owns the first caller |
| Wire the cascade into the scrape path | Outside the Files row; P11's |
| Tune `jaccard_threshold` to reach the collapse metric | §5 — and it would not have worked |
