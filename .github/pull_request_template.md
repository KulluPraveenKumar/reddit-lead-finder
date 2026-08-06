<!--
This project implements one phase at a time against a frozen architecture.
A PR that spans two phases will be asked to split.
-->

## What this changes

<!-- One or two sentences. -->

**Phase:** <!-- P2, P3, ... -->

## Architecture freeze

`docs/ARCHITECTURE_FREEZE.md` governs every change here.

- [ ] This introduces **no** technology, table, migration, AI call, dependency or
      capability that is not already named in the freeze document
- [ ] If it does, an amendment issue is linked below with the **measurement that
      failed** — not an argument

Amendment issue (if any): #

## Verification

Paste the actual output, not a claim that it passed.

```
python -m ruff check .
python -m ruff format --check <the files this PR touches>
python -m pytest
```

- [ ] Lint and format clean
- [ ] Full suite green, and the pass count **went up or stayed the same**
- [ ] `python -m alembic heads` returns exactly one head
- [ ] `python scripts/check_schema.py --db <a copy>` passes
- [ ] The legacy contract holds: 459 leads, unchanged `intent_score`, 13 CSV
      columns, 17 endpoints (`tests/test_boundaries.py`)

## Migrations

- [ ] Not applicable
- [ ] Additive only — no column dropped, renamed or retyped
- [ ] `downgrade()` written **and tested** up → down → up against a copy of the
      live database
- [ ] Manual testing guide updated, including any hardcoded counts it asserts

## Secrets

- [ ] No key, token, proxy line, absolute local path or real Reddit username is
      added to the repository, a log, a test fixture or a doc
