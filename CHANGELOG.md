# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/), and the version numbering is
`v<project version>-p<phase>` — the version in `pyproject.toml`, suffixed with the phase of the
frozen [P0–P30 plan](docs/34-implementation-plan.md) that the release completes.

This file is **maintained by hand**. It is not generated from commit messages: a changelog is for
humans, and a `git log` dump is not a changelog. Entries are added by the phase that ships them,
under the process in [docs/EXECUTION_MODE_LOCK.md](docs/EXECUTION_MODE_LOCK.md).

---

## [Unreleased]

**P3 — run service, run API, run pages** ([docs/PHASE-03-COMPLETION-REPORT.md](docs/PHASE-03-COMPLETION-REPORT.md))
and **P2 — job queue, worker, structured logging** ([docs/PHASE-02-COMPLETION-REPORT.md](docs/PHASE-02-COMPLETION-REPORT.md)),
plus the process and hygiene work completed after `v0.1.0-p1`.

> Not yet tagged. [EXECUTION_MODE_LOCK §6.2](docs/EXECUTION_MODE_LOCK.md) forbids tagging a phase
> whose manual sign-off table is unsigned.

### ⚠️ Changed — P3, behaviour an operator will notice

- **`POST /api/scrape` and `python main.py schedule` now collect subreddit leads only.** They create
  a run and enqueue one `scrape_subreddit` job per subreddit; the **keyword and user scrapers no
  longer run on those two paths**. The frozen job-type list ([docs/04 §2.4](docs/04-system-design.md))
  contains no keyword or user type, and those stages arrive in P5/P17. This is a deliberate,
  approved scope decision, not an oversight.
  **Unaffected:** `python main.py scrape` still runs all three, and setting
  `orchestration.enabled: false` restores the previous behaviour on every path.
- **The "Run Scrape Now" button navigates to `/runs/<id>`** instead of showing "Scrape complete!"
  after a five-second timer that was never connected to the scrape.
- **A second scrape while one is running no longer starts a second run.** `POST /api/scrape` returns
  the run already in flight, and the UI opens it. `POST /api/runs` returns `409` with its id.

### Added — P3

- `src/orchestration/run_service.py` — `RunService` (create / transition / cancel / retry /
  progress), `RunOptions`, `RunProgress`, the duplicate-run guard, and `orchestration_enabled()`.
  A run walks all seven legal hops from `PENDING` to `SCRAPING`; both review gates lie on that path
  and each records on the timeline why the operator's configured list already satisfies it
  ([ARCHITECTURE_FREEZE §11.1](docs/ARCHITECTURE_FREEZE.md)).
- `src/orchestration/handlers/scrape.py` and `finalize.py` — one job per subreddit, and the job that
  closes a run. A failed subreddit does not fail the run (AD-9); the timeline says what was lost.
- `src/dashboard/routes_runs.py` — `GET/POST /api/runs`, `/api/runs/<id>`, `/progress`, `/events`,
  `/cancel`, `/retry`, `GET /api/jobs`, `POST /api/jobs/<id>/retry`, and the `/runs` and `/runs/<id>`
  pages.
- `poll()` in `_base_ai.html` — stops on a terminal state, backs off to 10 s after three consecutive
  errors, and pauses while the tab is hidden.
- `JobQueue.requeue()` — the operator's force-retry for one failed job, granting one extra attempt.
- `Worker.join()` — waits for the loop to actually exit rather than only asking it to.
- `orchestration.enabled` in `config.yaml` (default `true`) — the phase's rollback switch, distinct
  from `WORKER_INPROCESS`.
- `/api/health` gained a `queue` block: depth, `oldest_queued_at`, and whether **this** process holds
  a worker. Cross-process worker liveness needs a heartbeat table P3 does not own.
- `SubredditScraper.run()` gained two additive keyword arguments, `subreddits` and `run_id`; both
  default to the previous behaviour. `scrape_runs.run_id` is now populated.

### Fixed — P3

- **Cancelling a run while a subreddit was being scraped returned HTTP 500** (`database is locked`).
  The scrape handler left pending writes on its session and then spent minutes on the network; the
  scraper's first query flushed them, taking SQLite's single write lock and holding it for the whole
  fetch, so `POST /api/runs/<id>/cancel` waited out `busy_timeout` and failed. The handler now
  commits its bookkeeping before the scrape starts. **"Scraping r/x" also now appears on the run page
  while that subreddit is being scraped, instead of after it finishes.** Found by manual testing.
- **`config.yaml` was read with the locale's default encoding.** On Windows that is cp1252, so a
  single non-ASCII character anywhere in the file — including in a comment — raised
  `UnicodeDecodeError` from every command that loads config. It is now read as UTF-8, which is what
  YAML specifies.
