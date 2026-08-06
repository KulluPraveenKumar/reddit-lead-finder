---
name: phase-manager
description: Enforce one-phase-at-a-time implementation with its testing gate
version: 2.0.0
---

# Phase Manager

The single entry point for implementing this project. **Nothing is implemented outside this
workflow.**

The project is in **Execution Mode** (`docs/EXECUTION_MODE_LOCK.md`). Planning is finished. Do not
write a new architecture document, roadmap, strategy, governance model, ADR or technology comparison.
A better idea goes to `docs/DEFERRED-IMPROVEMENTS.md` with its trigger; the current phase continues.

## When to Use

- The user says "implement the next phase", "start P7", "continue implementation", or similar.
- Any session that will write production code for this project.
- **Always invoke this before writing the first line of code.** If you are about to edit a file
  under `src/` and this skill has not been loaded, stop and load it.

## Procedure

Sixteen steps, in this order. None is optional.

### 1. Establish where we are

Read, in this order:
1. `docs/ARCHITECTURE_FREEZE.md` — the binding constraints
2. `docs/EXECUTION_MODE_LOCK.md` — the process this skill executes
3. `docs/34-implementation-plan.md` — locate the phase
4. `docs/35-testing-strategy.md` §2 — the gate you will have to pass

Then determine the current phase:
- Check `docs/testing/` for the highest `PNN-testing.md` that exists and is signed off.
- The next phase is `PNN+1`.

**Refuse to proceed if:**
- The previous phase's manual guide does not exist → it was never generated.
- The previous phase's manual guide has an unsigned sign-off table → it was never approved.
- The user asks for a phase that is not `previous + 1` → say which phase is next and why.

State plainly: *"Phase PNN is next. Phase PNN-1 was signed off on <date>."*

### 2. Review the previous handover

Read `docs/PHASE-NN-HANDOVER.md` for the phase before this one, in full. It exists so you do not
re-derive the previous phase's decisions from the diff.

Extract and restate: its **entry conditions** (which must all be met), its **guarantees you must not
break**, and its **traps**. Then read `docs/DEFERRED-IMPROVEMENTS.md` — an entry may have become
relevant to this phase.

**If an entry condition is unmet, stop and say so.** That is the gate working.

### 3. Verify repository health

Before the first edit. Run and report each:

```powershell
git status --short                                  # clean
.\.venv\Scripts\python.exe -m ruff check .          # clean
.\.venv\Scripts\python.exe -m pytest                # all pass; record the count
.\.venv\Scripts\python.exe -m alembic heads         # exactly one head
.\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db
```

A dirty tree, a red suite or two heads is fixed **before** the phase starts, never during it —
otherwise you cannot tell which failure this phase caused.

### 4. Read the phase specification

From `docs/34-implementation-plan.md`, extract all thirteen fields. Restate to the user, in under
ten lines: the Objective, the Deliverables, the migration (if any), the Risk level, and the
Estimated Time.

**Do not begin until you have read every field.** The Acceptance Criteria in particular determine
what you build; discovering them after implementation causes rework.

### 5. Plan before editing

Produce an ordered file-by-file plan covering every file in the phase's **Files** row. If a file is
needed that the row does not name, say so — the plan may be incomplete, or the phase may be creeping.

### 6. Implement

- **One phase only.** Never start the next one, even if it is small, even if it is obviously next.
- Every new module is created with its tests in the same change.
- Follow the surrounding code's idiom: match its comment density, naming, and structure.
- Configuration goes in `config.yaml`; secrets go in `.env`; **never the reverse**.

### 7. Run automated testing

Invoke the `test-gate` skill. It runs `docs/35-testing-strategy.md` §2 and repeats until clean.

Then invoke the `architecture-reviewer` skill against the phase's diff. **A freeze violation blocks
the phase** — it is not a finding to note and move past.

### 8. Fix issues

Fix the **root cause**. Do not weaken an assertion to make it pass — if an assertion was genuinely
wrong, say so explicitly and record why it was wrong.

### 9. Run automated testing again

The gate has passed only on a **single uninterrupted clean run**. Fixes break other checks; a gate
run before the last fix proves nothing.

### 10. Generate the manual testing guide

Invoke the `manual-test-generator` skill. Output goes to `docs/testing/PNN-testing.md`, including a
sign-off table.

### 11. Generate the Phase Completion Report

`docs/PHASE-NN-COMPLETION-REPORT.md` (`NN` zero-padded — `P2` → `02`). Backward-looking: what was
built, and the evidence. Follow the exemplar `docs/PHASE-01-COMPLETION-REPORT.md`. **There is no
template file** — a template drifts from the exemplar and becomes a second source of truth.

### 12. Generate the Phase Handover

