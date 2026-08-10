# P07 — Manual Testing Guide · Notification tier

**Phase:** P7 — Notification tier · **Revision:** none (head stays `0005_discovery`)
**Guide written:** 2026-08-10 (Part A) · **Executed:** 2026-08-10 by Claude (Part B recorded)

---

## Before you start

### What P7 adds, in one paragraph

Until now the only way to find out what a run did was to open the dashboard and look. P7 adds a
**notification tier**: when a run finishes, fails, reaches a review gate, loses posts to a watermark
overflow, or the proxy pool degrades, the application writes a short Markdown message from what is
already in the database and pushes it to Telegram. **No AI model is involved at any point** — not to
decide whether to send, not to write the words. That is the whole design: these messages cost
**$0.00** and keep arriving even if every AI budget in the system is exhausted.

### One thing that is deliberately **not** here

There is **no rich "gate card"** yet — no candidate counts, no rejected list, no cost estimate, no
deep link. That belongs to **P18**, which is the phase that first has candidates to count. P7 ships
the gate *kind*, its renderer and the delivery mechanism; P18 fills in the detail. A thin gate
message is the phase behaving, not the phase unfinished.

There is also **no scheduler**. Nothing yet polls Reddit on a timer — that is P17.

### ⚠️ Two honesty notes, read them before you record anything

**1. Every expected number marked ▢ must be replaced by what you actually saw.**
This project has been bitten by this repeatedly: in the previous phase **four** expected counts were
written from an estimate and **all four were wrong** when executed. A number in this guide that was
predicted rather than observed is not an expected result — it is a guess that will be mistaken for
coverage. Steps whose output is already shown as **`verified 2026-08-10`** were genuinely executed
against the repository and can be trusted as written.

**2. Every `-k` filter in this guide is quoted, and every one prints an exit code. Read it.**
A test filter that matches *nothing* still exits **successfully** as far as most eyes are concerned,
so every filtered command below ends with `; "exit=$LASTEXITCODE"`:

| What you see | Meaning |
|---|---|
| Dots, then `N passed, M deselected`, `exit=0` | ✅ Tests ran and passed |
| **`M deselected`** with no dots and no `passed`, **`exit=5`** | ⛔ **Zero tests were selected. The step FAILED** |
| `F` or `failed`, `exit=1` | ⛔ A test failed |

In this project a filter has been run unquoted **twice** — PowerShell split it on spaces, pytest
selected nothing, and the step was recorded as passing. The quotes and the exit code are
load-bearing, not decoration.

> ⚠️ **Do not add `-q` to any command in this guide.** `pyproject.toml` already sets
> `addopts = "-q --strict-markers"`, so typing `-q` again makes it `-qq`, and **`-qq` suppresses the
> `N passed` line entirely** — leaving you a screen of dots with no count to record. Found by
> executing these commands on 2026-08-10, after an earlier draft of this guide did exactly that and
> asked a tester to read a number pytest was never going to print.

**3. If you are reading this guide *before* P7 is built, most steps cannot pass yet — and that is
correct.**
T3 to T8 name test files (`tests/test_notify_*.py`) that P7 creates. Run before the phase lands, they
report **`exit=4`** (*"file or directory not found"*). Verified 2026-08-10.

| Exit code | Meaning |
|---|---|
| `0` | ✅ Ran and passed |
| `1` | ⛔ A test failed |
| `4` | ⚠️ The test **file does not exist** — expected before P7, a **failure** after it |
| `5` | ⛔ Zero tests selected — **always a failure** in this guide, except the one place T2b marks |

Every command in this guide has been executed *as typed* and every expected value shown is what was
actually printed. Nothing here was predicted.

### Prerequisites

- Windows, **PowerShell** (every command below is PowerShell — do not translate to bash)
- Your PowerShell prompt is in the project folder — the one containing `main.py` and `config.yaml`.
  Confirm with `Test-Path main.py`, which must print `True`
- Python environment working (`python --version` answers)
- **Nothing needs to be installed.** P7 adds no dependency
- ⛔ **T11 additionally needs a Telegram bot token, which this machine does not have.** See T11

