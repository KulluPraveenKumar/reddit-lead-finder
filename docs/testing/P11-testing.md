# P11 — Manual Testing Guide · Pre-score, funnel & comments

**Phase:** P11 ([34 §P11](../34-implementation-plan.md)) · **Written:** 2026-08-15
**Time needed:** about 25 minutes · **You do not need to be a developer.**

> **What this phase did.** Every post the scraper collects now gets a **deterministic 0–100
> score**, with all six of its components stored. The run page shows the **funnel** — how many
> items came in, how many were rejected and why. Comments are fetched for the **best-scoring**
> posts first. And 2% of the posts the early filter *rejected* are re-checked, so the system can
> tell you whether that filter is throwing away real leads.
>
> **Nothing here costs money.** P11 makes **zero** AI calls, and step T8 checks that directly.
>
> **What is still yours to do:** run these steps and sign the table at the bottom. **The sign-off
> table is the phase gate** — the phase is not complete until a human has signed it.

Every expected output below was **copied from a real run on 2026-08-15**, not predicted. If what
you see differs, that is a finding worth recording, not something to explain away.

> ⚠️ **Do not add `-q` to any `pytest` command.** `pyproject.toml` already sets it, so a second one
> becomes `-qq` and hides the `N passed` line these steps ask you to read
> ([DI19](../DEFERRED-IMPROVEMENTS.md)).

Open PowerShell in the project folder first:

```powershell
cd C:\path\to\reddit-scraper
```

---

## T1 — The score, on four posts chosen to show all four outcomes

```powershell
python -m src.scoring
```

**Expected.** A weights table, then three absent components, then four posts. The first block
should read exactly:

```
Admission floor: 35   (pipeline.prescore_admission_floor)
Weights, normalised from docs/04 section 9.1 (raw: {'keyword_tier': 0.05, 'keyword_density': 0.05, 'question_form': 0.03, 'recency': 0.07, 'engagement': 0.05, 'length': 0.03}):
    recency            0.2500
    keyword_tier       0.1786
    keyword_density    0.1786
    engagement         0.1786
    question_form      0.1071
    length             0.1071

Not shipped in P11 -- declared absent, never scored as 0.0:
    pain_phrase        P12 — `pain_points` arrives in revision 0007
    competitor         P15 — the EntityRegistry over `bkb_entities` (0007)
    subreddit_fit      P12 — `projects` arrives in revision 0007
```

Then the four posts, ending in the four verdicts:

| Post | TOTAL | VERDICT |
|---|---:|---|
| `Looking for a CRM — any recommendations for a small team?` | **79.49** | `ADMIT` |
| `Shipped a small update today` | **21.61** | `REJECT  (below_prescore: 21.61 < 35.00)` |
| `[HIRING] Senior backend engineer, remote` | **27.29** | `REJECT  (structural_noise: hiring)` |
| `Looking for a CRM …` *(400 days old)* | **48.14** | `REJECT  (out_of_window: 400.0d > 30d)` |

**PASS if:** the six weights add up to **1.0000**, the three absent components are **named with the
phase that will supply them** (not shown as zeroes), and all four verdicts match.

▶ *Why the fourth one matters:* it scores **48.14**, comfortably above the floor of 35, and is
still rejected — because it is 400 days old. The age check runs **before** the score cut, so the
funnel tells you the real reason instead of blaming the score.

---

## T2 — Add up the column yourself

Look at the first post in T1's output:

```
    keyword_tier        1.000  x 0.1786  =  17.86
    keyword_density     1.000  x 0.1786  =  17.86
    question_form       1.000  x 0.1071  =  10.71
    recency             0.955  x 0.2500  =  23.87
    engagement          0.380  x 0.1786  =   6.79
    length              0.225  x 0.1071  =   2.41
    TOTAL               79.49 / 100
```

**Expected.** `17.86 + 17.86 + 10.71 + 23.87 + 6.79 + 2.41 = 79.50`.

**PASS if:** your total is **79.49 or 79.50**. (The 0.01 is rounding — each line is rounded for
display, the real total is not.) **This is the point of the whole phase**: the number is not a
black box, and you can check it with a calculator.

---

## T3 — The lead that used to be silently thrown away

This is a real defect the phase fixed. Before P11, a post containing the word *"hiring"* anywhere
was discarded before anyone ever saw it.

```powershell
python -m src.scoring "Our hiring process is broken and I need a tool to fix it" --body "We have been struggling with tracking candidates across three spreadsheets and I am looking for any recommendations for something that works." --score 25 --num-comments 8
```

**Expected**, the last block:

```
Our hiring process is broken and I need a tool to fix it
    keyword_tier        1.000  x 0.1786  =  17.86
    keyword_density     1.000  x 0.1786  =  17.86
    question_form       0.000  x 0.1071  =   0.00
    recency             0.955  x 0.2500  =  23.87
    engagement          0.205  x 0.1786  =   3.66
    length              0.083  x 0.1071  =   0.89
    TOTAL               64.14 / 100
    VERDICT            ADMIT
```

**PASS if:** the verdict is **ADMIT**. This person is describing a problem your product solves;
they are a textbook lead, and until this phase they were being deleted before collection.

---

## T4 — The rollback, without editing any file

```powershell
python -m src.scoring "Weekly megathread" --prescore-enabled false
```

**Expected**, the last block:

```
Weekly megathread
    TOTAL                0.00 / 100
    VERDICT            ADMIT  (prescore_disabled)
```

