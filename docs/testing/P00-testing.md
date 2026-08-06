# Manual Testing Guide — P0: Validation Sprint

Written so a **non-developer can verify this phase without guessing**. Every step states what you
should see. If what you see differs, that step's *Possible failure* section tells you what it means.

- **Time:** ~25 minutes for the full suite; ~6 minutes for the smoke path (T1–T3).
- **You need:** a terminal. No browser, no API key, no Telegram account.
- **Destructive steps:** **none.** P0 writes nothing to the application database and nothing under
  `src/`. T7 exists specifically to prove that.
- **Note on timing:** T4 and T5 make real requests to Reddit and deliberately pause between them.
  Reddit rate-limits RSS to one request per minute per address, so a slow test is a *correct* test.

Throughout, `>` marks a command to run and `→` marks what you should see.

---

## Before you start

**Start in the project root.** Every command below is relative to it, so nothing in this guide
contains a machine-specific path:
```
> cd <the folder containing pyproject.toml>
```

**One thing this guide cannot make relative.** T3, T4 and T5 need your **proxy credentials file**,
which lives outside the repository *by design* — a credentials file inside the repo is a credentials
file that gets committed (R15). Set its location once and the later steps refer to the variable:
```
> $env:PROXY_FILE = "<full path to your proxy list .txt>"
```
→ On macOS or Linux: `export PROXY_FILE="<full path>"`.

**If the dashboard is running, stop it.** A stale process holds port 5000 and serves *old code*,
which looks exactly like a broken change:

```
> powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force"
```
→ No output, or an error saying no process matched. Both are fine.

**Confirm the interpreter:**
```
> .\.venv\Scripts\python.exe --version
```
→ `Python 3.12.5`

---

# T1 — The probe code is clean

**Objective:** the code written for P0 passes lint and formatting.
**Preconditions:** none.

### Step 1
```
> .\.venv\Scripts\python.exe -m ruff check scripts/probe tests/unit/test_probe_transport.py
```
→ **Expected:** `All checks passed!`

### Step 2
```
> .\.venv\Scripts\python.exe -m ruff format --check scripts/probe tests/unit/test_probe_transport.py
```
→ **Expected:** `6 files already formatted`

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `Found N errors` | Lint regressions were introduced | Run the same command with `--fix`, then re-run Step 1 |
| `N files would be reformatted` | Formatting drifted | Run `ruff format` (without `--check`), then re-run Step 2 |
| `No module named ruff` | Wrong interpreter | Use `.\.venv\Scripts\python.exe`, not a global `python` |

**Screenshot expected:** none.
**Logs to verify:** none.
**Database values:** none.
**API response:** none.

**Acceptance:** ✅ Both commands report clean.

---

# T2 — The whole test suite passes

**Objective:** P0 broke nothing that already worked, and the new safety tests pass.
**Preconditions:** T1 passed.

### Step 1
```
> .\.venv\Scripts\python.exe -m pytest
```
→ **Expected**, on the last line:
```
308 passed, 2 skipped
```
→ The count must be **308 or more**, and **`failed` must not appear**. The elapsed time varies and
does not matter.

> The figure was `265` when P0 was signed off. P1 added 36 tests and the P1 verification pass added
> nine more. A **higher** number is correct; a lower one means tests were lost.

> **The 2 skipped are correct, not a regression.** Both parse a *real* proxy credentials file, which
> lives outside the repository by design (R15), so they skip unless `PROXY_FILE` points at one. With
> `PROXY_FILE` set the suite reports `310 passed, 0 skipped`. Either line passes this step.

### Step 2
Confirm the new credential-safety tests ran:
```
> .\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_transport.py -v
```
→ **Expected:** 10 tests, all `PASSED`, including:
```
test_repr_never_contains_credentials PASSED
test_url_does_contain_credentials PASSED
test_disabled_provider_refuses_every_call PASSED
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N failed` | A real regression | Read the failure; do **not** edit the assertion to make it pass |
| `no tests ran` | Wrong directory | `cd` to the project root first |
| `300 passed` | The probe test file is missing | Confirm `tests/unit/test_probe_transport.py` exists |

**Logs to verify:** the 9 warnings are pre-existing `datetime.utcnow()` deprecations in SQLAlchemy.
They are expected and are not caused by P0.

**Acceptance:** ✅ 308+ passed, 0 failed (2 skipped is expected), 10 probe tests present.

---

# T3 — Credentials never leak

**Objective:** proxy usernames and passwords appear nowhere they could be logged.
**Preconditions:** T2 passed.

### Step 1
```
> .\.venv\Scripts\python.exe -c "import os; from scripts.probe.transport import parse_proxy_file; e = parse_proxy_file(os.environ['PROXY_FILE'])[0]; print('repr :', repr(e)); print('str  :', str(e)); print('label:', e.label)"
```
→ **Expected**, three lines of the form:
```
repr : _Endpoint(31.59.20.176:6754)
str  : _Endpoint(31.59.20.176:6754)
label: 31.59.20.176:6754
```
→ **Each line shows only an address and a port.** No username. No password.

