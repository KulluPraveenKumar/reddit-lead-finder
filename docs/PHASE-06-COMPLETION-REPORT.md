# PHASE-06 COMPLETION REPORT — Watermarks & incremental discovery

**Phase:** P6 · [34 §P6](34-implementation-plan.md)
**Completed:** 2026-08-08
**Companions:** [P6-IMPLEMENTATION-REVIEW.md](P6-IMPLEMENTATION-REVIEW.md) ·
[PHASE-06-HANDOVER.md](PHASE-06-HANDOVER.md) · [testing/P06-testing.md](testing/P06-testing.md)

---

## 1. Phase summary

Collection now has a memory. A poll asks Reddit one question — *what is new?* — diffs the answer
against a per-channel watermark, and when nothing has changed it issues **one request and writes no
data**. The polling interval is computed deterministically from the observed post rate, with **zero
AI calls**. And the failure that any watermark design invites — posts appearing faster than the
window can carry, then scrolling out of reach unseen — is detected and raised as an **error**, never
a silent gap (R19).

Three things in the specification turned out to be unimplementable as written. **None was worked
around silently**; each is recorded as a [freeze §11.1](ARCHITECTURE_FREEZE.md) reconciliation with
the evidence that forced it, and one of the three was found by mutation testing rather than by
reading.

---

## 2. Root cause analysis for every defect found

### D1 — Task 5's density heuristic rests on a refuted premise *(inherited, resolved)*

**Root cause.** [28 §2.2](28-discovery-redesign.md) asserted for months that an HTML listing page
carries post bodies. It does not: old Reddit renders listing expandos lazily and fetches text over
AJAX. P5 measured it; P6 had to decide what to build instead.

**Evidence.** Re-measured live during this phase, `scripts/validate_feed_parity.py --subreddit
startups`, exit 0: **0 of 25** bodies on the listing, **100 of 100** on the feed, with `body` the
sole tolerated difference on all 25 posts.

**Resolution.** The heuristic is **deleted, not re-targeted**. Enumerating what stage 4 was to source
makes it mechanical: bodies come free from the feed (~97%); the remaining ~3% are link/media posts
with no selftext on any endpoint; `score`/`num_comments`/comments are **P11's**, back-filled during a
permalink fetch it already makes. Nothing was left for a density decision to choose between. Stage 4
is now body *accounting* (`body_source`), and no `density_threshold` key ships.

### D2 — `prescores` could not be altered, because it did not exist

**Root cause.** [33 §2.4](33-final-review.md) moved `prescores` into `0005`; [28 §10](28-discovery-redesign.md)
still carried the pre-move `ALTER TABLE prescores ADD COLUMN stage`.

**Evidence.** `prescores` appears in **no** migration `0001`–`0004`, **no** module under `src/`, and
**none** of the live database's 18 tables. The `ALTER` could never have executed.

**Resolution.** `0005` **creates** the table with `stage` inline. [05 §5.4](05-database-plan.md)'s
inline `comment_id REFERENCES comments(id)` also violates **M8** and is created **bare**, with the FK
deferred to `0006`.

### D3 — Task 4's "provisional prescore" cannot be written *(found by mutation testing)*

**Root cause.** `prescores` carries `CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))`, so
every row must point at a stored `Lead`. A triage **rejection** is by definition a post that was
never stored — `src/scrapers/subreddit_scraper.py:60` persists a lead only when it clears
`is_lead(min_score=3)`. So [34 §P6](34-implementation-plan.md) task 4's "provisional prescore with
`stage='metadata'`" is unwritable for exactly the rows it most needs to record.

**How it was found — and this is the phase's methodological result.** The first implementation
carried a prescore write guarded on a `lead_id` that discovery never supplies. Reading the code, it
looked correct and its tests passed. **Two mutations survived** — M1 (idle poll writes a row anyway)
and M8 (prescores written only for admitted items) — because the branch they mutated was
unreachable. A surviving mutation is the only signal that would have caught this; coverage would not,
because the lines were never executed and the file still reported 87%.

**Resolution.** P6 records the stage-3 funnel as **counters keyed by rejection reason** on
`run_events`, and writes no `prescores` rows. Writing them only for admissions would have produced a
funnel that *looks* auditable while omitting every rejection — precisely AD-10b's prohibition. The
table and repository still ship (freeze §4.1 puts them in `0005`); per-item auditability and the 2%
stage-3 holdout stay with **P11**, which already owns both. Two alternatives were considered and
declined: storing every rejected post as a `Lead` (changes what `leads` means to the operator, and
touches the byte-frozen dashboard), and relaxing the CHECK plus adding a `reddit_id` column (a schema
amendment for capability P11 owns). **Operator-approved before implementation.**