**PASS if:** the verdict says **`prescore_disabled`**. That word is what tells you the rollback
actually took the rollback path — a real post can also score 0.00, so the number alone would not
prove it.

▶ In production the same switch is `pipeline.prescore_enabled: false` in `config.yaml`, and it
turns the whole stage off: no scores stored, no funnel on the run page, leads keep their old
`intent_score` only.

---

## T5 — The automated tests for this phase

```powershell
python -m pytest tests/test_scoring_features.py tests/test_scoring_prescore.py tests/test_scoring_holdout.py tests/test_scoring_funnel.py tests/test_scoring_cli.py tests/test_prescore_stage.py tests/test_holdout_audit.py tests/test_comment_scraper.py tests/test_unknown_metrics.py
```

**Expected:** `218 passed` (about 30 seconds).

**PASS if:** the number is **218** and there are no failures.

---

## T6 — The architectural boundary

The scoring code decides what is worth paying an AI for. It must not be *able* to call one.

```powershell
python -m pytest tests/test_boundaries.py -k "scoring"
```

**Expected:** `2 passed, 42 deselected`.

**PASS if:** **2 passed**. One test checks the boundary; the other checks the package still
exists — because a boundary check over a folder that has been deleted passes while checking
nothing.

---

## T7 — The rejection vocabularies agree

```powershell
python -m pytest tests/test_rules_vocabulary.py
```

**Expected:** `30 passed`.

**PASS if:** **30 passed**. This is the file that keeps four separate lists of rejection reasons
from drifting apart — the funnel you will read in T10 shows all of them on one page.

---

## T8 — Zero AI calls, checked against the database

```powershell
python -m pytest tests/test_prescore_stage.py -k "no_ai_call"
```

**Expected:** `1 passed, 18 deselected`.

**PASS if:** **1 passed**. The test scores six posts through the real pipeline and then counts the
rows in the `ai_calls` table. The expected count is **0**.

---

## T9 — The full test suite still passes

This is the one long step — about 5 minutes. Start it and make a cup of tea.

```powershell
python -m pytest
```

**Expected:** `1871 passed, 2 skipped` (measured at 293.57s).

**PASS if:** **0 failures.** The count may differ slightly if you are on a later commit; failures
are what matter.

▶ The 2 skipped are long-standing and expected — they need a real API key.

---

## T10 — The funnel on the run page

This is the operator-facing half of the phase, and the only step that needs the app running.

```powershell
python main.py dashboard
```

Open <http://127.0.0.1:5000/>, click **Run Scraper**, and let it finish. Then open the run from
the **Runs** page.

**Expected.** Once the run reaches **complete**, a **Funnel** card appears above Activity, showing:

- **Collected**, then one `−` line per rejection reason, largest first
- sub-reasons indented under `structural noise` (e.g. `hiring`, `megathread`)
- **Grouped as duplicates**
- **Admitted**, in bold above a rule
- a **Measured** section: hard-filter rate against the assumed 73%, collapse rate, gate miss rate
- a **Comments** section: requests made, requests saved by ordering, comments stored

**PASS if:**
1. **`Collected` = the sum of every `−` line plus `Admitted`.** Add them up. If they do not sum,
   the page says so in red — that is the check this step exists for.
2. The **gate miss rate** shows either a percentage **or the words `not measured`** — never
   `0.0%` when nothing was sampled.
3. The subtitle under "Funnel" ends with **`· 0 AI calls`**.

▶ **The Funnel card is absent while a run is still scraping, and that is correct.** A blank is an
honest *"not measured yet"*; a row of zeroes would claim nothing was collected and nothing was
filtered, which is a different and wrong statement.

▶ ⚠️ **A real run needs the internet and Reddit's cooperation.** If the run fails at the network,
that is not a P11 finding — note it and mark this step **N/A**, then confirm the funnel logic via
T5 instead, which exercises the same code against a database.

---

## T11 — Re-running collects no duplicate comments

With the app still running, click **Run Scraper** a second time and let it finish.

**PASS if:** the second run's funnel shows **Requests made** much lower than the first (most posts
report as already covered), and no error appears. Re-fetching a thread whose comments are already
stored must add nothing and must not fail.

---

## Sign-off

**Every step above must be executed by a human.** A generated table is not a signed one.

| Test | What it proves | Result | Date | Signature |
|---|---|---|---|---|
| T1 | Four outcomes, six weights, three absences named | ☐ PASS ☐ FAIL | | |
| T2 | The score is arithmetic you can check | ☐ PASS ☐ FAIL | | |
| T3 | DI25's lead is admitted, not discarded | ☐ PASS ☐ FAIL | | |
| T4 | The rollback works without editing a file | ☐ PASS ☐ FAIL | | |
| T5 | 218 phase tests pass | ☐ PASS ☐ FAIL | | |
| T6 | The AI boundary holds over `src/scoring/` | ☐ PASS ☐ FAIL | | |
| T7 | The rejection vocabularies agree | ☐ PASS ☐ FAIL | | |
| T8 | Zero AI calls, counted in the database | ☐ PASS ☐ FAIL | | |
| T9 | The full suite is green | ☐ PASS ☐ FAIL | | |
| T10 | The funnel renders and sums | ☐ PASS ☐ FAIL ☐ N/A | | |
| T11 | Re-running creates no duplicate comments | ☐ PASS ☐ FAIL ☐ N/A | | |

**Phase accepted by:** ________________  **Date:** ____________

**Notes / anything that did not match:**

```



```
