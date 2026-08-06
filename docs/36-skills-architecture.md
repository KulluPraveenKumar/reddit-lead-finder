# 36 — Skills Architecture

> **The skill catalogue and its authority.** Which skills exist, in which of three namespaces, and
> why most of the brief's examples are not skills at all.
>
> Research basis: **agentskills.io** ✅ ([33 §3.1](33-final-review.md)), [19 §4–6](19-hermes-research.md),
> [22](22-hermes-skills.md).

---

## 1. The three namespaces

The brief lists `implementation-planner`, `unit-test-runner`, `reddit-rss`, `deduplication`,
`lead-scoring` and `telegram-notifier` together as "project skills". ▶ **They belong to three
different things**, and conflating them is how a codebase acquires a language model in front of a
hash function.

✅ **agentskills.io confirms one format, three stages:** a skill is a folder with `SKILL.md`
(`name` + `description` minimum), loaded by *Discovery* (name + description only), *Activation*
(full body), *Execution* (bundled files). Claude Code and Hermes are both listed clients — so the
same file format serves two runtimes in two directories.

| # | Namespace | Location | Runtime | Consumed by | Costs tokens? |
|---|---|---|---|---|---|
| **N1** | **Development skills** | `.claude/skills/` | Claude Code | Me, during implementation | Only in a dev session |
| **N2** | **Operator skills** | `hermes-home/skills/` | Hermes | The operator, via Telegram | **Yes — every turn** |
| **N3** | **Runtime modules** | `src/` | Python | The platform itself | **No — never** |

### 1.1 The allocation test

> **Does a language model need to read it in order to act on it?**
>
> - **No, and it runs in production** → N3, a Python module. Not a skill.
> - **Yes, and the operator asks for it** → N2, a Hermes skill.
> - **Yes, and a developer asks for it** → N1, a Claude Code skill.

Applying it to the brief's list:

| Brief example | Namespace | Reality |
|---|---|---|
| `implementation-planner`, `phase-manager`, `migration-manager`, `architecture-reviewer`, `dependency-checker`, `database-reviewer`, `api-reviewer`, `configuration-reviewer` | **N1** | ✅ Genuinely useful. §3 |
| `unit-test-runner`, `integration-test-runner`, `manual-test-generator`, `performance-reviewer`, `regression-reviewer`, `security-reviewer`, `cost-reviewer`, `documentation-reviewer`, `qa-validator` | **N1** | ✅ Mostly. §4 consolidates nine into four |
| `knowledge-search`, `cost-optimizer`, `analytics`, `health-monitor` | **N2** | ✅ Already specified in [22](22-hermes-skills.md) |
| `reply-generator` | **N2** | ✅ As `outreach-draft` — **draft only, human sends** |
| `reddit-discovery`, `reddit-rss`, `reddit-fetch`, `reddit-search`, `reddit-comments`, `reddit-user` | **N3** | ⛔ `src/discovery/`, `src/scrapers/` — proxied HTTP walks, not reasoning |
| `deduplication` | **N3** | ⛔ `src/dedupe/` — sha256, MinHash, vectors. **Paying a model to hash text is the worst trade in the system** |
| `keyword-filter` | **N3** | ⛔ `src/rules/keywords.py` — set membership |
| `lead-scoring` | **N3** | ⛔ `ConfidenceScorer` — arithmetic. [AD-11](03-architecture.md) |
| `intent-analysis` | **N3** | ⛔ `AIService.enrich_batch()` — a *pipeline stage*, batched B=8 behind the gate. As a skill it would be one item per agent loop, ~45× more expensive |
| `telegram-notifier` | **N3** | ⛔ `src/notify/` — **a skill would make every notification cost a model call**; today they cost nothing ([AD-28](ARCHITECTURE_FREEZE.md)) |
| `memory-manager` | **N2, built in** | Hermes' own `memory` tool |
| `scheduler` | **N3** | `src/discovery/policy.py` + `hermes cron`. The *policy* is arithmetic |
| `proxy-manager`, `provider-manager` | **N3** | `src/net/providers/` |
| `logging` | **N3** | `src/obs/logging.py` |

**Nine of twenty-two are skills. Thirteen are Python modules.** ▶ That ratio is the finding, and it
is the same one [22 §7](22-hermes-skills.md) reached independently — restated here because the brief
re-proposed them.

---