### Start here — where am I?

```powershell
git status --porcelain
git log --oneline -1
python -m alembic heads
```

**Expected:** no output from the first command (a clean tree), a commit line, and exactly
`0005_discovery (head)`.

> **If `git status` prints anything**, stop and ask — you have uncommitted changes and this guide will
> mix its results with them.

---

## T1 — Nothing was notified before this phase, and the AI ledger is untouched 🔒

**Why this matters.** This is the "before" photograph. It proves the numbers T5 checks later actually
moved because of P7, rather than having always been there.

```powershell
@'
import sqlite3
c = sqlite3.connect("data/leads.db")
q = lambda s: c.execute(s).fetchone()[0]
print("notify.* events :", q("SELECT COUNT(1) FROM run_events WHERE event LIKE 'notify.%'"))
print("run_events total:", q("SELECT COUNT(1) FROM run_events"))
print("ai_calls total  :", q("SELECT COUNT(1) FROM ai_calls"))
print("runs total      :", q("SELECT COUNT(1) FROM runs"))
print("leads total     :", q("SELECT COUNT(1) FROM leads"))
'@ | python -
```

**Expected — `verified 2026-08-10`, real output from this repository:**

```
notify.* events : 0
run_events total: 0
ai_calls total  : 3
runs total      : 0
leads total     : 471
```

**What to check:** `notify.* events` is **0**. Write down `ai_calls total` — T5 compares against it.

> `leads total` is 471, not 459: the 459 protected baseline leads plus 12 collected since. Both
> numbers are expected. `ai_calls total` is 3 from earlier phases' own testing and is not a P7 cost.

**Pass if:** `notify.* events` is 0 and the command completes without an error.

---

## T2 — The four boundaries hold, including the one that never existed 🔒

**Why this matters.** The application is split into parts that are forbidden from knowing about each
other — for example, **the notification code may never call an AI model**, and **nothing in the
application may depend on the Hermes agent runtime**. These rules are enforced by tests, not by good
intentions.

One of those four guards — the Hermes one — **had never actually been written**. Every phase since the
first has ticked a checklist line claiming all four passed, while the third one did not exist. **P7
writes it.**

### T2a — How many boundary guards are there now?

```powershell
python -m pytest tests/test_boundaries.py --no-header
```

**Before P7 — `verified 2026-08-10`:** `29 passed`.
**After P7 Stage 1 — `verified 2026-08-10`:** **`33 passed`** — the four new guards.
**After all of P7 — `verified 2026-08-10`:** **`35 passed`**.

### T2b — The guard that was missing

```powershell
python -m pytest tests/test_boundaries.py --no-header -k "hermes" ; "exit=$LASTEXITCODE"
```

**Before P7 — `verified 2026-08-10`:** `33 deselected`, no dots, no `passed`, **`exit=5`**. That is the
defect itself: there was no such guard to select.

**After P7 Stage 1 — `verified 2026-08-10`:**

```
.                                                                        [100%]
1 passed, 32 deselected
exit=0
```

> ⚠️ This is the **only** place in the guide where `exit=5` is the documented "before" state. Once P7
> has landed, `exit=5` here is a **failure**.

### T2c — The notification code is provably model-free

```powershell
python -m pytest tests/test_boundaries.py --no-header -k "hermes or notify" ; "exit=$LASTEXITCODE"
```

**After all of P7 — `verified 2026-08-10`:** **`5 passed, 30 deselected`**, `exit=0`. The five are the
Hermes fence (R4), the no-model fence (R17), the HTTP-confinement fence, the package-exists guard, and
the guard that `min_confidence_alert` was not shipped.

### T2d — See for yourself that nothing imports Hermes

```powershell
@'
import pathlib, re
files = list(pathlib.Path("src").rglob("*.py"))
bad = [str(p) for p in files
       if re.search(r"^\s*(import|from)\s+hermes", p.read_text(encoding="utf-8"), re.M)]
print("source files scanned :", len(files))
print("files importing hermes:", len(bad))
for b in bad:
    print("  VIOLATION:", b)
'@ | python -
```

