# P05 — Manual Testing Guide · RSS client & Atom parser

**Phase:** P5 — RSS client & Atom parser · [34 §P5](../34-implementation-plan.md)
**Written:** 2026-08-08, **before** implementation, per [lock §3 step 8](../EXECUTION_MODE_LOCK.md).
**Companions:** [P5-IMPLEMENTATION-REVIEW.md](../P5-IMPLEMENTATION-REVIEW.md) ·
[P5-DECISION-ANALYSIS.md](../P5-DECISION-ANALYSIS.md)

> **Who this is for.** Someone who can copy a command into a terminal and read what comes back. You
> do **not** need to know Python, XML or Reddit. Every step says what you should see; if you see
> something else, the step tells you what it means.

---

## Before you start

### What P5 added, in one paragraph

Reddit publishes every subreddit as a **feed** — a machine-readable list of the newest posts, in a
format called Atom. P5 teaches this project to read those feeds. That matters because one feed
request returns up to **100** posts across **many** subreddits at once, where the old
page-scraping approach returned 25 posts from one subreddit. Nothing in the app *uses* feeds yet —
that is the next phase. P5 builds the reader and proves it produces exactly the same information the
old approach produces.

### Two things that are deliberately **not** here

1. **There is no "304 / not modified" test.** An earlier plan expected Reddit to tell us "nothing
   changed" cheaply. In P0 we measured that Reddit does not send the headers that would make that
   possible, so the feature was deleted from the design.
   See [P5-DECISION-ANALYSIS §D1](../P5-DECISION-ANALYSIS.md). If a step below seems to be missing,
   this is why.
2. **Almost nothing here touches the internet.** The tests read feed files that ship with the
   project, so they give the same answer every time. Exactly one step (**T7**) goes online, and it
   is optional.

### ⚠️ Mutations and rollback

This guide **never edits a tracked project file.** Where a test needs different settings, it writes
a **temporary** file in a scratch folder outside the project. T13 proves the project files were left
untouched.

### Prerequisites

| | |
|---|---|
| Terminal | **Windows PowerShell** |
| Location | The project folder |
| Time | ~25 minutes (~30 with the optional online step) |

Run this once. Leave the window open for the whole guide.

```powershell
Set-Location "$env:USERPROFILE\Downloads\reddit-scraper"
$py = ".\.venv\Scripts\python.exe"
$scratch = Join-Path $env:TEMP "p5-manual"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
& $py --version
```

**Expected:** `Python 3.12.5` (any `3.12.x` is fine).

**If you see `The term '.\.venv\Scripts\python.exe' is not recognized`** — you are in the wrong
folder, or the project's virtual environment was never created. Run `Get-Location` and check it ends
in `reddit-scraper`.

---

# T1 — The project is healthy before you begin

A failure here is **not** a P5 failure. It means something else is wrong and the rest of this guide
would be measuring the wrong thing.

### Step 1 — Nothing is half-edited

```powershell
git status --short
```

**Expected:** no output at all.

**If you see `M config.yaml`** — a previous test's settings were left behind. Undo it with
`git restore config.yaml` and run Step 1 again. *(This exact leftover was found at the start of P5;
see [review §3.3](../P5-IMPLEMENTATION-REVIEW.md).)*

### Step 2 — The database schema is correct

```powershell
& $py scripts\check_schema.py
```

**Expected:** the last line reads `OK — all 25 checks passed.`

### Step 3 — There is exactly one schema version, and P5 did not change it

```powershell
& $py -m alembic heads
```

**Expected:** exactly one line, `0004_orchestration (head)`.

**Why this matters:** P5 adds no database change at all. Two lines, or a number other than `0004`,
means something unrelated to P5 needs attention first.

---

# T2 — The feed reader reads a real feed

The project ships four example feeds. This one is a **multireddit** feed — one feed covering
several subreddits at once.

```powershell
& $py main.py feed --file tests\fixtures\atom\listing_multireddit.xml
```

**Expected:** a table of **3 posts**. Read down the columns and confirm:

| Column | What you should see |
|---|---|
| `id` | starts with `t3_` |
| `author` | a plain name — **no** `/u/` in front of it |
| `subreddit` | **two different** subreddit names across the three rows |
| `score` | `None` on every row |
| `comments` | `None` on every row |
| `body` | text on two rows, **empty** on the row whose title says it is a link post |

