# PHASE-06 HANDOVER — Watermarks & incremental discovery → P7

**From:** P6 — Watermarks & incremental discovery (complete 2026-08-08)
**To:** P7 — Notification tier
**Companion:** [PHASE-06-COMPLETION-REPORT.md](PHASE-06-COMPLETION-REPORT.md) ·
[testing/P06-testing.md](testing/P06-testing.md)
**Architecture status:** FROZEN. P6 produced **three reconciliations, no amendments**
([freeze §11.1](ARCHITECTURE_FREEZE.md)).

> ⚠️ **Not to be confused with the legacy "Phase 06."** [`16-phase-06.md`](16-phase-06.md) and
> [`testing/phase-06-testing.md`](testing/phase-06-testing.md) belong to the **superseded
> eight-phase numbering**. The two schemes are unrelated.

---

## 1. What now exists

```
migrations/versions/0005_discovery.py  +  discovery_watermarks, prescores
src/discovery/
├── feed_parser.py      (P5)
├── watermarks.py       +  diff · advance · overflow — pure, no session
├── policy.py           +  next_interval — deterministic, ZERO AI (R3)
└── triage.py           +  stage 3, closed reason vocabulary
src/db/repositories/discovery.py       +  watermarks · due-queue · known_ids
src/orchestration/handlers/discover.py +  the poll handler, stages 1–4
src/reddit_client.py   ~ + TransportError, _fetch, fetch_feed  (N2 closed)
scripts/check_schema.py ~ + 6 discovery checks, --skip-p6
config.yaml            ~ + polling keys
```

### 1.1 The interfaces P7 will use

```python
from src.orchestration.handlers.discover import DISCOVER_JOB     # "discover"
from src.db.repositories.discovery import DiscoveryRepository

repo.due(now)                     # channels whose next poll has come round
repo.state_of(sub, "listing")     # the watermark as a detached value object
```

The handler returns a dict P7's notifications can render **without a second query**:
`{channel, seen, new, admitted, rejected, rejected_by_reason, overflow, overflowed_subreddits,
html_recovered, next_interval_seconds, body_source_counts}`. The same fields are on the
`discovery.poll.done` event, and `overflowed_subreddits` is what an overflow alert should name.

---

## 2. Eight guarantees P7 must not break

**G1 — `src/discovery/` imports no `src.ai`.** Now an acceptance criterion, not just a convention
(R3, A5). `tests/test_boundaries.py` enforces it by AST, and a second test asserts `policy.py`
**exists** — because a fence that walks "whatever files are there" passes vacuously if the file it
was written for is deleted.

**G2 — the six frozen `RedditClient` methods still return `None` on failure.** P6 made the transport
*able* to raise, and then insulated every existing caller. `_get` catches `TransportError`. **Do not
"simplify" that catch away**: it is what keeps AD-2's return shape and R20 intact.

**G3 — a malformed feed raises; an empty feed returns `[]`; a *blocked* feed now raises too.** Three
states, three representations. Collapsing any pair re-opens D2 (watermark poisoning).

**G4 — the write lock is never held across I/O.** `handle_discover` commits its start event
*before* fetching. This is asserted by a test that inspects the session from inside the fetch, and by
mutation M10. **P7 emits notifications from handlers — this is exactly where it would be re-broken.**

**G5 — overflow is an error, it is detected *per subreddit*, and the recovery walk really runs.**
R19. Twelve tests, most of which assert it stays *quiet*. One combined multireddit request still
yields **one watermark row per subreddit** — keying it on `subreddits[0]` leaves the rest unable to
detect overflow at all, which is a per-subreddit fact.

**G6 — the watermark diffs on the id set, never on id comparison.** `t3_` fullnames look ordered and
are not.

**G7 — two partial unique indexes, not one.** SQLite treats NULLs as distinct in a UNIQUE index, so
the three-column index doc 28 specifies would not constrain listing rows at all.

**G8 — no `density_threshold`.** Deleted, fenced, and explained in `config.yaml`.

---

## 3. What P6 deliberately did NOT do

| Not done | Owner |
|---|---|
| **Per-item stage-3 `prescores` rows; the 2% holdout audit** | **P11** — see §4 |
| `score` / `num_comments` back-fill | **P11** task 4 |
| Comment expansion (stage 6) | **P11** task 3 — needs `comments` (`0006`) |
| The density-adaptive body fetch | **Nobody** — deleted, freeze §11.1 |
| Selftext for link/media posts | **Nobody** — exists on no endpoint |
| A scheduler process that *drives* the due-queue | P7/P17 — `repo.due()` exists, nothing calls it on a timer yet |
| `_extract_search_post` host normalisation (DI14) | Deferred |

---

## 4. ⚠️ The one narrowing P11 must pick up

[34 §P6](34-implementation-plan.md) task 4 asked triage to write "a provisional prescore with
`stage='metadata'`". **P6 does not, and cannot.**

`prescores` carries `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))`, so every row must
point at a stored `Lead`. A triage rejection is a post that was **never stored** —
`subreddit_scraper.py:60` persists a lead only when it clears `is_lead(min_score=3)`. Writing
prescores only for *admissions* would give a funnel that looks auditable and silently omits every
rejection, which is AD-10b's exact prohibition.

**So P6 counts instead:** `rejected_by_reason` on every `discovery.poll.done` event, from a closed
vocabulary (`REASONS` in `triage.py`).

**P11 owns the fix**, and already has the pieces — full prescoring, `gate.metadata_holdout_rate`, and
`gate_audits` in `0009`. It will need to decide *how* a stage-3 rejection becomes addressable: store
rejected posts as leads, or relax the CHECK and carry a `reddit_id`. **The second needs a freeze §11
amendment.** `tests/test_discovery_handler.py::test_p6_writes_no_prescore_rows` is the test that
should fail and be replaced when P11 does this.

