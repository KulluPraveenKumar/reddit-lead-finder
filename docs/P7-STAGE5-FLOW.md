# P7 Stage 5 — execution flow, before implementation

**Written:** 2026-08-10 · Documentation only. **No production code exists for this stage yet.**

Purpose: fix the boundaries on paper so the implementation can be checked against them, rather than
the diagram being drawn afterwards to match whatever was built.

---

## 1. The flow

```
┌── WORKER (src/orchestration/worker.py) ─ UNCHANGED by P7 ─────────────────────┐
│  execute(job)                                                                 │
│    └─ _handler_session():  Session(...)                                       │
│         ├─ yield  ──────────────► handler runs here                           │
│         └─ session.commit()      ◄── commits AFTER the handler returns        │
└───────────────────────────────────────────────────────────────────────────────┘
                                      │
         ╔════════════════════════════▼══════════════════════════════════════╗
         ║  handle_finalize_run(session, job)     src/orchestration/handlers ║
         ╚════════════════════════════╤══════════════════════════════════════╝
                                      │
   ① RUN TRANSITION                   │
      service.transition(SCRAPING → ANALYZING → COMPLETE)
      emit_event(...)  ─── adds rows to the session, does NOT commit
                                      │
      ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▼━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
      ┃  ▓▓▓ TRANSACTION BOUNDARY ▓▓▓   session.commit()                   ┃
      ┃  The handler commits its own bookkeeping HERE, before any I/O.      ┃
      ┃  handlers/__init__.py: "a handler about to block on I/O commits its ┃
      ┃  bookkeeping *before* the blocking call."                           ┃
      ┃  After this line: session.dirty / .new / .deleted are all EMPTY,    ┃
      ┃  so SQLite's single write lock is NOT held.          ← trap T0      ┃
      ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
   ② NotificationService.dispatch_pending(run_id, now=…)      src/notify/service
                                      │
      ┌───────────────────────────────▼────────────────────────────────────┐
      │ ░░░ DATABASE READ BOUNDARY ░░░   SELECT only                       │
      │   • run_events  WHERE run_id = ?          → candidate events       │
      │   • run_events  WHERE event = 'notify.sent'  → what already went   │
      │   (the LEFT-JOIN-shaped dedup; AD-29: dedup rides on run_events)   │
      └───────────────────────────────┬────────────────────────────────────┘
                                      │
   ③ POLICY   decide(kind, payload, settings=…, now=…)     PURE — no I/O
      │  • enabled?           → suppress absolutely (the rollback)
      │  • POLICY[kind]       → notify / suppress + one-line reason
      │  • quiet hours        → may only turn a yes into a no
      │  • unknown event      → suppress  (docs/22 §4.12's last row)
      └─► suppressed ⇒ STOP. Nothing recorded, so a later pass can retry it.
                                      │ notify
   ④ RENDERER  render(kind, session, run_id)               src/notify/renderers
      ┌───────────────────────────────▼────────────────────────────────────┐
      │ ░░░ DATABASE READ BOUNDARY ░░░   SELECT only, asserted by a        │
      │   statement counter. scrape_runs · jobs · runs · run_events        │
      └───────────────────────────────┬────────────────────────────────────┘
                                      │  markdown: str
   ⑤ TRANSPORT  transport.send(chat_id=…, markdown=…)      src/notify/transport
      ┌───────────────────────────────▼────────────────────────────────────┐
      │ ══ NETWORK / SUBPROCESS ══   the blocking call.                    │
      │   NO transaction is open here. NO write lock is held.             │
      │   Returns a provider message id, or raises SendError(retryable).   │
      └───────────────────────────────┬────────────────────────────────────┘
                                      │
   ⑥ RECORD THE OUTCOME
      ┌───────────────────────────────▼────────────────────────────────────┐
      │ ▓▓▓ DATABASE WRITE BOUNDARY ▓▓▓                                    │
      │   emit_event(session, run_id, 'notify.sent'  | 'notify.failed')    │
      │   session.commit()          ← a SECOND, separate transaction       │
      │   No table is added (AD-29). notification_log is withdrawn.        │
      └────────────────────────────────────────────────────────────────────┘
```

### The failure path

```
   ⑤ transport.send  ── raises SendError ──►  ⑥ emit_event('notify.failed', level='error')
                                                 + commit
                        the run is UNAFFECTED: handle_finalize_run has already
                        committed the terminal transition at the boundary above,
                        so a dead transport cannot fail a completed run.
```

---

## 2. The four boundaries, stated as rules

| Boundary | Where | The rule |
|---|---|---|
| **Transaction** | between ① and ② | The handler commits **before** dispatch. `dispatch_pending` is called with a **clean session** — a documented precondition, asserted by a test that inspects the session *from inside the transport*, and targeted by mutation **M1**. |
| **Read** | ② and ④ | `SELECT` only. Rendering already proves this with a statement counter (Stage 3); dispatch's own reads get the same treatment. |
| **Write** | ⑥ only | Exactly one write per dispatched notification, in its **own** transaction, after the send returns. Nothing is written before the send — that is what keeps the write lock out of the network call. |
| **Enqueue** | `RunService.fail()` (D7) | `fail()` adds one `enqueue(FINALIZE_JOB)` row **inside its existing transaction**, so the enqueue is atomic with the `FAILED` transition. It performs **no I/O** — delivery is handed to the worker, never done in a web request (**R8**). |

---

## 3. What this shape buys, and what it costs

**Buys.** Emitters stay unaware that notifications exist — they keep calling `emit_event`. So
`worker.py` is untouched, no job type is added (`04 §2.4`'s list stays closed), and nothing is ever
sent from inside a Flask request. Dedup is inherent rather than bolted on: a `notify.sent` row per
`(run_id, kind)` *is* the key AD-29 says `run_events` should carry.

**Costs, stated rather than discovered later.**

- **At-least-once, not exactly-once.** There is an irreducible window between ⑤ succeeding and ⑥
  committing. A crash inside it re-sends on the next dispatch. Assumption **A3**; this stage does not
  claim exactly-once.
- **Late for three of five kinds.** `gate.reached`, `proxy.pool_degraded` and `discovery.overflow` are
  emitted from a web route or mid-handler and are delivered when the run finalises. `run.complete` and
  `run.failed` are immediate. AC1's *"within 10 s"* is scoped to *"a **completed** run"*, so it is met.
  Assumption **A9** — and P18 will want an *immediate* gate card, so it inherits this.

---

## 4. Scope of Stage 5, as narrowed by the operator

The approved checklist put **bounded retry** in this stage (D5: one attempt plus two, at 1 s and 2 s).
The operator's instruction for Stage 5 is *"Do not begin retries."*

**So Stage 5 ships a single attempt.** A failure is **recorded** (`notify.failed`, `level='error'`) and
never silent — the half of `34 §P7` task 6 that says *"failures recorded, never silent"* holds.

⚠️ **The other half of task 6 — *"Retry on failure"* — is therefore NOT delivered by Stage 5**, and is
recorded here so it cannot be quietly dropped from P7's completion claim ([lock §4.1](EXECUTION_MODE_LOCK.md):
*"finish every other part in full and state precisely what was left and why"*). It needs either a later
stage or an explicit deferral. Note that **DI17** already records that no periodic driver exists to
retry on, so a retry budget inside one dispatch call is the only form available without a scheduler.

**Also out of scope for Stage 5**, per the same instruction: scheduling, future notification kinds
(`lead.high_confidence`, `quality.red`, `budget.warning` — DI16), and any refactoring.
