# Final Pre-P2 Review

**Date:** 2026-08-06 · **Scope:** the final operational work before P2. **No architecture changed.
No roadmap changed. No phase modified. No P2 implementation.**

Governing documents: [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) ·
[EXECUTION_MODE_LOCK.md](EXECUTION_MODE_LOCK.md). Nothing below introduces a technology, table,
migration, AI call, dependency or capability the freeze does not already name.

---

## 1. Repository health

Measured today, not cited from a previous report.

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | ✅ **All checks passed!** |
| Format | `ruff format --check .` | ✅ **67 files already formatted** — clean repo-wide for the first time (§3) |
| Full suite | `pytest` | ✅ **308 passed, 2 skipped** |
| Migration head | `alembic heads` | ✅ exactly one — `0004_orchestration` |
| Schema | `check_schema.py --db data/leads.db` | ✅ **OK — all 25 checks passed** |
| Migration round-trip | `upgrade → downgrade 0003 → upgrade head` on a **copy** | ✅ 25 checks at `0004`, 5 at `0003`, 459 leads at every stage |
| Live database | untouched by any step above | ✅ 459 leads · 164.28 / 42.29 |
| Working tree | `git status` | ✅ clean after commit |

---

## 2. Privacy review — [PRIVACY_REVIEW.md](PRIVACY_REVIEW.md)

**Researched, decided, implemented.** Verdict: **synthesise.**

The decisive finding is that anonymising the author does not protect the author while the text is
verbatim — search engines re-identify the source, which is why the accepted mitigation in
internet-mediated research is paraphrase or synthesis, not handle replacement. The earlier pass had
anonymised 413 authors and left their titles beside them; in a public repository that was a
redirection one search query undoes.

The engineering side was measured rather than assumed: **no test reads fixture text.** Every
assertion is structural — counts, response shapes, the CSV header, the 459/164.28/42.29 fingerprint.

| Replaced | Kept, deliberately |
|---|---|
| 445 + 48 verbatim post titles | Subreddit names — a community is not a person |
| 44 usernames, 25 account ids | `AutoModerator` — a site-wide bot, not a natural person |
| 48 post ids, every title-derived URL slug | Every number, timestamp and DOM structure |

Verified: 10 invariants pass; 0 real titles, 0 real post ids and 0 real usernames remain (the one
documented bot excepted). **Mutation-tested:** the anonymised search fixture still catches the exact
pagination bug it exists for, and a coverage gap the mutation exposed — a broken title selector left
every post untitled and the test still passed — was closed with one assertion, itself mutation-tested.

---

## 3. GitHub Actions — [GITHUB_ACTIONS_REPORT.md](GITHUB_ACTIONS_REPORT.md)

**One workflow. Four commands. No secrets.** `ruff check` · `ruff format --check` · `pytest`, on push
to `main` and every pull request, with `permissions: contents: read` and a 15-minute timeout.

Two findings worth naming:

1. **`ruff format --check .` was red before the workflow existed** — 50 files. A workflow shipped
   without checking that would have been red on its first run. Cause was split: 22 Markdown files
   (ruff formats Python inside fenced blocks; the design documents align those blocks deliberately)
   and 28 Python files. Resolution: Markdown and the 5 pre-Phase-1 modules excluded from the
   formatter in `pyproject.toml` with the reasoning inline; **23 files reformatted**, no behaviour
   changed, full suite green.
2. **Caching adopted on measurement, not preference** — cold install 66.7 s, warm 46.1 s, saving
   20.6 s for one line of YAML and no cache key to maintain.

`ruff` is now pinned to `==0.16.1`: an unpinned formatter turns CI red on a day nobody touched the
code. This adds no technology — the freeze already names ruff.

**Verified locally** by reproducing the steps in a fresh virtual environment with only
`requirements.txt` installed: install ✅, lint ✅, format ✅, `308 passed, 2 skipped` ✅. That is the
check that matters — it proves CI will not fail on a dependency that exists only on this machine.

---

## 4. Git tag — [TAG_REPORT.md](TAG_REPORT.md)

**No tag was created, moved or deleted.** `v0.1.0-p1` already exists, is **annotated**, and is
**already on the remote**, pointing at `d5089ee` — the last commit of the P1 implementation.

It was deliberately **not** moved to `HEAD`: moving a published tag rewrites a ref that clones may
reference, and the commits since are process and hygiene work, not P1 code. They are recorded in
[CHANGELOG.md](../CHANGELOG.md) under **[Unreleased]**.

**Honest verification result:** under [EXECUTION_MODE_LOCK §6.2](EXECUTION_MODE_LOCK.md) this tag
*could not be created today*, because both manual sign-off tables are unsigned. The tag predates that
rule. The rule is not retroactive — but it will block P2's tag, and that is the point of it.

---

## 5. Repository hygiene

H1–H8 of [EXECUTION_MODE_LOCK §5](EXECUTION_MODE_LOCK.md), run against the staged diff of all 40
changed files.

