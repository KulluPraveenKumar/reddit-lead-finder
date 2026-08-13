# P09 — Manual Testing Guide · Rule engine

**Phase:** P9 (frozen numbering) · **Revision:** none — P9 adds no migration
**Part A written:** 2026-08-13 · **Part B:** to be executed against the finished phase

> ⚠️ **This guide is written before the code exists.** Every expected output below is **predicted,
> not measured**. Before this guide ships, every command is executed against the finished phase and
> the predictions are corrected in [Part B](#part-b--execution-record) — because two guides in this
> project have already shipped with commands that could not produce the output they promised
> ([DI19](../DEFERRED-IMPROVEMENTS.md), and P7's 31 corrections).
>
> ⚠️ **This is not `docs/testing/phase-06-testing.md`.** That file belongs to the superseded
> eight-phase numbering and covers scraping, comments, dedup and pre-scoring all at once. If you
> opened a guide about MinHash and comment scrapers, you have the wrong file.

---

## Before you start

### What P9 adds, in one paragraph

**A filter, and nothing that uses it yet.** P9 teaches the system to recognise five kinds of Reddit
post that are never worth paying to analyse — a hiring ad, a giveaway, a weekly megathread, an AMA,
and a bot or deleted account — plus posts containing words you have said you do not care about, and
posts too short to say anything. It adds **no page, no button, no message, and no database change.**
Nothing in the app calls it yet: the parts that will are P10 and P11.

Because there is no page to look at, this phase ships a small command that lets you ask it about one
post at a time. **That command is how you test this phase.**

### The one thing this phase is really about

There is a rule in this project that the filtering code must **never** be able to reach the AI code.
That rule is the reason the whole system is cheap to run — if filtering could quietly call a model,
the thing built to avoid paying would be the thing doing the paying. Until this phase, **nothing
checked it** for this part of the code.

**T6 is the test for that.** If you only have time for two tests, do T2 and T6.

### ⚠️ Three honesty notes — read before recording anything

1. **A step that fails is a result, not your mistake.** Write down exactly what appeared, including
   the error text. Do not re-run it until it passes and record that.
2. **Your lead total is not fixed.** The scraper keeps running. **459 is the only number that must
   never change** — it is the frozen guarantee. Everywhere else, compare against the total from T1.
3. **Nothing in this phase should change the database.** If any number in T1 moves, something is
   wrong — P9 is not supposed to be able to write anything.

### Prerequisites

- Windows, PowerShell, the project's virtual environment active, and you are in the project folder
- **You do not need to understand code.** Every command is copy-paste.

### ⚠️ These commands are PowerShell, and the quoting matters

Copy them exactly, including which quotes are double and which are single. **Do not translate them
into bash or Git Bash.**

> **This is not fussiness.** An earlier guide in this project used a different quote style and *every
> command in it was a silent parse error* — PowerShell printed a complaint and ran nothing, which in
> a hurried read looks a lot like a test that passed.

### Start here — where am I?

```powershell
git log --oneline -1
python -m alembic heads
```

**Expected once P9 has shipped:** the newest commit mentions `P9`, and `alembic heads` prints exactly
one line, ending `(head)` and naming `0006_content_and_dedup`.

⚠️ **`0006` is correct and important.** P9 adds **no** migration. If this names anything other than
`0006_content_and_dedup`, stop — something was built that should not have been.

---

## T1 — Nothing was lost 🔒

P9 should not have touched the database at all. This proves it.

```powershell
python scripts\check_schema.py
```

**Expected:** ends with `OK — all 51 checks passed`, and includes:

```
PASS  the 459 original leads are all still present
PASS  max(intent_score) over the original leads = 164.28
PASS  avg(intent_score) over the original leads = 42.29
```

- [ ] The 459 original leads are all still present
- [ ] `max` is `164.28` and `avg` is `42.29`
- [ ] **Total lead count:** ______ ← *call this "the T1 total"*
- [ ] **Check count:** ______ *(expected `51` — unchanged from P8, because P9 adds no schema)*

---

## T2 — ⭐ The rule engine judges a post 🔒

This is the phase, in one command. You type a post title; it tells you whether it would be kept and
why.

**A post it should throw away:**

```powershell
python -m src.rules "Weekly megathread - ask your questions here"
```

**Expected:** a line saying it was rejected, naming `structural_noise`, and naming `megathread` as
the specific reason.

**A hiring ad:**

```powershell
python -m src.rules "[HIRING] Senior Python developer, remote"
```

**Expected:** rejected · `structural_noise` · `hiring`.

**A post it should keep:**

```powershell
python -m src.rules "Looking for a tool to track competitor pricing"
```

**Expected:** **admitted.** No rejection reason.

- [ ] The megathread is rejected, and the output names `megathread`
- [ ] The hiring ad is rejected, and the output names `hiring`
- [ ] The genuine question is **admitted**
- [ ] **Write down exactly what the first command printed:** ______________________________

---

## T3 — ⭐ A real lead is not thrown away 🔒

The risk with a filter is not that it misses junk — it is that it silently discards good leads. This
post contains the word "hiring", but it is exactly the kind of conversation this whole system exists
to find.

```powershell
python -m src.rules "Our hiring process is broken and I need a tool to fix it"
```

**Expected:** **admitted.** Not rejected.

> **Why this matters more than it looks.** If this comes back rejected, the filter is throwing away
> real customers who happen to use a common word, and **nothing else in the system would ever tell
> you.** There is no report that shows you the leads you never collected.

- [ ] The post is **admitted**
- [ ] If it was rejected, write down exactly what it said: ______________________________

---

## T4 — The off switch really switches off 🔒

Every phase must be reversible, and the reversal must be *seen to work*, not just described.

**You do not need to edit any file for this test.** The command takes the switch as an option, so you
can watch it work without touching your configuration.

**Step 1 — the filter on (this is the normal state):**

```powershell
python -m src.rules "Weekly megathread - ask your questions here"
```

**Expected:** rejected · `structural_noise` · `megathread` — the same as T2.

**Step 2 — the filter off:**

```powershell
python -m src.rules --rules-enabled false "Weekly megathread - ask your questions here"
```

**Expected:** **admitted.** With the filter off, nothing is rejected.

**Step 3 — confirm the setting in your file is still on:**

```powershell
Select-String -Path config.yaml -Pattern 'rules_enabled'
```

**Expected:** one line reading `rules_enabled: true`.

> ⚠️ **If you would rather test it by editing `config.yaml`, you may — but save the file as
> UTF-8 *without* a BOM.** Notepad's default on Windows can add an invisible marker to the start of
> the file, after which every command in this project fails with `Missing required config key:
> subreddits` — which looks exactly like a defect in this phase and is not one. The `--rules-enabled`
> option above exists so you never have to take that risk.

- [ ] With the filter on, the megathread is **rejected**
- [ ] With `--rules-enabled false`, it is **admitted**
- [ ] `config.yaml` still reads `rules_enabled: true` and was never edited

---

## T5 — The competitor rule is deliberately asleep 🔒

P9 builds the ability to spot a competitor's name in a post, but **the list of competitors does not
exist yet** — it comes from your business profile, which is built in a much later phase. This test
confirms that is a deliberate state and not a bug.

```powershell
python -m pytest tests\test_boundaries.py -k "competitor"
```

**Expected:** ends with `1 passed`. That test is the enforcement: it **fails** if anyone wires the
competitor list up before the phase that owns it.

> **Why this is a test and not an omission.** A competitor rule that quietly matches nothing looks
> exactly like a business with no competitors. So switching it on later has to be a deliberate act —
> someone has to delete that test on purpose — rather than something discovered by accident.

> ⚠️ **Do not test this by searching `config.yaml` for the word "competitors".** The configuration
> file explains, in a comment, *why* the key is deliberately absent — so a word-search finds the
> explanation and reports a failure on correct code. This project has already recorded that trap
> twice ([ARCHITECTURE_FREEZE §11.1](../ARCHITECTURE_FREEZE.md)): a check that matches prose forces
> someone to delete the sentence explaining why the rule exists. The automated test above reads the
> settings, not the prose.

- [ ] The test passed
- [ ] You understand this rule is intentionally inactive until a later phase

---

## T6 — ⭐ The filter cannot reach the AI code 🔒

The rule that makes this system cheap.

```powershell
Get-ChildItem src\rules -Filter *.py -Recurse | Select-String -Pattern 'import.*src\.ai'
```

**Expected:** **no output at all.** Not "0 results" — literally nothing printed.

> ⚠️ **This command alone is not sufficient, and you should know why.** It also prints nothing if the
> `src\rules` folder has been deleted — verified 2026-08-13, when it printed nothing and raised no
> error against a tree where the folder did not exist. So a blank result means *either* "the boundary
> holds" *or* "there is no code left to check." **The second command below is the half that tells
> them apart:** one of its two tests exists solely to fail if the package disappears.

Now confirm the automatic version of this check is running, so it is enforced on every future change
rather than only when someone remembers:

```powershell
python -m pytest tests\test_boundaries.py -k "rules"
```

**Expected:** ends with something like `2 passed` — one test that the filtering code imports no AI
code, and one that fails if the filtering code is deleted.

⚠️ **Do not add `-q` to that command.** This project is configured so that `-q` hides the summary
line you are being asked to read ([DI19](../DEFERRED-IMPROVEMENTS.md)).

- [ ] The first command printed **nothing**
- [ ] The second command passed
- [ ] **How many tests passed:** ______

---

## T7 — Nothing that used to work has stopped working 🔒

```powershell
python -m pytest
```

This takes about six minutes. Let it finish.

**Expected:** the last line reads `NNNN passed, 2 skipped`, with **no failures**.

The count was **1148 passed, 2 skipped** before this phase and will be higher now.

⚠️ **If it reports a failure, do not re-run it and record the second result.** Write down which test
failed. A re-run is not a pass. Three tests in this project have a history of failing when the
machine is busy — two of them were **fixed in this phase** — so a failure here is worth reporting
either way.

- [ ] **Number passed:** ______  **Number failed:** ______  **Number skipped:** ______
- [ ] If anything failed, its name: ______________________________

---

## T8 — The dashboard is visibly unchanged 🔒

P9 adds no page and changes no page. This confirms it.

```powershell
python main.py dashboard
```

Open http://127.0.0.1:5000 in a browser.

- [ ] The leads list loads and shows leads
- [ ] The lead count matches **the T1 total**
- [ ] The page looks exactly as it did before this phase — no new menu, no new column, no new banner
- [ ] Clicking into a lead still works
- [ ] The CSV export still downloads and still opens

Press `Ctrl+C` in the terminal to stop the dashboard.

---

## T9 — A clean workspace, and no new migration 🔒

```powershell
git status --short
python -m alembic heads
```

**Expected:** `git status --short` prints **nothing at all**, and `alembic heads` prints exactly one
line ending `(head)` naming `0006_content_and_dedup`.

⚠️ **If `config.yaml` shows as modified here, T4 was not finished.** Go back and restore
`rules_enabled: true`.

- [ ] Working tree clean
- [ ] Exactly one head, and it is **`0006`** — unchanged from P8

---

## Sign-off

Fill this in **after** running the tests. An unsigned table means the phase cannot be tagged
([EXECUTION_MODE_LOCK §6.2](../EXECUTION_MODE_LOCK.md)).

| Test | What it proves | Pass / Fail | Notes |
|---|---|---|---|
| T1 | The database was not touched; 459 leads intact | | |
| **T2** | **⭐ The rule engine judges a post, with a reason** | | |
| **T3** | **⭐ A real lead containing "hiring" is not discarded** | | |
| T4 | The off switch works, and was seen to work | | |
| T5 | The competitor rule is deliberately inactive | | |
| **T6** | **⭐ The filter cannot reach the AI code** | | |
| T7 | The full test suite passes | | |
| T8 | The dashboard is visibly unchanged | | |
| T9 | Clean tree, still one migration head at `0006` | | |

**Tested by:** ________________  **Date:** ____________

**Environment:** Windows ______ · Python ______ · commit ____________

**Overall result:** ☐ Pass ☐ Pass with notes ☐ Fail

**Anything that surprised you, however small:**

<br><br>

---

<a id="part-a-verification"></a>
## Part A — command verification record (done 2026-08-13, before implementation)

Every command was executed verbatim in PowerShell against the current tree at `0006_content_and_dedup`,
**before** any P9 code existed — so that a command which cannot run is found now rather than by the
tester.

**Executed verbatim, exactly as printed above:**

| Command | Result today, pre-implementation | Meaning |
|---|---|---|
| `python -m alembic heads` | `0006_content_and_dedup (head)` | ✅ runs; **and this is the value P9 must not change** |
| `python scripts\check_schema.py` | `OK — all 51 checks passed` | ✅ runs |
| `python -m pytest` | `1148 passed, 2 skipped` in 298 s | ✅ the P8 baseline exactly, on a clean tree |
| T6 `Get-ChildItem src\rules -Filter *.py -Recurse \| Select-String …` | **no output, and no error** | ⚠️ runs — **see the finding below** |
| T4 `Select-String -Path config.yaml -Pattern 'rules_enabled'` | no output | ✅ runs; **expected** to be empty before P9 adds the block |

> ⚠️ **A finding from running T6 verbatim, rather than reasoning about it.** With `src/rules/` absent
> the command printed **nothing and raised no error** — the same output it will give when the package
> exists and is clean. **On its own, T6's first command cannot distinguish "the boundary holds" from
> "the code was deleted."** That is precisely the vacuous-pass trap this project has recorded four
> times ([review §6.1](../P9-IMPLEMENTATION-REVIEW.md)). It is why T6 pairs the search with the
> pytest run, one of whose two tests exists solely to fail if the package disappears — and why the
> guide now says so in T6 itself rather than leaving the tester to assume.

**Not yet verifiable, and flagged as such:**

| Command | Why not | Resolved by |
|---|---|---|
| T2 / T3 / T4 `python -m src.rules …` | `No module named src.rules` — it is Stage 4's deliverable. **Its exact printed wording is predicted, not measured** | Part B replaces every predicted string with the real one |
| T4 `--rules-enabled false` | Same — the option does not exist yet | Part B |
| T5 / T6 `pytest -k …` | Those tests are Stage 1 and Stage 3 deliverables. The **counts** (`1 passed`, `2 passed`) are predicted | Part B records the real counts |

**A guide that tells a tester to expect wording the program does not print is the
[DI19](../DEFERRED-IMPROVEMENTS.md) failure repeated**, which is why the unverifiable rows are listed
here explicitly rather than left to look measured.

---

<a id="part-b--execution-record"></a>
## Part B — execution record

*To be filled in when P9 has shipped, per [checklist P.2](../P9-IMPLEMENTATION-CHECKLIST.md). Every
predicted output above is replaced by the measured one, and every correction is recorded here with
what the prediction had said.*
