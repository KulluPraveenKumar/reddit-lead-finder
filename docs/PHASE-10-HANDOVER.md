# Phase 10 — Handover

**From:** P10, the dedup cascade (`src/dedupe/`) · **Written:** 2026-08-14
**To:** **P11**, and for the debts, **P12**, **P19** and **P21**

> Evidence lives in [PHASE-10-COMPLETION-REPORT.md](PHASE-10-COMPLETION-REPORT.md).
> Reasoning lives in [P10-DECISION-ANALYSIS.md](P10-DECISION-ANALYSIS.md).
> Where the next session resumes lives in [progress/P10-COMPLETE.md](progress/P10-COMPLETE.md).

---

## 1. What now exists

Six modules under `src/dedupe/` — exact, MinHash, semantic, the cascade, a settings/vocabulary
module, and a demo CLI. **Nothing imports them.** P10 built the library; **P11 is its first caller** —
the same sentence P9's handover wrote about P10, and it is now P11's turn.

No migration, no table, no column, no route. `alembic heads` is `0006_content_and_dedup`, unchanged
for the third phase running.

**The public surface P11 will use:**

```python
from src.dedupe import DedupItem, DedupSettings
from src.dedupe.groups import build_groups, persist

result = build_groups(items, DedupSettings.from_config(config))
groups, members = persist(session, result, run_id=run.id, project_id=None)
```

`result` carries `.groups`, `.content_hashes`, `.signatures`, `.rejections`, `.grouped_keys`,
`.representatives` and `.collapse_rate(n)`.

---

## 2. Guarantees P11 must not break

| | Guarantee | Enforced by |
|---|---|---|
| **G1** | **`src/dedupe/` imports neither `src.ai` nor `hermes`** | `test_the_dedupe_package_is_inside_the_ai_fence`, AST-based |
| **G2** | **Deleting the package fails a test rather than silencing the fence** | `test_the_dedupe_package_exists`, plus `assert scanned > 0` |
| **G3** | **P9's four + P10's two stay a strict subset of P19's eleven** | `test_p9_and_p10_together_reach_six_of_p19s_eleven` |
| **G4** | **`duplicate()` refuses any reason outside `REASONS`** | `ValueError`, and mutation M36 |
| **G5** | **DI22 — no item belongs to two groups** | Structural in `_Clusters`, checked by `validate_membership`, refused by `group_rows`/`persist`, and a 40-corpus property test |
| **G6** | **Grouping mutates no per-item score** | `test_grouping_mutates_no_per_item_score` — [06c §4.4](06c-local-first-pipeline.md) |
| **G7** | **The cascade is keyed on content, never on `url`** | `test_the_dedup_cascade_is_keyed_on_content_not_on_url` — DI14 |
| **G8** | The 459 original leads and the `intent_score` fingerprint | `check_schema.py`, unchanged by P10 |
| **G9** | One head, always — and P10 added no revision | `test_single_head` |

---

## 3. ⚠️ What P11 inherits directly

**P11 is the first caller of `src/dedupe/`, and the phase that owes three of P10's reconciliations.**

1. **`DedupItem.rank` is waiting for your pre-score.** It defaults to `None` and the representative
   ordering falls back to `(score, created_utc, row_id)`. Fill `rank` in from
   `src/scoring/prescore.py` and [06c §4.3](06c-local-first-pipeline.md)'s specified ordering is
   restored **without a signature change**. This is operator decision **D1**, and it is the reason
   *"a group of N yields N distinct pre-scores"* is now yours.

2. **Two acceptance criteria transferred to you**, both recorded at
   [freeze §11.1](ARCHITECTURE_FREEZE.md):
   - *"a group of N yields **N distinct pre-scores**"* — P10 proved N distinct **members** and no
     score mutation; the pre-scores are yours.
   - *"collapse rate **> 8%** on real data"* — see §4 T1. This one has a measurement behind it, and
     the measurement says the number is not reachable the way it was being read.

3. **Extend fence 2 to `src/scoring/`, with an existence guard beside it.**
   [35 §2.1](35-testing-strategy.md) row 9's table now says P10 enforced its own path. **Copy the
   pairing exactly** — a fence that walks whatever is there passes vacuously the moment the package
   is deleted, which is **P5's F3, now recorded five times**. Fence 2 covers **3 of 6**.

4. **`RuleResult`, not `GateDecision`, still.** `src/scoring/` is inside the same R3 fence. The
   adapter remains P19's.

