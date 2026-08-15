# Reddit Lead Finder

[![CI](https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/KulluPraveenKumar/reddit-lead-finder/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-308%20passing-brightgreen.svg)](#development)

**Paste a website URL; get a ranked list of Reddit conversations where real
people are describing the problem that website solves — with evidence for why
each one is a lead.**

Scrapes `old.reddit.com` and public `.rss` only — **no Reddit API, no OAuth, no
PRAW, and no account of any kind.** Scores discussions against a model of your
business and ranks them with explanations you can audit, because the AI never
produces the final number: categoricals go in, arithmetic comes out.

One operator. One machine. One SQLite file.

> **Not a posting tool.** There is no Reddit write path and there never will be —
> no posting, commenting or DMing. Drafting a reply for a human to send is in
> scope; sending it is not.

---

## This is a Python project. There is no Node.js, npm, or pnpm.

```
pnpm run dev     ->  ERR_PNPM_NO_PKG_MANIFEST: No package.json found
npm  run dev     ->  ENOENT: no such file or directory, open 'package.json'
```

Both are correct: there is no `package.json`, no lockfile, no Vite, no
TypeScript, and no `node_modules` anywhere in this repository, and there never
has been. **Nothing is broken — those are the wrong tools for this project.**

The dashboard is server-rendered Jinja with inline CSS and JS. That is a
deliberate architectural decision, recorded in
[docs/09 §1](docs/09-dashboard-plan.md): a build step would add an entire
toolchain, a lockfile, and a `node_modules` directory to a single-operator tool
that renders eight pages. **npm and pnpm are not supported and are not intended
to be.**

### The actual commands

```bash
python -m pip install -r requirements.txt     # instead of `pnpm install`
python main.py dashboard                      # instead of `pnpm run dev`
```

Then open <http://127.0.0.1:5000>.

---

## Quick start

```bash
# 1. Dependencies (Python 3.11+)
python -m pip install -r requirements.txt

# 2. Secrets. Generate an APP_SECRET_KEY - it encrypts the AI provider key.
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into .env

# 3. Schema. Backs up automatically before any change.
python main.py migrate

# 4. Run
python main.py dashboard
```

Without `APP_SECRET_KEY`, AI features are disabled with a clear message and
everything else keeps working.

### The AI provider key does not go in a file

Add it at **Settings → AI Provider** (`/settings/ai`). It is validated with the
provider before being stored, then encrypted at rest.

A key in `config.yaml` gets committed, pasted into support tickets, and shared
whenever the file is shared. Runtime entry means the repository never contains a
credential.

Supported providers: **DeepSeek** (direct), **OpenRouter** (gateway to DeepSeek
V4 Flash and ~360 other models), **OpenAI**. Selectable from the Settings page.

---

## Commands

| Command | What it does |
|---|---|
| `python main.py dashboard` | Start the web dashboard (**this is "dev"**) |
| `python main.py scrape [--scraper keyword\|subreddit\|user]` | Run scrapers |
| `python main.py schedule` | Scrape on a schedule |
| `python main.py add-user USERNAME` | Track a Reddit user |
| `python main.py migrate [status\|upgrade\|stamp REV\|downgrade REV]` | Schema |
| `python main.py ai [status\|test\|usage]` | Provider status and connectivity |

## Development

```bash
python -m pytest                           # full suite, no network calls
python -m pytest tests/ --cov=src/ai       # with coverage
python -m ruff check .                     # lint
python -m ruff check --fix .               # autofix
```

The suite runs entirely offline: HTTP is mocked with `responses`, and everything
else uses `FakeProvider`. Two tests parse a real proxy list and **skip** unless
`PROXY_FILE` points at one — that file holds live credentials, so it lives
outside the repository by design. Expect `308 passed, 2 skipped`, or
`310 passed` with `PROXY_FILE` set.

The same three commands run in CI on every push to `main` and every pull request
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) — no secrets, no
deployment. The test fixtures are fully synthetic: no real Reddit username,
post title or post id is published here ([docs/PRIVACY_REVIEW.md](docs/PRIVACY_REVIEW.md)).

### Verifying the database

`scripts/check_schema.py` checks a database against the schema the current phase
specified — tables, index **column order**, foreign-key `ON DELETE` actions,
constraints, row counts, integrity, and the 459-lead legacy fingerprint:

```bash
python scripts/check_schema.py --db data/leads.db          # full check
python scripts/check_schema.py --db data/leads.db --help   # options
```

It is stdlib-only, opens the database read-only, and needs **no `sqlite3`
command-line tool** — which is why it runs unchanged on Windows. The manual
testing guides in [docs/testing/](docs/testing/) use it throughout.

---

## Layout

```
main.py              CLI entry point
CHANGELOG.md         Release history, hand-maintained
.github/workflows/   CI: ruff check, ruff format --check, pytest
config.yaml          Non-secret configuration (never an API key)
.env                 APP_SECRET_KEY  (gitignored)
migrations/          Alembic revisions - a single linear chain
scripts/
  check_schema.py    Schema verifier used by the manual testing guides
  probe/             P0 measurement probes (network, RSS, environment)
src/
  ai/                AI Service Layer - the only path to a model
    providers/       The ONLY package that names a vendor
  db/                Models, engine, migration runner, repositories
  dashboard/         Flask blueprints and Jinja templates
  net/               Egress policy, proxy pool, HTTP cache
  orchestration/     Run/job state machines
  scrapers/          Reddit scrapers
  obs/               Structured logging with credential redaction
docs/                Architecture and phase plans (~40 documents)
  testing/           Per-phase manual testing guides
tests/               Offline test suite
```

Start with [docs/ARCHITECTURE_FREEZE.md](docs/ARCHITECTURE_FREEZE.md) — the
binding constraint set that governs every change — then
[docs/EXECUTION_MODE_LOCK.md](docs/EXECUTION_MODE_LOCK.md) for the process every
change follows, and [docs/README.md](docs/README.md) for the architecture.

---

## Status

**P0 through P13 complete**, against the frozen P0–P30 plan in
[docs/34-implementation-plan.md](docs/34-implementation-plan.md). *(This section
had said "P0 and P1" since P1; corrected in P13.)*

What exists: the run and job schema with a worker and run pages (P1–P3), a
network provider abstraction where **egress is chosen per request class** (P4),
RSS discovery and watermarks (P5–P6), a notification tier that never invokes a
model (P7), the content and dedup schema (P8), a rule engine (P9), a three-tier
dedup cascade (P10), pre-scoring with the funnel and comment collection (P11),
the project and knowledge-base schema (P12), and website fetching with local
signal extraction (P13).

**No model has been called yet.** Every phase to here is deterministic Python —
`SELECT COUNT(*) FROM ai_calls` is `0`, asserted rather than assumed. The first
AI call in the pipeline is **P14**'s single `analyze_business` request.

The legacy dashboard and its 459 leads are unaffected throughout, which
`tests/test_boundaries.py` enforces after every phase.

Verify a phase yourself with its guide in
[docs/testing/](docs/testing/) — each is written to be executed by a
non-developer, with an expected result for every step.

---

## Licence

[MIT](LICENSE).

The tooling is MIT-licensed; **the data it collects is not yours to relicense.**
Reddit content remains subject to Reddit's terms and its authors' rights, and
the lead fixtures under `tests/baseline/` are anonymised for that reason. Respect
`robots.txt`, the rate limits this project already enforces, and the people whose
posts you are reading.