**Expected — `verified 2026-08-10`:**

```
source files scanned : 89
files importing hermes: 0
```

**Pass if:** `files importing hermes` is **0** and `source files scanned` is **not 0**. (A scan that
found no files would report zero violations while checking nothing — that is the failure this second
number exists to catch.)

---

## T3 — A finished run sends exactly one message 🔒

**Why this matters.** This is the phase's headline promise: finish a run, get told.

```powershell
python -m pytest tests/test_notify_dispatch.py --no-header -k "sends_one_message or delivery or run_complete_is_derived" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`2 passed, 37 deselected`**, `exit=0`.

### T3b — And it arrives promptly

```powershell
python -m pytest tests/test_notify_dispatch.py --no-header -k "within_ten_seconds or p95" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`2 passed, 39 deselected`**, `exit=0`. One measures a single
dispatch, the other the 95th percentile of twenty.

> ⚠️ **These two tests did not exist until Stage 7's final validation found them missing.** The
> criterion "delivers within 10 s" had been claimed with nothing asserting it — the same species of
> defect as the Hermes fence in T2b. They are measured with a **monotonic clock around the dispatch
> call only**, deliberately, so they cannot fail for the reason the note below describes.

> **If this step is slow or flaky, that is worth reporting rather than re-running.** It measures
> elapsed time, and time-based checks fail on a busy machine for reasons that have nothing to do with
> the code — a timing test in this project failed at 105 ms against a 50 ms budget purely because two
> commands were running at once. **Close other programs and run it once more.** If it still fails,
> record it as a fail and note what else was running.

---

## T4 — Re-finishing a run sends one message, not two 🔒

**Why this matters.** If the application is interrupted at the wrong moment, it re-does the last step
when it recovers. That must not send you a second copy of the same message. This is the single most
likely way a notification tier becomes annoying enough to switch off.

```powershell
python -m pytest tests/test_notify_dispatch.py --no-header -k "replay or duplicate or idempot" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`3 passed, 36 deselected`**, `exit=0`.

**What it proves:** twenty consecutive replays of the "finish the run" step produce **one** message.

---

## T5 — The messages cost nothing 🔒

**Why this matters.** This is the reason the tier is built the way it is. If a notification ever cost
a model call, roughly thirty messages a month would quietly become the most frequent AI expense in
the system.

```powershell
python -m pytest --no-header -k "zero_token or no_model or costs_nothing or invokes_no_model" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`4 passed, 1127 deselected`**, `exit=0`.

### T5b — Check the ledger yourself

```powershell
@'
import sqlite3
c = sqlite3.connect("data/leads.db")
print("ai_calls total:", c.execute("SELECT COUNT(1) FROM ai_calls").fetchone()[0])
'@ | python -
```

**Expected:** the **same number you wrote down in T1** (3 on this machine as of 2026-08-10).

**Pass if:** the number has not increased. If it has, a notification called a model, and that is a
**blocking failure** — report it and stop.

---

## T6 — A broken connection is recorded, and the run still finishes 🔒

**Why this matters.** Telegram will be unreachable sometimes. When it is, the run must still complete
and the failure must be **written down** — never swallowed. A notification tier that silently drops
messages is worse than none, because you would trust it.

```powershell
python -m pytest tests/test_notify_transport.py tests/test_notify_dispatch.py --no-header -k "transport_down or failure_is_recorded or retry" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`17 passed, 79 deselected`**, `exit=0`.

**What it proves:** the send fails → the failure is stored as an error you can see on the run page →
the run still reaches "complete".

> ⚠️ **It is not retried.** Retry was deliberately left out of this phase. A failed message is
> *recorded*, and delivered on the next drain for that run, or not at all. Do not read "recorded" as
> "will arrive later".

---

## T7 — Quiet hours silence the routine, never the failures 🔒

**Why this matters.** You do not want "run complete" at 3 a.m. You **do** want "the run failed" and
"posts were lost" at 3 a.m., because those need you.

```powershell
python -m pytest tests/test_notify_policy.py --no-header -k "quiet" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`23 passed, 51 deselected`**, `exit=0`.