### Step 2
Confirm the deliberate exception — the one place credentials *must* appear:
```
> .\.venv\Scripts\python.exe -c "import os; from scripts.probe.transport import parse_proxy_file; e = parse_proxy_file(os.environ['PROXY_FILE'])[0]; print('has creds:', '@' in e.url and e.url.startswith('http://'))"
```
→ **Expected:** `has creds: True`

**Why this second step matters:** a suite that only asserted "no credentials anywhere" would pass
just as happily against a pool that could not authenticate at all. This pins that the credential
*is* present exactly where it is needed.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| A username or password in Step 1 output | **Serious** — redaction is broken | Stop. Report it. Do not run any probe that logs endpoints |
| `KeyError: 'PROXY_FILE'` | The variable was not set | Re-run the `$env:PROXY_FILE` line in *Before you start* — it is per-terminal |
| `FileNotFoundError` | Proxy file moved or renamed | Check the path in `$env:PROXY_FILE`, including any spaces or `(1)` in the filename |
| `has creds: False` | Endpoints cannot authenticate | The URL builder is broken |

**Acceptance:** ✅ Step 1 shows only `host:port`; Step 2 shows `True`.

---

# T4 — Transport comparison reproduces

**Objective:** confirm the headline finding — direct beats the datacenter proxy pool.
**Preconditions:** internet access. Takes ~2 minutes (requests are deliberately paced).

### Step 1
```
> .\.venv\Scripts\python.exe -m scripts.probe.probe_transport "$env:PROXY_FILE"
```
→ **Expected console output**, one line per request:
```
  [direct  ] ok            200     984ms  115128B posts=25  local
  [direct  ] ok            200    1391ms  133156B posts=25  local
  ...
  [webshare] ok            200    3391ms  175671B posts=25  31.59.20.176:6754
  [webshare] hard_block    403    1469ms    1522B posts=0   45.38.107.97:6014
```

### Step 2
Read the `recommendation` block at the end.
→ **Expected:**
```
"recommendation": "direct",
"direct_success_rate": 1.0,
"webshare_success_rate": 0.714,
```
→ `direct_success_rate` should be **1.0** (or ≥0.85).
→ `webshare_success_rate` should be **materially lower** (measured 0.714 twice).

### Step 3
Confirm no IP leak.
→ **Expected**, near the end:
```
LEAKS    []
```
→ An **empty list** means no proxy exited from your own address.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `direct` shows `hard_block 403` | A header set was changed, or your address is genuinely blocked | Check `src/net/user_agents.py` is unmodified. This was the exact 2026-07-31 bug |
| `LEAKS` is non-empty | **Serious** — a proxy is not proxying | Stop scraping through it. Check the proxy account |
| All webshare rows are `hard_block` | The proxy account expired or the pool is fully burned | Direct still works; this strengthens the recommendation |
| `recommendation: webshare` | The measurement disagrees with the report | Re-run. If it repeats, the conclusion has changed and P0 must be re-reported |

**Logs to verify:** every `[webshare]` line ends in a `host:port` label — **never** a username.

**Database values:** none — this probe does not open the database.

**Acceptance:** ✅ `recommendation` is `direct`, and `LEAKS` is empty.

---

# T5 — RSS behaves as measured

**Objective:** confirm RSS carries bodies, honours `limit=100`, and is rate-limited per address.
**Preconditions:** internet access. **Takes ~10 minutes** — the pauses are the point.

### Step 1
```
> .\.venv\Scripts\python.exe -m scripts.probe.probe_rss_limits
```
→ **Expected:** the script announces `Cooling down 75s before first probe...` and then prints one
line per probe.

### Step 2
Read the `baseline_SaaS` line.
→ **Expected:** status `200`, `25 entries`, and a headers block containing:
```
"x-ratelimit-used": "1", "x-ratelimit-remaining": "0.0"
```

### Step 3
Read the `immediate_different_feed` line and the `U1_verdict`.
→ **Expected:** the second feed returns **429**, and:
```
"U1_verdict": "per_ip"
```
→ This is the finding that makes multireddit combining mandatory.

### Step 4
Read `recovery_seconds`.
→ **Expected:** `60` (30 s returns 429; 60 s returns 200).

### Step 5
Read the `verdicts` block.
→ **Expected:**
```
"multireddit_works": true,
"restricted_search_works": true,
"U3_boolean_search_works": true,
"U6_old_host_works": true
```

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| Every step returns 429 | You are still inside a penalty window | Wait 5 minutes and re-run. Do not shorten the sleeps |
| `U1_verdict: per_feed` | Reddit changed its limit — **favourable** | Update `docs/28` §2.1; more headroom than assumed |
| `multireddit_works: false` | Multireddit was withdrawn — **serious** | Discovery would need one request per subreddit. Escalate |
| `etag_present: true` | Reddit added conditional GET — **favourable** | U4 could be reinstated; update `docs/28` §5.1 |

**Acceptance:** ✅ `U1_verdict` is `per_ip`, all four `verdicts` are `true`.

---

# T6 — Environment and the live database

