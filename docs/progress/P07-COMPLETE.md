# P07 — COMPLETE

**Phase:** P7 — Notification tier · **Date:** 2026-08-10 · **Revision:** none (head stays `0005_discovery`)

> This file answers one question: **if the session is lost, where does the next one resume?**
> Evidence lives in [PHASE-07-COMPLETION-REPORT.md](../PHASE-07-COMPLETION-REPORT.md); what the next
> phase must know lives in [PHASE-07-HANDOVER.md](../PHASE-07-HANDOVER.md).

---

## 1. Resume point

**P7 is complete, pushed and CI-green. The next action is P8 — Content & dedup schema (`0006`), and it
does not begin until it is approved.**

```
main @ (the Stage 7 commit) -- see §3
alembic heads: 0005_discovery   (one head; P7 added no revision)
full suite:    1131 passed, 2 skipped
```

**Do not begin P8 without explicit approval** ([lock §3](../EXECUTION_MODE_LOCK.md) step 16).

---

## 2. What P7 delivered

`src/notify/` — a four-module notification tier that reads `run_events`, decides with a deterministic
table, renders Markdown from SQL, and sends through one of four transports. **Five kinds. Zero tokens.
No migration, no table, no endpoint, no new dependency.**

Wired at two points only: `finalize_run` dispatches after committing, and `RunService.fail()` enqueues
`finalize_run` so a failed run has a delivery path at all.

---

## 3. Commits, in order

| Stage | Commit | Subject |
|---|---|---|
| plan | `19a8c8a` | implementation review, decisions, checklist, testing guide |
| 1 | `5218977` | **grep fence 3 (R4)** and the `src/notify` boundary fences |
| — | `a79a893` | DI15–DI19 registered with triggers |
| 2 | `a81526e` | five notification kinds and the deterministic policy table |
| 3 | `67b0c48` | markdown renderers built from SQL, never from a caller |
| 4 | `32b0d13` | transport interface with T1/T2/T3 and bot-token redaction |
| 5 | `e6ad44a` | Stage 5 execution flow and boundary rules, before the code |
| 5 | `20621c1` | `run_events`-backed dispatch, committed before the send |
| 6 | `2342924` | proof the wiring did not re-open P6's guarantees |
| 7 | `42ab9b6` | the notify config block, and the YAML `null` it exposed |
| 7 | *this commit* | dashboard §8, reconciliations, executed rollback, records |

---

## 4. The six operator decisions P7 was built on

Answered before implementation, analysed in
[P7-DECISION-ANALYSIS.md](../P7-DECISION-ANALYSIS.md):

| | Decision |
|---|---|
| **D1** | All three transports behind one interface, Bot API the intended default |
| **D2** | Five kinds, chosen on having a live emitter at `0005` |
| **D2b** | `proxy.pool_degraded` fires on a *recorded degradation*, not on `healthy < 3` |
| **D3** | Dispatch reads `run_events`; commit, then send, then record |
| **D7** | `RunService.fail()` enqueues `finalize_run` (Option A — `retry()` cancels it, and that is correct) |
| **D4** | `NullTransport` default; the live half deferred on blocker B1 |

---

## 5. What is NOT done, and who owns it

| Item | Owner |
|---|---|
| **Retry on failure** — [34 §P7](../34-implementation-plan.md) task 6's other half | ⚠️ **Nobody yet.** An open P7 obligation, not a closed one |
| Real Telegram delivery (T11) | Blocked on **B1** — no token in `.env` |
| M-5, M-9, M-10 | **Track B, before P23**. Reported **unsatisfied** |
| T1/T2 live verification | **P23** — `hermes` is not installed |
| Immediate `gate.reached`, the rich gate card | **P18** — see handover §4 |
| `lead.high_confidence`, `quality.red`, `budget.warning` | **P21 / P26 / P19-20** — DI16 |
| A periodic driver for `maintenance` | **P17** — DI17 |

---

## 6. If something looks wrong

| Symptom | Read this first |
|---|---|
| "P7 should have been the enrichment phase" | Completion report's banner. `17-phase-07.md` is the **superseded** numbering and maps to P19–P22 |
| "Why does `gate.reached` arrive late?" | Handover §4 — a recorded design cost, not a defect |
| "Why is `min_confidence_alert` missing?" | D2. It configures a column that arrives in `0006` and is populated in P21. A fence prevents adding it |
| "Why does `dispatch_pending` raise on my session?" | Handover **G1**. Commit first; the guard is trap T0 made executable |
| "The notification tier does nothing" | `notify.enabled` defaults to **false**. That is the shipped rollback state |
| "A `notify.failed` row appeared and nothing retried" | Correct. Retry is not implemented — §5 |
