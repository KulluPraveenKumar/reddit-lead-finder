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
