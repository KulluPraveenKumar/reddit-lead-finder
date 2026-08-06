---
name: test-gate
description: Run the full automated testing gate and fix every failure
version: 1.0.0
---

# Test Gate

Runs `docs/35-testing-strategy.md` §2 end to end, fixes what it finds, and repeats until clean.

## When to Use

- At the end of every implementation phase, invoked by `phase-manager`.
- Before declaring any code change complete.
- When the user asks to "run the tests" or "check everything".

## Procedure

### 1. Universal checks — all 31 phases, no exceptions

Run in this order. Stop at the first failure, fix it, then restart from check 1 — a later fix can
break an earlier check.

| # | Command | Pass condition |
|---|---|---|
| 1 | `ruff check .` | Clean |
| 2 | `ruff format --check .` | Clean |
| 3 | `mypy src/ --ignore-missing-imports` | No new errors vs the recorded baseline |
| 4 | `pytest tests/unit -q` | All pass |
| 5 | `pytest tests/integration -q` | All pass |
| 6 | Offline guarantee — socket-blocking fixture active | Zero network calls |
| 7 | `pytest --cov=src --cov-fail-under=70` | ≥70%; ≥85% on `src/{ai,net,scoring,knowledge}` |
| 8 | `grep -ri "deepseek" src/ --exclude-dir=ai/providers` | 0 matches |
| 9 | `grep -rn "import.*src\.ai" src/rules/ src/dedupe/ src/scoring/ src/knowledge/ src/feedback/ src/discovery/policy.py` | 0 matches |
| 10 | `grep -rn "import.*hermes" src/` | 0 matches |
| 11 | `grep -ri "reddit\|subreddit\|lead" src/net/` | 0 matches |
| 12 | Migration round-trip on a **copy** of `data/leads.db` | Succeeds; `alembic heads` = 1 |
| 13 | Legacy regression | 459 leads · `intent_score` SHA-256 unchanged · `GET /` byte-identical · 13 CSV columns · 17 endpoints |
| 14 | Secret scan — logs, DB, templates, repo, API responses | 0 matches |
| 15 | Error-path tests | Every typed exception raised and handled |
| 16 | Edge cases | Empty, null, max-length, unicode, malformed |
| 17 | Logging validation | Correlation IDs present when in scope; redaction active |
| 18 | Documentation validation | This phase's doc edits landed; no broken internal link |

### 2. Conditional checks

Add these when the phase touches the area. The phase's row in `docs/35-testing-strategy.md` §6 names
which apply.

API contract · database validation · performance budget · concurrency · retry · cost validation ·
telemetry · memory validation.

### 3. Mutation discipline

For every acceptance criterion printed in **bold** in `docs/34-implementation-plan.md`, and for
checks 6, 8–13:

1. Deliberately break the guarantee in the source.
2. Confirm the test **fails**.
3. Restore the source.
4. Confirm the test passes again.

A test that has never been observed to fail is not evidence. This has already caught two
false-passing tests in this codebase (`docs/PHASE-02-STATUS.md` §7).

### 4. Report

Produce a table: check number, command, result, and — for failures — the exact output. Never
summarise a failure as "some tests failed".

## Pitfalls

- **Weakening an assertion to make it pass.** If the assertion was wrong, say so explicitly, explain
  why, and record it. Silently relaxing a check removes the only evidence the guarantee held.
- **Skipping check 12 because "the migration is simple".** It runs against a copy of the live
  459-lead database precisely because simple migrations are the ones that get shipped untested.
- **Running the gate once and reporting a fix without re-running.** Fixes break other checks.
- **Treating a grep fence as advisory.** They are the architecture's only mechanical enforcement.
- **Accepting a coverage number without checking *which* module is under-covered.** 70% overall can
  hide 0% on the module this phase added.
- **Reporting `pytest` green while the socket-blocking fixture is disabled.** That makes the offline
  guarantee a claim rather than a fact.

## Verification

The gate has passed only when:

- [ ] All 18 universal checks pass **on a single uninterrupted run**
- [ ] Every conditional check for this phase passes
- [ ] Mutation discipline applied and recorded for every bold criterion
- [ ] The report names every command and its result
- [ ] Total gate duration recorded (target < 10 minutes)
