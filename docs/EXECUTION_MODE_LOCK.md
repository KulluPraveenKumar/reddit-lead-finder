# EXECUTION MODE LOCK

**Locked: 2026-08-06** · Governs *process*. [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) governs
*constraints*.

> As of this date the project leaves **Research Mode** permanently and enters **Execution Mode**.
>
> The architecture is frozen. The roadmap is frozen. The technology set is frozen. **The planning
> stage is finished.** Every remaining improvement comes from implementation quality, not from new
> ideas.
>
> **This is the last planning document.** It is terminal by design: it exists to stop documents like
> itself from being written again.

---

## 1. What changed, and what did not

| | Research Mode (until 2026-08-05) | Execution Mode (from 2026-08-06) |
|---|---|---|
| Output of a session | A document | A shipped, tested, pushed phase |
| A better idea | Was worth writing down | Goes to [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) with its trigger, or nowhere |
| Architecture change | An argument could carry it | Only a **failed measurement** ([freeze §11](ARCHITECTURE_FREEZE.md)) |
| Success measured by | Depth of analysis | Phases complete · tests passing · clean history · stable releases |

**Nothing in the freeze is restated here.** The 20 architecture rules, 31 decisions, 10 migration
rules, technology set, budgets, non-goals and 18 risks live in
[ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) and are read from there, never copied. A copy is a
second source of truth, and this repository has already been bitten twice by frozen documents
disagreeing with each other ([freeze §11.1](ARCHITECTURE_FREEZE.md)).

---

## 2. What may no longer be created

**Prohibited from this date**, unless a failed implementation, a failed measurement or a failed
validation proves an existing decision incorrect:

| Not to be created | Where the need goes instead |
|---|---|
| A new architecture document | [freeze §11](ARCHITECTURE_FREEZE.md) amendment, with the measurement that forced it |
| A new roadmap or implementation strategy | [34-implementation-plan.md](34-implementation-plan.md) is the plan. There is no other |
| A new governance or process model | This document. Amend it under §10, do not replace it |
| A new ADR | AD-1…AD-31 are closed. A 32nd requires an amendment |
| A new technology evaluation or framework comparison | [freeze §5](ARCHITECTURE_FREEZE.md) is closed |
| A new testing strategy | [35-testing-strategy.md](35-testing-strategy.md) is the gate |
| A "v2", "revised", "final" or "improved" copy of any frozen document | Edit the original, or record the reconciliation in [freeze §11.1](ARCHITECTURE_FREEZE.md) |

**A better idea is not sufficient reason.** If the idea survives contact with the current phase, it
belongs in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) with the evidence that would justify
building it.

### 2.1 What is still written every phase

These are **execution records**, not planning documents, and each phase produces its own:

| Artefact | Canonical path |
|---|---|
| Manual testing guide | `docs/testing/PNN-testing.md` |
| Phase completion report | `docs/PHASE-NN-COMPLETION-REPORT.md` |
| Phase handover | `docs/PHASE-NN-HANDOVER.md` |
| Progress / resume record | `docs/progress/PNN-COMPLETE.md` |

`NN` is the frozen phase number, zero-padded to two digits (`P2` → `02`). Worked exemplars, to be
followed rather than re-invented: [PHASE-01-COMPLETION-REPORT.md](PHASE-01-COMPLETION-REPORT.md) ·
[PHASE-01-HANDOVER.md](PHASE-01-HANDOVER.md) · [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md) ·
[testing/P01-testing.md](testing/P01-testing.md). **There is no separate template**, deliberately: a
template drifts from the exemplar and becomes a second source of truth.

Each answers a different question, and none of the four is optional:

| Artefact | Answers |
|---|---|
| Manual guide | *Can a non-developer verify this works?* — executed and **signed** by a human |
| Completion report | *What was built, and what is the evidence?* — backward-looking |
| Handover | *What must the next phase know, and what traps wait in it?* — forward-looking |
| Progress record | *If this session is lost, where does the next one resume?* |

> ⚠️ **Two unrelated phase numberings live in `docs/`.** **P0–P30** is the frozen plan
> ([34](34-implementation-plan.md)) and is the only active scheme. **"Phase 01"–"Phase 08"**
> ([11](11-phase-01.md)…[18](18-phase-08.md), [PHASE-01-STATUS.md](PHASE-01-STATUS.md),
> [PHASE-02-STATUS.md](PHASE-02-STATUS.md), `docs/testing/phase-0N-testing.md` in lower case) is the
> **superseded** scheme, completed 2026-07-30/31. Those files are **historical records: read-only,
> never extended, never renumbered.** `PHASE-01-STATUS.md` and `PHASE-01-COMPLETION-REPORT.md` are
> about different phases.

