# PHASE-07 HANDOVER — Notification tier → P8

**From:** P7 — Notification tier (complete 2026-08-10)
**To:** P8 — Content & dedup schema (revision `0006`)
**Companion:** [PHASE-07-COMPLETION-REPORT.md](PHASE-07-COMPLETION-REPORT.md) ·
[testing/P07-testing.md](testing/P07-testing.md)
**Architecture status:** FROZEN. P7 produced **two reconciliations, no amendments**
([freeze §11.1](ARCHITECTURE_FREEZE.md)).

> ⚠️ **Not to be confused with the legacy "Phase 07."** [`17-phase-07.md`](17-phase-07.md) and
> [`testing/phase-07-testing.md`](testing/phase-07-testing.md) belong to the **superseded eight-phase
> numbering** and map to **P19–P22**. P7 cost half a day of review to establish that; do not spend it
> again.

---

## 1. What now exists

```
src/notify/
├── __init__.py      the package's public surface -- import from here
├── service.py       Kind (5) · POLICY · quiet_hours · NotifySettings ·
│                    NotificationService.dispatch_pending · TRANSITION_KINDS · EVENT_KINDS
├── renderers.py     render(kind, session, run_id) -- one per kind, from SQL
└── transport.py     Transport protocol · NullTransport · BotApiTransport (T3) ·
                     ServeTransport (T1) · SubprocessTransport (T2) · SendError
src/orchestration/handlers/finalize.py  ~ commits, THEN dispatches
src/orchestration/run_service.py        ~ fail() enqueues finalize_run (D7)
src/obs/logging.py                      ~ TELEGRAM_BOT_TOKEN redaction
config.yaml                             ~ notify: {enabled, transport, telegram_chat_id, quiet_hours_utc}
```

**No migration, no table, no endpoint, no new dependency.** `alembic heads` is `0005_discovery`, so
**P8 authors `0006` against exactly the chain it expected.**

### 1.1 The interface P8 and later phases will use

```python
from src.notify import Kind, NotificationService, NotifySettings

# Read the timeline, decide, render, send, record. The caller MUST have committed.
NotificationService(session, settings=settings).dispatch_pending(run_id)
```

Nothing else needs calling. Emitters keep using `emit_event` and stay unaware the tier exists.

---

## 2. Seven guarantees P8 must not break

**G1 — `dispatch_pending` refuses a dirty session, and that is load-bearing.** It raises
`RuntimeError` if `session.dirty | new | deleted` is non-empty. A session with pending writes holds
SQLite's single write lock until commit, and a send takes seconds — trap **T0**, which P3 lost a
sign-off to. **Do not "helpfully" remove the guard** because a caller trips it; the caller is wrong.

**G2 — `handle_discover` still commits exactly once, before its fetch.** Asserted twice now: at
runtime and in the source. P7 deliberately dispatches from `finalize_run` instead of that handler, and
the tests are what make "deliberately" checkable. **G4/G5 from P6 depend on it.**

**G3 — a kind is not a timeline event name.** Only `discovery.overflow` matches by identity;
`run.transition` carries four of the five in its `to_state` payload. Use `TRANSITION_KINDS` and
`EVENT_KINDS`, never string equality against `Kind`.

**G4 — dedup is keyed on `(run_id, kind)`.** On `run_id` alone a run gets one message ever; on `kind`
alone later runs go silent. Both terms are mutation-tested.

**G5 — no table was added.** AD-29: dedup rides on `run_events` plus the transition guard, and
`notification_log` is **withdrawn**. If P8 finds itself wanting a notification table, that is a
[freeze §11](ARCHITECTURE_FREEZE.md) amendment and it needs a failed measurement.

**G6 — `run_events.data_json` carries a **hash** of the chat id, never the id.** That table renders
into an HTML page (**R15**).

**G7 — `src/notify/` imports no `src.ai` and nothing under `src/` imports Hermes.** Grep fence 3
exists now. `transport.py` is the only module in the package allowed an HTTP client.

