# P10 — Manual Testing Guide · Dedup cascade

**Phase:** P10 (frozen numbering) · **Revision:** none — P10 adds no migration
**Written and executed:** 2026-08-14

> ✅ **Every command below was executed against the finished phase before this guide was written, and
> every expected output is copied from what actually appeared.** They are **measured, not
> predicted** — which is the correction P9 had to make after the fact, when two of its steps promised
> output the code did not produce (commit `defa9ca`).
>
> **What is still yours to do:** run them yourself and sign the table. **The sign-off table is
> deliberately blank** — a machine executing the commands is not a human accepting the phase.
>
> ⚠️ **This is not `docs/testing/phase-06-testing.md`.** That file belongs to the superseded
> eight-phase numbering and covers scraping, comments, dedup and pre-scoring all at once. If you
> opened a guide about MinHash *and* comment scrapers, you have the wrong file.

---

## Before you start

### What P10 adds, in one paragraph

**A way to notice that two posts are the same conversation — and nothing that uses it yet.** If three
people ask *"which CRM should I use"* in slightly different words, the system currently pays to
analyse all three. After this phase it can group them, analyse **one**, and share the answer with the
other two. It adds **no page, no button, no message, and no database change.** Nothing in the app
calls it yet: the part that will is P11.

Because there is no page to look at, this phase ships a small command that runs the grouping over a
handful of example posts. **That command is how you test this phase.**

### The one thing this phase is really about

Grouping is for **analysis only**. Every post keeps its **own** score.

That sounds like a detail and it is the whole point. Three near-identical threads can have different
authors, different subreddits, and different ages — so they are worth different amounts to you as
leads. If the grouping also collapsed the scores, you would get three identical numbers for three
different-value leads, and you would be right to stop trusting the ranking.

**T4 is the test for that.** If you only have time for three tests, do T2, T4 and T6.

### ⚠️ Three honesty notes — read before recording anything

1. **A step that fails is a result, not your mistake.** Write down exactly what appeared, including
   the error text. Do not re-run it until it passes and then record that.
2. **Your lead total is not fixed.** The scraper keeps running. **459 is the only number that must
   never change** — it is the frozen guarantee. Everywhere else, compare against the total from T1.
3. **Nothing in this phase should change the database.** If any number in T1 moves, something is
   wrong — P10 is not supposed to be able to write anything on its own.

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

**Expected once P10 has shipped:** the newest commit mentions `P10`, and `alembic heads` prints
exactly one line, ending `(head)` and naming `0006_content_and_dedup`.

⚠️ **`0006` is correct and important.** P10 adds **no** migration and uses the tables P8 already
created. If this names anything other than `0006_content_and_dedup`, stop — something was built that
should not have been.

---

## T1 — Nothing was lost 🔒

P10 should not have touched the database at all. This proves it.

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
- [ ] **Check count:** ______ *(expected `51` — unchanged from P8 and P9, because P10 adds no schema)*

---

## T2 — ⭐ The cascade groups near-identical posts 🔒

This is the phase, in one command. It runs four example posts through the grouping and shows you what
it decided.

```powershell
python -m src.dedupe
```

**Expected — exactly this:**

```
exact=on  minhash=on  jaccard>=0.85  semantic=off
4 posts -> 1 group(s), collapse rate 50%

  minhash group, 3 members, similarity 0.867
    #1    representative -> enriched
    #2    duplicate -> duplicate_exact
    #3    duplicate -> duplicate_near

  ungrouped: #4
```

**What you are looking at.** Posts #1, #2 and #3 are the same question — #2 is #1 with bold markdown
and an "EDIT:" line added, #3 changes one word. The system picked **#1** as the one worth paying to
analyse, and marked the other two as duplicates. Post #4 is about pizza and was correctly left alone.

**"Collapse rate 50%"** means half the posts no longer need their own analysis. That is the saving
this phase exists for.

- [ ] It reports **1 group** and **collapse rate 50%**
- [ ] Post **#1** is the representative
- [ ] Post **#4** is listed as **ungrouped**
- [ ] **Write down exactly what the first two lines printed:** ______________________________

---

## T3 — ⭐ Two kinds of duplicate are told apart 🔒

Look again at the T2 output. Posts #2 and #3 are **not** described the same way:

| Post | Reported as | Why |
|---|---|---|
| **#2** | `duplicate_exact` | identical once formatting and the "EDIT:" line are ignored |
| **#3** | `duplicate_near` | one word is different, so it is 86.7% similar, not identical |

**Why this matters.** An exact duplicate is a repost — there is nothing new in it. A near-duplicate is
a **separate conversation with a different person**, who is a separate potential customer even though
their question is nearly the same. Reporting both as "near" would hide how much of your feed is plain
reposting.

- [ ] #2 says `duplicate_exact` and #3 says `duplicate_near`
- [ ] They are **not** both the same word

---