## 2. Authoring rules — now with a primary source

✅ From agentskills.io: *"agents load only the name and description of each available skill"* at
discovery; *"Full instructions load only when a task calls for them."*

| # | Rule | Applies to |
|---|---|---|
| **SR1** | **≤15 skills per namespace** | N1, N2 |
| **SR2** | **Description ≤12 words, trigger-shaped** — it is paid at every discovery | N1, N2 |
| **SR3** | **Bodies may be long** — activation is on demand | N1, N2 |
| **SR4** | **A skill never restates data** — no thresholds, weights, or prices in the body | N1, N2 |
| **SR5** | Hermes skills declare `requires_toolsets: [hermes_reddit]` | N2 |
| **SR6** | **A skill never instructs the agent to compute.** Numbers come from tools | N2 |
| **SR7** | **A development skill never edits production code directly** — it reviews, plans, or runs a command | N1 |

▶ SR7 is new and specific to N1. A skill that both decides *and* edits removes the review step that
makes the phase gate meaningful.

### 2.1 Standard structure

```
<namespace>/<skill-name>/
├── SKILL.md          # required: frontmatter + body
├── references/       # optional: long checklists loaded on demand
├── scripts/          # optional: executable helpers
└── templates/        # optional
```

```markdown
---
name: phase-manager
description: Enforce one-phase-at-a-time implementation with its testing gate
version: 1.0.0
---
# Phase Manager
## When to Use
## Procedure
## Pitfalls
## Verification
```

---

## 3. N1 — Development skills (`.claude/skills/`)

**Eight skills.** Each carries the thirteen fields the brief requires.

### 3.1 `phase-manager` ★ the one that matters most

| Field | Value |
|---|---|
| **Purpose** | Enforce the [34 §1](34-implementation-plan.md) workflow: one phase per session, gated |
| **Responsibilities** | Identify the current phase; refuse to start if the predecessor is unapproved; run the phase; invoke the gate; generate the manual guide; stop and wait |
| **Inputs** | Phase number, or "next" |
| **Outputs** | Implemented phase, gate results, manual guide, an explicit stop |
| **Dependencies** | [34](34-implementation-plan.md), [35](35-testing-strategy.md), [ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md) |
| **AI required** | The session itself |
| **Caching** | None |
| **Error handling** | A failed gate blocks the phase; the failure is reported with the exact command and output |
| **Retry** | Fix and re-run the gate until clean; **never** by weakening an assertion |
| **Performance** | n/a |
| **Testing** | A dry run against an already-complete phase must refuse to re-implement it |
| **Cost** | One development session |
| **Metrics** | Phases completed with a passing gate ÷ phases attempted = 1.0 |

### 3.2 `architecture-reviewer`

| Field | Value |
|---|---|
| **Purpose** | Check a diff against [ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md) before it merges |
| **Responsibilities** | Verify R1–R20; verify no new table/dependency/technology outside §4.1/§5; verify AD compliance |
| **Inputs** | A diff or a phase number |
| **Outputs** | Pass, or a list of violations with the rule number |
| **Dependencies** | [ARCHITECTURE_FREEZE](ARCHITECTURE_FREEZE.md), [03 §6](03-architecture.md) |
| **AI required** | Yes — judgement over a diff |
| **Caching** | None |
| **Error handling** | Any violation blocks; **an amendment requires a failed measurement**, never an argument |
| **Retry** | n/a |
| **Testing** | A fixture diff adding `import redis` must be rejected citing §5 |
| **Cost** | ~1 turn |
| **Metrics** | Violations caught before merge |

### 3.3 `migration-manager`

| Field | Value |
|---|---|
| **Purpose** | Author and validate Alembic revisions under M1–M10 |
| **Responsibilities** | Correct intra-revision table order; deferred FKs; tested `downgrade()`; single head; backup before upgrade |
| **Inputs** | Phase number, table list |
| **Outputs** | A revision file; a round-trip test result |
| **Dependencies** | [05 §7](05-database-plan.md), [ARCHITECTURE_FREEZE §4](ARCHITECTURE_FREEZE.md) |
| **AI required** | Yes |
| **Caching** | None |
| **Error handling** | Two heads, a missing `downgrade`, or a failed round-trip blocks the phase |
| **Retry** | Fix and re-run |
| **Testing** | Round-trip on a **copy** of the live DB; 459 rows asserted |
| **Cost** | ~1–2 turns |
| **Metrics** | `alembic heads` = 1, always |