---

## 3. What P7 deliberately did NOT do

| Not done | Owner |
|---|---|
| **Retry on failure** — a send is attempted once; a failure is *recorded* | ⚠️ **Nobody yet.** [34 §P7](34-implementation-plan.md) task 6's other half is **undelivered**. Needs a decision, and [DI17](DEFERRED-IMPROVEMENTS.md) notes there is no periodic driver to retry on |
| The rich **gate card** — counts, rejects, estimate, deep link | **P18** — needs `project_subreddits` (`0008`) |
| Immediate `gate.reached` delivery | **P18**, and it inherits the late-delivery limit (§4) |
| `lead.high_confidence`, `quality.red`, `budget.warning` | **P21 / P26 / P19-20** — [DI16](DEFERRED-IMPROVEMENTS.md) |
| A periodic driver for `maintenance` | **P17** — [DI17](DEFERRED-IMPROVEMENTS.md); nothing enqueues it today |
| Inbound Telegram commands | **P18 / P23** |
| Measuring M-5, M-9, M-10 | **Track B, before P23** |

---

## 4. ⚠️ The one limitation P18 inherits

**Three of the five kinds are delivered when the run finalises, not when they occur.**

`gate.reached`, `proxy.pool_degraded` and `discovery.overflow` are emitted from a web route or from
mid-handler, where sending would put a network call inside a Flask request (**R8**) or hold the write
lock across it (**T0**). So the drain in `finalize_run` picks them up later.

AC1's *"within 10 s"* is scoped to *"a **completed** run"*, so it holds — `run.complete` and
`run.failed` are immediate. But **P18's gate card is meant to arrive while the operator is waiting at
the gate**, and under P7 it arrives after the run finalises. P18 needs either its own dispatch point or
the periodic driver [DI17](DEFERRED-IMPROVEMENTS.md) describes. **This is not a defect to discover; it
is a design cost recorded in advance** ([P7-STAGE5-FLOW §3](P7-STAGE5-FLOW.md), assumption A9).

---

## 5. Traps waiting in P8

**T0 — the write lock, still.** P8 is a schema phase, so its exposure is lower than P7's — but
`0006` adds four tables and four columns to `leads`, and a migration that holds a lock while doing
something slow is the same defect in a different place. P7's proof technique is reusable: inspect the
session from inside the slow call.

**T1 — `leads` gains `confidence_score` in `0006`, and that unblocks a deferred kind.**
[DI16](DEFERRED-IMPROVEMENTS.md)'s `lead.high_confidence` trigger is *"the column exists **and** is
populated (P21)"* — **the column alone is not the trigger.** Do not ship the kind in P8; P21 populates
the column, and a kind that reads a column of `NULL` would notify about nothing.

**T2 — `min_confidence_alert` is fenced.** `tests/test_boundaries.py::test_min_confidence_alert_was_not_shipped`
will fail if P8 adds it to `config.yaml`. Delete the fence deliberately when P21 ships the kind — do
not discover it failing.

**T3 — a mutation you have not run is a test you do not have.** P7 ran **78**. **Six survived a first
pass**, and every one was real: two were masked by a *second guard*, one exposed dead code, one was a
genuine missing scope filter, one had a fixture with no evidence to find, and one was a badly-built
mutation of mine. **Not one was noise.**

**T4 — an expected number written from an estimate is not an expected result.** P7's guide had **six**
wrong instructions until executed, including one that asked a tester to read a count pytest does not
print.

**T5 — `git checkout -- <file>` restores to HEAD.** If a rollback drill runs before the change is
committed, the restore *deletes the work*. It happened in P7.

**T6 — `session.get` is served from the identity map.** If a caller already holds the row, no SQL is
issued and you read *their* in-memory object. Use an explicit `select` when the point is to read the
database.

---

## 6. Findings worth carrying forward

