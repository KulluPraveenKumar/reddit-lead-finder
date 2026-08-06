# Pre-P2 Verification Report

**Date:** 2026-08-06 · **Scope:** final verification pass before the GitHub repository is created
and P2 is approved. **No P2 work was started.** No architecture was redesigned.

Governing document: [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md). Nothing below introduces a
technology, table, migration, AI call, dependency or capability the freeze does not already name.

---

## 1. Final Manual Testing Report

### 1.1 The `sqlite3` CLI premise did not hold

The brief assumed the manual guides require the `sqlite3` command-line tool, which Windows does not
ship. **They do not, and never did.** Every database check in `P00-testing.md` and `P01-testing.md`
used `python -c "import sqlite3; ..."` — the Python **standard library module**, which has no
relationship to the `sqlite3.exe` binary.

The only true CLI invocations in the repository are in
[`docs/testing/phase-01-testing.md`](testing/phase-01-testing.md) lines 183 and 511, which belongs to
the **superseded eight-phase numbering** and is explicitly marked as such by P01-testing.md itself.
It was left unmodified — it is out of scope and is a historical record.

**So no portability defect existed.** A different defect did, and it was worth fixing.

### 1.2 The defect that was real

T5 verified the schema with five `python -c` one-liners, the longest **350 characters on a single
line**. They were correct and they were unusable by the non-developer the guide is written for: a
mistyped bracket produced a `SyntaxError` about string quoting rather than an answer about the
database, and the guide carried a whole explanatory paragraph about PowerShell's handling of `\"`
purely to survive a copy-paste.

**Resolution: [`scripts/check_schema.py`](../scripts/check_schema.py).** One command, one verdict per
check, with the found value printed beside the wanted one on failure.

| Property | Choice | Why |
|---|---|---|
| Dependencies | **stdlib `sqlite3` + `argparse` only** | Freeze §5 forbids adding one; `scripts/probe/` is the in-repo precedent for a dev-tool script |
| Platform | Windows, macOS, Linux | No `sqlite3` binary, no shell built-ins |
| Database access | **read-only** (`file:...?mode=ro`) | Running a check must never be the thing that changes the fingerprint being checked. Asserted by `test_does_not_write_to_the_database_it_checks` |
| Spec source | **transcribed** from `docs/05` and `docs/04` | Reading `src/db/models.py` would make it agree with itself no matter what shipped |
| Failure mode | every check runs, then all failures list | Stopping at the first would make the operator re-run once per problem |

