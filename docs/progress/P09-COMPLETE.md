# P09 — COMPLETE

**Phase:** P9 — Rule engine · **Date:** 2026-08-14 · **Revision:** none — P9 adds no migration

> This file answers one question: **if the session is lost, where does the next one resume?**
> Evidence lives in [PHASE-09-COMPLETION-REPORT.md](../PHASE-09-COMPLETION-REPORT.md); what the next
> phase must know lives in [PHASE-09-HANDOVER.md](../PHASE-09-HANDOVER.md).

---

## 1. Resume point

**P9 is implemented, pushed and CI-green. The next action is P10, and it does not begin until it is
approved.**

```
main @ dbd7dab   (docs(P9): four reconciliations, and the DI20 gap closed)
alembic heads:   0006_content_and_dedup   (one head — P9 added no revision)
live database:   0006_content_and_dedup   (untouched by P9)
full suite:      1380 passed, 2 skipped
```

⚠️ **P9's manual guide is not yet signed.** [testing/P09-testing.md](../testing/P09-testing.md) has
Part B executed through Stage 6, but the operator sign-off table is blank. **No tag until it is
signed** ([lock §6.2](../EXECUTION_MODE_LOCK.md)).

**Do not begin P10 without explicit approval** ([lock §3](../EXECUTION_MODE_LOCK.md) step 16).

---

## 2. What P9 delivered

Six modules under `src/rules/` — `__init__`, `keywords`, `structural`, `authors`, `competitors`,
`__main__`. **Imported by nothing.** P10 and P11 are the first callers.

**No migration, no table, no column, no route, no template, no handler change.** The one production
file changed outside `src/rules/` was `config.yaml`, which gained two blocks.

The phase's real product is arguably the pair of guards: **fence 2 over `src/rules/`**, which had
been specified since P0 over six paths of which only one existed — and the **property test that found
a 67.8-second denial-of-service** in P9's own code on its first run.

---

## 3. Commits, in order

| Stage | Commit | Subject |
|---|---|---|
| plan | `2832d38` | implementation review, decisions, checklist and testing guide |
| — | `f9e1ffc` | **P8's** manual testing sign-off — closed the entry-condition blocker |
| 1 | `dc0f155` | the R3 fence, before the package it constrains |
| — | `4a7b96a` | stabilize the DI18 timing test *(pulled forward from Stage 6)* |
| — | `8707f19` | measure parse cost as a ratio, not in milliseconds |
| 2 | `85cb286` | the four predicates, and the neutral type that keeps R3 intact |
| 3 | `64ad729` | competitor matching, and the registry that does not exist yet |
| 4 | `e30aafb` | the rules config block, and a rollback that runs |
| — | `e24fb90` | **fix:** catastrophic backtracking in the AMA pattern |
| 5 | `6beac44` | property tests, two performance assertions, and the demo's coverage |
| 6 | `8b83235` | the heartbeat flake, measured and registered rather than guessed at |
| 7 | `dbd7dab` | four reconciliations, and the DI20 gap closed |
| post | *this commit* | completion report, handover, progress record, README |

---

## 4. The six operator decisions P9 was built on

| | Decision |
|---|---|
| **D1** | `src/rules/` owns a neutral `RuleResult`; no `src.ai` import; the fence lands in Stage 1 |
| **D2** | Four predicates, three production-wired; counting is P19's |
| **D3** | `RejectionReason`'s spelling, granularity in `detail`; convergence deferred to DI23 |
| **D4** | `src/rules/` reads `pipeline.rules_enabled` itself; a demo module for manual verification |
| **D5** | `EntityRegistry` protocol + dictionary fallback + an inertness guard until P15 |
| **D6** | Fix the timing tests; register what cannot be fixed; weaken nothing |

Plus three mid-phase approvals: DI18 pulled forward, its metric redesigned, and the AMA fix taken as
a cross-stage correctness fix.

---

## 5. What is NOT done, and who owns it

| Item | Owner |
|---|---|
| **P9's manual sign-off table** | ⚠️ **The operator.** No tag until signed |
| P00–P07 sign-off tables | ⚠️ **The operator.** P8's was signed 2026-08-14, the first in the project |
| `src/rules/` has no caller | **P10**, then **P11** |
| Fence 2 over `src/dedupe/` | **P10**; `src/scoring/` P11, `src/knowledge/` P15, `src/feedback/` P19 |
| The competitor rule is inert | **P15** — and it must delete a test to enable it |
| DI14, DI22 | **P10** |
| DI23, DI24, DI25, DI13 | **P11** |
| DI26 | **P11 or P15** |
| DI20, DI27 | Awaiting a further occurrence |
| `mypy` / O2 — 193 errors | Its own scoped task |
| Notification retry (L4) | **Still nobody** — open since P7 |

**No DI was closed in P9.**

---

## 6. If something looks wrong

| Symptom | Read this first |
|---|---|
| "P9 should have been scraping, comments and dedup" | `16-phase-06.md` is the **superseded** numbering and maps to P9–P11 and P15 |
| "`alembic heads` should have moved" | It should not. **P9 adds no revision**; the chain stays at `0006` until P12's `0007` |
| "Nothing uses `src/rules/`" | Correct, and deliberate. P10 is the first caller — handover §3 |
| "The competitor rule never matches anything" | Correct. Inert until P15, and a test fails if anyone wires it early — handover §6 |
| "`triage.py` rejects a post `python -m src.rules` admits" | Real, and known: **DI25**. P9's pattern is right; the live discovery path is not |
| "The suite has two skips" | The performance tests, under the coverage tracer, by design — instrumentation biases the ratio |
| "A mutation says *anchor not found*" | That is **not** a pass. Handover §4 T4 |
| "The heartbeat test failed" | **That is a second occurrence — capture the output.** It is DI27's documented trigger |
| "`config.yaml` shows as modified" | Check for a real chat id before staging. It happened at the start of both P8 and P9 |