The last line reads `3 posts`.

**Why `score` and `comments` are empty:** a feed does not carry them. Printing `0` would be a made-up
fact — the project reports "unknown" instead. This is the single documented difference between the
feed reader and the page reader.

---

# T3 — A feed and a web page describe the same posts identically 🔒

**This is the most important test in the guide.** The whole point of P5 is that switching to feeds
does not change the information the project collects.

The project ships two matched pairs of files — a saved Reddit web page and the matching feed, each
describing **the same posts**. This command reads both of each pair and compares them field by field.

```powershell
& $py -m pytest tests\test_feed_parity.py -v
```

**Expected:** every line ends in `PASSED`, and the last line reads `17 passed`.

**What a failure means:** the feed reader and the page reader disagree about something — a title, a
body, a timestamp, an author. That is a genuine defect and P5 is **not** complete. The failure
message names the field and prints both values.

### The four things that are *supposed* to differ

Not everything can match, because the two sources do not carry the same information. These four are
expected, measured, and written down — the tests allow exactly these and nothing else:

| What differs | Which is right | Why |
|---|---|---|
| **score** | the web page | A feed carries no vote count. The feed says "unknown" rather than inventing `0` |
| **comment count** | the web page | Same reason |
| **body** *(listing pages only)* | **the feed** | A Reddit listing page does not actually contain the post text — it loads it later, when a reader clicks. The feed has it. Measured 2026-08-08 |
| **link address** *(link and photo posts only)* | both, differently | On a listing page the title links to *the thing being shared* (a photo, a video, another site). The feed always links to *the Reddit post*. The project keeps the Reddit post link, because that is where you go to reply |

**The third one is the surprising one, and it was found by T7a below**, not by these tests. That is
the reason T7a exists.

---

# T4 — A feed can carry 100 posts, and reading them is fast

```powershell
& $py main.py feed --file tests\fixtures\atom\listing_100.xml --limit 100
```

**Expected:** the last line reads `100 posts`.

Now ask for fewer:

```powershell
& $py main.py feed --file tests\fixtures\atom\listing_100.xml --limit 10
```

**Expected:** the last line reads `10 posts`.

**Why both:** the first proves the project can take everything Reddit will give it in one request.
The second proves `--limit` is actually obeyed rather than ignored — a limit that quietly does
nothing is the kind of bug that only shows up as a surprise bill.

The speed budget is checked automatically:

```powershell
& $py -m pytest tests\test_feed_parser.py -k "speed" -v
```

**Expected:** `PASSED`. (It asserts 100 posts are read in under 50 milliseconds.)

---

# T5 — A damaged feed complains loudly 🔒

The dangerous failure is not a crash. It is a feed that arrives damaged and is read as **"no new
posts"** — the project would then report "nothing happening" forever, and nobody would know.

```powershell
& $py main.py feed --file tests\fixtures\atom\malformed.xml
```

**Expected:** a clear error mentioning that the feed could not be parsed, and **no** post table.

Confirm the command actually reported failure:

```powershell
$LASTEXITCODE
```

**Expected:** a number that is **not** `0`.

**If you see `0 posts` and no error** — this is the exact defect the test exists to catch. P5 is not
complete. Report it.

---

# T6 — An empty feed is not an error

A subreddit with no recent posts sends a valid, empty feed. That is normal and must be treated as
normal.

```powershell
& $py main.py feed --file tests\fixtures\atom\empty.xml
```

**Expected:** `0 posts`, **no** error.

```powershell
$LASTEXITCODE
```

**Expected:** `0`.

**T5 and T6 together are the point:** damaged is loud, empty is quiet. Getting these the wrong way
round is how a scraper dies silently.

---

# T7 — Fetch one real feed from Reddit *(optional; needs internet)*

Skip this if the machine is offline or you would rather not make an outside request. Every other
test still stands on its own.

```powershell
& $py main.py feed --subreddits SaaS --limit 25
```

**Expected:** a table of posts and a count of **up to 25**. The count may be lower; that is fine.

**Now compare it to the real site.** Open <https://old.reddit.com/r/SaaS/new/> in a browser. The
titles at the top of the page should match the titles at the top of your table. They may not match
exactly if someone posted in the last few seconds.