### 3.4–3.8 The remaining five

| Skill | Purpose | Key acceptance |
|---|---|---|
| `implementation-planner` | Turn a phase's Tasks into an ordered file-by-file plan before writing code | Plan names every file in the phase's Files row |
| `dependency-checker` | Verify no dependency outside [ARCHITECTURE_FREEZE §5](ARCHITECTURE_FREEZE.md); run `pip-audit` | A new package not in §5 blocks |
| `database-reviewer` | Verify schema, indexes, FKs and query plans; catch the N+1 and unindexed-hot-query anti-patterns | Every hot query uses its intended index (`EXPLAIN QUERY PLAN`) |
| `api-reviewer` | Verify the 17 legacy endpoints are unchanged and new ones follow the error conventions | Contract replay passes; only additive fields |
| `configuration-reviewer` | Verify every new key is documented in `config.yaml` and `.env.example`; **no secret in either** | 0 secrets in config; 0 undocumented keys |

**All eight share the same fields; the five above are compressed for length. Each is authored with
the full thirteen in its `SKILL.md`.**

---

## 4. N1 — Testing skills

The brief lists nine. ▶ **Four is the right number**, because five of the nine are *checks within a
gate*, not workflows a model needs instructions to perform — `ruff check` does not need a skill.

| Brief's nine | Disposition |
|---|---|
| `unit-test-runner`, `integration-test-runner`, `regression-reviewer`, `performance-reviewer` | **Merged into `test-gate`** — one skill running [35 §2](35-testing-strategy.md) in order |
| `manual-test-generator` | ✅ **Kept** — a genuine authoring task with a template and rules |
| `security-reviewer` | ✅ **Kept** — judgement, not a command |
| `cost-reviewer` | ✅ **Kept** — judgement over `ai_calls` |
| `documentation-reviewer` | ✅ **Kept** — merged with `qa-validator` |
| `qa-validator` | Merged into `documentation-reviewer` as the definition-of-done check |

### 4.1 `test-gate`

| Field | Value |
|---|---|
| **Purpose** | Run [35 §2](35-testing-strategy.md) end to end and fix what it finds |
| **Responsibilities** | 18 universal checks + the phase's conditional ones; **apply mutation discipline to bold criteria**; repeat until clean |
| **Inputs** | Phase number |
| **Outputs** | Pass/fail per check with commands and output |
| **Dependencies** | [35](35-testing-strategy.md) |
| **AI required** | Yes — for fixing, not for running |
| **Caching** | None — a stale pass is worse than no pass |
| **Error handling** | Report the exact failing command and its output; **never weaken an assertion to make it pass** |
| **Retry** | Fix → re-run, unbounded until clean |
| **Performance** | Target < 10 min |
| **Testing** | A deliberately broken guarantee must fail the gate |
| **Cost** | Several turns on failure |
| **Metrics** | Gate duration; first-run pass rate |

### 4.2 `manual-test-generator`

| Field | Value |
|---|---|
| **Purpose** | Produce `docs/testing/PNN-testing.md` a non-developer can execute |
| **Responsibilities** | Apply the [35 §5](35-testing-strategy.md) template; one assertion per step; every step names an observable; **include the rollback test** |
| **Inputs** | Phase number, its acceptance criteria |
| **Outputs** | The guide |
| **Dependencies** | [35 §5](35-testing-strategy.md), [MANUAL-TESTING-PHASE-01](MANUAL-TESTING-PHASE-01.md) as the style reference |
| **AI required** | Yes |
| **Caching** | None |
| **Error handling** | A step that cannot be verified without reading code is rewritten |
| **Retry** | n/a |
| **Testing** | Every acceptance criterion maps to at least one step |
| **Cost** | ~2 turns |
| **Metrics** | Criteria covered ÷ criteria = 1.0; steps with no observable = 0 |

### 4.3–4.4

| Skill | Purpose | Key acceptance |
|---|---|---|
| `security-reviewer` | Secrets, injection, `\|safe`, `pip-audit`, Flask config, no Reddit auth | 0 findings; full-log secret grep clean |
| `documentation-reviewer` | Doc edits landed; no broken internal link; **definition of done complete** | Every [35 §7](35-testing-strategy.md) line checked |

---