## T4 — ⭐ Grouping did not collapse the posts into one 🔒

This is the test for the thing that would be a silent quality problem. Three posts were grouped — all
three must still exist afterwards.

```powershell
python -m src.dedupe --show-hashes
```

**Expected:** the same grouping as T2, followed by a list of **four** lines, one per post, each with a
long string of letters and numbers:

```
  content hashes (P19 keys incremental enrichment on these):
    #1    <64 characters>
    #2    <64 characters>
    #3    <64 characters>
    #4    <64 characters>
```

**What you are checking.** All four posts are still listed individually, including the two marked as
duplicates. Nothing was merged away or deleted. Grouping decided *which one to pay to analyse*; it did
not decide *which ones exist*.

⚠️ **#1 and #2 will have the same hash** — that is correct and is exactly why they were grouped. #3
and #4 will each be different.

- [ ] **Four** posts are listed, not one, not three
- [ ] #1 and #2 have the **same** hash
- [ ] #3 and #4 each have a **different** hash

---

## T5 — A real post is not swept up by mistake 🔒

The risk with grouping is not that it misses a duplicate — it is that it merges two *different*
conversations and you never hear from one of the people. Post #4 in the demo is the control.

Look at the T2 output again:

```
  ungrouped: #4
```

**Expected:** #4 — *"Best deep dish pizza in Chicago?"* — is never grouped with the CRM questions, and
never appears inside a group.

> **Why this matters more than it looks.** If unrelated posts were being merged, one of them would
> silently never be analysed, and **nothing in this system would ever tell you.** There is no report
> that shows you the leads that were grouped away.

- [ ] #4 appears **only** on the `ungrouped:` line
- [ ] #4 does **not** appear inside the group

---

## T6 — ⭐ The rollback works 🔒

Every phase must be switchable off. This one has two switches; here is the main one, and you do not
have to edit any file to try it.

```powershell
python -m src.dedupe --minhash-enabled false
```

**Expected — exactly this:**

```
exact=on  minhash=OFF (rollback state)  jaccard>=0.85  semantic=off
4 posts -> 1 group(s), collapse rate 25%

  exact group, 2 members, identical
    #1    representative -> enriched
    #2    duplicate -> duplicate_exact

  ungrouped: #3, #4
```

**What changed.** With near-duplicate matching switched off, only the *identical* pair is still
grouped. Post #3 — the one word different — is no longer grouped, and the saving drops from 50% to
25%. Nothing broke, nothing was lost; the system simply does less.

**That is what a rollback should look like:** less capability, never a different answer.

Now switch **both** tiers off:

```powershell
python -m src.dedupe --exact-enabled false --minhash-enabled false
```

**Expected:** `exact=OFF (rollback state)`, `0 group(s)`, and all four posts listed as ungrouped.

- [ ] With `--minhash-enabled false`, the collapse rate drops to **25%** and #3 becomes ungrouped
- [ ] The word `OFF (rollback state)` appears
- [ ] With both off, it reports **0 group(s)** and no post is lost
- [ ] **Write down the collapse rate from each of the three runs (T2, and both here):** ______ / ______ / ______

---

## T7 — The semantic layer is off, and says so 🔒

There is an optional third method that can spot two posts meaning the same thing in completely
different words. It needs an extra library that **is not installed**, so it ships switched off.

Look at the first line of any of the runs above:

```
exact=on  minhash=on  jaccard>=0.85  semantic=off
```

**Expected:** `semantic=off`.

> **Why it is off rather than on-and-silent.** The library is not installed on this machine. A setting
> that said "on" while the feature quietly did nothing would be worse than one that says "off" — you
> would believe you had a capability you did not have. When the library is installed, this is one
> config change away.

- [ ] The first line ends with `semantic=off`

---

## T8 — The filtering code still cannot reach the AI code 🔒

There is a rule in this project that the filtering and grouping code must **never** be able to reach
the AI code. That rule is the reason the whole system is cheap to run. P9 proved it for the rule
engine; this phase adds the same proof for the grouping code.

```powershell
python -m pytest tests\test_boundaries.py -k dedup
```

**Expected — one line:**

```
3 passed, 38 deselected in 0.38s
```

The time will differ; **`3 passed` and `0 failed` are the point.** The three tests are:

| Test | What it holds |
|---|---|
| `test_the_dedupe_package_is_inside_the_ai_fence` | the grouping code cannot import the AI code |
| `test_the_dedupe_package_exists` | …and the check above cannot pass by looking at nothing |
| `test_the_dedup_cascade_is_keyed_on_content_not_on_url` | grouping compares *content*, never web addresses |

⚠️ **The second one matters as much as the first.** A check that looks at a folder passes trivially if
the folder is deleted. That test fails loudly if the code ever goes missing, so the first one can
never pass by looking at nothing.