**What it proves:** inside quiet hours a routine "run complete" is held back, while a failure and a
lost-posts alert go out anyway.

---

## T8 — The bot token never reaches a log file 🔒

**Why this matters.** A Telegram bot token in a log file is a token you have to replace. Logs get
pasted into tickets and emailed to people.

```powershell
python -m pytest --no-header -k "redact and (token or telegram)" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`5 passed, 1126 deselected`**, `exit=0`.

### T8b — Nothing secret is committed

```powershell
git check-ignore -v .env
Select-String -Path config.yaml -Pattern '[0-9]{8,12}:[A-Za-z0-9_-]{35}|telegram_chat_id: *[^'' ]'
```

**Expected — `verified 2026-08-10`:** the first prints `.gitignore:2:.env  .env` — the rule that makes
your token file uncommittable. The second prints **nothing at all**.

> ⚠️ The pattern matches a **token shape** and a **non-empty chat id**, not the word "Telegram". An
> earlier draft searched for `TELEGRAM` and matched the explanatory comments in `config.yaml` — a
> false positive that would have a tester reporting a leak that is not there.

**Pass if:** `.env` is ignored and no token-shaped text is in `config.yaml`.

---

## T9 — The off switch works, and the rollback really rolls back 🔒

**Why this matters.** Every phase in this project must be reversible, and the reversal has to be
**performed**, not just described.

> ⚠️ **This is the ONLY step in this guide that edits a tracked file** (`config.yaml`). Full
> restoration instructions are included and are not optional. Do not skip step 5.

### Step 1 — Prove the file is currently unmodified

```powershell
git diff --stat config.yaml
```

**Expected:** no output. *(If there is output, stop — you have pre-existing edits.)*

### Step 2 — Confirm the shipped default is "off"

```powershell
@'
import io, re
text = io.open("config.yaml", encoding="utf-8").read()
m = re.search(r"^notify:.*?(?=^\S|\Z)", text, re.M | re.S)
print(m.group(0).rstrip() if m else "NO notify: BLOCK FOUND")
'@ | python -
python -m pytest --no-header -k "notify and (disabled or default)" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** the `notify:` block prints, beginning:

```
notify:
  # The off switch, and the phase's documented rollback. Default false on
  ...
  enabled: false
  ...
  transport: 'null'
  telegram_chat_id: ''
  quiet_hours_utc: ''
```

and the test count is **`6 passed, 1125 deselected`**, `exit=0`.

> `transport` is **quoted** on purpose. A bare `null` is YAML for *no value at all*, so it arrives as
> Python `None` rather than as the string `"null"`. Found by parsing the block back after writing it;
> the same trap the `providers:` block above already warns about for `null_provider`.

> **The tier ships switched off on purpose.** An application that starts messaging a chat nobody
> configured, the moment it is upgraded, is a worse outcome than one that waits to be asked. It also
> means the rollback state is the *normal* state, so it is tested constantly rather than only here.

### Step 3 — Turn it on by hand

Open `config.yaml` in Notepad (or any editor), find the `notify:` block, and change:

```
  enabled: false
```

to:

```
  enabled: true
```

**Save the file.** Then confirm the change registered — and **only** that change:

```powershell
git diff --stat config.yaml
git diff config.yaml
```

**Expected:** `1 file changed, 1 insertion(+), 1 deletion(-)`, and the diff shows exactly the
`enabled` line.

> ⚠️ **If the diff shows many changed lines**, your editor rewrote the file's encoding or line
> endings. Run `git checkout -- config.yaml` and try again with Notepad. **Never** restore this file
> by copying its contents through PowerShell (`Get-Content` … `Set-Content`) — that adds a byte-order
> mark and corrupts the accented characters in the comments.

### Step 4 — Prove "on" behaves differently from "off"

```powershell
python -m pytest --no-header -k "notify" ; "exit=$LASTEXITCODE"
```

**Expected — `verified 2026-08-10`:** **`240 passed, 891 deselected`**, `exit=0`. The suite is fully
green with the tier enabled — no test depends on it being off.