| # | Check | Result |
|---|---|---|
| H1 | Secrets, keys, credentials, tokens | ✅ none |
| H2 | Personal information | ✅ none — full-tree sweep for real titles, usernames and post ids |
| H3 | Machine-specific paths (`C:\Users\`, `/home/`, `/Users/`) | ✅ none |
| H4 | Temporary files, debug artefacts, scratch scripts | ✅ none tracked or untracked |
| H5 | Local databases | ✅ `data/*.db`, `-wal`, `-shm`, `data/backups/` all ignored, proved |
| H6 | Generated artefacts | ✅ no `__pycache__`, `*.log`, `coverage.xml`, `*.zip`, `.venv/` staged |
| H7 | Ignore rules actually fire | ✅ `git check-ignore -v` printed the rule for `.env`, `data/leads.db`, the local `*.zip` archives, `.venv/` and `.claude/settings.local.json` |
| H8 | Every staged file intentional | ✅ 40 files, each accounted for in §7 |

**The sweep caught this review's own companion document.** The first draft of
[PRIVACY_REVIEW.md](PRIVACY_REVIEW.md) quoted a real username and a real post id as illustrations,
and H2 failed on it. Both were replaced. Recorded because it is the argument in miniature: the leak is
rarely in the file you set out to clean.

**Verdict: suitable for public distribution.** One documented exception — the anonymisation tooling
was run as a one-off script kept outside the repository, so the transformation is described in
[PRIVACY_REVIEW §3](PRIVACY_REVIEW.md) rather than shipped as a script nobody will run again.

---

## 6. Test results

| Suite | Result |
|---|---|
| Full suite | **308 passed, 2 skipped** |
| Boundary / architecture fences | **18 passed** |
| Migrations | **9 passed** |
| Orchestration | **44 passed** |
| Legacy contract, navigation and pages | **31 passed** |
| Transport, parsers, proxy pool (`test_net.py`) | **112 passed, 2 skipped** |
| Schema verification | **25 / 25** |
| Workflow validation | ✅ `ci.yml` parses; triggers, permissions and steps as intended |
| Clean-environment CI simulation | ✅ install, lint, format, **308 passed, 2 skipped** |
| **Tracked-files-only checkout** (what `actions/checkout` produces) | ✅ **305 passed, 5 skipped** — the three extra skips are the live-database guards firing correctly, since `data/` is not in the repository |
| First hosted CI run | ⚠️ **blocked by a GitHub Actions outage**, not by the workflow — R5 in §9 |

The 2 skips are correct: both parse a real proxy credentials file, which lives outside the repository
by design (R15). With `PROXY_FILE` set the suite reports `310 passed, 0 skipped`.

**Three expected lines, all correct, for three environments** — worth stating once so nobody reads a
regression into a difference:

| Environment | Expected | Why |
|---|---|---|
| Developer machine | `308 passed, 2 skipped` | Live database present; no proxy file |
| Developer machine with `PROXY_FILE` | `310 passed, 0 skipped` | Everything available |
| **CI** | `305 passed, 5 skipped` | Tracked files only — no `data/leads.db`, no proxy file |

---

## 7. Documentation status

Only affected documentation was touched.

| Document | Change |
|---|---|
| [PRIVACY_REVIEW.md](PRIVACY_REVIEW.md) · [GITHUB_ACTIONS_REPORT.md](GITHUB_ACTIONS_REPORT.md) · [TAG_REPORT.md](TAG_REPORT.md) · this file | New — **execution records**, not planning documents, and therefore not what [EXECUTION_MODE_LOCK §2](EXECUTION_MODE_LOCK.md) prohibits |
| [../CHANGELOG.md](../CHANGELOG.md) | New — Keep a Changelog format, hand-maintained (§8) |
| [testing/P00-testing.md](testing/P00-testing.md) · [testing/P01-testing.md](testing/P01-testing.md) | **Stale counts corrected** — see below |
| [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md) | DI2 and O1 closed with the line saying which; DI7–DI9 added |
| [../README.md](../README.md) | CI badge, CI and fixture notes, `CHANGELOG.md` and `.github/workflows/` in the layout |
| [README.md](README.md) | Operational records linked from the execution record |
| `pyproject.toml` · `requirements.txt` | Formatter exclusions with inline reasoning; `ruff` pinned |

### 7.1 The correction that actually matters

**Both manual guides were unexecutable as written.** P00 and P01 expected `310 passed` where the
suite reports `308 passed, 2 skipped`; P01 expected `26 schema checks` where the verifier reports
`25`, and `6 checks` after a downgrade where it reports `5`. A tester following either guide would
have recorded a healthy repository as a **failure** — on the guides that are the last gate before P2.

Every corrected number was measured by running the guide's own command, including the downgrade
counts, which were obtained from an actual round-trip on a copy of the live database.

### 7.2 Not modified

Freeze, roadmap, phase plans, system design, database plan, testing strategy, skills architecture and
every 00–36 rationale document are untouched.

---

## 8. The changelog decision

**Keep a Changelog, hand-maintained.** The decisive argument is not taste:

- `semantic-release` is a **technology**, and [freeze §5](ARCHITECTURE_FREEZE.md) is a closed list —
  adopting it would require an amendment, which requires a failed measurement. It is also a Node
  toolchain, which [README §This is a Python project](../README.md) rules out explicitly.
- Keep a Changelog is a **formatting convention**. No dependency, no amendment, no toolchain.
- The practical argument agrees: automated changelogs read as a list of commits, and this project's
  releases are phases with reasoning behind them.

Versioning follows the existing convention `v<pyproject version>-p<phase>`, set by `v0.1.0-p1`.

---

## 9. Remaining risks

| # | Risk | Severity | Note |
|---|---|---|---|
| **R1** | **Both manual sign-off tables are unsigned** | **Blocking, procedurally** | The project's own rule ([handover §8](PHASE-01-HANDOVER.md), [lock §4](EXECUTION_MODE_LOCK.md)). ~20 minutes each, non-developer, non-destructive. Tracked as **O3** |
| R2 | `mypy` required by [35 §2](35-testing-strategy.md) check 3 and [freeze §5](ARCHITECTURE_FREEZE.md), not installed — verified absent today | Medium | The gate cannot be claimed **in full**. Tracked as **O2**. Deliberately not installed here: adding it would change the gate's baseline the day before P2 starts, and choosing that baseline is the operator's call |
| R3 | Git history still contains the original fixtures in `87ba926` and `d5089ee` | Low, recorded | Rewriting published history breaks every clone and the tag, for content that was public for the life of those commits. **Not done silently** — [PRIVACY_REVIEW §4.2](PRIVACY_REVIEW.md) |
| R4 | [Freeze R20](ARCHITECTURE_FREEZE.md) says "`GET /` byte-identical"; the shipped guard is an API-contract check | Low | A documentation reconciliation, not an amendment. Tracked as **DI7**; editing the freeze is the operator's call |
| R5 | **CI has not yet completed a real run.** The first two attempts failed at *Set up job* with `Failed to resolve action download info / Service Unavailable` — **GitHub Actions was in a declared partial outage** (incident opened 15:22 UTC; the run started 15:32 UTC) | Low, external | No step of the workflow executed, so nothing in it can be the cause. Repository settings verified permissive. The steps are proven green in a clean-environment reproduction. Re-run `gh run rerun 31116314876` once the incident closes — [GITHUB_ACTIONS_REPORT §5.1](GITHUB_ACTIONS_REPORT.md) |
| R6 | Formatter drift on a future ruff bump | Low | Mitigated by the exact pin; bumping runs `ruff format .` in the same change |
| R7 | Four statements about the required Python version give two answers (freeze 3.12; `pyproject` `>=3.11`/`py311`; a guide's "floor is 3.11"; CI 3.12) | Low | Documentation inconsistency, not an architecture change. Pins deliberately unchanged. Tracked as **DI10** |

**No unresolved technical blocker.**

---

## 10. Deferred improvements

Ten open entries and two open decisions in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md), each
with the evidence that would justify acting. Closed in this pass: **DI2** (CI, built) and **O1**
(fixture titles, resolved). Added: **DI7** (R20 wording), **DI8** (SHA-pinned actions), **DI9**
(workflow concurrency), **DI10** (Python-version statements).

Nothing here is scheduled, and nothing here blocks P2.

---

## 11. Recommendation

Every technical criterion passes: the suite is green, the repository is clean, the fixtures are
synthetic, the workflow is verified, the tag is correct, the documentation is accurate, and no
architecture, roadmap or phase changed.

**One criterion does not pass, and it is not technical:**

> **P2 is NOT yet approved.**
>
> [PHASE-01-HANDOVER.md §8](PHASE-01-HANDOVER.md) makes a signed P01 sign-off table P2's first entry
> condition; [progress/P01-COMPLETE.md](progress/P01-COMPLETE.md) records it as *"Blocks P2? **Yes**"*;
> [EXECUTION_MODE_LOCK §4](EXECUTION_MODE_LOCK.md) requires manual testing **completed and signed off
> by a human**. Both tables are blank.
>
> [PRE-P2 §8](PRE-P2-VERIFICATION-REPORT.md) states *"P2 is approved for implementation."* That was a
> judgement about the **implementation**, and it stands: no defect was found then and none was found
> now. It did not, and could not, satisfy a gate that only a human can satisfy. **Where the two
> disagree, the project's own entry condition wins** — and the guides it depends on were, until
> today, impossible to pass.

**The path to approval, in order:**

1. Execute and sign [testing/P00-testing.md](testing/P00-testing.md) — ~20 min, non-destructive.
2. Execute and sign [testing/P01-testing.md](testing/P01-testing.md) — ~20 min, non-destructive.
   Both now state the numbers the commands actually print.
3. Optionally install `mypy` and record its baseline (**O2**), so the [35 §2](35-testing-strategy.md)
   gate can be claimed in full from P2 onward.

**When both tables are signed, P2 is approved and may begin — and not before.**

---

*P2 was not started. No work beyond the operational scope of this pass was performed.*
