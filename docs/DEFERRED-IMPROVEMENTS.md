# DEFERRED IMPROVEMENTS

**Opened: 2026-08-06** · The register named by
[EXECUTION_MODE_LOCK.md §8](EXECUTION_MODE_LOCK.md).

> An improvement discovered mid-phase that does not meet all four conditions in
> [§8](EXECUTION_MODE_LOCK.md) is recorded here and the phase continues.
>
> **This is not a backlog.** Nothing here is scheduled. Each entry names the **evidence that would
> justify building it** — and until that evidence exists, the entry stays where it is. An entry with
> no trigger is an idea, and ideas are what this register exists to absorb.

Related, and deliberately separate: [freeze §9](ARCHITECTURE_FREEZE.md) holds deferred *features*
with their triggers. This file holds deferred *implementation and process* improvements. If an entry
here would change architecture, it does not belong here — it is a [freeze §11](ARCHITECTURE_FREEZE.md)
amendment and it needs a failed measurement.

---

## 1. Register

| # | Improvement | Trigger — the evidence that would justify it | Raised |
|---|---|---|---|
| **DI1** | **`scripts/check_repo_hygiene.py`** — mechanise the [§5](EXECUTION_MODE_LOCK.md) hygiene checklist as a script, the way `check_schema.py` mechanised the schema checks | A hygiene review **misses** something that reaches a public commit, or a phase ships with the review demonstrably skipped. Until then the brief calls for a *review* of staged changes, and gate check 14 already covers the secret scan | 2026-08-06 |
| **DI7** | **[Freeze R20](ARCHITECTURE_FREEZE.md) states the legacy contract as "`GET /` byte-identical", but the shipped guard is an API-contract check** (`tests/test_boundaries.py::test_legacy_api_contract_is_frozen`), which compares response *shape* and the 13-column CSV header. The docstring says the byte-identical form was deliberately superseded during Phase 1 | Someone acts on R20 as written — most likely by refusing a correct change, or by claiming a guarantee the suite does not enforce. This is a [freeze §11.1](ARCHITECTURE_FREEZE.md) documentation reconciliation, not an amendment: no technology, table or decision changes. **Recorded here rather than reconciled unilaterally**, because editing the freeze is the operator's call | 2026-08-06 |
| **DI10** | **Four statements about the Python version, two answers.** [Freeze §5](ARCHITECTURE_FREEZE.md) says Python **3.12**; `pyproject.toml` says `requires-python = ">=3.11"` and `target-version = "py311"`; [testing/P01-testing.md](testing/P01-testing.md) says *"the project floor is 3.11"*; CI pins **3.12** | Someone runs the project on 3.11 and hits a 3.12-only construct, or the freeze is reconciled. Same species as **DI7**: a documentation inconsistency, not an architecture change, and editing the freeze is the operator's call. **The pins were deliberately left alone** — changing them the day before P2 would alter what the gate tests | 2026-08-06 |
| **DI8** | **Pin GitHub Actions to commit SHAs** instead of major-version tags | A supply-chain advisory affecting `actions/checkout` or `actions/setup-python`, or a second contributor. Major tags are GitHub's documented default and are re-pointed by GitHub | 2026-08-06 |
| **DI9** | **`concurrency: cancel-in-progress` in the CI workflow** | More than one push in flight at a time — i.e. a second contributor. With one developer there is nothing to supersede | 2026-08-06 |
| **DI3** | **Consolidate the completion report and the progress record.** Both describe a finished phase and overlap substantially ([PHASE-01-COMPLETION-REPORT.md](PHASE-01-COMPLETION-REPORT.md) vs [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md)) | The two **contradict each other** in a phase. They answer different questions today (evidence vs resume point) and merging them would lose the resume point that [RECOVERY_REPORT.md](../RECOVERY_REPORT.md) exists because of | 2026-08-06 |
| **DI4** | **`ruff format` the 28 unformatted legacy modules** | The **byte-identical `GET /`** half of the R20 legacy contract is retired. Not before: reformatting `src/dashboard/routes.py` risks the exact guarantee the contract pins. Excluded in `pyproject.toml` on purpose | 2026-08-06 |
| **DI5** | **`docs/02-research-findings.md` is linked from several documents but does not exist** — a pre-existing broken link, recorded in [RECOVERY_REPORT.md](../RECOVERY_REPORT.md) §5.4 | A documentation link check is added to the gate (check 18 covers *this phase's* links only), or a reader is actually blocked by it | 2026-08-06 |
| **DI6** | **`data/leads.db` is at `0004` while [PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md) §3 says `0003`** | Nothing — P2 needs `0004` anyway, the tables are empty and all 25 `check_schema.py` checks pass. Documented in [PRE-P2 §1.4](PRE-P2-VERIFICATION-REPORT.md). Recorded so the next session does not "fix" it | 2026-08-06 |
| **DI12** | **Conditional GET on `.rss`** — `if_none_match` / `if_modified_since` / 304-as-success, as [34 §P5](34-implementation-plan.md) originally specified | **Reddit starts sending the headers.** Concretely: `scripts/probe/probe_rss.py::probe_u4_conditional` reports `etag_present: true` or `last_modified_present: true` on a live run. Refuted in P0 across 4 feeds and 2 hosts, re-observed 2026-08-08 (`Cache-Control: private, max-age=3600`, neither header). Until then the branch cannot be taken and no test could prove it works, so building it would ship dead code — `tests/test_boundaries.py::test_conditional_get_has_not_been_reintroduced` blocks it | 2026-08-08 |
| **DI13** | **`_extract_post` reports `num_comments = 0` when the count is absent**, where the honest value is `None` — the same class of bug fixed for search-sourced `score` in [07 §4.1](07-scraping-pipeline.md). The feed path already reports `None` | A consumer treats `0` as "nobody commented" and acts on it — most likely the comment-fetch eligibility test in **P11**, which is where the distinction first has a decision hanging off it. Not fixed in P5: it changes shipped behaviour on a path P5 is additive to, and it would perturb the legacy contract | 2026-08-08 |
| **DI14** | **`_extract_search_post` does not normalise its permalink host**, so search-sourced leads store `old.reddit.com` while listing-sourced leads store `www.reddit.com`. The live database is split **444 / 27** across 471 rows | A user-visible inconsistency is reported, or an export/dedup step keys on `url` and treats the two hosts as different posts — **P10's dedup cascade is the first place that bites**. A fix must decide what happens to the 444 existing rows, which is a data-migration question and not P5's. The feed path follows the listing path's canonical `www.reddit.com` | 2026-08-08 |
| **DI15** | **An eighth job type shipped unreconciled.** `src/orchestration/handlers/__init__.py` states that *"`docs/04` §2.4 names seven job types and the freeze closes that list"*, and the registry then contains `DISCOVER_JOB = "discover"` — which appears in [04 §2.4](04-system-design.md)'s table nowhere, and in no [freeze §11.1](ARCHITECTURE_FREEZE.md) entry | **The next phase that wants a job type** — most likely **P8** or **P11**. Either [04 §2.4](04-system-design.md) gains `discover` as a §11.1 reconciliation, or the list is not closed and the docstring is wrong. **Not fixed in P7**, deliberately: P7's dispatch design (D3/D7) adds no job type, so it neither needs the precedent nor worsens the debt. Recorded so the next phase does not either cite it as licence or trip over it | 2026-08-10 |
| **DI16** | **Three notification kinds deferred for want of a data source** — `lead.high_confidence`, `quality.red`, `budget.warning` ([P7-DECISION-ANALYSIS D2](P7-DECISION-ANALYSIS.md)) | One trigger each. `lead.high_confidence`: `leads.confidence_score` exists (`0006`, P8) **and** is populated (P21) — it ships then, with `notify.min_confidence_alert`, which P7 deliberately does **not** ship. `quality.red`: `quality_snapshots` exists (`0010`, P25) and P26 computes a red state. `budget.warning`: something spends **and** an 80%-of-cap signal exists — `src/ai/cost.py::check_budget` currently raises at 100% only. Each addition past five is a [freeze §7](ARCHITECTURE_FREEZE.md) expansion and *"requires operator request"* | 2026-08-10 |
| **DI17** | **A periodic driver for background work.** `handle_maintenance` is registered in the handler registry and has `MAX_ATTEMPTS`, but **nothing enqueues it** — the only `enqueue(` sites in `src/` are `run_service.py:298`, `run_service.py:317` and `scrape.py:172`, and `main.py schedule` enqueues *runs*. Same species as P6's `repo.due()`: *"exists, nothing calls it on a timer yet"* | **The first phase that needs periodic background work.** [34 §P17](34-implementation-plan.md)'s due-queue scheduler is the natural home and needs the identical driver, so building one in P7 would be built twice. P7 routed around it (**D7**): `RunService.fail()` enqueues `finalize_run`, so no notification depends on a sweeper that never runs. **A consequence worth knowing:** a transport failure past P7's retry budget is *recorded* and delivered on the next drain for that run, or not at all — it is not "retried later" | 2026-08-10 |
| **DI18** | **`test_parse_speed_stays_inside_the_budget` is a wall-clock assertion and fails under machine load.** Observed **twice on 2026-08-10**: `100 entries took 105.3 ms, budget is 50 ms` during P7's baseline (run concurrently with another command), and again in P7 Stage 1's `-W error::DeprecationWarning` run, which took 311 s against the same suite's usual ~185 s. Passes 3/3 in isolation at 1.25–1.84 s | **It fails in CI**, or a third local occurrence. It threatens the *"CI green after every stage"* rule while testing nothing about correctness — the parser is not slow, the machine is busy. The fix is a monotonic or CPU-time budget with headroom, **not a raised threshold**, which would be weakening an assertion ([lock §3](EXECUTION_MODE_LOCK.md) step 6). **Not fixed in P7:** it is P5's test on a path P7 does not touch, and P7's own timing criterion (AC1) is specified to avoid the same trap. This is also why the P7 guide warns a tester that a timing step may fail for reasons unrelated to the code | 2026-08-10 |
| **DI19** | **`pyproject.toml` sets `addopts = "-q --strict-markers"`, so a documented `pytest -q` becomes `-qq` — which suppresses the `N passed` summary line entirely.** A guide asking a tester to record a count from such a command asks for a number pytest never prints | **Nothing, for P7** — `docs/testing/P07-testing.md` was corrected before it shipped (31 commands), and it now warns against adding `-q`. **Recorded because the earlier guides may carry it:** [testing/P06-testing.md](testing/P06-testing.md) and its predecessors use `-q` in steps whose expected output is a count. Trigger: a tester reports being unable to find a number the guide asked for. Found by executing the commands rather than by reading them | 2026-08-10 |
| **DI11** | **`scripts/check_schema.py` crashes at revision `0003`** with `sqlite3.OperationalError: no such table: runs` in `check_row_counts`, instead of reporting the missing objects as failures and exiting cleanly. [testing/P01-testing.md](testing/P01-testing.md) tells a tester it reports *"5 checks"* there — it reports 9 and then aborts with a traceback | A phase whose rollback **is** a downgrade needs the verifier to work at the earlier revision. P2's rollback is an environment variable and touches no migration, so nothing is blocked today. Found during P2's round-trip check; the round-trip itself passed (`0004 → 0003 → 0004`, 459 leads at every stage). The fix is a `try`/`except` per table plus a corrected sentence in the P01 guide — **not done here** because editing another phase's signed-off guide is the operator's call | 2026-08-06 |

---

## 2. Open decisions awaiting the operator

Not improvements — **choices only the operator can make.** Each blocks nothing, and each stays here
until answered.

| # | Decision | Why it is open now | Cost of acting |
|---|---|---|---|
| **O2** | **`mypy` is required by [35 §2](35-testing-strategy.md) check 3 and [freeze §5](ARCHITECTURE_FREEZE.md), and is not installed** (blocker **B3**, still open) | The gate cannot be claimed in full until it runs. Verified absent 2026-08-06 | `python -m pip install mypy`, then record the baseline error count so check 3 has something to compare against |
| **O3** | **P00 and P01 manual sign-off tables are unsigned** (blocker **D1** in [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md)) | [PHASE-01-HANDOVER.md §8](PHASE-01-HANDOVER.md) makes this the entry condition for P2. **This is the one gate standing between here and P2** | ~20 minutes each, non-destructive, by a non-developer |

---

## 3. Closed

Per rule 2 below, an entry leaves §1 or §2 only when it is built or its trigger is disproved — with a
line saying which.

| # | Was | Closed | Date |
|---|---|---|---|
| **DI2** | GitHub Actions CI — one workflow: `ruff check` · `ruff format --check` · `pytest` | **Built.** `.github/workflows/ci.yml`; the research, the measured caching decision and the local verification are in [GITHUB_ACTIONS_REPORT.md](GITHUB_ACTIONS_REPORT.md) | 2026-08-06 |
| **O1** | Post titles retained in `tests/baseline/` under a private-repository premise that no longer held | **Resolved by synthesising.** Every verbatim title, username, account id, post id and title-derived slug in `tests/baseline/` and `tests/fixtures/reddit/` is now synthetic; row counts, columns, numbers and the fingerprint are unchanged. Evidence and mutation testing in [PRIVACY_REVIEW.md](PRIVACY_REVIEW.md) | 2026-08-06 |

---

## 4. Rules for this file

1. **Every entry names a trigger.** No trigger, no entry.
2. **An entry is removed only when it is built, or when its trigger is proved impossible** — with a
   line saying which.
3. **Nothing here is scheduled.** Being in this file confers no claim on a future phase.
4. **Architecture changes do not belong here.** They belong in
   [freeze §11](ARCHITECTURE_FREEZE.md), and they require a failed measurement.