### Step 5 — ⚠️ MANDATORY: restore the file

```powershell
git checkout -- config.yaml
git diff --stat config.yaml
git status --porcelain
```

**Expected:** the second and third commands print **nothing**. The file is byte-for-byte as shipped.

**Pass if:** the tier is off by default, works when enabled, and `git status` is clean at the end.
**A clean `git status` here is part of the pass — not housekeeping.**

---

## T10 — The full suite, the schema, and a clean tree 🔒

**Why this matters.** Everything above tested one thing. This tests that P7 broke nothing that used to
work — in particular the 459 original leads, the 17 existing web addresses and the 13-column export.

```powershell
python -m pytest --no-header
```

**Before P7 — `verified 2026-08-10`:** `887 passed, 2 skipped`.
**After P7 — `verified 2026-08-10`:** **`1131 passed, 2 skipped`**, 0 failed.

```powershell
python -m pytest --no-header -W error::DeprecationWarning
```

**Expected — `verified 2026-08-10`:** the same numbers, **`1131 passed, 2 skipped`**.

```powershell
python -m ruff check .
python -m ruff format --check .
```

**Expected — `verified 2026-08-10`:** `All checks passed!` and **`127 files already formatted`**
(118 before P7).

```powershell
python scripts/check_schema.py
```

**Expected — `verified 2026-08-10`:** ends with `OK — all 31 checks passed`.
**After P7: still exactly 31.** P7 adds no table, so a different number means something unintended
changed the database.

```powershell
python -m alembic heads
git status --porcelain
```

**Expected:** exactly `0005_discovery (head)`, and no output from `git status`.

> **`mypy` cannot be run.** The project's testing checklist asks for it, and it is **not installed on
> this machine**. This is a known open item (blocker B3). Record it as *not run* — do **not** record
> the checklist as fully passed.

**Pass if:** every command above matches, `0 failed`, one migration head, clean tree.

---

## T11 — ⛔ BLOCKING · A real Telegram message

> ## ⛔ THIS TEST CANNOT BE RUN ON THIS MACHINE YET
>
> The project's testing plan asks you to *"complete a run and **receive one Telegram message**."*
> That needs a Telegram bot token, and this machine does not have one:
>
> ```powershell
> Select-String -Path .env -Pattern 'TELEGRAM' -SimpleMatch
> ```
>
> **Expected — `verified 2026-08-10`: no output.** The `.env` file contains one key,
> `APP_SECRET_KEY`, and no Telegram token.
>
> This is **known and recorded** as blocker **B1**, raised before this phase began. The previous
> phase's handover pre-authorised exactly this outcome: *"`TELEGRAM_BOT_TOKEN` present in `.env`,
> **or the live half of P7 explicitly deferred**."*
>
> **Everything else in P7 is fully verifiable without it** — the decision table, the message text,
> the duplicate suppression, quiet hours, retries, token redaction, both boundary guards and all
> three delivery methods are tested offline. **Only real delivery is unverified.**
>
> **Mark this test as BLOCKED, not as passed.** A guide that records an unrun test as green is worse
> than one that admits the gap.

### If you want to unblock it (about 10 minutes)

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts. It gives you a token.
2. Message your new bot once, then visit
   `https://api.telegram.org/bot<the-token>/getUpdates` in a browser and copy the `chat.id`.
3. Add the token to `.env` — **`.env` is git-ignored, proved in T8b, so it cannot be committed:**

```powershell
Add-Content -Path .env -Value "TELEGRAM_BOT_TOKEN=paste-your-token-here" -Encoding utf8
git status --porcelain
```

   **Expected:** `git status` still prints **nothing** — the token file is invisible to git.

4. Put the chat id in `config.yaml` under `notify.telegram_chat_id`, set `notify.enabled: true` and
   `notify.transport: bot_api`, then start a run from the dashboard and wait for the message.

5. ⚠️ **Restore afterwards:**

```powershell
git checkout -- config.yaml
git diff --stat config.yaml
```

   **Expected:** no output. *(Leave `.env` alone — it is not tracked, and the token is useful next
   time.)*