- **`RunService.fail()` stored its error unredacted.** That column is rendered on `/runs/<id>`, so a
  credential in an exception message could have reached the page (R15, and P2's F3 finding).
- The scrape button no longer reports success it cannot know about, and no longer fails silently
  when the request errors.

### Added — P2

- `src/orchestration/job_queue.py` — `JobQueue` with an atomic claim-and-lease (`BEGIN IMMEDIATE`
  plus an `AND state='queued'` guard), per-type attempt budgets, jittered exponential backoff capped
  at 600 s, lease reclamation, and `RetryableError`.
- `src/orchestration/worker.py` — the worker loop, a heartbeat thread extending the lease every
  `lease/3`, graceful `SIGTERM`/`SIGINT` shutdown, `WORKER_INPROCESS`, and `start_inprocess_worker()`.
- `src/orchestration/handlers/` — the handler registry and the `maintenance` handler: four retention
  purges (`jobs` > 30 d, `run_events` for runs finished > 90 d, expired `http_cache`, `metrics`
  > 14 d) plus a `VACUUM` guarded by a free-page threshold. **`ai_cache` is never purged** — it is
  the cost saving, and a test asserts it.
- `src/obs/events.py` — `emit_event()`, writing one `run_events` row in the caller's transaction and
  logging the same fact.
- `src/db/repositories/runs.py` — `RunRepository` and `JobRepository`, including the single
  `GROUP BY` that P3's progress endpoint is built on.
- `python main.py worker` — the standalone foreground worker.
- A socket-blocking autouse fixture in `tests/conftest.py`: the offline guarantee is now
  machine-enforced rather than a convention. Loopback stays open.
- 120 tests, including a 1,000-job / 4-thread claim race, a duration-parameterised concurrency soak
  (`SOAK_SECONDS=600` runs the real 10 minutes) and a 10 MB log capture grepped for credentials.

### Changed — P2

- `src/obs/logging.py` now formats with **`python-json-logger`** rather than a hand-rolled
  `json.dumps` formatter, and gains a `ContextFilter` + `log_context()` so every record carries
  `run_id`/`job_id`/`project_id` — including records from third-party libraries. Both formatters now
  redact the **rendered traceback**: a credential in an exception message previously reached the log,
  because a traceback does not exist until a formatter renders it, so the filter had nothing to
  redact.
- `migrations/env.py` — `fileConfig(..., disable_existing_loggers=False)`. Migrations run in-process
  on every start, and `fileConfig`'s default had been silently disabling **every** application logger
  from the first line of the application onward.
- `config.yaml` — `logging.file` and `worker.poll_interval_seconds`.

### Fixed — P2

- **Every `DateTime` column default now uses the timezone-aware `models._utcnow` instead of the
  deprecated `datetime.utcnow`** (7 columns across `leads`, `dashboard_subreddits`,
  `dashboard_keywords`, `dashboard_search_queries`, `tracked_users` and `scrape_runs`). SQLAlchemy
  evaluates Python-side defaults *inside* statement execution, so under
  `pytest -W error::DeprecationWarning` the deprecation raised as a `StatementError` on INSERT —
  an error naming neither the column nor the datetime. Six tests failed this way, and one of them,
  `test_a_reclaimed_job_re_runs_without_duplicating_rows`, reported *"the re-run duplicated a row"*
  when the truth was the opposite: the rolled-back INSERT wrote **zero** rows, and the reclaim and
  idempotency logic it guards were correct throughout. The stored value stays **naive** UTC:
  `JobQueue.claim` compares timestamps as formatted SQLite strings, so an aware value would carry a
  `+00:00` suffix and the `<=` would silently stop matching — a queue that claims nothing and
  reports no error.
- The same substitution in `src/scoring.py` and the three scrapers, which computed naive UTC
  directly. No test reaches these call sites; they are behaviour-preserving by construction.
- Three regression tests in `tests/test_boundaries.py`, reflecting off `Base.metadata` so they cover
  columns added later rather than the ones that happened to break: no `DateTime` default may be
  `datetime.utcnow` (deprecated) or a bare `datetime.now` (local time, not UTC); every default must
  return a naive value on a UTC clock; and both offending columns must round-trip that way through a
  real INSERT and SELECT. The first is keyed on `__qualname__` rather than identity, because
  `datetime.datetime.utcnow` returns a fresh bound-builtin on every attribute access and an `is`
  check would pass no matter what the model did. Verified by mutation, not by assumption.

### Dependencies

- `python-json-logger>=3.1` — the one dependency P2 adds, named by
  [ARCHITECTURE_FREEZE §5](docs/ARCHITECTURE_FREEZE.md). The floor is 3.1 rather than the 2.0 doc 33
  proposed: the 2.x import path emits a `DeprecationWarning` from 3.0, and its replacement does not
  exist before 3.1.

### Added
- `docs/EXECUTION_MODE_LOCK.md` — the binding process: the 16-step session workflow, phase
  discipline, the public-repository hygiene review, git and tagging discipline, ranked engineering
  priorities, and what may no longer be written. The last planning document.
- `docs/DEFERRED-IMPROVEMENTS.md` — the register where an improvement waits for the evidence that
  would justify building it, plus the open operator decisions.
- `.github/workflows/ci.yml` — one workflow: `ruff check`, `ruff format --check`, `pytest`, on push
  to `main` and on every pull request. No secrets, no deployment, no coverage upload.
- `CHANGELOG.md` — this file.
- A title assertion in `test_listing_page_parses_posts_with_real_scores`, found by mutation testing:
  breaking the listing title selector previously left every post untitled and the test still passed.

### Changed
- **Test fixtures are fully synthetic.** Verbatim Reddit post titles, usernames, account ids and
  title-derived URL slugs were replaced with deterministic synthetic equivalents across
  `tests/baseline/` and `tests/fixtures/reddit/`. Row counts, column order, every numeric value and
  the 459-lead / 164.28 / 42.29 fingerprint are unchanged. See
  [docs/PRIVACY_REVIEW.md](docs/PRIVACY_REVIEW.md).
- `ruff format` now covers the whole repository except Markdown and the pre-Phase-1 modules that are
  exempt by design, so `ruff format --check .` is a check CI can run rather than one every caller
  scopes by hand. 23 files reformatted; no behaviour changed.
- `ruff` is pinned to `==0.16.1`. The formatter's output changes between releases, so an unpinned
  ruff turns CI red on a day nobody touched the code.
- `phase-manager` skill 2.0.0 and `architecture-reviewer` skill 1.1.0 — the session workflow now
  covers handover review, repository health, the completion report, the handover, the hygiene review
  and the commit/push/tag steps.
- Manual testing guides P00 and P01: stale counts corrected (`310 passed` → `308 passed, 2 skipped`;
  `26 schema checks` → `25`; `6 checks` → `5`). The guides were unexecutable as written — a tester
  following them would have recorded a passing suite as a failure.

---

## [v0.1.0-p1] — 2026-08-06

The first tagged state: two phases of the frozen plan complete, the architecture frozen, and the
repository published.

### Added
- **P0 — Validation sprint.** Eight measurements against live `old.reddit.com` and the proxy pool,
  each answering a question the architecture depended on. Two forced amendments: conditional GET is
  unavailable on Reddit's `.rss` (layer L1 deleted), and multireddit combining is mandatory rather
  than optional. Recorded in [docs/SPRINT-0-MEASUREMENTS.md](docs/SPRINT-0-MEASUREMENTS.md).
- **P1 — Run & job schema.** Migration `0004_orchestration`: `runs`, `jobs`, `run_events`, and
  `scrape_runs.run_id`, plus the run and job state machines in `src/orchestration/`. Shape, not
  behaviour — there is no worker and no page until P2 and P3. 44 orchestration tests, including
  exhaustive rejection of all 144 run-state and 25 job-state pairs.
- `scripts/check_schema.py` — a stdlib-only, read-only schema verifier the manual guides use instead
  of long `python -c` one-liners. 25 checks across tables, index column order, foreign-key actions,
  constraints, row counts, integrity and the legacy fingerprint.
- Manual testing guides for P0 and P1, written to be executed by a non-developer.
- Repository files for publication: `LICENSE` (MIT), `.gitattributes`, pull-request and issue
  templates, including one that enforces the amendment rule — *a failed measurement, not an
  argument*.

### Changed
- **Architecture frozen** ([docs/ARCHITECTURE_FREEZE.md](docs/ARCHITECTURE_FREEZE.md)): 20
  architecture rules, 31 decisions, a 10-revision migration chain, a closed technology set, frozen
  budgets, permanent non-goals and 18 carried risks. Amendable only by a failed measurement.
- **Recovery from an unexpected shutdown.** The phase timeline was reconstructed and every claim
  re-verified rather than carried over; the audit is in
  [RECOVERY_REPORT.md](RECOVERY_REPORT.md). Its top recommendation — put the project under version
  control — is what this release is.
- **Repository hardening for publication.** Third-party data anonymised, machine-specific paths
  removed, ignore rules proved with `git check-ignore`, and a final verification pass recorded in
  [docs/PRE-P2-VERIFICATION-REPORT.md](docs/PRE-P2-VERIFICATION-REPORT.md).

### Security
- Secrets never enter the repository, the database, a log or an API response (R15): the AI provider
  key is entered at runtime and encrypted at rest, proxy credentials live in a file outside the
  repository, and `.env` is ignored.

[Unreleased]: https://github.com/KulluPraveenKumar/reddit-lead-finder/compare/v0.1.0-p1...HEAD
[v0.1.0-p1]: https://github.com/KulluPraveenKumar/reddit-lead-finder/releases/tag/v0.1.0-p1