---

## 3. The session workflow

**Every future session follows exactly this sequence.** The `phase-manager` skill
(`.claude/skills/phase-manager/SKILL.md`) is the executable form of it and must be loaded before the
first edit under `src/`.

| # | Step | Done when |
|---|---|---|
| 1 | **Read the current phase** — [34](34-implementation-plan.md), all thirteen fields | Objective, Deliverables, Files, DB, Acceptance Criteria restated |
| 2 | **Review the previous handover** — `docs/PHASE-NN-HANDOVER.md` | Its entry conditions are checked, its traps are known |
| 3 | **Verify repository health** | `git status` clean · suite green · `alembic heads` = 1 · `check_schema.py` OK |
| 4 | **Implement ONE phase only** | Every file in the phase's **Files** row, and nothing outside it |
| 5 | **Run automated testing** | `test-gate` skill — [35 §2](35-testing-strategy.md) |
| 6 | **Fix issues** | Root cause fixed, never an assertion weakened |
| 7 | **Run automated testing again** | Clean on a single uninterrupted run |
| 8 | **Generate / update the manual guide** | `docs/testing/PNN-testing.md`, with a sign-off table |
| 9 | **Generate the Phase Completion Report** | `docs/PHASE-NN-COMPLETION-REPORT.md` |
| 10 | **Generate the Phase Handover** | `docs/PHASE-NN-HANDOVER.md` |
| 11 | **Update documentation and progress** | The phase's **Docs** field landed; `docs/progress/PNN-COMPLETE.md`, ending in a resume point; `docs/README.md` execution table |
| 12 | **Repository Hygiene Review** — §5 | Every staged file reviewed and justified |
| 13 | **Commit** | §6 |
| 14 | **Push** | `git push origin main` |
| 15 | **Tag, when applicable** — §6.2 | Tag pushed |
| 16 | **STOP** | Report delivered; **waiting for explicit approval** |

**Claude must never automatically continue into the next phase.** Not when the next phase is small,
not when it is obviously next, not when the current one finished early. The gate between phases is
the quality mechanism, not overhead.

---

## 4. Phase discipline

Each phase behaves like a production release. **A phase is complete only when every line below is
true.** If a line is not true, the phase is not done — say which, and why.

- [ ] Implementation complete — every deliverable in the phase's row
- [ ] Automated tests passing — the full [35 §2](35-testing-strategy.md) gate, one clean run
- [ ] Mutation discipline applied to every **bold** acceptance criterion
- [ ] Manual testing guide updated
- [ ] **Manual testing completed and signed off by a human**
- [ ] Documentation updated — the phase's **Docs** field
- [ ] Progress updated — `docs/progress/PNN-COMPLETE.md`
- [ ] Rollback **executed and verified**, not merely documented
- [ ] Repository hygiene reviewed — §5
- [ ] Git committed
- [ ] Git pushed
- [ ] Git tagged, when applicable — §6.2
- [ ] No unresolved blockers

Only then may the next phase begin — **after explicit approval.**

### 4.1 Partial delivery

If part of a phase is blocked, **finish every other part in full** and state precisely what was left
and why. Scaling a phase down is the operator's decision, never Claude's. Silent narrowing is the
failure mode this rule exists to prevent.

---

## 5. Repository Hygiene Review

**This repository is public.** Every phase performs this review on the **staged** changes, before the
commit, not at release time.

### 5.1 The checklist