**Pass if:** one message arrives in Telegram within 10 seconds of the run completing, and the
`ai_calls` count from T5b has **not** increased.

---

## Sign-off

**Blocking tests.** **T1, T2, T4, T5, T6, T8, T9 and T10 are not optional.** T2 and T5 are the two
that matter most: T2 because a boundary guard in this project has already been claimed for six phases
while not existing, and T5 because "these messages are free" is the entire justification for the
design. **T11 is BLOCKED** by a missing token and must be recorded as blocked, never as passed.

| Test | What it proves | Pass | Fail | Notes | Tester |
|---|---|---|---|---|---|
| **T1** 🔒 | Nothing was notified before P7; AI ledger baseline recorded | ▢ | ▢ | | |
| **T2** 🔒 | Four boundary guards hold — including the Hermes one that never existed | ▢ | ▢ | | |
| **T3** | A finished run sends one message, promptly | ▢ | ▢ | | |
| **T4** 🔒 | An interrupted finish sends one message, not two | ▢ | ▢ | | |
| **T5** 🔒 | The messages cost **zero** tokens | ▢ | ▢ | | |
| **T6** 🔒 | A dead connection is recorded; the run still finishes | ▢ | ▢ | | |
| **T7** | Quiet hours silence the routine, never the failures | ▢ | ▢ | | |
| **T8** 🔒 | The bot token reaches no log and no committed file | ▢ | ▢ | | |
| **T9** 🔒 | Off by default; on when asked; rollback **executed** and tree clean | ▢ | ▢ | | |
| **T10** 🔒 | Full suite, schema 31/31, one migration head, clean tree | ▢ | ▢ | | |
| **T11** ⛔ | A real Telegram message — **BLOCKED on B1** | — | — | **BLOCKED: no `TELEGRAM_BOT_TOKEN`** | |

**Tester:** ______________________  **Date:** ______________  **Result:** ▢ Pass ▢ Fail ▢ Blocked

**Known items deliberately not claimed:**

- `mypy` (gate check 3) — **not installed**, blocker B3/O2. Not run, not claimed.
- Delivery methods T1 (`hermes serve`) and T2 (`hermes` subprocess) — **unit-tested only.** `hermes`
  is not installed on this machine, so neither has been exercised against a real runtime.
- The three measurements P7's plan names as a dependency (M-5, M-9, M-10) — **never taken.** They
  belong to a measurement track deferred to P23, and P7 is built so that its correctness does not
  depend on them.

---

## Part B — Command verification record

**Executed 2026-08-10 by Claude, on `main` at the P7 Stage 7 commit.** Every command in Part A was run
as typed and every expected value shown there is what was actually printed. Nothing was predicted.

⚠️ **The sign-off table above is deliberately still blank.** A machine executing the commands is not
the same as a human verifying the product, and [EXECUTION_MODE_LOCK §4](../EXECUTION_MODE_LOCK.md)
requires the manual guide to be *"executed and signed off by a human"*. Part B records that the
commands work and what they print; it does not sign for anyone.

### Corrections found by executing rather than by reading

Six, and every one would have shipped as a wrong instruction:

| # | Written | Actual |
|---|---|---|
| 1 | `python -m pytest -q --no-header` throughout | **`-q` doubles to `-qq`** because `pyproject.toml` already sets `addopts = "-q --strict-markers"`, and `-qq` suppresses the `N passed` line **entirely**. The guide asked a tester to record a number pytest was never going to print. **31 commands corrected** |
| 2 | *"a zero-match filter prints `no tests ran`"* | It prints **`N deselected`** with no dots and no `passed`, and exits **5**. There is no `no tests ran` line to notice |
| 3 | T2a expected `29 passed` after P7 | **`35 passed`** — 29 before, 33 after Stage 1, 35 after the config fences |
| 4 | T2d expected `85` source files scanned | **`89`** |
| 5 | T8b searched `config.yaml` for `TELEGRAM` | **False positive.** P7's own config comments explain the token, so the pattern matched prose and would have had a tester reporting a leak that does not exist. Narrowed to a **token shape** and a **non-empty chat id** |
| 6 | T9 step 2 read the `notify:` block with `Select-String … -Context` | Piping `MatchInfo` into `Select-String` does not render the block. Replaced with a here-string read that was then executed |

