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
| **DI2** | **GitHub Actions CI** — one workflow: `ruff check` · `ruff format --check` · `pytest`, on push and PR. No secrets needed; the suite is offline | A phase reaches `main` with a gate failure the local run would have caught. Proposed in [PRE-P2 §6.3](PRE-P2-VERIFICATION-REPORT.md) and **not** built, because nothing has yet failed that it would have caught | 2026-08-06 |
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
| **O1** | **Post titles in `tests/baseline/` were retained when the repository was going to be private.** It is now public. Authors, post ids and permalinks are anonymised; titles are not, and a title plus its subreddit is searchable — which re-identifies the 413 authors the anonymisation protected | [PRE-P2 §5.3](PRE-P2-VERIFICATION-REPORT.md) justified retention with *"acceptable for a private repository"*. That premise no longer holds | One command. Titles are the fixture's reference value but nothing asserts their **content** — the 459-row / 13-column / 164.28 / 42.29 fingerprint is what the suite pins |
| **O2** | **`mypy` is required by [35 §2](35-testing-strategy.md) check 3 and [freeze §5](ARCHITECTURE_FREEZE.md), and is not installed** (blocker **B3**, still open) | The gate cannot be claimed in full until it runs. Verified absent 2026-08-06 | `python -m pip install mypy`, then record the baseline error count so check 3 has something to compare against |
| **O3** | **P00 and P01 manual sign-off tables are unsigned** (blocker **D1** in [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md)) | [PHASE-01-HANDOVER.md §8](PHASE-01-HANDOVER.md) makes this the entry condition for P2. **This is the one gate standing between here and P2** | ~20 minutes each, non-destructive, by a non-developer |

---

## 3. Rules for this file

1. **Every entry names a trigger.** No trigger, no entry.
2. **An entry is removed only when it is built, or when its trigger is proved impossible** — with a
   line saying which.
3. **Nothing here is scheduled.** Being in this file confers no claim on a future phase.
4. **Architecture changes do not belong here.** They belong in
   [freeze §11](ARCHITECTURE_FREEZE.md), and they require a failed measurement.