| # | Finding | Lesson |
|---|---|---|
| **F1** | Grep fence 3 (R4) was claimed as a universal criterion for six phases and **did not exist** — third occurrence of the species | **A criterion nobody has watched fail is not enforced.** Prove every new fence red before green |
| **F2** | Two mutations survived because a **second guard masked the first** | Defence in depth makes a guard **untestable**. Give each guard an observable consequence — the `enabled` check earns its place by making a disabled tier cost *no SQL* |
| **F3** | An unreachable `None` guard and an unreachable `""` arm were **deleted, not tested** | P6's F1 again. 100% coverage means nothing if the branches are unreachable |
| **F4** | AC1 had **no test at all**, found while filling in the manual guide | **The guide is a verification pass, not paperwork.** Writing it found a missing acceptance criterion |
| **F5** | `transport: null` in YAML is `None` — **second time** this bit `config.yaml` | A footgun documented once, in a comment, elsewhere in the same file, is not fixed |
| **F6** | Two of my own tests asserted behaviour that does not happen; executing them found out | **A test is a hypothesis until it runs.** A run created via `create()` walks both gates |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **1131 passed, 2 skipped** (P6: 887 / 2) |
| Under `-W error::DeprecationWarning` | **1131 passed, 2 skipped** |
| New P7 tests | **+244** |
| `ruff check` / `format --check` | All checks passed / 127 files |
| Coverage | `src/notify/` **100%** (449 statements) |
| `alembic heads` | `0005_discovery` — one head, **unchanged** |
| `check_schema.py` | **OK — all 31 checks passed** |
| Legacy contract | 459 baseline leads · `intent_score` fingerprint · 17 endpoints · 13 CSV columns |
| Mutation testing | **78 designed, 78 detected** |
| Grep fences | **4 of 4** — fence 3 for the first time |
| Rollback | **Executed**, three phases, restore verified |

---

## 8. Blockers carried into P8

| ID | Blocker | Blocks P8? |
|---|---|---|
| **D1** | P00–P07 manual sign-off tables unsigned | **By the project's own rule, yes** ([lock §4](EXECUTION_MODE_LOCK.md)). **No tag created** |
| **B3/O2** | `mypy` not installed | **No** — but the gate cannot be claimed in full |
| **B1** | `.env` has no `TELEGRAM_BOT_TOKEN` | **No.** P7's live half is deferred; P8 is a schema phase and needs no token |
| **L4** | **Retry is undelivered** — task 6's other half | **No**, but it is an open P7 obligation, not a closed one |
| **DI17** | Nothing enqueues `maintenance` | **No** — P17's |
| **DI18** | `test_parse_speed_stays_inside_the_budget` is load-sensitive | **No.** Did not fire in P7's CI, including a 4-minute run |
| **DI20** *(proposed)* | `test_does_not_write_to_the_database_it_checks` — WAL/mtime race | **No.** Failed once in P7's CI, passed on re-run with identical code |
| **C8 / DI15** | `discover` is an unreconciled eighth job type | **No** — P7 added none |

---

## 9. Entry conditions for P8

- [ ] `docs/testing/P07-testing.md` sign-off table signed (and P00–P06, still outstanding)
- [ ] **[§4 of this document read]** — the late-delivery limitation P18 inherits
- [ ] [34 §P8](34-implementation-plan.md) read — all thirteen fields
- [ ] **§5 T1 and T2 read** — `confidence_score` arriving in `0006` does **not** unblock the deferred kind
- [ ] [freeze §4.1](ARCHITECTURE_FREEZE.md) read — `0006` is `content_and_dedup`, and **M5 forbids rewriting a row**
- [ ] [05 §7.1a](05-database-plan.md) read — the table creation order
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] **The full suite recorded green before the first change** — 1131 passed, 2 skipped
- [ ] `git status` clean · `alembic heads` = one `0005` · `check_schema.py` 31/31
- [ ] `gh run list` checked: P7 green on `origin/main`
- [ ] A timestamped backup of `data/leads.db` before the first `alembic upgrade` (**M7**)