5. **Your reasons are `below_prescore` and `out_of_window`**, spelled to match `RejectionReason` and
   **not imported from it**. Follow P10's shape, not P9's instruction: declare them in
   `src/scoring/`, and extend `tests/test_rules_vocabulary.py`'s subset assertions from six to eight.

---

## 4. Traps waiting in P11

**T1 — 🔴 the collapse-rate metric is not reachable against the stored archive, and you own the real
measurement.** P10 measured **5.74%** against a *"> 8%"* target and, crucially, **flat at 5.74% all
the way down to a 0.60 threshold** — loosening finds nothing, so this is not a tuning problem. Two
structural causes: every `reddit_id` in `leads` is distinct, so [28 §L3](28-discovery-redesign.md)'s
*"3–8% residual overlap"* is already spent; and the corpus is **59 runs over 29 months**, while
[06c §3.2](06c-local-first-pipeline.md)'s estimates are explicitly *"this run"*. **You have the first
live call site and the funnel counters**, so you can measure the intra-run rate that the target was
always about. **Do not tune `jaccard_threshold` to reach a number** — P10 measured that it does not
work.

**T1a — 🔴 grouping is COMPLETE linkage, and single linkage is the defect it replaced.** A member
joins only if it reaches the threshold against **every** member, not just the one that matched it.
The single-linkage version produced a **14-member group whose furthest pair was 0.445 similar** —
two barely-related leads sharing one AI analysis, which is [06c §4.4](06c-local-first-pipeline.md)'s
silent quality regression exactly. Found by mutation testing, not review. **Do not "simplify"
`_Clusters.attach`'s `admissible()` away**; three mutations (M37, M38, M39) exist to stop that, and
the fix itself needed two passes because the first version checked the wrong item.

⚠️ **`attach()`'s `similarity` argument defaults to `None`, and that default IS single linkage.**
With nothing to compare against, `admissible()` returns `True`. Both call sites in `build_groups`
pass it and the three mutations guard them — but **a fourth tier that forgot to would silently get
the 0.445 behaviour back**, with no test failing. If you add a tier, pass it.

**T1b — a corpus-driven test of grouping can be a coin flip.** LSH banding is **probabilistic**: a
0.906-similar pair shares a band only ~83% of the time at 8 bands of 16 rows. A test asserting *which*
items group is therefore flaky; assert the **property** (no group contains a below-threshold pair)
or drive the logic with a fixed similarity table. P10's first linkage test failed on correct code for
exactly this reason.

**T2 — the sketch and exact Jaccard disagree near the threshold, by design.** A 128-slot signature
estimates Jaccard to ~±0.05. Measured: a pair at exactly **0.815** estimates **0.859** and therefore
groups. `test_near_the_threshold_the_sketch_and_exact_jaccard_can_disagree` pins it. **Do not "fix"
it by computing exact Jaccard over every candidate** — that is the O(n²) cost banding exists to
avoid, and the classic 128-permutation implementation measured *less* accurate anyway. The
consequence is bounded: a borderline pair is grouped, one is enriched, and **both keep their own
score**.

**T3 — 🔴 a performance test can measure the wrong quantity on the wrong data, and look fine for a
whole phase.** A5's assertion failed P10 acceptance testing at 2.206 s where the same commit measured
0.92 s on the **same machine**. No regression — two defects in the test, both fixed 2026-08-15:

- **It timed wall clock where the spec says CPU.** Use `cpu_seconds()` (`time.process_time`). Note the
  honest limit, measured: contention inflates wall clock 2.08× and CPU **1.97×**, so this fixes
  *what* is measured, not immunity to a busy machine.
- **Its corpus was lighter than production — twice over.** Fixed-length 870-character documents
  against a real median of 1,060; and, after that was fixed, still only **391 distinct 5-grams per
  document against a real 1,053**, because a 19-word vocabulary saturates at **65** distinct 5-grams
  regardless of document length. **`shingles()` returns a set, so cost tracks distinct 5-grams, not
  characters** — match your corpus on *that*, or you will measure a workload you do not have.

`test_the_benchmark_corpus_matches_real_data` now asserts the corpus's own mean, median, tail and
5-gram density. **If you add a performance test in P11, copy all three habits**: `assert_within()`
(which skips under a tracer — [35 §2.1](35-testing-strategy.md) check 7 runs the suite under
coverage), CPU time, and a corpus that asserts its own representativeness.

**Residual risk you inherit:** A5's margin is **1.86×** on representative data (0.95–1.08 s CPU
quiet, 0/15 over budget), and under a 3×-oversubscribed machine it still exceeded once in 8. No
absolute threshold can be immune to that.

