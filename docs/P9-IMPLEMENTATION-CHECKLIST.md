# P9 IMPLEMENTATION CHECKLIST — Rule engine

**Written:** 2026-08-13 · **Revision:** none — P9 adds no migration · **Days / Risk:** 2 · Low
**Status:** not started. **Awaiting operator approval of this document and
[docs/testing/P09-testing.md](testing/P09-testing.md).**

> ✅ **All six decisions are settled** — [D1](P9-DECISION-ANALYSIS.md) Option B,
> [D2](P9-DECISION-ANALYSIS.md) Option B, [D3](P9-DECISION-ANALYSIS.md) Option A,
> [D4](P9-DECISION-ANALYSIS.md) Option C, [D5](P9-DECISION-ANALYSIS.md) Option A,
> [D6](P9-DECISION-ANALYSIS.md) Option B. Approved by the operator 2026-08-13.
>
> ⛔ **No production code may be written until this checklist and the testing guide are approved.**

Seven stages. **The gate is run at the end of every stage, not only at the end of the phase**
([lock §3](EXECUTION_MODE_LOCK.md) steps 5–7). CI must be green after each commit, and work stops for
a report after each one.

| Stage | What lands | Commit type |
|---|---|---|
| [0](#stage-0) | Pre-flight — nothing is written | — |
| [1](#stage-1) | **The R3 fence, before the package it constrains** | `test(P9)` |
| [2](#stage-2) | `src/rules/` — `RuleResult`, keywords, structural, authors | `feat(P9)` |
| [3](#stage-3) | `competitors.py`, the `EntityRegistry` protocol, the inertness guard | `feat(P9)` |
| [4](#stage-4) | The config block, `pipeline.rules_enabled`, the demo, **the executed rollback** | `feat(P9)` |
| [5](#stage-5) | Property, performance and mutation evidence | `test(P9)` |
| [6](#stage-6) | The two flaky-test fixes — D6 | `fix(P9)` |
| [7](#stage-7) | Documentation, reconciliations, DI20 · DI23 · DI24 | `docs(P9)` |

---

<a id="stage-0"></a>
## Stage 0 — Pre-flight gate

Nothing is written in this stage. Every line is a check.

- [ ] **0.1** Load the `phase-manager` skill — [lock §3](EXECUTION_MODE_LOCK.md) requires it before
      the first edit under `src/`
- [ ] **0.2** `git status --short` → only this session's new documents, no modified files
      ✅ **`config.yaml` was reverted 2026-08-13, this session.** P7's live Telegram values
      (`enabled: true`, `transport: bot_api`, a real chat id) are gone from the working tree.
      **Leave `.env` alone** — it is git-ignored and the token is worth keeping.
      ⚠️ **This is the second consecutive phase to find that file dirty.** If it is dirty again,
      `git checkout -- config.yaml` before anything else, and **never commit it** — R15
- [ ] **0.3** `git rev-parse HEAD` == `git rev-parse origin/main`
      Verified 2026-08-13: both `1ef3bbaf1a0310a5181c2e0e506100553cfd1cd7`
- [ ] **0.4** Latest CI run on `HEAD` is **success** — verified 2026-08-13, 2m45s
- [ ] **0.5** `python -m alembic heads` → exactly `0006_content_and_dedup (head)`
      ⚠️ **This must be unchanged at every later step.** P9 authors no migration; if this ever
      prints anything else, something has gone badly wrong
- [ ] **0.6** `python scripts\check_schema.py` → **OK — all 51 checks passed**
- [ ] **0.7** `python -m pytest` → green, one uninterrupted run. **Baseline: 1148 passed, 2 skipped**
      ⚠️ Do **not** write `-q`: `pyproject.toml` sets `addopts = "-q --strict-markers"`, so `-q`
      becomes `-qq` and suppresses the summary line entirely ([DI19](DEFERRED-IMPROVEMENTS.md))
- [ ] **0.8** Read [PHASE-08-HANDOVER.md](PHASE-08-HANDOVER.md) in full; its entry conditions
      checked, its traps T1–T7 known
- [ ] **0.9** Confirm **D1, D2 and D4** are approved in writing — they are, 2026-08-13
- [ ] **0.10** Record the current `leads` total. It moves as the scraper runs; **459 is the only
      number that must never change**
- [ ] **0.11** ➖ **No M7 backup is required.** P9 runs no `alembic upgrade` against the live
      database. If a step in this checklist ever asks you to, that step is wrong — stop and report

> ⚠️ **0.12 — Read this before opening any file.** `docs/16-phase-06.md`,
> `docs/testing/phase-06-testing.md` and `docs/10-implementation-roadmap.md` are the **superseded**
> eight-phase numbering ([lock §2.1](EXECUTION_MODE_LOCK.md)). They bundle the rule engine with the
> dedup cascade, entity resolution and the pre-score against migration `0007` — **P9, P10, P11 and
> P15 combined.** They are read-only. **P9 is `src/rules/` and nothing else.**

---

<a id="stage-1"></a>
## Stage 1 — The R3 fence, before the package it constrains

**This stage exists because of [review F1](P9-IMPLEMENTATION-REVIEW.md).** Writing it first means the
fence is proven to *fail* against the violating form and *pass* against the correct one — the only
way to know it guards anything. It is the P8 pattern, which
[progress/P08-COMPLETE.md §2](progress/P08-COMPLETE.md) calls *"the phase's real product"*.

- [ ] **1.1** Create `src/rules/__init__.py` containing **only** a module docstring and
      `__all__ = []` — the minimum that makes the package importable so the fence has a subject.
      No logic. The types land in Stage 2
- [ ] **1.2** Add `tests/test_boundaries.py::test_the_rules_package_is_inside_the_ai_fence`
      ([D1](P9-DECISION-ANALYSIS.md) Option B). Use the **existing** `_imported_modules` /
      `_imports_any` helpers — they parse the AST, and they already resolve relative imports, so
      `from ..ai import gate` cannot slip past a check written for the absolute form.
      Forbidden roots: `{"src.ai", "hermes"}`.
      ⚠️ Name it so `pytest -k "rules"` selects it together with 1.4 and **only** those two — the
      manual guide's **T6** invokes it that way and asks the tester to record the count
- [ ] **1.3** Add `assert scanned > 0` inside 1.2, with fence 3's own message idiom — *"a fence that
      walked nothing would report no violations while checking nothing"*
- [ ] **1.4** Add `tests/test_boundaries.py::test_the_rules_package_exists` — asserts
      `src/rules/__init__.py` is present. **Without this, deleting the package silently reduces 1.2
      to a no-op over an empty directory.** P5's F3, P6's G1, and `test_the_notify_package_exists`
      are the precedent; cite them in the docstring
- [ ] **1.5** ⚠️ **Prove the fence bites.** Temporarily add `from src.ai.gate import GateDecision`
      to `src/rules/__init__.py`. Test 1.2 **must fail**, naming the offending file.
      **Revert immediately.** Record the failure output — it is the evidence F1 was real
- [ ] **1.6** ⚠️ **Prove the existence guard bites.** Temporarily rename `src/rules/`. Test 1.4 must
      fail **and** 1.2 must fail on `scanned > 0` rather than passing vacuously. **Revert
      immediately.** Record both outputs
- [ ] **1.7** Confirm `test_the_platform_never_imports_hermes` (fence 3) now walks `src/rules/`
      automatically — it is scoped to all of `src/`, so this is passive coverage, but assert the
      scanned count rose by one rather than assuming it
- [ ] **1.8** `python -m pytest tests/test_boundaries.py` green; no leftover import, no renamed
      directory
- [ ] **1.9** Full gate + commit: `test(P9): the R3 fence, before the package it constrains`
- [ ] **1.10** **STOP.** Wait for green CI. Report: files changed · mutation results (M1–M3) ·
      validation · CI · findings · architectural observations · doc conflicts · risks

---

<a id="stage-2"></a>
## Stage 2 — `RuleResult` and the three production-wired predicates

- [ ] **2.1** `src/rules/__init__.py` — the neutral result type ([D1](P9-DECISION-ANALYSIS.md)):

      ```python
      @dataclass(frozen=True)
      class RuleResult:
          rejected: bool
          reason: str | None = None   # RejectionReason spelling, NOT imported
          detail: str | None = None   # the granular sub-reason (D3)
      ```

      ⚠️ **The docstring must say why it is not `GateDecision`** — R3 forbids `src/rules/` importing
      `src.ai`, and the adapter is P19's. A future reader who does not know that will "simplify" it
- [ ] **2.2** `REASONS: frozenset[str]` — **exactly four**: `negative_term`, `structural_noise`,
      `too_short`, `bot_or_deleted` ([D2](P9-DECISION-ANALYSIS.md)). Spelled to match
      `src/ai/gate.py::RejectionReason`, **without importing it**
- [ ] **2.3** `src/rules/keywords.py`
  - [ ] Tier matching over the **mapping** `config["keywords"]`, keyed on whatever tiers it contains
        — `high_intent`, `medium_intent` today ([review F7](P9-IMPLEMENTATION-REVIEW.md), reading 3)
  - [ ] ⚠️ **Read the tier lists; never edit them.** `src/scoring.py::LeadScorer` consumes the same
        two, and **R20 pins the resulting `intent_score` fingerprint over 459 rows**
  - [ ] ⚠️ **Do not reproduce [F6](P9-IMPLEMENTATION-REVIEW.md).** `_triage_config` iterates that
        mapping as a list and gets `('high_intent', 'medium_intent')`. Ship a test that would have
        failed against that form
  - [ ] Negative-term matching → `RuleResult(rejected=True, reason="negative_term", detail=<term>)`.
        Case-folded **and** punctuation-normalised, and the normaliser must **not** over-match
        (`notion` ≠ `no tion`)
- [ ] **2.4** `src/rules/structural.py` — the five patterns from
      [06c §3.2](06c-local-first-pipeline.md) / [34 §P9](34-implementation-plan.md) task 2: hiring,
      giveaway, megathread, AMA, promo/engagement-bait. Compiled once at module level, `re.IGNORECASE`
  - [ ] **Every rejection is `reason="structural_noise"`, `detail="megathread"` etc.**
        ([D3](P9-DECISION-ANALYSIS.md)) — one counted reason, full granularity underneath
  - [ ] ⚠️ **Ship a near-miss fixture for every pattern.** `\bhiring\b` must reject
        *"[HIRING] Senior dev"* and **admit** *"our hiring process is broken and I need a tool"* —
        which is a textbook lead and this rule's characteristic false positive
- [ ] **2.5** `src/rules/authors.py` — `[deleted]`, AutoModerator, `*Bot` suffix, allowlist →
      `reason="bot_or_deleted"`, `detail=<which rule fired>`
  - [ ] ⚠️ **Anchor and case-fold the `*Bot` suffix.** `Botany_Nerd`, `robotics_guy` and `Abbott`
        are the known collisions — which is exactly why `triage.py`'s `BOT_AUTHORS` is an exact-match
        frozenset. Ship those three as false-positive fixtures
- [ ] **2.6** `is_too_short(text: str, min_chars: int) -> bool` — a pure, **text-agnostic** predicate
      ([D2](P9-DECISION-ANALYSIS.md)). ⚠️ **Nothing binds it to a body in P9.**
      [06b](06b-deepseek-optimization.md)'s `min_chars: 80` measures a body, and P9's rules see
      titles and authors only. The docstring must say so, and the handover must repeat it
- [ ] **2.7** **Vocabulary test** — `tests/test_rules_vocabulary.py`. A test **may** import both
      sides, so assert `REASONS <= set(RejectionReason.ALL)` and that no call site returns a string
      outside `REASONS`. This is the assertion that keeps [D2](P9-DECISION-ANALYSIS.md)'s subset
      claim honest as P10 and P11 extend the package
- [ ] **2.8** Unit tests per module; **100% branch coverage on the reason paths** (A7).
      `src/rules/` takes the **≥70%** floor — the ≥85% tier names `src/{ai,net,scoring,knowledge}`
      and not `src/rules/` — but the reason paths are held to 100% anyway
- [ ] **2.9** ⚠️ **`src/discovery/triage.py` is NOT touched.**
      [A-2](P9-IMPLEMENTATION-REVIEW.md) and [D3](P9-DECISION-ANALYSIS.md). Its nine-reason vocabulary
      stays; convergence is DI23 and P11's
- [ ] **2.10** Full gate + commit: `feat(P9): the neutral result type, and three predicates that count`
- [ ] **2.11** **STOP.** Wait for green CI. Report as in 1.10

---

<a id="stage-3"></a>
## Stage 3 — Competitors, the protocol, and the inertness guard

- [ ] **3.1** `src/rules/competitors.py` — the protocol ([D5](P9-DECISION-ANALYSIS.md)):

      ```python
      class EntityRegistry(Protocol):
          def resolve(self, text: str) -> list[str]: ...
      ```

      ⚠️ **`typing.Protocol`, not an ABC, and not an import from `src/knowledge/`** — that package
      does not exist until P15
- [ ] **3.2** `DictionaryEntityRegistry` — the fallback, built from an explicit
      `{canonical: [aliases]}` mapping passed by the caller. Alias- and misspelling-tolerant matching
- [ ] **3.3** A competitor mention is a **positive signal, not a rejection**. It returns no `reason`
      and adds no entry to `REASONS` — [06c §3.1](06c-local-first-pipeline.md) makes it a pre-score
      *component*, and the pre-score is P11's
- [ ] **3.4** **A3** — a post containing **only an alias** resolves to the canonical name, proved
      against an injected double
- [ ] **3.5** ⚠️ **The inertness guard** ([D5](P9-DECISION-ANALYSIS.md)). A test asserting **no
      production wiring exists**: no `rules.competitors` key in `config.yaml`, and no module under
      `src/` constructs a `DictionaryEntityRegistry` with real data. Model it on
      `test_min_confidence_alert_was_not_shipped`, and **name P15 in the docstring** — so P15 must
      delete a test to wire it, exactly as [PHASE-08-HANDOVER §4 T1](PHASE-08-HANDOVER.md) demands
      for `min_confidence_alert`: *"delete that fence deliberately … do not discover it failing"*
  - [ ] ⚠️ **Scope it to executable code and settings only, never prose** — the exact scoping
        `test_the_density_heuristic_was_not_reintroduced` already uses, and for the same recorded
        reason: `config.yaml` will *explain in a comment* why the competitor key is absent (4.3's
        house style), and a fence that matched prose would force deleting the explanation.
        [freeze §11.1](ARCHITECTURE_FREEZE.md) records this trap for fences 1 and 4
  - [ ] Name the test so `pytest -k "competitor"` selects it and **only** it — the manual guide's
        **T5** invokes it that way
- [ ] **3.6** Full gate + commit: `feat(P9): competitor matching, and the registry that does not exist yet`
- [ ] **3.7** **STOP.** Wait for green CI. Report as in 1.10

---

<a id="stage-4"></a>
## Stage 4 — Configuration, the flag, and the rollback that is executed

- [ ] **4.1** `RulesSettings.from_config(config)` in `src/rules/__init__.py`, modelled on
      `NotifySettings.from_config` — **including its property that deleting the whole block
      reproduces the defaults exactly**, so a rollback by deletion behaves identically to a rollback
      by flag
  - [ ] ⚠️ **It reads two blocks**, because [34 §P9](34-implementation-plan.md) puts them in two:
        `rules.{min_chars,skip_deleted_authors,skip_bot_authors}` and `pipeline.rules_enabled`.
        Take the whole config mapping, not one sub-mapping
- [ ] **4.2** Defaults, each recorded rather than silently chosen (the P8 **D7** discipline):
  - [ ] `min_chars: 80` — **[06b](06b-deepseek-optimization.md)'s value, cited not invented**
        ([review F12](P9-IMPLEMENTATION-REVIEW.md)). 34 §P9 gives no default
  - [ ] `skip_deleted_authors: true`, `skip_bot_authors: true` — 06b's values
  - [ ] `rules_enabled: **true**` — ⚠️ **this is a recorded choice, and it departs from P7's
        default-off precedent deliberately.** `false` is the *rollback* state per
        [34 §P9](34-implementation-plan.md), so `true` is normal operation; an off-by-default filter
        is the *"documented capability that does not exist"* trap. The rollback is proved by an
        explicit test that flips it (4.5), **not** by the default. **If the operator prefers
        default-off, say so — it is a one-line change and it inverts what P11 inherits**
- [ ] **4.3** Add the `rules:` and `pipeline:` blocks to `config.yaml`, in the house comment style —
      every key explained, with the reason, as the `discovery:` and `notify:` blocks do
  - [ ] ⚠️ **Immediately before staging `config.yaml`, re-run the H1/H2 hygiene patterns against
        `git diff --cached`** ([lock §5.2](EXECUTION_MODE_LOCK.md)), not only at the end of the
        phase. This is the file that has twice carried a real chat identifier
  - [ ] ⚠️ **Use `rules:`, not `ai.prefilter:`.** [06b](06b-deepseek-optimization.md) specifies the
        same three keys under `ai:`; [34 §P9](34-implementation-plan.md) wins on authority, and
        putting the rule engine's config under `ai:` invites the exact coupling **R3** forbids
- [ ] **4.4** `src/rules/` reads `rules_enabled` itself ([D4](P9-DECISION-ANALYSIS.md) Option C).
      Disabled → every predicate returns `RuleResult(rejected=False)` and **short-circuits before any
      regex runs**
- [ ] **4.5** ⚠️ **Execute the rollback; do not merely document it** ([lock §4](EXECUTION_MODE_LOCK.md)).
      Set `pipeline.rules_enabled: false`, run the demo (4.6) against a post every rule would reject,
      confirm it is admitted, restore the flag, confirm it is rejected again. **Record the actual
      terminal output** — it goes in the completion report
- [ ] **4.6** `python -m src.rules "<title>"` — the demo entry point ([D4](P9-DECISION-ANALYSIS.md)),
      printing e.g. `reject · structural_noise · megathread`. It is what makes the manual guide
      executable by a non-developer, since P9 has no page and no row
  - [ ] ⚠️ **It must accept `--rules-enabled true|false` as an override**, so the manual guide's T4
        can exercise the flag path **without a non-developer editing `config.yaml`**. That edit is a
        real hazard on this machine: `load_config` opens with explicit `encoding="utf-8"` and
        `_validate` then reads `config["subreddits"]`, so a Notepad-added BOM turns that key into
        `﻿subreddits` and **every** command fails with `Missing required config key:
        subreddits` — which reads to a tester as a P9 defect and is not one
  - [ ] The **executed** rollback (4.5) is still done against the real `config.yaml` value, by an
        engineer, with the output recorded. The override is for the guide, not a substitute for
        [lock §4](EXECUTION_MODE_LOCK.md)
  - [ ] ⚠️ It must import **nothing** from `src.ai`, or it becomes the leak Stage 1's fence exists
        to catch. The fence covers it automatically — confirm the scanned count rose
  - [ ] It is outside the Files row, which [34 §1.1](34-implementation-plan.md) declares *"a guide,
        not a contract"*. P5's `feed` CLI and P6's `triage.py` are the precedents; record it as such
- [ ] **4.7** A config test: deleting both blocks reproduces the defaults; an unknown key is ignored
      rather than raising
- [ ] **4.8** Full gate + commit: `feat(P9): the rules config block, and a rollback that runs`
- [ ] **4.9** **STOP.** Wait for green CI. Report as in 1.10

---

<a id="stage-5"></a>
## Stage 5 — Property, performance, and mutation evidence

- [ ] **5.1** **A5 — property test, strengthened.** No input crashes: `None`, `""`, a 100 kB body,
      lone surrogates, RTL marks, and **ReDoS-shaped input**
  - [ ] ⚠️ **Read *"no input crashes"* to include *"no input hangs"*.** Five compiled patterns run
        against attacker-supplied post bodies, and a catastrophic backtrack does not raise — it
        stalls the worker. Assert bounded CPU time on a pathological input
- [ ] **5.2** **A6 — `< 1 ms/item`, measured as CPU time.** `time.process_time()` over ≥1,000 items
      with stated headroom
  - [ ] ⚠️ **Never wall clock.** [DI18](DEFERRED-IMPROVEMENTS.md), and Stage 6 is fixing two tests
        for exactly this defect. Adding a fourth flake in the phase asked to remove three would be
        its own indictment
  - [ ] Skip under a tracer, as `test_parse_speed_stays_inside_the_budget` already does — *"timing
        an instrumented interpreter measures the instrument"*
- [ ] **5.3** **Mutation discipline** — [35 §2.4](35-testing-strategy.md). P9 has one **bold**
      criterion (the fence), which is a thin literal minimum for a phase that is entirely branch
      logic. **Run all sixteen** from [review §7.3](P9-IMPLEMENTATION-REVIEW.md):

      | # | Mutation | Must be caught by |
      |---:|---|---|
      | M1 | `import src.ai.gate` in `structural.py` | Fence 2 — *already run at 1.5* |
      | M2 | Delete `src/rules/__init__.py` | Existence guard — *already run at 1.6* |
      | M3 | Fence file-walk returns `[]` | `assert scanned > 0` — *already run at 1.6* |
      | M4 | Drop one structural pattern | That pattern's positive test |
      | M5 | Remove `re.IGNORECASE` | Case-variant test |
      | M6 | Widen `\bhiring\b` → `hiring` | The *"our hiring process is broken"* near-miss |
      | M7 | Keep only `^\[hiring\]` | `[HIRING]`-elsewhere test |
      | M8 | Negative term compared without casefolding | A4 case test |
      | M9 | Negative term compared without punctuation normalisation | A4 punctuation test |
      | M10 | Over-normalise — strip all whitespace | The A4 **over-match** guard |
      | M11 | `min_chars` boundary `<` → `<=` | An exactly-`min_chars` fixture |
      | M12 | Ignore `skip_bot_authors: false` | The flag-respected test |
      | M13 | `*Bot` suffix unanchored | `Botany_Nerd` fixture |
      | M14 | Competitor matches canonical only, not aliases | A3 |
      | M15 | Return a reason outside `REASONS` | 2.7 vocabulary test |
      | M16 | `rules_enabled: false` still rejects | 4.5 rollback test |

- [ ] **5.4** ⚠️ **A survivor is diagnosed, never absorbed.** P8 ran 14, three survived a first pass,
      and **every one was informative** — one was a masked assertion, a real test defect
      ([PHASE-08-HANDOVER §4 T5](PHASE-08-HANDOVER.md)). If a survivor's fix crosses a stage
      boundary, **stop and report for approval**. Never weaken an assertion
      ([lock §3](EXECUTION_MODE_LOCK.md) step 6)
- [ ] **5.5** Record the tally — designed / detected / proven equivalent — for the completion report
- [ ] **5.6** Full gate + commit: `test(P9): sixteen mutations, and the ones that had to be proven`
- [ ] **5.7** **STOP.** Wait for green CI. Report as in 1.10

---

<a id="stage-6"></a>
## Stage 6 — The two flaky tests — [D6](P9-DECISION-ANALYSIS.md)

**Its own commit, deliberately.** [lock §6.1](EXECUTION_MODE_LOCK.md): *"Never mix a phase's code with
an unrelated cleanup."* These are inherited from P8's open D8, not P9's own work.

- [ ] **6.1** `tests/test_feed_parser.py::test_parse_speed_stays_inside_the_budget` — change
      `_time_one` from `time.perf_counter()` to **`time.process_time()`**.
      ⚠️ **The 50 ms budget is not raised.** [DI18](DEFERRED-IMPROVEMENTS.md) names the
      raised-threshold shortcut as the wrong fix in terms: *"a monotonic or CPU-time budget with
      headroom, **not** a raised threshold, which would be weakening an assertion."* CPU time
      excludes the neighbours the wall clock was measuring
- [ ] **6.2** Update that test's docstring — it currently explains the `min`-of-5 wall-clock
      reasoning, which stops being the reason
- [ ] **6.3** `tests/test_worker.py::test_the_heartbeat_thread_extends_a_lease_while_a_handler_runs`
      — replace the fixed `time.sleep(0.05)` with a **poll-until-claimed loop** on a `time.monotonic()`
      deadline. The race is that under load the worker has not claimed the job within 50 ms, so
      `lease_expires_at` is still `None` and `seen[0] > claimed_until` raises a `TypeError`.
      ⚠️ **The assertion `seen[0] > claimed_until` is unchanged.** Only the wait for the
      precondition changes — that is a fixed race, not a weakened test
- [ ] **6.4** Run each fixed test **20 times in a loop** under concurrent load, and record the pass
      rate. A single green run is not evidence — [DI18](DEFERRED-IMPROVEMENTS.md) records 3/3 in
      isolation for a test that has failed four times under load
- [ ] **6.5** ⚠️ **`test_does_not_write_to_the_database_it_checks` is NOT fixed here.** It is a
      WAL/mtime race in `scripts/check_schema.py`, a real investigation of unknown size and unrelated
      to P9. **It is registered as DI20 in Stage 7** — filling the number
      [DEFERRED-IMPROVEMENTS §1](DEFERRED-IMPROVEMENTS.md) has held reserved across two phases
- [ ] **6.6** Full gate + commit: `fix(P9): two timing assertions that were measuring the machine`
- [ ] **6.7** **STOP.** Wait for green CI. Report as in 1.10

---

<a id="stage-7"></a>
## Stage 7 — Documentation and reconciliations

**None of these edits was made during the review.**

- [ ] **7.1** [06c §2](06c-local-first-pipeline.md) — P9's **Docs** field owns this table. Repoint
      *"Subreddit filtering … `rules/subreddits.py`"* at `src/discovery/`
      ([review F8](P9-IMPLEMENTATION-REVIEW.md)): the module is in neither
      [34 §P9](34-implementation-plan.md)'s Files row nor [03 §2](03-architecture.md)'s map, and
      [03 §2](03-architecture.md) places subreddit work in discovery. **Do not create the module**
- [ ] **7.2** [34 §P9](34-implementation-plan.md) Acceptance — rewrite criterion A1 to
      [D2](P9-DECISION-ANALYSIS.md)'s wording: four predicates, three production-wired, counting is
      P19's. ⚠️ **Leave [34 §P19](34-implementation-plan.md)'s row alone** — it is the one that is
      correct
- [ ] **7.3** [35 §2.1](35-testing-strategy.md) check 9 — record which of fence 2's six paths are
      live and which phase creates each: `src/rules/` **P9**, `src/dedupe/` P10, `src/scoring/` P11,
      `src/knowledge/` P15, `src/feedback/` P19, `src/discovery/policy.py` shipped. A fence that
      looks complete while covering one path of six is how this went unnoticed for eight phases
- [ ] **7.4** [freeze §11.1](ARCHITECTURE_FREEZE.md) — **one** row, dated, phase **P9**, recording
      the [06b](06b-deepseek-optimization.md) `ai.prefilter` → `rules:` reconciliation and the
      adoption of its `min_chars: 80`. State explicitly that **no technology, table or decision
      changes** — this is a reconciliation, not an amendment
- [ ] **7.5** [DEFERRED-IMPROVEMENTS](DEFERRED-IMPROVEMENTS.md):
  - [ ] **DI20** — `test_does_not_write_to_the_database_it_checks`, the WAL/mtime race. Trigger: *a
        third occurrence, or one in CI*. ⚠️ **Fill the reserved number; do not skip it again.** The
        register's own §1 note explains why it was held open
  - [ ] **DI23** — the rejection-vocabulary convergence ([D3](P9-DECISION-ANALYSIS.md)). Trigger:
        **P11**, which owns both the funnel counters and the full-stage pre-score and is therefore
        the first phase that must render both vocabularies on one page
  - [ ] **DI24** — `_triage_config` reads `config["keywords"]` as a list when it is a dict
        ([review F6](P9-IMPLEMENTATION-REVIEW.md)). Trigger: **P11**, the first consumer of a triage
        score. Record the measurement: `TriageConfig.keywords == ('high_intent', 'medium_intent')`
  - [ ] ⚠️ **Update the §1 note about the DI20 gap** — it is no longer a gap
- [ ] **7.6** Full gate + commit: `docs(P9): the module table, the fence that covered one path of six`
- [ ] **7.7** **STOP.** Wait for green CI. Report as in 1.10

---

## Post-implementation — [lock §3](EXECUTION_MODE_LOCK.md) steps 8–16

- [ ] **P.1** `docs/testing/P09-testing.md` — Part B execution record filled in, sign-off table
      present and **blank** (a machine running commands is not a human accepting the phase)
- [ ] **P.2** ⚠️ **Execute every command in the guide before shipping it.** Two guides have already
      shipped with commands that could not produce the output they promised
      ([DI19](DEFERRED-IMPROVEMENTS.md), and P7's 31 corrections). Reading them is not executing them
- [ ] **P.3** ⚠️ Every command in the guide is **PowerShell**. A bash-escaped command silently
      no-ops on this machine and reads as a passing test
- [ ] **P.4** `docs/PHASE-09-COMPLETION-REPORT.md` — must record: the mutation tally (designed /
      detected / equivalent), the 20-run flake pass rates from 6.4, the executed rollback output from
      4.5, the fence-bites evidence from 1.5/1.6, and the pre- and post- test counts
- [ ] **P.5** `docs/PHASE-09-HANDOVER.md` — **must** carry:
  - **P10 inherits `src/rules/`'s return type and vocabulary.** `RuleResult`, four reasons, `detail`
    for granularity — and it must not import `src.ai` either
  - **`is_too_short` is not bound to any text in P9** — P11 binds it when a body first exists
  - **The competitor rule is inert, and a test guards that.** **P15 must delete it deliberately**
  - **DI23 fires in P11** — two rejection vocabularies on one page
  - **DI24 fires in P11** — P6's keyword matching has never matched a keyword
  - **DI14 still fires in P10** — the 444/27 permalink host split
  - **DI22 is still P10's** — the `dedup_members` invariant
  - **L4 (P7) is still undelivered and still has no owner** — the notification retry
  - **O2 / `mypy`** re-deferred, but `src/rules/` ships clean under it so the debt does not grow
  - **Fence 2 now covers one of six paths and says so** — P10 extends it to `src/dedupe/`
- [ ] **P.6** `docs/progress/P09-COMPLETE.md`, ending in a resume point
- [ ] **P.7** `docs/README.md` execution table updated
- [ ] **P.8** Repository Hygiene Review — [lock §5](EXECUTION_MODE_LOCK.md), all eight checks, on the
      **staged** diff. ⚠️ **H1/H2 on `config.yaml` specifically**, per 4.3
- [ ] **P.9** Push; **do not tag** — the P00–P08 manual sign-off tables are unsigned, and
      [lock §6.2](EXECUTION_MODE_LOCK.md) forbids a tag that would claim a verification that did not
      happen
- [ ] **P.10** **STOP.** Report and wait for explicit approval before P10