**Objective:** confirm the host can support the planned stack, and the live database is untouched.
**Preconditions:** none. Uses one Reddit request.

### Step 1
```
> .\.venv\Scripts\python.exe -m scripts.probe.probe_env
```
→ Prints one JSON document.

### Step 2
Find the `live_database` block.
→ **Expected exactly:**
```
"leads": 459,
"intent_score_min": 5.0,
"intent_score_max": 164.28,
"intent_score_avg": 42.29,
"alembic_version": "0003_net_infrastructure",
"mtime_unchanged": true
```
→ **`leads` must be 459** and **`mtime_unchanged` must be `true`**.

### Step 3
Find the `sqlite` block.
→ **Expected:**
```
"wal_supported": true,
"enable_load_extension_works": true
```

### Step 4
Find the `credentials` block.
→ **Expected:** `present_in_env` contains `APP_SECRET_KEY`, and `required_but_missing` lists
`DEEPSEEK_API_KEY` and `TELEGRAM_BOT_TOKEN`.
→ **This is the documented blocker B1, not a fault.**

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `leads` is not 459 | The live database changed | **Stop.** Restore from `data/backups/` |
| `mtime_unchanged: false` | Something wrote to the database | P0 must not write. Investigate before continuing |
| `enable_load_extension_works: false` | The semantic tier cannot work on this host | Not fatal — AD-16 degrades. Record it |
| `post_volume.status: 429` | Rate-limited | Wait 60 s and re-run. Harmless |

**Database values to verify:** the four `intent_score` figures above are the documented fingerprint
from `docs/00-current-state.md` §6. They must match exactly.

**Acceptance:** ✅ 459 leads, fingerprint matches, `mtime_unchanged: true`.

---

# T7 — P0 wrote no production code

**Objective:** prove the phase respected its own constraint.
**Preconditions:** none.

### Step 1
```
> powershell "Get-ChildItem -Recurse src -Include *.py | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-1) } | Select-Object FullName, LastWriteTime"
```
→ **Expected:** **no rows**. Nothing under `src/` was modified today.

### Step 2
```
> powershell "Get-ChildItem data -Filter *.db | Select-Object Name, Length, LastWriteTime"
```
→ **Expected:** `leads.db` with a `LastWriteTime` **older than this session**.

### Step 3
Confirm what P0 *did* create:
```
> powershell "Get-ChildItem -Recurse scripts\probe, docs\measurements -File | Select-Object Name"
```
→ **Expected:** `transport.py`, `probe_transport.py`, `probe_rss.py`, `probe_rss_limits.py`,
`probe_env.py`, `p0-transport.json`.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| Any file under `src/` modified today | P0 exceeded its scope | Revert it. P0 is measurement only |
| `leads.db` modified today | The database was written to | Restore from backup and investigate |

**Acceptance:** ✅ Nothing under `src/` changed; `leads.db` untouched; probe artefacts present.

---

## Rollback verification

**Purpose:** prove P0 can be undone. It is the easiest rollback in the project — P0 added files and
changed nothing.

### Step 1
```
> powershell "Remove-Item -Recurse -Force scripts\probe, docs\measurements, tests\unit\test_probe_transport.py -ErrorAction SilentlyContinue"
```
*(Only run this if you actually want to remove P0. It is reversible only from version control.)*

### Step 2
Confirm the application is unaffected:
```
> .\.venv\Scripts\python.exe -m pytest -q
```
→ **Expected:** 300 passed (the 10 probe tests are gone), **0 failed**.

### Step 3
```
> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db --skip-p1
```
→ **Expected:** `OK — all 5 checks passed.`, including `PASS  leads = 459`.
→ `--skip-p1` is right here: this is P0's rollback check, and P0 predates the 0004 tables.

**Acceptance:** ✅ The suite still passes and the database still has 459 leads.

---

## Coverage — every acceptance criterion maps to a step

| P0 acceptance criterion (doc 34) | Verified by |
|---|---|
| All 16 testable questions answered and recorded | T4, T5, T6 + `docs/SPRINT-0-MEASUREMENTS.md` |
| Each answer states which decision it settles | Report §5, §6 |
| Conflicting or surprising results flagged | Report §3.3 (volume anomaly), §7 (fence defect) |
| Provider decision (V-1) made | **Deferred** — blocker B1, report §4 |
| **No file under `src/` modified; live DB untouched** | **T7** |
| Go/no-go recorded for RSS, direct-first networking, Hermes | Report §2.4, §1.6, §4 |

---

## Sign-off

| Check | Pass |
|---|---|
| T1 — lint and format clean | ☐ |
| T2 — 308+ tests pass, 0 failed (2 skipped is expected) | ☐ |
| T3 — credentials never leak | ☐ |
| T4 — recommendation is `direct`, no IP leak | ☐ |
| T5 — RSS verdicts as measured | ☐ |
| T6 — 459 leads, fingerprint intact | ☐ |
| T7 — nothing under `src/` changed | ☐ |
| Rollback verified | ☐ |
| No unexpected errors in any output | ☐ |

**Tester:** __________  **Date:** __________
