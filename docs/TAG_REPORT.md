# Tag Report — `v0.1.0-p1`

**Date:** 2026-08-06 · **Action taken: none.** The tag already exists, is annotated, and is already
on GitHub. **No tag was created, moved or deleted.**

---

## 1. Verification of the existing tag

| Property | Value | Verdict |
|---|---|---|
| Name | `v0.1.0-p1` | ✅ matches the convention in [EXECUTION_MODE_LOCK §6.2](EXECUTION_MODE_LOCK.md) — `v<pyproject version>-pNN`, and `pyproject.toml` reads `0.1.0` |
| Object type | `tag` (not `commit`) | ✅ **annotated**, as required |
| Tagger | `Praveen` | ✅ |
| Date | 2026-08-06 | ✅ |
| Message | *P0 and P1 complete* | ✅ names the phases it marks |
| Points at | `d5089ee` — *docs: add pre-P2 verification report* | ✅ see §2 |
| On the remote | `refs/tags/v0.1.0-p1` → `d5089ee` | ✅ **already pushed** |

Commands run: `git tag -n99`, `git cat-file -t v0.1.0-p1`, `git show v0.1.0-p1`,
`git ls-remote --tags origin`.

**Only one tag exists.** No additional tag was created, per the brief.

---

## 2. Why the tag was not moved to `HEAD`

Since `d5089ee` the repository has gained process and hygiene commits: the execution-mode lock, the
workflow-alignment fix, and this pre-P2 operational pass. **None of them is P1 code.**

Moving a published tag rewrites a ref that clones and CI may already reference, and it would buy
nothing: the tag exists to be a labelled rollback point for the P1 implementation, and `d5089ee` is
exactly the last commit of that implementation. A stale-looking tag is better than a moved one.

The commits after it are recorded in [CHANGELOG.md](../CHANGELOG.md) under **[Unreleased]**, which is
what that section is for. The next tag is P2's.

---

## 3. Verification of the preconditions the tag claims

[EXECUTION_MODE_LOCK §6.2](EXECUTION_MODE_LOCK.md) says: *tag when a phase is signed off*, and
*do not tag a phase whose manual sign-off table is unsigned.*

| Precondition | State | Verdict |
|---|---|---|
| Repository health | `ruff check` clean · `ruff format --check` clean · 308 passed, 2 skipped · one alembic head · `check_schema.py` 25/25 | ✅ |
| Phase completion — P0 | Implementation, measurements and manual guide all present | ✅ |
| Phase completion — P1 | Implementation, tests, completion report, handover, progress record, manual guide all present | ✅ |
| **Manual sign-off — P00** | Sign-off table present, **all boxes ☐, Tester and Date blank** | ❌ **unsigned** |
| **Manual sign-off — P01** | Sign-off table present, **all ten boxes ☐, Tester and Date blank** | ❌ **unsigned** |

**So the honest verification result is: this tag could not be created today.** It was created by the
operator on 2026-08-06, before [EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md) existed, and the rule
it would now fail is not retroactive. It is recorded here rather than quietly accepted, because the
next tag — P2's — **will** be blocked by the same rule, and the block is the point.

---

## 4. What clears it

Open decision **O3** in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md): an operator executes and
signs [testing/P00-testing.md](testing/P00-testing.md) and [testing/P01-testing.md](testing/P01-testing.md).
Roughly 20 minutes each, non-destructive, no developer required.

Both guides were **corrected during this pass** — they previously expected `310 passed` where the
suite reports `308 passed, 2 skipped`, and `26 schema checks` where the verifier reports `25`. A
tester following them would have recorded a healthy repository as a failure. That correction is what
makes signing them possible.

---

## 5. Summary

| | |
|---|---|
| Tags in the repository | **1** — `v0.1.0-p1` |
| Created in this pass | **0** |
| Pushed in this pass | **0** — it was already on the remote |
| Verified | annotated ✅ · correct commit ✅ · correct name ✅ · on remote ✅ |
| Outstanding | the two unsigned manual sign-off tables (**O3**) |