## 5. N2 — Operator skills (`hermes-home/skills/`)

Specified in full in [22](22-hermes-skills.md). **Target 13; first delivery 3**
([ARCHITECTURE_FREEZE §7](ARCHITECTURE_FREEZE.md)).

| Skill | Category | First delivery | Phase |
|---|---|---|---|
| `reddit-run-control` | platform | ✅ **P24** | H |
| `quality-analyst` | platform | ✅ **P24** | H |
| `operator-onboarding` | ops | ✅ **P24** | H |
| `lead-triage` | platform | Backlog | — |
| `knowledge-query` | platform | Backlog | — |
| `patterns-analyst` | platform | Backlog | — |
| `cost-analyst` | platform | Backlog | — |
| `outreach-draft` | platform | Backlog — **draft only, never sends** | — |
| `run-diagnosis` | platform | Backlog | — |
| `daily-summary` | reporting | Backlog — **deterministic by default** | — |
| `weekly-summary` | reporting | Backlog | — |
| `monthly-cost-review` | reporting | Backlog | — |
| `notify-policy` | ops | Backlog | — |

**Entry criterion for a backlog skill:** a stated operator need, one at a time. ▶ Every skill's
description is paid on every turn; shipping thirteen to use three is a permanent tax for capability
nobody asked for.

---

## 6. N3 — Runtime modules (not skills)

Recorded so the question does not reopen. Each is a Python module with unit tests, zero token cost,
and a deterministic contract.

| Brief called it | It is |
|---|---|
| `reddit-discovery` | `src/discovery/{watermarks,policy}.py` |
| `reddit-rss` | `src/discovery/feed_parser.py` |
| `reddit-fetch` | `src/reddit_client.py` + `src/net/` |
| `reddit-search` | `src/scrapers/keyword_scraper.py` |
| `reddit-comments` | `src/scrapers/comment_scraper.py` |
| `reddit-user` | `src/scrapers/user_scraper.py` |
| `deduplication` | `src/dedupe/{exact,minhash,semantic,groups}.py` |
| `keyword-filter` | `src/rules/keywords.py` |
| `lead-scoring` | `src/scoring/{prescore,confidence,explain}.py` |
| `intent-analysis` | `AIService.enrich_batch()` — a pipeline stage |
| `telegram-notifier` | `src/notify/` |
| `scheduler` | `src/discovery/policy.py` + `hermes cron` |
| `cost-optimizer` | `src/ai/cost.py` + `PreAIGate` + `AdaptiveBudget` |
| `proxy-manager` / `provider-manager` | `src/net/providers/` + `src/net/policy.py` |
| `analytics` | `src/knowledge/patterns.py` + `src/quality/report.py` |
| `logging` | `src/obs/logging.py` |
| `health-monitor` | `src/dashboard/routes_health.py` |

▶ **The test that settles every one of these:** if it must run when nobody is talking to an agent, it
is not a skill. Discovery polls at 03:00. Dedup runs on every item. Notifications fire on run
completion. None of those has a conversation attached.

---

## 7. Cost

| Namespace | Token cost | When |
|---|---|---|
| **N1** | A development session; not production spend | Only while implementing |
| **N2** | **≤3k discovery + activation, every operator turn** | ~193 invocations/month ≈ **$0.34/month** ([22 §6](22-hermes-skills.md)) |
| **N3** | **$0.00** | Always |

---

## 8. Acceptance criteria

- [ ] **SK1** — Every skill has valid frontmatter: `name`, `description`, `version`
- [ ] **SK2** — **Every description ≤12 words** (SR2), both namespaces
- [ ] **SK3** — **≤15 skills per namespace** (SR1)
- [ ] **SK4** — Every `SKILL.md` has `## When to Use`, `## Procedure`, `## Pitfalls`, `## Verification`
- [ ] **SK5** — No skill body contains a hardcoded threshold, weight, or price (SR4)
- [ ] **SK6** — Every N2 skill declares `requires_toolsets: [hermes_reddit]` (SR5)
- [ ] **SK7** — **No N1 skill edits production code directly** (SR7)
- [ ] **SK8** — Concatenated N2 discovery metadata is within the P0 M-2 ceiling
- [ ] **SK9** — `outreach-draft`'s body carries the no-send clause; **no seam tool can post to Reddit**
- [ ] **SK10** — Nothing in N3 has a `SKILL.md`
