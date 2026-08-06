---
name: manual-test-generator
description: Write a manual testing guide a non-developer can execute
version: 1.0.0
---

# Manual Test Generator

Produces `docs/testing/PNN-testing.md` for a completed phase.

## When to Use

- After the automated gate passes, invoked by `phase-manager`.
- When the user asks for a manual testing guide or a verification checklist.

## Procedure

### 1. Gather

- The phase's **Acceptance Criteria** from `docs/34-implementation-plan.md`
- The phase's **manual guide focus** row from `docs/35-testing-strategy.md` §6
- The phase's **Rollback Plan**
- `docs/MANUAL-TESTING-PHASE-01.md` — the house style; match its voice and structure

### 2. Write

Use the template in `docs/35-testing-strategy.md` §5. Structure:

- Header: time estimate, what the tester needs, whether anything is destructive
- **Before you start** — install, and how to kill a stale server (a stale process on port 5000
  serves old code, which looks exactly like a broken change)
- One `T`-section per acceptance criterion
- A **Rollback verification** section — always
- A **Sign-off** table

For every step include: Step number · Action · Expected result · Possible failure ·
Troubleshooting · Screenshot expected · Logs to verify · Database values to verify ·
API response to verify · Acceptance.

Where a field does not apply, write "none" rather than omitting it — an absent field reads as an
oversight.

### 3. Rules for a good step

| Rule | Why |
|---|---|
| **Quote real output.** Paste the actual line the tester will see | *"Shows the run status"* is unverifiable |
| **One assertion per step** | A failed compound step does not say which half failed |
| **Every step names an observable** — a page, a log line, a SQL result, an API field | Never *"it should work"* |
| **Failures get meanings, not just symptoms** | *"`No package.json found` → You ran npm. This is a Python project"* |
| **Mark destructive steps ⚠️ and state the reversal** | The tester must never be surprised |
| **Give exact commands**, including the working directory | The tester is not a developer |
| **Include the rollback test** | A rollback plan nobody has run is a guess |

### 4. Verify coverage

Every acceptance criterion in the phase maps to at least one `T`-step. Print the mapping table at
the end of the guide so a gap is visible rather than assumed.

## Pitfalls

- **Writing steps that need code reading to verify.** If a tester must open a Python file, the step
  is wrong — rewrite it against something observable.
- **Describing expected output instead of quoting it.** The tester cannot compare against a
  paraphrase.
- **Omitting the rollback section** because the phase "seems safe". Every phase in the plan has a
  rollback; every guide tests it.
- **Assuming the tester knows the project.** They may not know that a stale server is the usual cause
  of a 404 on a route that exists.
- **Compound steps** — "start the app and check the dashboard and confirm 459 leads" is three steps.
- **Missing the legacy contract.** Every guide ends by confirming 459 leads and 13 CSV columns.

## Verification

- [ ] Every acceptance criterion maps to ≥1 step, shown in a mapping table
- [ ] Every step names an observable
- [ ] No step requires reading source code
- [ ] Every command is exact and includes its directory
- [ ] Destructive steps marked ⚠️ with their reversal
- [ ] Rollback verification section present and executable
- [ ] Legacy contract checked: 459 leads, 13 CSV columns, `GET /` renders
- [ ] Sign-off table present