`docs/PHASE-NN-HANDOVER.md`. Forward-looking, per the exemplar `docs/PHASE-01-HANDOVER.md`: what now
exists · the guarantees the next phase must not break · what this phase deliberately did **not** do ·
the traps waiting in the next phase · a verification snapshot · blockers carried forward · the next
phase's entry conditions.

### 13. Land the documentation and the progress record

- Apply the documentation edits the phase's **Docs** field owns.
- Write `docs/progress/PNN-COMPLETE.md`, ending in a **resume point** — it is what an interrupted
  session recovers from.
- Update the execution table in `docs/README.md`.

A phase whose documentation has not landed is not complete.

### 14. Repository Hygiene Review — this repository is public

Stage the changes, then work `docs/EXECUTION_MODE_LOCK.md` §5 (H1–H8) against the **staged diff**:

```powershell
git status --short                       # nothing unexpected, tracked or untracked
git diff --cached --stat                 # read the whole list; justify every file
git diff --cached | Select-String -Pattern 'sk-|api[_-]?key|password|secret|token|PRIVATE KEY' -CaseSensitive:$false
git diff --cached | Select-String -Pattern 'C:\\Users\\|/home/|/Users/'
git check-ignore -v .env data/leads.db   # must print the rule that ignores each
```

**Remove anything sensitive or unnecessary before committing.** A secret that reaches a public commit
is not fixed by a later commit — it is fixed by rotating the credential.

### 15. Commit, push, tag

- Commit: `<type>(PNN): <what changed>` — e.g. `feat(P2): job queue, worker, structured logging`.
  Never `--no-verify`.
- Push: `git push origin main`.
- Tag **only when the phase's manual sign-off table is signed**: `v<pyproject version>-pNN`, per
  `docs/EXECUTION_MODE_LOCK.md` §6.2. Push the tag.

### 16. Stop

Report:
- What was built
- Gate results, per check
- Where the manual guide is
- What the rollback command is
- The commit, the push, and the tag (or why no tag)
- **That you are waiting for approval before Phase PNN+1**

**Then stop.** Do not begin the next phase in the same session under any circumstance.

## Pitfalls

- **Implementing two phases because the first was small.** The gate between them is the quality
  mechanism, not overhead. Two half-tested phases are worse than one tested one.
- **Skipping the manual guide because the automated tests pass.** Automated tests do not catch a page
  that renders wrong, a notification that never arrives, or a number that is confidently incorrect.
- **Adding a table, dependency, or technology not in `ARCHITECTURE_FREEZE.md` §4.1/§5.** That is an
  amendment. Amendments require a *failed measurement*, not a good argument.
- **Writing a new planning document.** Execution Mode forbids it. The improvement goes in
  `docs/DEFERRED-IMPROVEMENTS.md` with its trigger.
- **Renumbering a migration.** Rule M2. Never.
- **Marking a phase done with a failing grep fence.** The four fences are the only mechanical
  enforcement this architecture has.
- **Fixing a failing test by editing the assertion.** If the assertion is wrong, say so explicitly and
  record why.
- **Committing without reading the staged file list.** The repository is public. A `.db`, a `.log`, a
  scratch script or an absolute path is one `git add .` away.
- **Tagging a phase whose sign-off table is blank.** The tag would claim a verification that did not
  happen.
- **Silently narrowing scope.** If part of a phase is blocked, finish everything else and state
  precisely what was left and why.

## Verification

Before reporting a phase complete, confirm every line of `docs/EXECUTION_MODE_LOCK.md` §4, which is
`docs/35-testing-strategy.md` §7 plus the release steps:

- [ ] Code implemented — every deliverable in the phase's row
- [ ] The full gate passes — 18 universal checks plus the phase's conditional ones — on one clean run
- [ ] Mutation discipline applied to every **bold** acceptance criterion
- [ ] Documentation edits landed
- [ ] `docs/testing/PNN-testing.md` generated, with a sign-off table
- [ ] `docs/PHASE-NN-COMPLETION-REPORT.md` written
- [ ] `docs/PHASE-NN-HANDOVER.md` written
- [ ] `docs/progress/PNN-COMPLETE.md` written, ending in a resume point
- [ ] Performance within the phase's stated budget
- [ ] Cost within the phase's stated bound
- [ ] Logging verified — correlation IDs present, redaction active
- [ ] Error handling verified
- [ ] **Rollback executed and verified**, not merely documented
- [ ] Repository hygiene reviewed — H1–H8 against the staged diff
- [ ] Committed · pushed · tagged when applicable
- [ ] Legacy contract intact: 459 leads · `intent_score` unchanged · `GET /` byte-identical ·
      13 CSV columns · 17 endpoints identical
- [ ] No unresolved blockers

If any line is unchecked, the phase is not done. Say which, and why.