⚠️ **Type `dedup`, not `dedupe`.** `-k dedupe` finds only **2** of the 3, because the third test's
name uses the shorter spelling. Two passing tests where three were expected reads like a missing
test. *(Found by executing this guide, 2026-08-14 — the same class of error P9 had to correct in
`defa9ca`.)*

- [ ] The line reads **`3 passed`**
- [ ] **How many passed?** ______ *(expected `3`)*

---

## T9 — The whole suite is green 🔒

```powershell
python -m pytest
```

⚠️ **Do not add `-q`.** The project's configuration already includes it, and a second one silently
hides the summary line you are about to read — leaving a green-looking run with no numbers on it.

**Expected — the final line:**

```
1640 passed, 2 skipped in 287.45s (0:04:47)
```

The time will differ on your machine; the counts should not. **2 skipped is normal and unchanged
since P8** — they are tests needing a real API key.

> ⚠️ **If you ran this guide before 2026-08-15 you may have seen one failure here**, in
> `test_a5_minhash_indexes_and_queries_2000_items_under_two_seconds`, reporting something like
> *"2.21s, budget 2.0s"*. That was a **defect in the test, not in the product**, and it is fixed.
>
> Two things were wrong with it. It timed the **wall clock** where the specification says
> **CPU time** — so any second the machine spent on your browser or the dashboard from T10 was being
> charged to the dedup cascade. And its test data was **lighter than real posts**: documents of a
> fixed 870 characters producing 372 distinct text fragments, where real leads average 1,333
> characters and 1,053 fragments.
>
> The corrected benchmark measures **about 1.5× more work** than the one that failed you, and passes
> with room to spare. **Nothing was relaxed to achieve that** — no budget was raised, no assertion
> weakened, and no application code changed. Full detail:
> [PHASE-10-COMPLETION-REPORT §3](../PHASE-10-COMPLETION-REPORT.md).
>
> **It can still fail on a heavily loaded machine.** If it does, close what is competing for the CPU
> and re-run before recording a failure — and if it fails on an idle machine, that is a genuine
> result worth reporting.

- [ ] **Passed:** ______ *(expected `1640`)*
- [ ] **Skipped:** ______ *(expected `2`)*
- [ ] **Failed:** ______ *(expected `0`)*

---

## T10 — The application still looks and works the same 👁️

A machine can prove the routes still serve and the CSV still has 13 columns, and it did. It cannot
sign *"it looks the same"*. That is this test, and only you can do it.

```powershell
python main.py dashboard
```

Then open `http://127.0.0.1:5000` in a browser.

- [ ] The home page loads and looks unchanged
- [ ] The lead list shows leads, and the count matches the T1 total
- [ ] Export to CSV works and the file opens
- [ ] Nothing on any page mentions grouping, duplicates or dedup — **P10 adds no UI, by design**

Press `Ctrl+C` in PowerShell to stop it.

---

## What P10 deliberately does **not** do

Recorded so that a missing thing does not read as a defect:

| Not there | Why |
|---|---|
| Any page, button or panel showing groups | P10 is a library; **P11** is its first caller |
| Any row written to the database during these tests | The cascade writes only when a caller asks it to, and nothing calls it yet |
| A "similar discussions (3)" affordance on a lead | [06c §4.4](../06c-local-first-pipeline.md) describes it; the UI is a later phase's |
| The semantic tier doing anything | Optional, and its library is not installed — see T7 |
| A fix for the *"hiring"* defect P9 found | **[DI25](../DEFERRED-IMPROVEMENTS.md)**, owned by P11, which has the measurement that can prove the fix |

---

## Sign-off

**Do not sign a row you did not personally run.** An unsigned guide is an honest record; a signed one
that was not executed is not.

| Test | What it proves | Result | Date | Signature |
|---|---|---|---|---|
| T1 | Nothing was lost | ☐ Pass ☐ Fail | | |
| **T2** ⭐ | Near-identical posts are grouped | ☐ Pass ☐ Fail | | |
| T3 ⭐ | Exact and near duplicates are told apart | ☐ Pass ☐ Fail | | |
| **T4** ⭐ | Grouping did not collapse the posts | ☐ Pass ☐ Fail | | |
| T5 | An unrelated post is not swept up | ☐ Pass ☐ Fail | | |
| **T6** ⭐ | The rollback works | ☐ Pass ☐ Fail | | |
| T7 | The semantic layer is off and says so | ☐ Pass ☐ Fail | | |
| T8 | The AI boundary holds | ☐ Pass ☐ Fail | | |
| T9 | The whole suite is green | ☐ Pass ☐ Fail | | |
| T10 | The app is unchanged | ☐ Pass ☐ Fail | | |

**Phase accepted by:** ________________  **Date:** ____________

> ⚠️ **Until this table is signed, P10 is not complete and must not be tagged** — a tag would claim a
> verification that did not happen ([lock §6.2](../EXECUTION_MODE_LOCK.md)).
