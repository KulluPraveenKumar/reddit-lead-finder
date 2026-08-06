# GitHub Actions Report

**Date:** 2026-08-06 · **Scope:** one workflow, `.github/workflows/ci.yml`. **No architecture
changed. No P2 work.**

Builds **DI2** in [DEFERRED-IMPROVEMENTS.md](DEFERRED-IMPROVEMENTS.md), proposed in
[PRE-P2 §6.3](PRE-P2-VERIFICATION-REPORT.md) and deliberately not built then.

---

## 1. Research summary

| Question | Finding | Applied |
|---|---|---|
| Minimum useful Python CI | `checkout` → `setup-python` → install → lint → test. No matrix unless multiple versions are actually supported | One job, one Python version |
| Dependency caching | `actions/setup-python@v5` has built-in `cache: pip` — one line, no separate `actions/cache` step, no cache key to maintain | Adopted, on measured evidence (§2) |
| Token permissions | Declare `permissions` explicitly; anything not declared becomes `none`. A test-only workflow needs `contents: read` | `permissions: contents: read` at workflow level |
| Action pinning | Pinning to a commit SHA is the supply-chain-hardened form; major-version tags are GitHub's documented default | Major tags (`@v4`, `@v5`). SHA pinning deferred — see §5 |
| Trigger shape | `push` unfiltered plus `pull_request` runs every PR commit **twice** | `push` filtered to `main`; `pull_request` unfiltered |

Sources: [GitHub — controlling permissions for GITHUB_TOKEN](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token) ·
[GitHub — workflow syntax](https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions) ·
[GitHub Actions best practices 2026](https://devtoollab.com/blog/github-actions-best-practices)

---

## 2. The caching decision — measured, not assumed

Measured on this project, installing `requirements.txt` into a fresh virtual environment:

| Condition | Time |
|---|---|
| Cold — empty pip cache | **66.7 s** |
| Warm — populated pip cache | **46.1 s** |
| **Saved** | **20.6 s per run (31%)** |
| Cache size | 34.8 MB |

**Adopted.** The saving is real and repeatable, the cost is one line, and there is no cache key to
maintain because `cache-dependency-path` points at the file that already defines the dependencies.

Honest caveats: the measurement is on a Windows developer machine, and GitHub's hosted runners have
faster network but slower disk, so the real saving will differ. Cache restore and save themselves
cost a few seconds. The decision would not change if the saving were half this.

---

## 3. The blocker that had to be fixed first

**`ruff format --check .` was red before this workflow existed.** 50 files would have been
reformatted, so the required workflow would have failed on its very first run — worse than no CI at
all. Two causes, two different answers:

| Cause | Files | Resolution |
|---|---|---|
| Ruff formats Python inside Markdown fenced blocks | **22 docs** | Excluded `*.md` from the formatter. The design documents use hand-aligned columns and arrows in those blocks deliberately; reflowing them would rewrite frozen documents to say the same thing less clearly |
| Formatter drift plus files never formatted | **28 `.py`** | 23 **reformatted** (`src/ai`, `src/net`, `src/obs`, `src/db`, `main.py`, tests). The 5 pre-Phase-1 modules already exempt from lint are now also exempt from the formatter, for the same recorded reason: `routes.py` must keep rendering the legacy dashboard unchanged |

Both are expressed in `pyproject.toml` under `[tool.ruff.format]`, with the reasoning inline and a
note that a line is removed when the phase that owns that module rewrites it. The alternative —
having CI scope the check to a hand-maintained path list — hides the problem in YAML instead of
fixing it, and drifts the moment a file is added.

**Result:** `ruff format --check .` now reports `67 files already formatted`. The check means
something for the first time.

### 3.1 Ruff is now pinned

`ruff>=0.5` → `ruff==0.16.1`. The formatter's output changes between releases, so an unpinned ruff
turns `ruff format --check` red on a day nobody touched the code. Bumping it is a deliberate change
that runs `ruff format .` in the same commit. This adds no technology — [freeze §5](ARCHITECTURE_FREEZE.md)
already names ruff; it pins the version of a tool already on the list.

---

## 4. The workflow

```yaml
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  gate:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
          cache-dependency-path: requirements.txt
      - run: python -m pip install -r requirements.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest
```

Four commands, one job, no secrets. Every choice:

| Choice | Why |
|---|---|
| Python **3.12**, no matrix | [Freeze §5](ARCHITECTURE_FREEZE.md) pins 3.12; the project runs on one VPS. A matrix would test a configuration nobody deploys |
| `ubuntu-latest` | The deployment target is Linux + systemd ([AD-30](ARCHITECTURE_FREEZE.md)). Development happens on Windows, so this also catches path and encoding assumptions the developer machine hides |
| `timeout-minutes: 15` | The suite takes ~45 s. A run that reaches 15 minutes is hung, and should stop rather than burn an hour |
| No `concurrency` block | Considered. It cancels superseded runs, but with one developer pushing to one branch there is nothing to supersede. Add it when there is |
| No secrets, no environment | The suite is offline by contract. `PROXY_FILE` is unset in CI, so the two proxy-file tests skip — the expected and correct behaviour |

### 4.1 Deliberately not built

Per the brief and [freeze §7](ARCHITECTURE_FREEZE.md)'s logic — capability nobody asked for is a
permanent tax: **no** deployment, releases, Docker, publishing, Dependabot, CodeQL, coverage upload,
matrix builds, scheduled runs, or release automation.

---

## 5. Local verification

The workflow cannot be executed locally without adding a tool (`act`), which would be a technology
addition. It was verified by **reproducing its steps exactly** instead:

| Check | Result |
|---|---|
| YAML parses; triggers, permissions and steps are what the file intends | ✅ `push`, `pull_request`; `contents: read`; 6 steps; 4 `run` commands |
| Fresh virtual environment, `pip install -r requirements.txt` **only** | ✅ exit 0 — no dev-only dependency is missing from `requirements.txt` |
| `ruff check .` in that environment | ✅ `All checks passed!` |
| `ruff format --check .` in that environment | ✅ `67 files already formatted` |
| `pytest` in that environment | ✅ `308 passed, 2 skipped` |

The fresh-environment run is the check that matters: it proves CI will not fail on a dependency that
exists only in the developer's virtual environment.

---

## 6. What this workflow is for

It mechanises three of the 18 gate checks in [35 §2](35-testing-strategy.md) — the three that need no
database, no fixtures beyond the repository, and no human. It does **not** replace the gate: the
migration round-trip, the legacy contract, the secret scan, mutation discipline and the manual guide
all remain the phase's responsibility.

Its value is narrow and real: a phase can no longer reach `main` with a lint error, a formatting drift
or a failing test that the developer forgot to run.

---

## 7. Deferred

| Improvement | Trigger |
|---|---|
| Pin actions to commit SHAs | A supply-chain advisory affecting `actions/checkout` or `actions/setup-python`, or a second contributor. Major-version tags are GitHub's own default and are re-pointed by GitHub, not by an attacker with repository access |
| `concurrency` cancel-in-progress | More than one push in flight at a time — i.e. a second contributor |
| Running the migration round-trip in CI | It needs a copy of the live 459-lead database, which is correctly not in the repository |
