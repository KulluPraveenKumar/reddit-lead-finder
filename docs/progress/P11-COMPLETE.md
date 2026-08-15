# P11 — Complete

**Date:** 2026-08-15 · **Phase:** P11, pre-score, funnel & comments
**Revision:** none. `alembic heads` = `0006_content_and_dedup`.

> This file answers one question: **if this session is lost, where does the next one resume?**
> Evidence is in [PHASE-11-COMPLETION-REPORT.md](../PHASE-11-COMPLETION-REPORT.md); what P12 must
> know is in [PHASE-11-HANDOVER.md](../PHASE-11-HANDOVER.md); the reasoning is in
> [P11-DECISION-ANALYSIS.md](../P11-DECISION-ANALYSIS.md).

---

## State at the end of the session

| | |
|---|---|
| Implementation | ✅ complete |
| Automated tests | ✅ **1871 passed, 2 skipped**, one clean run |
| Mutation testing | ✅ **46 designed · 43 detected · 3 survived · 0 hung · 0 not applied** — all three equivalent, one the control |
| Coverage | ✅ **100%** branch on P11's eight new modules; 87% tree |
| Documentation | ✅ landed — freeze §11.1 ×3, 34 §P11, 06c §3.1/§4.3/§6, 35 §2.1/§6, DI register, README |
| Manual guide | ✅ written and **executed by Claude**; [testing/P11-testing.md](../testing/P11-testing.md) |
| **Manual sign-off** | ❌ **NOT SIGNED — this is the gate** |
| Rollback | ✅ executed three ways |
| Repository hygiene | ✅ reviewed against the staged diff |
| Committed / pushed | ✅ / ✅ |
| Tagged | ❌ **not tagged** — the sign-off table is blank, and a tag would claim a verification that did not happen |

---

## The resume point

**P11 is code-complete, tested, documented, committed and pushed. It is NOT signed off.**

**The next action is not P12.** It is the operator running
[docs/testing/P11-testing.md](../testing/P11-testing.md) — eleven steps, about 25 minutes, no
developer needed — and signing the table.

Then, and only then:

1. Tag: `git tag -a v0.1.0-p11 -m "P11 complete: pre-score, funnel, comments"` and push it.
2. Begin **P12 — Project & BKB schema** ([34 §P12](../34-implementation-plan.md)), after explicit
   approval, working through
   [PHASE-11-HANDOVER §9](../PHASE-11-HANDOVER.md)'s entry conditions first.

**Claude must not begin P12 without that approval** — [lock §3](../EXECUTION_MODE_LOCK.md) step 16.

---

## What changed, in one paragraph

The deterministic pipeline started running. `src/rules/` (P9) and `src/dedupe/` (P10) had no caller
for three phases; P11 is the first caller of both. Every collected item now gets a 0–100 pre-score
with six stored components, the run page shows the funnel with every rejection reason counted,
comments are fetched for the best-scoring posts first, and 2% of the early filter's rejects are
re-checked so the filter can be measured rather than trusted. **Zero AI calls, and no migration.**
Four Deferred Improvements were built — including 🔴 **DI25**, a live defect that had been silently
discarding real leads since P6 — and **the audit that measures it was built first, deliberately, so
the evidence survived the fix**.

---

## If you are picking this up cold

```powershell
cd <project root>
git log --oneline -3                 # P11's commit should be at the top
python -m pytest                     # expect 1871 passed, 2 skipped
python -m alembic heads              # expect one head: 0006_content_and_dedup
python scripts\check_schema.py       # expect 51/51
python -m src.scoring                # the phase, in one command
```

Read, in this order: [PHASE-11-HANDOVER.md](../PHASE-11-HANDOVER.md) §3 and §4 (what P12 inherits
and the traps in it), then [34 §P12](../34-implementation-plan.md), then
[P11-DECISION-ANALYSIS.md](../P11-DECISION-ANALYSIS.md) if you need to know *why* something is the
way it is rather than *what* it is.

**The two things most likely to bite P12**, both in §4 of the handover: a component scoring `0.0` is
not the same as one that does not exist yet, and adding a seventh weight **rescales every pre-score
already stored** — so the admission floor of 35 must be re-measured, not assumed.