**If you see an error mentioning `429`** — Reddit allows roughly **one feed request per minute per
computer**. Wait 60 seconds and run it once more. This is measured, expected behaviour, not a bug
([SPRINT-0 §2.2](../SPRINT-0-MEASUREMENTS.md)).

**Why this step exists at all:** every other test reads a saved file. This is the only proof that
the address the project builds is one Reddit actually answers.

---

# T7a — Compare the feed against Reddit's own web page, live *(optional; needs internet)*

**Why this exists.** Every other test reads a saved file. Saved files are frozen on the day they are
saved — so if Reddit changes its web pages next month, every test here keeps passing while the
project quietly starts collecting two different sets of information. This step is the only one that
would notice.

It is not idle insurance: **this check failed the first time it was run**, and what it found changed
the project's design documents. See the note at the end of this step.

```powershell
& $py scripts\validate_feed_parity.py --subreddit SaaS
```

The tool makes exactly **two** requests: one for Reddit's web page, one for the feed. It then
compares every post that appears in both.

**Expected:** near the end,

```
OK — 25 posts agree on all 7 compared fields.
```

The numbers will differ — the two sources cover different time windows, so `only in RSS` is normally
around 75. That is not a problem; it is counted separately and labelled *coverage*.

```powershell
$LASTEXITCODE
```

**Expected:** `0`.

**Read the middle of the output too.** It prints:

- **Intentional differences** — the four from T3, each with its reason. Nothing is excluded silently.
- **Tolerated differences** — differences it decided are explainable, each with the explanation
  attached, so you can disagree with it.
- **Feed bodies** — how many feed posts carry the post text. Should be most of them. If it says
  **`FAILURE — the feed returned no bodies at all`**, the feed reader has broken; report it.

**If you see `FAILURE — N field mismatches`** — that is the tool doing its job. Copy the output and
report it. It means Reddit changed something and the two readers no longer agree.

**If you see an error mentioning `429`** — wait 60 seconds and run it once more (see T7).

> **What this found on 2026-08-08.** On its first run it reported 25 of 25 posts mismatching on
> `body`. Investigation showed the *web page* was at fault, not the feed: a Reddit listing page does
> not contain post text at all. That is now recorded as a measured finding in
> [ARCHITECTURE_FREEZE.md §11](../ARCHITECTURE_FREEZE.md), and it changes how the **next** phase must
> be designed. A test that only read saved files could never have found it.

---

# T8 — The off switch works ⚠️ *(uses a temporary file; nothing tracked is edited)*

If feeds ever misbehave in production, the operator must be able to switch them off without a code
change. This is P5's **first-level rollback**.

### Step 1 — Write a temporary settings file with feeds turned off

```powershell
@'
subreddits:
  - SaaS
keywords:
  high_intent:
    - looking for
scoring:
  min_score: 0
discovery:
  rss_enabled: false
'@ | Out-File -FilePath (Join-Path $scratch "config-rss-off.yaml") -Encoding utf8
Test-Path (Join-Path $scratch "config-rss-off.yaml")
```

**Expected:** `True`.

**Note the design:** this writes a brand-new small file in a scratch folder. It does **not** copy or
edit the project's `config.yaml`, so there is nothing to undo and nothing that can be forgotten.

### Step 2 — Ask for a feed with feeds switched off

```powershell
& $py main.py feed --config (Join-Path $scratch "config-rss-off.yaml") --subreddits SaaS
```

**Expected:** a message saying feed collection is disabled. **No** post table, and **no** request to
Reddit.

```powershell
$LASTEXITCODE
```

**Expected:** a number that is **not** `0`.

### Step 3 — Confirm it is the setting doing the work, not something broken

```powershell
@'
subreddits:
  - SaaS
keywords:
  high_intent:
    - looking for
scoring:
  min_score: 0
discovery:
  rss_enabled: true
'@ | Out-File -FilePath (Join-Path $scratch "config-rss-on.yaml") -Encoding utf8
& $py main.py feed --config (Join-Path $scratch "config-rss-on.yaml") --file tests\fixtures\atom\listing_multireddit.xml
```

**Expected:** `3 posts` — the same result as T2.