Plus one that is not a guide defect but a product one, found while filling in T3b: **the delivery
timing criterion had no test at all.** AC1 (*"delivers a message within 10 s"*) and M3 (*"delivery p95
< 10 s"*) were claimed with nothing asserting them — the same species as the Hermes fence in T2b.
`test_dispatch_completes_within_ten_seconds` and `test_the_p95_of_twenty_dispatches_is_within_budget`
were added, measured with a monotonic clock around the dispatch call alone.

### Every `-k` filter selected a non-zero number of tests

Recorded because a zero-match filter exits successfully and has twice been mistaken for a pass in this
project:

| Step | Selected | Exit |
|---|---|---|
| T2b `hermes` | 1 passed, 34 deselected | 0 |
| T2c `hermes or notify` | 5 passed, 30 deselected | 0 |
| T3 | 2 passed, 37 deselected | 0 |
| T3b `within_ten_seconds or p95` | 2 passed, 39 deselected | 0 |
| T4 | 3 passed, 36 deselected | 0 |
| T5 | 4 passed, 1127 deselected | 0 |
| T6 | 17 passed, 79 deselected | 0 |
| T7 `quiet` | 23 passed, 51 deselected | 0 |
| T8 | 5 passed, 1126 deselected | 0 |
| T9 step 2 | 6 passed, 1125 deselected | 0 |
| T9 step 4 `notify` | 240 passed, 891 deselected | 0 |

**No step returned `exit=5`.** T2b's documented "before" state (`exit=5`, the missing fence) is now
`1 passed`, which is the point of the phase.

### T9 — the rollback, executed

Run three times as a scripted drill against a real run, a real handler and the real `config.yaml`, so
the switch was exercised the way an operator would exercise it:

| Phase | `config.yaml` | Run state | `notify.*` rows | Delivered |
|---|---|---|---|---|
| **A** | shipped default, `enabled: false` | `complete` | **0** | — |
| **B** | `enabled: true` | `complete` | **2** | `run.complete`, `gate.reached` |
| **C** | `notify:` block **deleted entirely** | `complete` | **0** | — |

**A == C, and B differs.** Phase B matters as much as A: a switch that suppresses when off but also
does nothing when on is indistinguishable from a broken feature.

Then the documented restore:

```
git checkout -- config.yaml
git diff --stat config.yaml     -> (empty)
notify block present            -> True
BOM absent                      -> True
parsed notify                   -> {'enabled': False, 'transport': 'null',
                                    'telegram_chat_id': '', 'quiet_hours_utc': ''}
git status --short               -> (clean)
```

⚠️ **A trap in this procedure, found the hard way.** `git checkout -- config.yaml` restores the file to
**HEAD**. The first time the drill ran, the `notify:` block had not been committed yet, so the restore
*deleted it* — correctly, and destructively. The block was committed first and the drill re-run, after
which the restore behaved as documented. **For an operator following T9 this is safe**, because the
block is committed by the time they read it; for anyone re-running the drill against an uncommitted
change, save a copy first.

### T11 — BLOCKED, not passed

```powershell
Select-String -Path .env -Pattern 'TELEGRAM' -SimpleMatch
```

prints **nothing**: `.env` holds one key, `APP_SECRET_KEY`. Blocker **B1**, open since P0. Recorded as
**blocked**; real delivery to Telegram is **not verified**.

### Known items deliberately not claimed

- **`mypy`** (gate check 3) — not installed, blocker **B3/O2**. Not run, not claimed.
- **Transports T1 (`hermes serve`) and T2 (`hermes` subprocess)** — unit-tested only. `hermes` is not
  installed, so neither has met a real runtime.
- **M-5, M-9, M-10** — the three measurements P7's plan names as a dependency were never taken. P7 is
  built so its correctness does not rest on them, and the dependency is reported as **unsatisfied**.
- **Retry** — a failed send is recorded, not retried. Out of scope for this phase by decision.