| # | Check | How |
|---|---|---|
| H1 | No secrets, API keys, credentials or tokens | Review `git diff --cached` in full; search it for `sk-`, `api_key`, `password`, `secret`, `token`, `BEGIN .* PRIVATE KEY` |
| H2 | No personal information — real usernames, emails, permalinks, IP addresses | Fixtures under `tests/baseline/` and `docs/measurements/` are **anonymised**; keep them so |
| H3 | No machine-specific paths | Search the staged diff for `C:\Users\`, `/home/`, `/Users/`. Use `%USERPROFILE%` or `<project root>` |
| H4 | No temporary files, debug artefacts or scratch scripts | `git status --short` shows nothing unexpected, tracked or untracked |
| H5 | No local databases | `data/*.db`, `-wal`, `-shm`, `data/backups/` — all ignored; prove it, do not assume it |
| H6 | No unnecessary generated files | No `__pycache__/`, `*.log`, `coverage.xml`, `*.zip`, `.venv/`, cache directories |
| H7 | The ignore rules actually fire | `git check-ignore -v <path>` — **proved, not reasoned about** |
| H8 | Every staged file is intentional | Read the file list. A file you cannot justify is a file that does not ship |

### 5.2 The commands

```powershell
git status --short                       # H4 — nothing unexpected, tracked or untracked
git diff --cached --stat                 # H8 — read the whole list
git diff --cached | Select-String -Pattern 'sk-|api[_-]?key|password|secret|token|PRIVATE KEY' -CaseSensitive:$false
git diff --cached | Select-String -Pattern 'C:\\Users\\|/home/|/Users/'
git check-ignore -v .env data/leads.db   # H7 — must print the rule that ignores each
```

**If anything sensitive or unnecessary is found, remove it before committing.** A secret that reaches
a public commit is not fixed by a later commit — it is fixed by rotating the credential.

### 5.3 Standing exception

The commit author identity (`Praveen <…@gmail.com>`) is in the published history and is **not** a
finding. Rewriting pushed history to remove it would cost more than it buys, and a commit author is
ordinary for a public repository.

---

## 6. Git discipline

### 6.1 Commits

- One phase, one logical commit set. Never mix a phase's code with an unrelated cleanup.
- Subject line: `<type>(PNN): <what changed>` — e.g. `feat(P2): job queue, worker, structured logging`.
  Types: `feat`, `fix`, `test`, `docs`, `chore`, `refactor`.
- Never `--no-verify`. Never bypass signing.
- Commit only after §5 and after the gate is green.

### 6.2 Tags

Tag when a phase is **signed off**, using `v<the version currently in pyproject.toml>-pNN` — the
existing convention, set by `v0.1.0-p1`. The `-pNN` suffix makes the tag unique, so **bumping the
version is not part of the phase workflow**; it is an operator action, and the tag simply follows
whatever `pyproject.toml` says at that commit. The tag is the labelled rollback point the next phase
falls back to.

```bash
git tag -a v0.1.0-p2 -m "P2 complete: job queue, worker, structured logging"
git push origin v0.1.0-p2
```

**Do not tag** a phase whose manual sign-off table is unsigned — the tag would claim a verification
that did not happen.

---

## 7. Engineering priorities

Ranked. **A change must never compromise something higher in this list to serve something lower.**

| # | Priority | The rule it generates |
|---|---|---|
| 1 | **Correctness** | A wrong answer delivered fast is a defect, not a trade-off |
| 2 | **Testability** | Untestable code is unfinished code. New modules ship with their tests in the same change |
| 3 | **Maintainability** | Match the surrounding code's idiom — naming, structure, comment density |
| 4 | **Documentation** | A phase whose documentation has not landed is not complete |
| 5 | **Performance** | Optimise only against a measured budget the phase states |
| 6 | **Cost** | Within the ceilings in [freeze §6](ARCHITECTURE_FREEZE.md). Unmeasured cost optimisation is indistinguishable from quality loss |
| 7 | **Developer experience** | Last. Never a reason to add a technology, a build step or an abstraction |

---

## 8. Continuous improvement rule

A small improvement discovered mid-phase may be made **only if all four hold**:

1. It directly relates to the current phase.
2. It does not expand scope.
3. It does not redesign architecture.
4. It does not delay delivery significantly.

**Otherwise it is recorded in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md), with the trigger
that would justify building it, and the current phase continues.** The register is not a backlog to
be worked through; it is where an idea waits for evidence.

---

## 9. Success criteria

| Success is **not** | Success **is** |
|---|---|
| Number of architecture documents | Phases completed, in order, each signed off |
| Number of research documents | A green gate on a single uninterrupted run |
| Number of design improvements | A clean, linear, pushed Git history with tagged phases |
| Number of new ideas | Repeatable deployments and executed rollbacks |
| A more elegant design | Documentation a non-developer can execute |
| | **A production-ready application** |

The process should now be **mechanical, predictable, repeatable and measurable.** A session that
produced insight but no shipped, tested, pushed phase produced nothing.

---

## 10. Amending this document

This document may be amended when a **failed implementation, measurement or validation** shows a
process step to be wrong — the same standard as [freeze §11](ARCHITECTURE_FREEZE.md), applied to
process rather than architecture. Amendments are recorded below with the failure that forced them.

| Date | What failed | Step replaced | Replacement | Phase |
|---|---|---|---|---|
| — | — | — | — | — |

---

## 11. The lock statement

> As of **2026-08-06**, planning is **finished**.
>
> Research, architecture redesign, workflow redesign and governance redesign **stop here** — and
> resume only when a measurable implementation problem proves an existing decision incorrect.
>
> Every future session builds, tests, documents and releases **one phase at a time**, and then
> **stops and waits for approval.**
>
> The next action is **P2 — job queue, worker, structured logging**, and it does not begin until it
> is approved.