**T4 — a mutation driver without a timeout hangs forever, and the hang will not be a mutation.**
P10's first run had none and was killed after 30 minutes having reported nothing; the cause was the
driver's own root-finding loop, which walked up from the scratchpad, never found `src/`, and spun at
the drive root where `Path("C:/").parent` is itself. This is P9's T4 (*"anchor not found is not a
pass"*) with a sibling: **a timeout is its own outcome, neither a detection nor a survival**. Flush
each line to a file as you go, or a killed run leaves no record at all. Two of P10's anchors also
went stale mid-phase when a rewrite moved the code under them — **re-cut them; NOT-APPLIED is not a
pass.**

**T4a — 🔴 put a deliberate no-op control in the mutation set, and believe it.** P10's control (`x
if True else None`) is the *only* reason a contaminated run was caught: a regression test was failing
on correct code, so the run reported **39 of 39 detected** — including the control. **A run in which
everything is detected is a broken run, not a triumph.** Verify a new test passes on clean code
*before* trusting any mutation result that depends on it.

**T4b — a survivor may be neither a code defect nor a test defect, but an *equivalent* mutation.**
P10 had three, and the right response differed each time: the control **stays** (it is doing its
job); two redundant guards **stay** (defence in depth, with the load-bearing one separately
attacked); and one — a densification XOR mask whose stated purpose was arithmetically impossible —
was **deleted**, because the honest answer to dead code is removal, not a test that pins it.

**T5 — 🔴 [DI25](DEFERRED-IMPROVEMENTS.md) is now yours, and it is a live defect.** `triage.py`'s
bare `\bhiring\b` rejects *"Our hiring process is broken and I need a tool to fix it"* — a textbook
lead. You own the 2% metadata-triage holdout ([R11](ARCHITECTURE_FREEZE.md)), which is the **first
mechanism in this project capable of measuring the false-positive rate rather than arguing about
it.** P9 and P10 both deliberately declined to fix it in passing.

**T6 — [DI24](DEFERRED-IMPROVEMENTS.md) means P6's keyword score has always been 0.0.**
`_triage_config` reads the `keywords:` mapping as a sequence, so it yields tier *names*. Nothing
noticed because nothing consumed the score. **P11 is the first phase that consumes it**, so a silently
zero component will now change a decision.

**T7 — [DI23](DEFERRED-IMPROVEMENTS.md): you are the first phase that must render two disagreeing
vocabularies on one page.** `triage.py` produces nine reasons; `gate.py` fixes eleven; P9 and P10
between them produce six of the eleven. The funnel counters are yours.

**T8 — normalising before shingling is load-bearing, and it is not obvious.** `groups._dedupe_text`
normalises title and body **before** tier 2 sees them. Measured: a pair differing only in
capitalisation estimates **0.55** raw and **0.98** normalised, so the raw form misses the single most
common kind of repost. A reader "simplifying" this to raw text would silently halve tier 2's recall.
Mutation M27.

**T9 — `src/dedupe/exact.normalise` and `src/rules/keywords.normalise` are different functions with
opposite requirements**, and a reader will want to merge them. Punctuation becomes a space in one and
is kept in the other; emphasis markers are deleted in one and spaced in the other. The docstring in
`exact.py` carries the table. **[DI26](DEFERRED-IMPROVEMENTS.md) names the `keywords` one, not this
one.**

---

## 5. Debts carried forward, by owner

| | Item | Owner |
|---|---|---|
| **DI22** | **Discharged as designed by P10** — upheld at application level. Not *closed*: the schema gap is still real and a future writer other than this cascade would reintroduce it | Any future writer |
| **DI14** | Re-measured: **444 / 42 / 2 across 488 rows** (register says 444/27 across 471). **Does not bite P10** — the cascade is content-keyed. Still open | Unchanged |
| **DI23** | Two rejection vocabularies ship and disagree | **P11** |
| **DI24** | `_triage_config` reads a mapping as a list; P6 has never matched a keyword | **P11** |
| **DI25** | 🔴 `triage.py`'s bare `\bhiring\b` discards real leads | **P11** |
| **DI26** | `keywords.normalise` tears decomposed Unicode apart | **P11 or P15** |
| **DI13** | `num_comments = 0` where the honest value is `None` | **P11** |
| **DI20** | The `check_schema` WAL/mtime race | *A fifth occurrence, or one in CI* |
| **DI27** | The heartbeat flake — one occurrence, never reproduced | *A second occurrence* |
| **DI16 / T1 (P8)** | `leads.confidence_score` exists but is not populated | **P21** |
| **DI17** | Nothing enqueues `maintenance` | **P17** |
| **L4 (P7)** | Notification retry — **still nobody's** | Open since P7 |
| **O2** | `mypy`, 193 errors, deferred by D6 in P8. `src/dedupe/` ships clean under it | Its own scoped task |

**No DI was closed in P10, and none was created.** None of the recorded triggers was satisfied.

---

## 6. Things a later phase must delete on purpose

| Phase | Test | Why it is there |
|---|---|---|
| **P15** | `test_the_competitor_registry_was_not_wired_before_p15` | *(P9's)* A competitor rule that quietly matches nothing looks exactly like a business with no competitors |
| **P12** | *(none)* | But when `0007` creates the vector tables, `src/dedupe/semantic.py`'s in-memory comparison is the thing to revisit — and `test_tier_three_off_is_the_shipped_default` is what will fail if the default changes without a decision. **The specific thing to revisit:** complete linkage means tier 3 can extend a group tiers 1–2 opened only if the new item clears the *cosine* threshold against **every** existing member — and `similar_pairs` only returns pairs it scored above that threshold, so any unscored pair reads as `0.0` and refuses. Cross-tier extension is therefore rare by construction. That is **correct** under the linkage rule and invisible today (the tier ships off, and P0 measured both libraries absent), but a persisted vector index would make it observable, and it should be a decision rather than a rediscovered mystery |
| **P19** | *(none yet)* | **`build_groups()` is not `PreAIGate` and must not become it.** It composes only P10's three tiers. Nothing enforces that boundary today |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1640 passed, 2 skipped** (P9: 1380 / 2) |
| New tests | **+260** |
| Branch coverage, `src/dedupe/` | **100%** — 533 statements, 186 branches |
| `ruff check` / `format --check` | Clean · 156 files |
| `alembic heads` | `0006_content_and_dedup` — one head, unchanged |
| `check_schema.py` | **51/51** |
| Legacy contract | 459 baseline leads · `max 164.28` · `avg 42.29` · 13 CSV columns |
| Mutation testing | **39 designed · 36 detected · 3 survived · 0 hung · 0 not applied.** All three survivors are **provably equivalent** — one is the deliberate no-op control ([completion report §4](PHASE-10-COMPLETION-REPORT.md)) |
| Grep fences | Fence 2 covers **3 of 6** specified paths, and says so |
| A5 | **Measured and met** — 0.59 s / 0.87 s against 2 s |
| Collapse on real data | **5.74%** against a >8% target — reconciled, see §4 T1 |
| Rollback | **Executed** three ways — flag, config file, block deletion |

---

## 8. Blockers carried into P11

| ID | Blocker | Blocks P11? |
|---|---|---|
| **D1/O3** | **P00–P07 manual sign-off tables unsigned.** P8's was signed 2026-08-14 | **No, but no tag.** P9's and P10's guides are unsigned until the operator runs them |
| **O2** | `mypy` not in the gate — 193 errors in 23 files | **No.** Deferred by D6 in P8 |
| **L4 (P7)** | Notification retry undelivered | **No**, still an open P7 obligation |
| **DI25** | 🔴 A live defect discarding leads | **No — it is now P11's own work item**, not a blocker on starting |
| **Collapse metric** | 5.74% against >8% | **No.** Reconciled and transferred; P11 owns the measurement |

---

## 9. Entry conditions for P11

- [ ] `docs/testing/P10-testing.md` sign-off table signed — **T2, T4 and T6 especially**
- [ ] **[§3 read]** — `DedupItem.rank` is yours to fill; fence 2 for `src/scoring/` is yours to extend
- [ ] **[§4 T1 read]** — the collapse metric transferred to you **with a measurement saying not to tune for it**
- [ ] **[§4 T5/T6/T7 read]** — DI25, DI24 and DI23 all land in P11, and DI25 is live
- [ ] **[§4 T3 read]** — copy `assert_within()` if you add a timing assertion
- [ ] **[§4 T8/T9 read]** — normalise before shingling, and the two `normalise` functions are not the same function
- [ ] [34 §P11](34-implementation-plan.md) read — all thirteen fields, including the **2% stage-3 holdout** and **`SELECT COUNT(*) FROM ai_calls WHERE run_id=?` = 0**
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] The full suite recorded green before the first change — **1640 passed, 2 skipped**
- [ ] `git status` clean · `alembic heads` = one `0006` · `check_schema.py` 51/51
- [ ] `gh run list` checked: P10 green on `origin/main`
- [ ] ⚠️ **`config.yaml` checked for uncommitted local values** — it carried a real chat id at the
      start of both P8 and P9. It was clean at the start of P10, and P10 added the `dedup:` block to it