### Step 4 — The project's own settings were never touched

```powershell
git status --short
```

**Expected:** no output.

### Step 5 — Clean up

```powershell
Remove-Item -Recurse -Force $scratch
Test-Path $scratch
```

**Expected:** `False`.

---

# T9 — Everything that worked before P5 still works 🔒

P5 **adds** a capability. It must not have changed one.

### Step 1 — The six original Reddit methods are untouched

```powershell
& $py -m pytest tests\test_boundaries.py -v
```

**Expected:** every line `PASSED`.

This checks, among other things, that `get_new_posts`, `get_hot_posts`, `search_posts`,
`get_post_comments`, `get_user_posts` and `get_subreddit_info` still exist with exactly the same
shape they had before P5.

### Step 2 — The dashboard and its data are unchanged

```powershell
& $py -m pytest tests\test_scrape_contract.py tests\test_migrations.py -v
```

**Expected:** every line `PASSED` or `SKIPPED`.

**About `SKIPPED`:** three tests need the real `data/leads.db`, which is deliberately not shared. If
you have one, they run; if not, they skip. A skip is not a failure.

### Step 3 — The complete rollback route exists

P5 can be removed entirely by returning to the last P4 commit. Confirm that commit is still there:

```powershell
git log --oneline -1 9b5fbe5
```

**Expected:** one line, `9b5fbe5 docs(P4): make every command in the manual guide PowerShell-safe`.
That commit is the point the project returns to if P5 has to be undone.

**Do not run a checkout.** You are confirming the escape route is there, not using it.

**Why there is no `v0.1.0-p4` tag to point at:** the project only tags a phase once a human has
signed its manual testing guide, and the P0–P4 sign-off tables are still blank
([lock §6.2](../EXECUTION_MODE_LOCK.md), blocker **D1**). The commit is the rollback point until
those are signed. Checking:

```powershell
git tag --list
```

**Expected:** `v0.1.0-p1` only. This is a known, recorded state, not a P5 defect.

---

# T10 — The architecture rules still hold 🔒

Four automatic checks protect boundaries that are expensive to restore once broken. One of them
(fence 4) did not exist until P4, and when it was finally written it failed immediately — so these
are checked by running them, never by trusting the documentation.

```powershell
& $py -m pytest tests\test_boundaries.py -k "network_layer or makes_no_ai_calls or conditional_get or no_real_identities" -v
```

**Expected:** `4 passed`, every line `PASSED`. These four assert that:

1. The networking code contains **no** knowledge of Reddit — it must stay reusable.
2. The new feed code makes **no** AI calls and imports no AI module.
3. The deleted "conditional GET" feature has **not** crept back in
   ([P5-DECISION-ANALYSIS §D1](../P5-DECISION-ANALYSIS.md)).
4. The example feeds contain no real usernames or links. This repository is public.

⚠️ **Check the count, not just the colour.** If the last line says `deselected` with a low number
passed, the filter matched fewer tests than it should and the step proved less than it claims — a
`-k` filter that matches nothing still exits successfully. `4 passed` is the assertion.

---

# T11 — P5 added no new software

A stated promise of this phase is that it uses only what is already installed.

```powershell
& $py -m pip list --format=freeze | Out-File -FilePath (Join-Path $env:TEMP "p5-packages.txt") -Encoding utf8
(Get-Content (Join-Path $env:TEMP "p5-packages.txt") | Measure-Object -Line).Lines
Select-String -Path (Join-Path $env:TEMP "p5-packages.txt") -Pattern "^lxml"
```

**Expected:** a package count, and a line showing `lxml` at version 5 or higher.

**The point:** `lxml` — the library that reads the feeds — was already installed and already listed
in `requirements.txt`. Nothing was added.

```powershell
Select-String -Path requirements.txt -Pattern "lxml"
```

**Expected:** `lxml>=5.0.0`.

---

# T12 — The full automatic test suite passes

The last check, and the broadest.

```powershell
& $py -m pytest --tb=short
```

**Expected:** the final line reports **passed** with **0 failed**, and around **2 skipped**
(see T9 Step 2). Roughly three minutes.

**Record the numbers here:** ______ passed, ______ skipped, ______ failed.

**If anything failed:** copy the last 30 lines and report them. Do not continue.

