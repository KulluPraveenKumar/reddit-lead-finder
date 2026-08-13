# P08 — COMPLETE

**Phase:** P8 — Content & dedup schema · **Date:** 2026-08-13 · **Revision:** `0006_content_and_dedup`

> This file answers one question: **if the session is lost, where does the next one resume?**
> Evidence lives in [PHASE-08-COMPLETION-REPORT.md](../PHASE-08-COMPLETION-REPORT.md); what the next
> phase must know lives in [PHASE-08-HANDOVER.md](../PHASE-08-HANDOVER.md).

---

## 1. Resume point

**P8 is complete, pushed and CI-green. The next action is P9, and it does not begin until it is
approved.**

```
main @ (the post-implementation commit) -- see §3
alembic heads: 0006_content_and_dedup   (one head)
live database: 0006_content_and_dedup   (upgraded 2026-08-13)
full suite:    1148 passed, 2 skipped
```

**Do not begin P9 without explicit approval** ([lock §3](../EXECUTION_MODE_LOCK.md) step 16).

---

## 2. What P8 delivered

Four empty tables — `comments`, `dedup_groups`, `dedup_members`, `minhash_bands` — four new `leads`
columns with four indexes, and the closure of `prescores.comment_id`. **No page, no endpoint, no
behaviour, no dependency, no job type, and zero rows written.**

The phase's real product is arguably the **guard**: `test_no_revision_leaves_a_dangling_foreign_key`
catches a defect class that every other gate in this project reports green on.

---

## 3. Commits, in order

| Stage | Commit | Subject |
|---|---|---|
| plan | `2e0b41f` | implementation review, decisions, checklist, testing guide |
| — | `762ec2e` | the operator's decisions, and what measuring D6 found |
| 1 | `af2e064` | the insert guard that the FK round-trip cannot see |
| 2 | `5e55070` | `0006` content and dedup, with four foreign keys left open |
| 3 | `723249e` | the five models, and the four columns `leads` did not have |
| 4 | `e0ced7c` | prove the migration is metadata-only and the CHECK survived |
| 5 | `74f9380` | the migration table that predated the reorder |
| post | *this commit* | completion report, handover, progress record, guide Part B |

---

## 4. The eight operator decisions P8 was built on

| | Decision |
|---|---|
| **D1** | Bare `project_id` at `0006`; the four FKs close in `0007` |
| **D2** | [freeze §4.1](../ARCHITECTURE_FREEZE.md) is authoritative; repair `05 §7` as a §11.1 reconciliation |
| **D3** | Adopt `leads.source` from the superseded [16 §115](../16-phase-06.md) into the frozen schema |
| **D4** | Dedup `project_id` columns nullable and bare; the `NOT NULL` question is **P12's** |
| **D5** | A guard over **every** revision, not just `0006` (option B) |
| **D6** | `mypy` **deferred** — the <30 min condition was tested and failed at **193 errors** |
| **D7** | Unspecified details recorded rather than silently defaulted |
| **D8** | The flaky-test decision — **deferred by the operator; still open** |

---

## 5. What is NOT done, and who owns it

| Item | Owner |
|---|---|
| **The manual sign-off table** — T9's four visual checks | ⚠️ **The operator.** No tag until signed |
| Four `project_id` FKs still open | **P12** (`0007`) |
| Whether the dedup `project_id`s become `NOT NULL` | **P12** — an explicit decision, not a default |
| The `dedup_members` "one group per run" invariant | **P10** — DI22; not expressible in the schema |
| `mypy` / O2 — 193 errors | **Its own scoped task**, between phases |
| The three flaky tests | **D8**, open |
| Notification retry | **Still nobody** — an open P7 obligation |

---

## 6. If something looks wrong

| Symptom | Read this first |
|---|---|
| "P8 should have been quality measurement and exports" | Completion report's banner. `18-phase-08.md` is the **superseded** numbering and maps to P25–P27 / P30 |
| "`docs/05 §7` says `content_and_dedup` is `0007`" | It **did**, and it was wrong. [freeze §4.1](../ARCHITECTURE_FREEZE.md) wins; corrected 2026-08-13 and recorded in §11.1 |
| "Why is `leads.project_id` not a foreign key?" | Deliberate, and load-bearing. Handover §3; a `REFERENCES` clause there breaks every lead insert **silently** |
| "`check_schema.py` says 51, the docs say 52" | Both are right. Plain run = 51; with `--revision 0006` the revision comparison becomes a check = 52 |
| "`check_schema.py` fails on a database at `0005`" | Pass `--skip-p8`. Same idiom as `--skip-p6` |
| "The suite went red on a timing test" | Handover §8. Three known flaky tests, five occurrences in P8. **Re-run that test alone** — but a re-run is not a pass |
| "A dedup group and another claim the same lead" | Correct, and not enforceable in SQL. **DI22**, P10's |
