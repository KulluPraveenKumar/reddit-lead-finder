---
name: architecture-reviewer
description: Check a change against the frozen architecture before it merges
version: 1.1.0
---

# Architecture Reviewer

Verifies a change against `docs/ARCHITECTURE_FREEZE.md`. **A violation blocks the phase.**

## When to Use

- Before completing any phase, invoked by `phase-manager`.
- When a change adds a table, a dependency, a technology, an AI call, or a new capability.
- When anyone proposes deviating from the plan.

## Procedure

### 1. Read the freeze

`docs/ARCHITECTURE_FREEZE.md` is the authority. Nothing overrides it except an amendment under §11,
and **an amendment requires a failed measurement, not an argument**.

### 2. Check the twenty architecture rules (§2)

Rules R1–R20. The mechanically checkable ones:

| Rule | Check |
|---|---|
| R1 | No `praw`, `asyncpraw`, `oauth`, `client_secret` anywhere |
| R2 | No `deepseek` outside `src/ai/providers/` |
| R3 | No `src.ai` import in `rules`, `dedupe`, `scoring`, `knowledge`, `feedback`, `discovery/policy.py` |
| R4 | No `hermes` import anywhere in `src/` |
| R5 | No Reddit identifier in `src/net/` |
| R6 | `ConfidenceScorer` is pure Python; no model call in the scoring path |
| R7 | `confidence_reasoning` is rendered by `scoring/explain.py`, never model-written |
| R8 | Web routes write single rows only; the worker is the sole bulk writer |
| R17 | `src/notify/` imports neither `src.ai` nor an agent runtime |
| R20 | Legacy contract intact |

The judgement-based ones — R9 idempotency, R10 gate discipline, R11 audit obligation, R12 origin
guard, R13 version pinning, R14 cache-is-not-state, R15 secrets, R16 untrusted content, R18 egress
policy, R19 overflow-is-an-error — are read against the diff.

### 3. Check the frozen lists

| List | Check |
|---|---|
| §4.1 migration chain | No new revision; no renumbering; one head |
| §5 technology set | No dependency or technology outside the left column; nothing from the right column |
| §6 budgets | No ceiling raised |
| §7 scope limits | Seam tools ≤ the stated first delivery; skills ≤ 15 per namespace |
| §8 non-goals | Nothing on the permanent list is being built |

### 4. Check the decision register

Every AD-1…AD-31 that the change touches. Name the AD number in the finding — *"violates AD-21"* is
actionable; *"seems wrong"* is not.

### 5. Check the execution-mode lock

`docs/EXECUTION_MODE_LOCK.md` §2 closes the planning stage. Block the change if the diff adds a new
architecture document, roadmap, implementation strategy, governance model, ADR, technology
evaluation, framework comparison, testing strategy, or a "v2 / revised / final" copy of a frozen
document — unless a **failed** implementation, measurement or validation is named alongside it.

Execution records are not planning documents and are expected every phase: the manual guide,
completion report, handover and progress record listed in §2.1. An improvement with no failed
measurement behind it belongs in `docs/DEFERRED-IMPROVEMENTS.md`, with its trigger.

### 6. Report

For each finding: the rule or AD number, the file and line, what the change does, and what the rule
requires. Then a verdict: **pass** or **blocked**.

## Pitfalls

- **Accepting "it's just one small dependency".** §5 is a closed list. One addition is an amendment.
- **Accepting a new table because "it's additive".** §4.1 is a closed list of ten revisions.
- **Letting Hermes reach the deterministic core.** R3 and R4 exist because a model in front of a
  hash function destroys the cost argument. Check both fences, not just the one that changed.
- **Approving an "improvement" that reopens a rejected decision.** Redis, Postgres, vector databases,
  learned rankers, Docker, agent-orchestrated pipelines, and automated Reddit engagement are on §8.
  They were each rejected with reasoning; a new idea is not new evidence.
- **Treating a raised ceiling as configuration.** §6 budgets are frozen. Raising one is an amendment.
- **Approving an amendment without a failed measurement.** This is the single most important line in
  this skill. The freeze exists to stop the fifth redesign.

## Verification

- [ ] All twenty rules checked, mechanical ones by command
- [ ] Migration chain unchanged: one head, ten revisions, no renumbering
- [ ] No dependency or technology outside §5
- [ ] No ceiling raised
- [ ] No non-goal being built
- [ ] No prohibited planning document added — `EXECUTION_MODE_LOCK.md` §2
- [ ] Every finding names its rule or AD number, with file and line
- [ ] Verdict stated: pass or blocked
- [ ] If an amendment is proposed, the **failed measurement** is named, dated, and recorded in §11
