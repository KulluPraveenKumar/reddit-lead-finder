---
name: phase-manager
description: Enforce one-phase-at-a-time implementation with its testing gate
version: 1.0.0
---

# Phase Manager

The single entry point for implementing this project. **Nothing is implemented outside this
workflow.**

## When to Use

- The user says "implement the next phase", "start P7", "continue implementation", or similar.
- Any session that will write production code for this project.
- **Always invoke this before writing the first line of code.** If you are about to edit a file
  under `src/` and this skill has not been loaded, stop and load it.

## Procedure

### 1. Establish where we are

Read, in this order:
1. `docs/ARCHITECTURE_FREEZE.md` — the binding constraints
2. `docs/34-implementation-plan.md` — locate the phase
3. `docs/35-testing-strategy.md` §2 — the gate you will have to pass

Then determine the current phase:
- Check `docs/testing/` for the highest `PNN-testing.md` that exists and is signed off.
- The next phase is `PNN+1`.

**Refuse to proceed if:**
- The previous phase's manual guide does not exist → it was never generated.
- The previous phase's manual guide has an unsigned sign-off table → it was never approved.
- The user asks for a phase that is not `previous + 1` → say which phase is next and why.

State plainly: *"Phase PNN is next. Phase PNN-1 was signed off on <date>."*

### 2. Read the phase specification

From `docs/34-implementation-plan.md`, extract all thirteen fields. Restate to the user, in under
ten lines: the Objective, the Deliverables, the migration (if any), the Risk level, and the
Estimated Time.

**Do not begin until you have read every field.** The Acceptance Criteria in particular determine
what you build; discovering them after implementation causes rework.

### 3. Plan before editing

Produce an ordered file-by-file plan covering every file in the phase's **Files** row. If a file is
needed that the row does not name, say so — the plan may be incomplete, or the phase may be creeping.

### 4. Implement

- **One phase only.** Never start the next one, even if it is small, even if it is obviously next.
- Every new module is created with its tests in the same change.
- Follow the surrounding code's idiom: match its comment density, naming, and structure.
- Configuration goes in `config.yaml`; secrets go in `.env`; **never the reverse**.

### 5. Run the gate

Invoke the `test-gate` skill. It runs `docs/35-testing-strategy.md` §2 and repeats until clean.

**Do not proceed on a failing check.** Do not weaken an assertion to make it pass — if an assertion
was genuinely wrong, that is an amendment and it needs its reasoning recorded.

### 6. Generate the manual guide

Invoke the `manual-test-generator` skill. Output goes to `docs/testing/PNN-testing.md`.

### 7. Land the documentation

Apply the documentation edits the phase's **Docs** field owns. A phase whose documentation has not
landed is not complete.

### 8. Stop

Report:
- What was built
- Gate results, per check
- Where the manual guide is
- What the rollback command is
- **That you are waiting for approval before Phase PNN+1**

**Then stop.** Do not begin the next phase in the same session under any circumstance.

## Pitfalls

- **Implementing two phases because the first was small.** The gate between them is the quality
  mechanism, not overhead. Two half-tested phases are worse than one tested one.
- **Skipping the manual guide because the automated tests pass.** Automated tests do not catch a page
  that renders wrong, a notification that never arrives, or a number that is confidently incorrect.
- **Adding a table, dependency, or technology not in `ARCHITECTURE_FREEZE.md` §4.1/§5.** That is an
  amendment. Amendments require a *failed measurement*, not a good argument.
- **Renumbering a migration.** Rule M2. Never.
- **Marking a phase done with a failing grep fence.** The four fences are the only mechanical
  enforcement this architecture has.
- **Fixing a failing test by editing the assertion.** If the assertion is wrong, say so explicitly and
  record why.
- **Silently narrowing scope.** If part of a phase turns out to be blocked, finish everything else and
  state precisely what was left and why.

## Verification

Before reporting a phase complete, confirm every line of `docs/35-testing-strategy.md` §7:

- [ ] Code implemented
- [ ] `make gate` passes — 18 universal checks plus the phase's conditional ones
- [ ] Mutation discipline applied to every **bold** acceptance criterion
- [ ] Documentation edits landed
- [ ] `docs/testing/PNN-testing.md` generated
- [ ] Performance within the phase's stated budget
- [ ] Cost within the phase's stated bound
- [ ] Logging verified — correlation IDs present, redaction active
- [ ] Error handling verified
- [ ] **Rollback executed and verified**, not merely documented
- [ ] Legacy contract intact: 459 leads · `intent_score` unchanged · `GET /` byte-identical ·
      13 CSV columns · 17 endpoints identical

If any line is unchecked, the phase is not done. Say which, and why.
