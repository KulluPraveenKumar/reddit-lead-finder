# P10 — COMPLETE

**Phase:** P10, the dedup cascade · **Date:** 2026-08-14
**Status:** implementation, tests, docs and rollback complete. **Awaiting manual sign-off.**

> This file answers one question: **if this session is lost, where does the next one resume?**
> Evidence: [PHASE-10-COMPLETION-REPORT.md](../PHASE-10-COMPLETION-REPORT.md).
> Forward-looking traps: [PHASE-10-HANDOVER.md](../PHASE-10-HANDOVER.md).
> Reasoning: [P10-DECISION-ANALYSIS.md](../P10-DECISION-ANALYSIS.md).

---

## Resume point

**P10 is code-complete and documented. The next action is the operator running
[docs/testing/P10-testing.md](../testing/P10-testing.md) and signing its table.**

**Do not begin P11 until that signature exists** ([lock §3](../EXECUTION_MODE_LOCK.md) step 16).
**Do not tag** until it exists either — a tag would claim a verification that did not happen
([lock §6.2](../EXECUTION_MODE_LOCK.md)).

---

## State of the repository

| | |
|---|---|
| Branch | `main` |
| `alembic heads` | `0006_content_and_dedup` — one head, **unchanged for three phases** |
| `check_schema.py` | 51/51 |
| Full suite | **1640 passed, 2 skipped** |
| Coverage, `src/dedupe/` | **100%** branch — 533 statements, 186 branches |
| Mutation testing | **39 designed · 36 detected · 3 survived** (all three provably equivalent, one a deliberate control) |
| `ruff` | clean, 156 files |
| Legacy contract | 459 leads · `max 164.28` · `avg 42.29` · 13 CSV columns |

### Files added

```
src/dedupe/__init__.py        constants, DedupSettings, DedupItem, the vocabulary guard
src/dedupe/exact.py           tier 1 — normalise + SHA-256 content hash
src/dedupe/minhash.py         tier 2 — shingles, 128-slot signature, LSH banding, index
src/dedupe/semantic.py        tier 3 — optional Model2Vec cosine, no-op when absent
src/dedupe/groups.py          the cascade, representative, DI22, persistence
src/dedupe/__main__.py        python -m src.dedupe — the manual guide's instrument

tests/test_dedupe_exact.py
tests/test_dedupe_minhash.py
tests/test_dedupe_semantic.py
tests/test_dedupe_groups.py
tests/test_dedupe_settings.py
tests/test_dedupe_properties.py
tests/test_dedupe_performance.py
tests/test_dedupe_cli.py

docs/P10-DECISION-ANALYSIS.md
docs/PHASE-10-COMPLETION-REPORT.md
docs/PHASE-10-HANDOVER.md
docs/testing/P10-testing.md
docs/progress/P10-COMPLETE.md
```

### Files modified

```
config.yaml                        + the dedup: block
requirements.txt                   + an OPTIONAL block; NO required dependency added
tests/test_boundaries.py           + fence 2 over src/dedupe/, its existence guard, the DI14 guard
tests/test_rules_vocabulary.py     + P10's two reasons; six of eleven asserted across both packages
docs/ARCHITECTURE_FREEZE.md        + four §11.1 reconciliations
docs/06c-local-first-pipeline.md   §4.2 corrected, §4.2a added, §4.3 annotated
docs/34-implementation-plan.md     + the P10 reconciliation note
docs/35-testing-strategy.md        fence 2 table, §6 P10 row
docs/README.md                     + the P10 execution row
```

---

## The four things a new session most needs to know

1. **A5 was measured and the literal spec fails it.** *"MinHash 128 perms"* read as 128 independent
   permutations costs **6.36 s / 11.11 s** for 2,000 items against a **2 s** budget. `minhash.py`
   ships **One-Permutation Hashing** — same 128-slot signature, same banding, same estimator,
   **0.59 s / 0.87 s** end to end and *more* accurate. [freeze §11.1](../ARCHITECTURE_FREEZE.md).
   **Do not "restore" classic MinHash.**

2. **The collapse metric is the one thing not met: 5.74% against >8%** — and it is **flat down to a
   0.60 threshold**, so it is not a tuning problem. ID dedup is already spent (every `reddit_id`
   distinct) and the corpus is 59 runs over 29 months where the estimate is *"this run"*. **P11 owns
   the real measurement.** Do not tune the threshold.

3. **DI22 is upheld in the write path, not checked at the end.** `_Clusters` makes a double claim
   impossible to construct; `validate_membership` checks it independently; `persist` refuses a
   result that fails. **No column was added to `dedup_members`.**

3b. **🔴 Grouping is COMPLETE linkage, and that is a defect fix, not a preference.** Mutation testing
   found the single-linkage version producing a **14-member group whose furthest pair was 0.445
   similar** — two unrelated leads sharing one AI analysis. Do not simplify
   `_Clusters.attach`'s `admissible()` away; M37/M38/M39 exist to stop it.

4. **Nothing calls `src/dedupe/`.** P11 is the first caller, and `DedupItem.rank` is the slot waiting
   for P11's pre-score.

---

## What is NOT done, deliberately

| | |
|---|---|
| Manual sign-off | **The operator's.** The guide is written and was executed by machine; the table is blank |
| Git tag | Blocked on the signature |
| Any call site | P11's |
| DI23 · DI24 · DI25 · DI26 | P11's / P15's. **DI25 is a live defect and P10 was told not to fix it in passing** |
| `mypy` in the gate | O2, deferred by D6 in P8. `src/dedupe/` is clean under it |

---

## If something looks wrong

| Symptom | Where to look |
|---|---|
| A5 assertion red under `--cov` | Expected — coverage costs 3.0×. `assert_within()` skips and says so. [Completion report §3](../PHASE-10-COMPLETION-REPORT.md) |
| Collapse rate below 8% | Expected and diagnosed. [Completion report §5](../PHASE-10-COMPLETION-REPORT.md) |
| A borderline pair grouped that exact Jaccard would not | Expected — a 128-slot sketch is ±0.05. [Handover §4 T2](../PHASE-10-HANDOVER.md) |
| Two `normalise` functions | Different functions, opposite requirements, on purpose. [Handover §4 T9](../PHASE-10-HANDOVER.md) |
| `python -m src.dedupe` groups nothing | Check `config.yaml`'s `dedup:` block — a rollback may be left switched on |