---

# T13 — Leave the project exactly as you found it

```powershell
git status --short
Test-Path (Join-Path $env:TEMP "p5-manual")
```

**Expected:** no output from the first command, and `False` from the second.

**If `git status` shows anything**, undo it before signing off:

```powershell
git restore .
git status --short
```

**Expected after:** no output.

---

## Sign-off

**Blocking tests.** **T3, T5, T8, T9, T10 and T12 are not optional.** T3 is the phase's central
claim; T5 protects against silent data loss; T8 and T9 protect the ability to undo; T10 protects
frozen architecture; T12 is the gate. A guide signed with any of these unrun records a verification
that did not happen.

**T7 and T7a are optional** and are the only steps that contact Reddit. T7a is strongly recommended
whenever this guide is re-run after a gap: it is the only check that can notice Reddit changing
underneath the project.

| Test | What it proves | Pass | Fail | Tester | Date |
|---|---|---|---|---|---|
| T1 | The project is healthy before P5 is judged | | | | |
| T2 | A real multireddit feed is read into posts | | | | |
| **T3** 🔒 | **Feed and web page produce identical posts** | | | | |
| T4 | 100 posts in one feed; `--limit` obeyed; under the speed budget | | | | |
| **T5** 🔒 | **A damaged feed fails loudly, never silently** | | | | |
| T6 | An empty feed is not an error | | | | |
| T7 *(optional)* | A live feed is fetched and matches the site | | | | |
| **T7a** *(optional)* | **Live feed and live web page agree, field by field** | | | | |
| **T8** 🔒 | **`rss_enabled: false` switches feeds off; nothing tracked was edited** | | | | |
| **T9** 🔒 | **Pre-P5 behaviour is unchanged; the rollback route exists** | | | | |
| **T10** 🔒 | **Boundaries hold; conditional GET has not returned; fixtures are anonymous** | | | | |
| T11 | No new software was installed | | | | |
| **T12** 🔒 | **The full suite passes** | | | | |
| T13 | The project is left clean | | | | |

**Signed:** ______________________  **Date:** ______________

---

## Command verification record

[Lock §3 step 8](../EXECUTION_MODE_LOCK.md) and the task standard require every command in this
guide to have been **executed as written** before the guide is finalised.

| When | Which commands | Status |
|---|---|---|
| 2026-08-08, pre-implementation | Prerequisites · T1 all steps · T8 Steps 1, 4, 5 (file and cleanup mechanics) · **T9 Step 3** · T11 · T13 | ✅ Executed and verified as written |
| 2026-08-08, post-implementation | **Every remaining command** — T2, T3, T4, T5, T6, T7a, T8 Steps 2–3, T9 Steps 1–2, T10, T12 | ✅ Executed and verified as written |

**T7 (live single-feed fetch) is the one command not re-executed at the end**, because T7a exercises
the same live path more thoroughly — two requests, field-by-field — and each extra live fetch costs
a 60-second rate-limit window. T7a was executed twice, on `r/startups` and `r/SaaS`, both exit 0.

**Four corrections were forced by executing rather than assuming**, which is the entire reason this
record exists:

| Step | What was wrong | Why it mattered |
|---|---|---|
| **T9 Step 3** | Checked for a `v0.1.0-p4` tag that does not exist | P2–P5 are untagged because their sign-off tables are blank |
| **T8** | Originally copied `config.yaml` and appended to it | Would have created a duplicate `discovery:` key and risked corrupting a tracked file. Now writes a small standalone file |
| **T10** | `-k "discovery"` selected 2 tests and `-k "fixtures_are_anonymised"` selected **0** | **A `-k` filter that matches nothing still exits successfully.** The step would have passed while proving nothing — the same class of defect as P4's T12. The guide now asserts the count |
| **T3** | Expected "something like 18 passed" | The real number is 17. "Something like" is not an expected result |

**Why the guide exists before the code:** it is what the implementation is written to satisfy. Its
commands are re-run in full at Stage 10 of
[P5-IMPLEMENTATION-CHECKLIST.md](../P5-IMPLEMENTATION-CHECKLIST.md), and any that do not behave
exactly as written are corrected there — the failure mode
[testing/P04-testing.md](P04-testing.md) T12 was rewritten to remove.