Options considered and rejected: **pytest-only** (a traceback is not an operator-facing answer, and
the manual guide's value is that a non-developer can read the result); **SQLAlchemy inspection**
(reads the same declaration the migration reads — it would agree with itself).

### 1.3 Guides updated

Both guides were revised and **every documented command was then executed to confirm its documented
output**.

| Change | P00 | P01 |
|---|---|---|
| Absolute `C:\Users\...` paths removed | ✅ | ✅ |
| `ALEMBIC_DB_URL` made relative (`sqlite:///data/p1-test.db`) | — | ✅ |
| macOS/Linux equivalents noted | ✅ | ✅ |
| Long one-liners replaced by `check_schema.py` | ✅ (1) | ✅ (7) |
| Stale test counts corrected | ✅ | ✅ |
| Proxy file via `$env:PROXY_FILE` instead of a hardcoded path | ✅ | — |
| Live-DB revision reality documented (§1.4) | — | ✅ |
| PowerShell-quoting workaround paragraph deleted (no longer needed) | — | ✅ |

Stale counts found and corrected:

| Location | Said | Actual |
|---|---|---|
| P00 T2 Step 1 | 265 passed | **310** |
| P00 T2 Step 2 | 11 probe tests | **10** |
| P00 rollback Step 2 | 254 passed | **300** |
| P01 T2 Step 1 | 301 passed | **310** |
| P01 T2 Step 2 | 35 orchestration tests | **44** |
| P01 T1 Step 2 | 6 files formatted | **7** |

### 1.4 Finding: the live database is at `0004`, not `0003`

`data/leads.db` reports `alembic_version = 0004_orchestration`. Both guides asserted `0003`.

**This is not a defect and not data loss.** All 26 schema checks pass against it: 459 leads,
`max(intent_score)` 164.28, `avg` 42.29 — the fingerprint is exact — and `runs`, `jobs` and
`run_events` are all **empty**, so the migration was applied but never used. It is the state T4
warns can arise from running with `ALEMBIC_DB_URL` unset, and it is equally consistent with a
deliberate operator upgrade.

**Action taken:** documented rather than "fixed". P01-testing.md now carries a
*Which revision should the live database be at?* table treating `0003` and `0004` as both correct,
and explains how to return to `0003` if wanted. **Downgrading a live database is an operator
decision, not one to take unasked.**

---

## 2. Schema Verification Report

**Verdict: the P1 schema is exactly as specified. No schema defect found. No migration was changed.**

`check_schema.py` runs **26 checks** across the eight categories the brief listed:

| Category | Checks | Result |
|---|---|---|
| Tables | 2 | 18 expected present; **no unexpected tables** |
| Indexes | 5 | Column **order** exact, including `ix_jobs_claim = state, available_at, priority, id` |
| Foreign keys | 5 | `ai_calls`/`scrape_runs` `SET NULL`; `jobs`/`run_events` `CASCADE`; `runs` still bare |
| Constraints | 5 | `runs` columns exact and ordered; **no expiry column**; nullability of all three `run_id`-adjacent columns |
| Migration version | 1 | Accepts short (`0004`) or full revision id |
| Alembic head | — | `alembic heads` → exactly one: `0004_orchestration` |
| Expected row counts | 3 | `runs`, `jobs`, `run_events` empty |
| Database integrity | 2 | `PRAGMA integrity_check` + `PRAGMA foreign_key_check` |
| *(legacy fingerprint)* | 3 | 459 leads · max 164.28 · avg 42.29 |

Coverage added beyond what T5 previously checked: **`integrity_check`**, **`foreign_key_check`**,
**no-unexpected-tables**, **column nullability**, **`runs` column order** (not just membership),
**empty-table assertions**, and the **fifth index** `ix_runs_project_state`, which the old T5 Step 3
listed but which had no failure-table entry.

### 2.1 One check was wrong and was corrected — the implementation was right

An early draft asserted `jobs.run_id IS NOT NULL`. It failed. Checking
[`docs/05-database-plan.md`](05-database-plan.md) line 502 — `run_id INTEGER NULL REFERENCES runs(id)
ON DELETE CASCADE` — confirmed the **specification says nullable** and migration `0004` implements it
correctly. The check was an invented requirement and was rewritten to assert the spec: `jobs.run_id`
nullable (a job need not belong to a run), `run_events.run_id` `NOT NULL` (an event always does).

Recorded because it is the failure mode a verification pass is most prone to: a checker asserting
what the author assumed rather than what the specification says.

### 2.2 Migration reversibility re-proved

Executed on a copy of the live 459-lead database, using the new relative URL:

```
upgrade head -> downgrade 0003 -> upgrade head
```

459 leads intact at every stage; 26 checks pass at `0004`; 6 checks pass at `0003`;
`scrape_runs.run_id` and the `ai_calls` FK both removed by the downgrade and restored by the
re-upgrade.

---

## 3. State Machine Verification Report

**Verdict: coverage was strong and is now exhaustive. No state-machine defect found. No transition
was added, removed or changed.**

Pre-existing strengths worth naming: the specification is transcribed **independently** rather than
imported; `test_cascade_actually_deletes` sets `PRAGMA foreign_keys=ON` because asserting a
constraint exists is not asserting it fires; and the no-expiry guarantee is guarded in **both** the
model and the schema, because mutation testing during P1 found a fault in one slipping past a guard
on the other.

### 3.1 Gaps found and closed

| Gap | Fix |
|---|---|
| Rejected transitions were **spot-checked** (3 of 110) | `test_every_unspecified_edge_is_rejected` — all **144** ordered run-state pairs; asserts the accepted set equals the spec exactly, then that every other pair **raises** |
| `JOB_TRANSITIONS` had **no independent spec copy** while `TRANSITIONS` did | `SPEC_JOB_TRANSITIONS` + edge-by-edge equality. This asymmetry was the real hole |
| Job rejections spot-checked | `test_every_unspecified_job_edge_is_rejected` — all **25** pairs |
| No guard against a job state named like a run gate | `test_job_states_never_reach_a_run_gate` |
| `check_schema.py` itself untested | Four tests, including one that **deliberately breaks `ix_jobs_claim` and asserts the checker reports FAIL** — a verifier that passes on a broken database is worse than none |

**+9 tests** (35 → 44 in `tests/test_orchestration.py`).

### 3.2 On "timeout states"

**There are none, and their absence is the design.** A gate that expires proceeds without the human
it exists to wait for, defeating the quality mechanism the pipeline is built on (AD-6). This is
guarded in four places: `test_runs_schema_has_no_expiry_column`, `test_runs_model_has_no_expiry_column`,
`check_schema.py`'s *Constraints* section, and manual steps T5 Step 1 + T6 Step 5.

**No timeout tests were added** — doing so would invent a state the freeze forbids.

**Retry and error states** were already covered and remain so: `FAILED -> PENDING` (full retry),
`RUNNING -> QUEUED` (lease reclamation after a worker dies), `FAILED -> QUEUED` (retry with backoff),
`COMPLETE -> ANALYZING` (re-analyse without re-scraping). `CANCELLED` and `DONE` are final.

---

## 4. Automated Validation

Run after every change, repeated until green.

| Gate | Result |
|---|---|
| `ruff check .` | **All checks passed!** |
| `ruff format --check` (files in scope) | **7 files already formatted** |
| `pytest` (full suite) | **308 passed, 2 skipped, 0 failed** |
| Boundary tests | 18 passed |
| Migration tests | 9 passed |
| Orchestration tests | **44 passed** (was 35) |
| Legacy contract | 459 leads · 164.28 / 42.29 · 13 CSV columns · 17 endpoints |
| Navigation / pages | 31 passed |
| `alembic heads` | exactly one — `0004_orchestration` |
| `check_schema.py` on live DB | **OK — all 26 checks passed** |

### 4.1 The two skips are correct, not a regression

Before this pass the suite reported `310 passed`. It now reports `308 passed, 2 skipped`. **No test
was lost or weakened.** Both skips are the same two tests, which parse a **real proxy credentials
file**:

- `tests/test_net.py::test_real_proxy_file_parses`
- `tests/test_net.py` (proxy pool configured from `config.yaml`)

They previously passed only because a path to one person's machine was hardcoded in the test and in
`config.yaml`. That path could not ship. Both now read `PROXY_FILE`, and **with `PROXY_FILE` set the
file reports `114 passed, 0 skipped`** — verified. Skipping when the environment cannot supply a
credentials file is the correct portable behaviour.

### 4.2 Pre-existing, deliberately untouched

`ruff format --check .` reports 50 files across the whole repository. This predates this pass and
must stay: `src/dashboard/routes.py` and the other legacy modules are excluded in
`pyproject.toml` because reformatting them would risk the **byte-identical `GET /`** guarantee that
is half of the R20 legacy contract. Both guides scope their format checks to specific files for this
reason.

---

## 5. GitHub Readiness Report

### 5.1 Email

**The address flagged in the brief appears nowhere** — not in any file, not in git history, not in
the commit author or committer fields. Verified by a case-insensitive search of the whole tree and a
scan of staged content before committing. It is deliberately not reproduced in this report, since
writing it down here would itself put it in the repository.

The commit is authored `Praveen <kullupraveenkumar@gmail.com>`, an identity set **repo-locally** so
it does not depend on the global git config.

### 5.2 Secrets

| Item | Status |
|---|---|
| `.env` (holds a real `APP_SECRET_KEY`) | **Ignored** — `git check-ignore` confirms |
| API keys / tokens | None. Every `sk-...` in the tree is a test fixture (`sk-test0123456789abcdef`) |
| Proxy credentials | No proxy file in the repo; `*proxies*.txt` ignored |
| `data/*.db`, `-wal`, `-shm`, backups | **Ignored** — confirmed |
| `.venv/`, caches, `*.zip` (9 archives) | **Ignored** — confirmed |
| `.claude/settings.local.json` | **Newly ignored** — it recorded absolute local paths |

Ignore rules were **proved with `git check-ignore -v`**, not reasoned about, and the full 192-file
staged list was reviewed before committing.

### 5.3 Third-party data — anonymised

Three committed files carried real data. Per your decision they were anonymised even though the
repository will be private (defence in depth), preserving everything any test or guide reads.

| File | Was | Now |
|---|---|---|
| `tests/baseline/export_baseline.csv` | 459 real Reddit usernames, post ids, permalinks | 413 synthetic authors (`redditor_0001`), ids (`t3_anon0001`), URLs. **Header, 13 columns, 459 rows, and the 164.28 / 42.29 fingerprint preserved exactly** |
| `tests/baseline/index_baseline.html`, `index_pre_ux.html` | Same leads, rendered | Same mapping applied, plus a regex sweep for residual permalinks and `u/` handles |
| `docs/measurements/p0-transport.json` | 10 purchased proxy `IP:port` endpoints | `proxy-01 … proxy-10`; 11 bare IPs → `ip-01 …`. Still valid JSON |

Verified afterwards: **0** non-anonymised URL slugs, **0** non-anonymised authors, **0** residual
IPs, and the full suite still green. Originals backed up outside the repository.

> **Retained by design:** post **titles** remain, being public post text and the fixture's actual
> reference value. Titles plus subreddit are searchable, so if you want them synthesised too, say so
> — it is a one-command change.

### 5.4 Machine-specific paths removed

`config.yaml` (`proxy.file` → empty, configured via `PROXY_FILE`), `tests/test_net.py`, and seven
occurrences across six documents. `%USERPROFILE%` or `<project root>` substituted; **no prose was
changed**.

---

## 6. Repository Preparation Report

### 6.1 Added

| File | Purpose |
|---|---|
| `LICENSE` | MIT, per your decision |
| `.gitattributes` | `text=auto` — without it a Windows checkout rewrites the tree to CRLF and every other platform sees the whole repo as modified |
| `.github/pull_request_template.md` | Freeze compliance, verification output, migration and secret checklists |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Requires the phase, the guide step quoted, and `check_schema.py` output; forbids pasting credentials |
| `.github/ISSUE_TEMPLATE/architecture_amendment.yml` | Enforces the §11 rule: **a failed measurement, not an argument** |
| `scripts/check_schema.py` | §1.2 |

### 6.2 Updated

- **`README.md`** — badges; the actual one-line product statement; the explicit *no Reddit write
  path* non-goal; a *Verifying the database* section; `scripts/`, `net/`, `orchestration/` and
  `docs/testing/` added to the layout; **Status corrected from the stale "Phase 1 of 8" to "P0 and P1
  complete" against the frozen P0–P30 plan**; a Licence section noting that the tooling is MIT but
  the collected data is not yours to relicense.
- **`pyproject.toml`** — `description` no longer says *"internal tool"*; `license`, `readme`,
  `keywords`, classifiers added.
- **`.env.example`** — `PROXY_FILE` documented properly, including why it is not in `config.yaml`.
- **`.gitignore`** — `.claude/settings.local.json`, `*.log`, `coverage.xml`, `.mypy_cache/`, `.tox/`.
  `.claude/skills/` is **deliberately committed**: it encodes the project's own review and phase-gate
  process.

### 6.3 Suggested repository settings

| Field | Suggestion |
|---|---|
| **Name** | `reddit-lead-finder` — matches `pyproject.toml`; the current folder name `reddit-scraper` understates it and "scraper" reads worse than it is |
| **Description** | *Paste a website URL; get a ranked list of Reddit conversations where people describe the problem it solves. No Reddit API, no OAuth, no account.* |
| **Topics** | `reddit`, `lead-generation`, `python`, `flask`, `sqlite`, `alembic`, `web-scraping`, `self-hosted`, `deepseek`, `llm` |
| **Licence** | MIT ✅ added |
| **Visibility** | **Private**, per your decision |
| **Initial tag** | `v0.1.0-p1` — the version already in `pyproject.toml`, with the phase named. Tag **after** pushing |
| **Discussions** | **Not yet.** Single-operator, private. Freeze §7's logic applies: capability nobody has asked for is a permanent tax. Enable when there is a second participant |
| **Actions** | **Recommended, one workflow only** — `ruff check` + `ruff format --check` + `pytest` on push and PR. It mechanises the gate P00/P01 already require by hand. It needs no secrets, since the suite is fully offline. Deliberately **not** proposed: release automation, coverage upload, matrix builds, dependency bots — none is answering a measured problem. **Not created**, because Actions is outside what you asked me to change; say the word |

### 6.4 Suggested labels

`bug`, `amendment`, `needs-measurement`, `blocked`, `documentation`, `testing`, `migration`,
`security`, plus one per active phase (`P2`, `P3`, …) so the one-phase-at-a-time rule is visible in
the issue list.

### 6.5 Git state

```
branch  main
tree    clean

87ba926  Initial commit: Reddit Lead Finder (P0 and P1 complete)   192 files
<next>   docs: add pre-P2 verification report                      +1 file
```

Author and committer on both: `Praveen <kullupraveenkumar@gmail.com>`.

**Nothing has been pushed. No remote is configured.**

### 6.6 Commands to push, once you have created the empty repository

Create it **empty** — no README, no .gitignore, no licence — or the first push will conflict.

```bash
git remote add origin https://github.com/<your-username>/reddit-lead-finder.git
git push -u origin main

# then, optionally:
git tag -a v0.1.0-p1 -m "P0 and P1 complete: validation sprint, run and job schema"
git push origin v0.1.0-p1
```

---

## 7. Remaining Blockers

**None.**

Two items are **decisions, not blockers** — neither prevents P2:

1. **The live database is at `0004`.** Data verified intact, tables empty. P2 needs `0004` anyway, so
   the practical effect is that a step P2 would have required is already done. Documented in
   P01-testing.md.
2. **Post titles retained** in the anonymised fixtures (§5.3). Acceptable for a private repository;
   one command to change.

Reviewed and found clear: architecture (no freeze violation introduced — no new technology, table,
migration, AI call, dependency or capability), database, testing, documentation, progress records,
manual testing, recovery, implementation plan.

---

## 8. Recommendation

The verification pass found **no defect in the P1 implementation**. Everything changed was either
tooling (`check_schema.py`), test coverage (+9 exhaustive tests), documentation accuracy (stale
counts, machine-specific paths, the `0004` reality), or repository hygiene. **No migration, no state
transition, and no architectural decision was altered.**

> ## P2 is approved for implementation.

Recommended before P2 begins: create the repository, push, and tag `v0.1.0-p1`, so P2 has a
labelled rollback point that is not just a local commit.

---

*P2 was not started. No work beyond P1 was performed.*