### D4 — A UNIQUE index that would not have been unique *(found while writing the migration)*

**Root cause.** [28 §3.1](28-discovery-redesign.md) specifies
`CREATE UNIQUE INDEX ux_watermarks ON discovery_watermarks (subreddit, channel, query)`. In SQLite,
**NULLs are distinct in a UNIQUE index**, and `query` is NULL for every listing row — so the index
would not have constrained listing watermarks at all.

**Why it matters.** Two watermarks for the same subreddit advance independently and each hides posts
from the other. That is D2 (watermark poisoning) arriving through the schema rather than through a
bug, and it would have been invisible until posts went missing.

**Evidence.** Demonstrated directly: two identical listing rows insert cleanly under the specified
index and are rejected under the shipped one.

**Resolution.** Two **partial** unique indexes — `ux_watermarks_listing (subreddit, channel) WHERE
query IS NULL` and `ux_watermarks_search (subreddit, channel, query) WHERE query IS NOT NULL`. The
column semantics doc 28 specifies are unchanged; only the enforcement is corrected.
`check_schema.py` asserts both.

### D5 — `default_rate` sent an unmeasured channel to the 24-hour maximum

**Root cause.** [28 §8.1](28-discovery-redesign.md) names every polling default except
`default_rate`. The first value chosen (1.0) yields `60/1 = 60` hours, which clamps to
`max_interval` — making a brand-new channel indistinguishable from one measured as dead, and erasing
the distinction `observed_rate_per_hour=None` exists to preserve.

**Resolution.** `default_rate = 60.0` ("until measured, assume the window fills in one hour"). It
errs toward the failure that matters — guessing too slow loses posts silently, guessing too fast
costs one request — and applies only until the second poll, when the EWMA takes over. A test asserts
that unmeasured and dead produce **different** intervals.

### D6 — Overflow reported a fallback it never performed *(found in review)*

**Root cause.** The handler set `html_fallback = True`, returned it, and tested it — but nothing
consumed the flag. `_fetch_html` was reachable only from the `rss_enabled: false` branch, so
**overflow recovered nothing**, while this report, the review's A2 and D-AC3 all said it "triggers
HTML fallback." A claim the code did not support: the F1 defect, again.

**Resolution.** The recovery walk is now **performed** — `_recover_by_html` runs before the overflow
event is emitted (so the session is still clean, B1), its posts are merged by id with the feed's copy
winning, and the diff is recomputed. Recovery failure is logged and does not fail the poll, because
the overflow is already an error and losing recovery must not also lose what the feed did carry.
Asserted by `test_overflow_actually_performs_the_html_recovery_walk` and mutation **M13**.

### D7 — Only the first subreddit of a combined poll got a watermark *(found in review)*

**Root cause.** `watermark_key = subreddits[0] if channel == "listing" else subreddits[0]` — a
ternary whose branches were identical, and a real gap behind it. U1 makes multireddit combining
mandatory, so one request covers ten subreddits; keying one watermark on the first left the other
nine with **no row at all** — never in the due-queue, never rate-measured, and unable to detect
overflow, which is a per-subreddit fact. A busy subreddit sharing a feed with quiet ones is precisely
where posts scroll away unseen.

**Resolution.** One request, **one watermark per subreddit**, as [28 §3.1](28-discovery-redesign.md)
specifies. Posts are grouped by subreddit (case-insensitively) and diffed, advanced and scheduled
independently. Overflow is per-subreddit and the interval is shortened only for the ones that
overflowed. Asserted by two tests and mutation **M14**.

### D8 — The overflow-interval test could not fail *(found in review)*

**Root cause.** It asserted `next_poll_at <= now + 24h`, which `_clamp` guarantees
unconditionally. Deleting `shortened_after_overflow` left it green, and no mutation targeted that
line.

**Resolution.** It now computes what the interval *would* have been and requires the stored one to be
strictly shorter (and exactly half). Mutation **M12** added. **P5's F3, fourth occurrence in this
project** — and the second in this phase.

### D9 — A test that could not fail *(found in review of my own work)*

**Root cause.** The first version of the cold-start test built two synthetic id sets, compared a set
with itself, and asserted 100% coverage. It was documentation wearing a test's clothes — P5's **F3**,
third occurrence in this project.