**Found by mutation testing, not by reading.** Two mutations survived because the branch they
targeted was unreachable; coverage still reported 87% on the file. That is the lesson worth carrying:
a surviving mutation was the only signal.

---

## 5. Traps waiting in P7

**T0 — the write lock, again, and P7 is where it returns.** P6 closed it in the discovery handler;
P7 adds notification emission to *every* handler. A notification sent while the session is dirty
holds SQLite's single write lock across a network call to Telegram. **Send outside the transaction,
or queue the send and commit first.** P3 lost a sign-off to this; P4, P5 and P6 each had to prove
they had not re-opened it.

**T1 — R17: notifications never invoke a model.** `src/notify/` must import neither `src.ai` nor an
agent runtime. Establish the fence in the first commit, as P5 did for `src/discovery/` — retrofitting
is far more expensive.

**T2 — a mutation you have not run is a test you do not have.** P6's proof: two survivors exposed a
design defect nothing else had caught. **And three more mutations (M12–M14) were only added in
review**, each covering a line no existing mutation touched — a green mutation run proves the
mutations you wrote, not the ones you did not.

**T2a — a returned flag is not a performed action.** P6 shipped `html_fallback: True` from a branch
that fetched nothing, and its test asserted the flag. Assert the *effect*: that the walk happened,
that its posts arrived.

**T3 — a filter that matches nothing exits successfully.** Reproduced *again* during P6's guide
verification: two `-k` expressions run unquoted selected zero tests and reported success. Assert the
count.

**T4 — an expected number written from an estimate is not an expected result.** Four of P6's manual
counts were wrong until executed.

**T5 — `reset_policy()` in any test touching egress.** Unchanged since P4.

**T6 — the feed is one request per ~60 s per IP.** Unchanged. Multireddit combining is mandatory.

---

## 6. Findings worth carrying forward

| # | Finding | Lesson |
|---|---|---|
| **F1** | A prescore branch guarded on a value discovery never supplies looked correct, passed its tests, and reported 87% coverage | **Coverage counts executed lines; it cannot see a branch nothing reaches.** Mutation testing can |
| **F2** | A UNIQUE index specified in a frozen document would not have been unique | **Check the database's semantics, not the DDL's intent.** SQLite NULLs are distinct |
| **F3** | The first cold-start test compared a set with itself | **P5's F3, third occurrence.** A guard that cannot fail is documentation |
| **F4** | `default_rate` had no documented value; the obvious choice erased a distinction the code makes | An unspecified constant is a decision, and it belongs in the docstring |
| **F5** | Three specification statements were unimplementable, and two were found only by writing the code | **A specification is a hypothesis until something executes it** |

---

## 7. Verification snapshot at handover

| | |
|---|---|
| Full suite | **887 passed, 2 skipped** (P5: 803 / 2) |
| Under `-W error::DeprecationWarning` | **887 passed, 2 skipped** |
| New P6 tests | **+84** |
| `ruff check` / `format --check` | All checks passed! / 118 files already formatted |
| Coverage | `discovery/` **96%** · repository **98%** · handler **87%** |
| `alembic heads` | `0005_discovery (head)` — one head |
| `check_schema.py` | **OK — all 31 checks passed** |
| Legacy contract | 459 baseline leads · `GET /` · 13 CSV columns · 17 endpoints |
| Mutation testing | **16 designed, 16 detected** (2 after the defect they exposed was fixed) |
| Grep fences | 4 of 4 |
| Live parity | r/startups **0 mismatches**, exit 0 |

---

## 8. Blockers carried into P7

| ID | Blocker | Blocks P7? |
|---|---|---|
| **D1** | P00–P06 manual sign-off tables unsigned | **By the project's own rule, yes** ([lock §4](EXECUTION_MODE_LOCK.md)). No tag created |
| **B3/O2** | `mypy` not installed | **No** — the gate cannot be claimed in full |
| **B1** | `.env` has no `TELEGRAM_BOT_TOKEN` | ⚠️ **Yes, for the live half.** P7 is the notification tier and its transport needs this |
| **A4** | Cold-start ≥95% not live-verified | **No** — recorded as not verified |
| **N1** | Keyword and user leads not collected by the button or scheduler | **No** — P17's scope |
| ~~**N2**~~ | ~~`pause_run` and `fail_run` indistinguishable~~ | ✅ **CLOSED in P6** |
| **C1** | R20's migration half unverified in CI | ✅ **Closed** — `0005` is exercised up/down/up |

---

## 9. Entry conditions for P7

- [ ] `docs/testing/P06-testing.md` sign-off table signed (and P00–P05, still outstanding)
- [ ] **[§4 of this document read]** — the prescores narrowing P11 inherits
- [ ] [34 §P7](34-implementation-plan.md) read — all thirteen fields
- [ ] [freeze R17 and AD-28](ARCHITECTURE_FREEZE.md) read — **notifications never invoke a model**
- [ ] [freeze §7](ARCHITECTURE_FREEZE.md) read — **five** notification kinds, not nine
- [ ] `TELEGRAM_BOT_TOKEN` present in `.env`, or the live half of P7 explicitly deferred
- [ ] **T0 re-read (§5)** — P7 emits from every handler, and that is where the lock returns
- [ ] `phase-manager` skill loaded before the first edit under `src/`
- [ ] **The full suite recorded green before the first change** — 887 passed, 2 skipped
- [ ] `git status` clean · `alembic heads` = one `0005` · `check_schema.py` 31/31
- [ ] `gh run list` checked: P6 green on `origin/main`
