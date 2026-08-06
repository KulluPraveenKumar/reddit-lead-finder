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

Work completed after `v0.1.0-p1` and before P2 begins. **No P2 implementation.**

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