**Resolution.** Deleted rather than adjusted, and replaced with a check of the arithmetic that can
genuinely fail offline (feed ceiling vs the HTML walk's reach). **D-AC5's real ≥95% claim is a live
measurement and is recorded as not verified** — see §9.

---

## 3. Files created

| File | Purpose |
|---|---|
| `migrations/versions/0005_discovery.py` | `discovery_watermarks` + `prescores`, two partial uniques, deferred FK |
| `src/discovery/watermarks.py` | Diff, advance, overflow detection — pure, no session |
| `src/discovery/policy.py` | `next_interval` — deterministic, zero AI |
| `src/discovery/triage.py` | Stage 3 metadata triage, closed reason vocabulary |
| `src/db/repositories/discovery.py` | Watermarks, due-queue, `known_ids`, prescores |
| `src/orchestration/handlers/discover.py` | The poll handler — stages 1–4 |
| `tests/test_watermarks.py` | 21 tests |
| `tests/test_discovery_policy.py` | 19 tests |
| `tests/test_discovery_triage.py` | 14 tests |
| `tests/test_discovery_handler.py` | 25 tests |
| `docs/P6-IMPLEMENTATION-REVIEW.md` | Written before production code |
| `docs/testing/P06-testing.md` | Manual guide |
| `docs/PHASE-06-COMPLETION-REPORT.md`, `docs/PHASE-06-HANDOVER.md`, `docs/progress/P06-COMPLETE.md` | Execution records |

## 4. Files modified

| File | Change |
|---|---|
| `src/db/models.py` | `DiscoveryWatermark`, `Prescore` |
| `src/discovery/__init__.py` | Exports the new modules |
| `src/reddit_client.py` | **`TransportError`; `_fetch` and `fetch_feed` raise; `_get`/`get_feed` keep `None`/`[]`** |
| `src/orchestration/handlers/__init__.py` | Registers `discover` |
| `scripts/check_schema.py` | 6 new `0005` checks, `--skip-p6` |
| `config.yaml` | Polling keys; an explicit note on the absent `density_threshold` |
| `tests/test_boundaries.py` | Density fence; policy-module fence |
| `tests/test_orchestration.py`, `tests/test_handlers_scrape.py` | Revision and registry pins follow the new head |
| `docs/ARCHITECTURE_FREEZE.md` | 3 reconciliations (§11.1) |
| `docs/28-discovery-redesign.md` | Stage 4, §3.1(2), D3, D7, §10 corrected |
| `docs/34-implementation-plan.md` | P6 delivered note |

## 5. Database changes

`0005_discovery`, additive only. `discovery_watermarks` (10 columns, 3 indexes) and `prescores`
(11 columns, 3 indexes, 1 CHECK). No existing table altered; **M5** holds. `comment_id` is bare, FK
deferred to `0006` (**M8**). Tested **up → down → up** on a copy of the live database (**M9**), and
applied to the live database after a backup (**M7**). `alembic heads` returns exactly one.

## 6. Interface changes

**Additive.** `RedditClient` gains `TransportError`, `_fetch` and `fetch_feed`. **The six frozen
methods are untouched** (AD-2) — `_get` catches `TransportError` and returns `None` exactly as
before, so no shipped caller changes behaviour. `_fetch`/`fetch_feed` are the opt-in path for a
caller that needs to distinguish *blocked* from *empty*, which is what closes **N2**.

## 7. Automated test results

| Check | Result |
|---|---|
| Full suite | **887 passed, 2 skipped** (P5 baseline: 803 / 2 — **+84**) |
| `-W error::DeprecationWarning` | **887 passed, 2 skipped** |
| `ruff check .` | All checks passed! |
| `ruff format --check .` | 118 files already formatted |
| `alembic heads` | `0005_discovery (head)` — one head |
| `check_schema.py` | **OK — all 31 checks passed** (was 25) |
| Grep fences | 4 of 4 |
| Legacy contract | 459 baseline leads · `intent_score` fingerprint · `GET /` · 13 CSV columns · 17 endpoints |
| Migration up/down/up | On a copy of the live DB ✅ |
| `mypy` | **Not run — blocker B3/O2, unchanged** |
| **GitHub Actions** | ✅ **success** — run `31272619320`, 1m38s, on `origin/main` at `2921a79` (and `31270866135` at `4c18152`) |

## 8. Mutation testing

**16 designed, 16 detected** — after the two that first survived exposed D3, and three added in
review to cover D6, D7 and D8.

| # | Mutation | Detected by |
|---|---|---|
| M12 | Overflow no longer shortens the interval | interval test (rewritten — D8) |
| M13 | Overflow flags but does not walk | recovery-walk test (D6) |
| M14 | Only the first subreddit gets a watermark | per-subreddit test (D7) |

The original thirteen:

| # | Mutation | Detected by |
|---|---|---|
| M1 | Idle poll treats known posts as new | idle-poll test |
| M2 | Overflow check always `False` | 150-post fixture |
| M2a | Overflow **null-guard** dropped | cold-start / empty-feed fixtures |
| M3 | `policy.py` imports `src.ai` | boundary fence |
| M4 | `rss_enabled: false` no longer falls back | rollback test |
| M5 | `allow_cache=True` on the discovery path | cache-bypass test |
| M6 | Watermark advances on an empty diff | `consecutive_empty` test |
| M7 | `next_interval` skips the clamp | property test |
| M8 | Rejection reasons not counted | funnel-counter test |
| M8a | A rejection counted as an admission | funnel-counter test |
| M9 | `_fetch` swallows the exception again | N2 mapping test |
| M10 | Handler emits its event **before** the fetch | T0 lock test |
| M11 | Triage ignores the time window | window test |

⚠️ **M2 alone could not catch M2a**, because the null-guard's failure direction is *over*-reporting.
The harness asserts that each mutation actually changed the file and that pytest actually collected
tests — P5's **F4**, where two mutations silently skipped and the run still printed a total.

## 9. Coverage

| Module | Coverage |
|---|---|
| `src/discovery/policy.py` | **100%** |
| `src/discovery/triage.py` | **100%** |
| `src/discovery/watermarks.py` | **100%** |
| `src/db/repositories/discovery.py` | **98%** |
| `src/orchestration/handlers/discover.py` | **87%** |
| `src/discovery/` overall | **96%** |

## 10. Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| A1 | Idle poll = **one** request, zero rows | ✅ Automated + M1 |
| A2 | Overflow is an **error** + HTML fallback + shorter interval | ✅ Automated + M2/M2a |
| A3 | Steady state **≤ 80** requests/day | ✅ Deterministic simulation |
| A4 | Cold start ≥ **95%** of the HTML design | ⚠️ **Not verified** — see below |
| A5 | `policy.py` makes zero AI calls, imports no `src.ai` | ✅ Fence + M3 |
| A6 | Discovery bypasses `http_cache` | ✅ M5 |
| A7 | `rss_enabled: false` keeps the HTML path working | ✅ M4 |
| A8 | Interval computed in < 1 ms | ✅ Measured over 1,000 calls |

⚠️ **A4 is recorded as measured-against-arithmetic, not verified.** D-AC5 compares what a cold start
collects against what the HTML design collects, which needs two captures of the same subreddit at the
same instant. That capture was not taken, so **the word "verified" is not written** — P5's own
precedent, applied in the direction that is invisible from inside. What *is* checked offline is that
the feed's 100-item ceiling reaches at least as far as the HTML walk, which is the arithmetic the
claim rests on. Falsification path: run both collectors against one subreddit in one window and
compare id sets.

## 11. Manual testing

[testing/P06-testing.md](testing/P06-testing.md) — 11 tests, 8 blocking, one optional live step.
Every command executed as written. **Four expected counts were corrected by executing them**, and the
F5 defect reproduced during verification: two `-k` expressions run unquoted selected **nothing** and
still exited successfully.

**Sign-off table is unsigned** — blocker D1, unchanged since P0.

## 12. Remaining risks

| # | Risk | State |
|---|---|---|
| K9 | Watermark overflow | **Mitigated** — error, fallback, shortened interval, 10 tests |
| K8 | RSS deprecated/throttled | Mitigated — `rss_enabled: false` tested both ways |
| K13 | SQLite lock contention | **Mitigated** — commit-before-fetch, asserted by test and M10 |
| K14 | Migration corrupts the live DB | Mitigated — backup, up/down/up on a copy |
| D1 | Manual sign-off tables unsigned | **Open**, P00–P06 |
| B3/O2 | `mypy` not installed | **Open** — the gate cannot be claimed in full |
| — | A4 not live-verified | **Open** — §10 |

## 13. Deferred improvements

| Item | Owner / trigger |
|---|---|
| Per-item stage-3 `prescores` rows + 2% holdout audit | **P11** (owns full prescoring, `gate.metadata_holdout_rate`) |
| `score` / `num_comments` back-fill | **P11** task 4 |
| Comment expansion (stage 6) | **P11** task 3 — needs `comments` (`0006`) |
| Selftext for link/media posts | **Nobody** — it exists on no endpoint |
| `_extract_search_post` host normalisation (DI14) | Deferred — shipped-behaviour change |
