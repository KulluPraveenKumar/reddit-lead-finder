# Manual Testing Guide — P4: Network provider abstraction

> ⚠️ **This is P4 of the frozen P0–P30 plan ([34](../34-implementation-plan.md)) — NOT the legacy
> "Phase 04."** [`testing/phase-04-testing.md`](phase-04-testing.md) belongs to the **old
> eight-phase numbering** (where "Phase 04" was the Business Knowledge Base) and is a historical
> record. The two schemes are unrelated. If a step below mentions a website knowledge base, you are
> reading the wrong file.

Written so a **non-developer can validate this phase without guessing**. Every step states what you
should see. If what you see differs, that step's *Possible failure* table tells you what it means.

- **Time:** ~75 minutes for the full suite; ~15 minutes for the smoke path (T1, T3, T13).
- **You need:** a terminal and a web browser. **No API key.** No internet except **T15**, which is
  the only test that reaches Reddit for real and is clearly marked.
- **Destructive steps:** T15 only, and it writes leads to `data\leads.db` exactly as pressing the
  scrape button has always done. Everything else uses a temporary database or a temporary config
  file which you delete afterwards.
- **You do NOT need a proxy subscription.** Every proxy behaviour below is tested with a *fake
  proxy file* you create in T2. Nothing dials a real proxy except the optional T11 Step 5, which is
  clearly marked and skippable.

Throughout, `>` marks a command to run and `→` marks what you should see.

> ⚠️ **Every command in this guide is written for Windows PowerShell** and has been executed there
> before shipping. Copy them verbatim — do not "fix" the quoting.
>
> If you are adding a command to this guide, three things will bite you, and all three have:
> - **PowerShell's escape character is a backtick, not a backslash.** `\"` inside a double-quoted
>   string is a `SyntaxError`, not an escaped quote. Nest single quotes inside double quotes instead,
>   and if you need a quote character inside Python, restructure so you do not.
> - **`%USERPROFILE%` is `cmd` syntax.** In PowerShell it is `$env:USERPROFILE`.
> - **`&&` and `||` do not exist** in Windows PowerShell 5.1. Use `;`, or separate commands.
>
> The first two were shipped in the first draft of this guide and found during manual testing — see
> T12, where the mutation command silently did nothing and the test that should have failed passed.

**What this phase changes, in one sentence:** the tool used to send *all* traffic through the proxy
pool and stop if the pool died; it now chooses **direct or proxy per kind of request**, and when the
proxy pool dies it degrades along a configured ladder instead of stopping — visibly, and under an
hourly cap on your own connection.

> **Interface note for the reviewer.** This guide is written against the interfaces named in
> [P4-IMPLEMENTATION-REVIEW §4](../P4-IMPLEMENTATION-REVIEW.md). It was written **before**
> implementation, deliberately. If implementation changes an interface, this file is corrected in
> the same commit, and the change is justified in the completion report.

---

## Before you start

> cd <the folder containing pyproject.toml>

**If the app is already running**, stop it — a stale process keeps port 5000 and serves you *old
code*, which looks exactly like a broken change:

> Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*dashboard*' } | Stop-Process -Force

**Record the state of the live database, so you can prove it afterwards:**

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ Ends with `OK — all 25 checks passed.`

**Back up your configuration.** Several tests edit `config.yaml`, and one of them deliberately puts
it in a state the suite reports as a failure:

> Copy-Item config.yaml config.yaml.backup

→ No output means it worked (PowerShell cmdlets are quiet on success). **Restore it with
`Copy-Item config.yaml.backup config.yaml -Force` at the end**, and delete the backup.

---

## Prerequisites checklist

Tick all of these before T1. Any unticked item makes later results meaningless.

| # | Prerequisite | How to confirm |
|---|---|---|
| P-1 | You are on the P4 branch or on `main` after P4 merged | `git log -1 --oneline` mentions P4 |
| P-2 | The virtual environment exists | `.\.venv\Scripts\python.exe --version` → `Python 3.12.x` |
| P-3 | Dependencies are installed | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` runs clean |
| P-4 | **No new package was added by P4** | `git diff <P3-tag>..HEAD -- requirements.txt` → **empty**. P4 adds no dependency |
| P-5 | The live database is present and intact | The `check_schema.py` run above passed |
| P-6 | `config.yaml.backup` exists | The copy above succeeded |
| P-7 | Nothing is listening on port 5000 | The stop-process command above ran |
| P-8 | P3's sign-off table is signed | [P03-testing.md](P03-testing.md) — the project's own rule ([EXECUTION_MODE_LOCK §4](../EXECUTION_MODE_LOCK.md)) |

---

# T1 — The automated gate is green

**Purpose:** prove the phase ships without lint errors, formatting drift, failing tests, deprecation
warnings, a coverage regression, or a broken architectural boundary.
**Preconditions:** none.

### Step 1 — Lint

> .\.venv\Scripts\python.exe -m ruff check .

→ **Expected:** `All checks passed!`

### Step 2 — Formatting

> .\.venv\Scripts\python.exe -m ruff format --check .

→ **Expected:** `N files already formatted` — N is larger than P3's 90, because P4 adds files.

### Step 3 — The full suite

> .\.venv\Scripts\python.exe -m pytest

→ **Expected:** all tests pass, with **2 skipped**. The count is higher than P3's `583 passed`.
Write the number down — you will compare it in T16.

The two skips are both in `tests/test_net.py` and need a proxy list this machine does not have
(`PROXY_FILE is not set`). They are skipped by design. To see which two:

> .\.venv\Scripts\python.exe -m pytest -q -rs

→ Two `SKIPPED` lines, both mentioning proxies. **If you now see three or more skips, stop** — P4
must not add a skipped test.

### Step 4 — No deprecation warnings

> .\.venv\Scripts\python.exe -m pytest -W error::DeprecationWarning

→ **Expected:** the same counts as Step 3.

### Step 5 — Coverage on the network layer

> .\.venv\Scripts\python.exe -m pytest --cov=src/net --cov-report=term

→ **Expected:** the `TOTAL` line shows **85% or higher**.

Before P4 this was **exactly 85%** — the gate floor. P4 adds five modules, so this number moving
*down* means new code shipped without tests.

### Step 6 — The database schema is untouched

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ `OK — all 25 checks passed.` **The same 25 as before.** P4 adds no table and no column.

### Step 7 — One migration head, unchanged

> .\.venv\Scripts\python.exe -m alembic heads

→ **Expected:** exactly one line, `0004_orchestration (head)`. P4 adds no migration.

**Possible failure**

| You see | Meaning | Troubleshooting |
|---|---|---|
| `N files would be reformatted` | A file was edited after formatting | `ruff format .` then re-run |
| Coverage below 85% | New network code shipped without tests | Stop. This is a gate failure, not a warning |
| More than one head | A migration was added | Stop. P4 owns no migration — this is a boundary breach |
| `26 checks passed` | The schema changed | Stop. Same |
| Three or more skips | A test was skipped rather than fixed | Stop |

---

# T2 — Environment setup for the proxy tests

**Purpose:** create a *fake* proxy file and a scratch config so every later test can exercise proxy
behaviour without a subscription and without touching the internet.
**Preconditions:** T1 passed.

### Step 1 — Create a fake proxy file

> notepad $env:USERPROFILE\p4-fake-proxies.txt

Paste exactly this and save:

```
203.0.113.10:8080:testuser:S3cretPassw0rd
203.0.113.11:8080:testuser:S3cretPassw0rd
203.0.113.12:8080:testuser:S3cretPassw0rd
```

These are **reserved documentation addresses** (RFC 5737). They do not exist and cannot be reached,
which is exactly what we want: every request through them fails, which is how the degradation tests
below are triggered.

`S3cretPassw0rd` is the string you will search for in T10. If it appears anywhere it should not,
that is a credential leak.

### Step 2 — Point the configuration at it

> notepad config.yaml

Find the `proxy:` section and set `file` to your fake file, **in single quotes**:

```yaml
proxy:
  enabled: true
  file: 'C:\Users\<you>\p4-fake-proxies.txt'
```

> ⚠️ Single quotes, not double. In a double-quoted YAML value a backslash starts an escape sequence,
> so `C:\Users` is a parse error. The existing comment in `config.yaml` says the same thing.

### Step 3 — Confirm the pool loaded

> .\.venv\Scripts\python.exe main.py dashboard

Open **http://127.0.0.1:5000/health/proxies**.

→ The page shows **3 proxies**, listed as `203.0.113.10:8080`, `203.0.113.11:8080`,
`203.0.113.12:8080`, all in state `untested`.

→ **The page shows no username and no password anywhere.** Only `host:port`.

Leave the dashboard running for T3–T12.

---

# T3 — Configuration verification: the `network:` block

**Purpose:** the phase's new configuration surface exists, is documented in the file itself, and the
app works with it *and* without it.
**Preconditions:** T2 done.

### Step 1 — Read the new block

> notepad config.yaml

→ There is a `network:` section. It contains, at minimum:

```yaml
network:
  policy: prefer_proxy            # direct_only | prefer_proxy | proxy_only
  direct:
    enabled: true
    max_requests_per_hour: 120
    classes: [rss, health, website]
  providers:
    - name: direct
      type: direct
      classes: [rss, health, website]
    - name: dc
      type: managed_list
      file: '${PROXY_FILE}'
      classes: [html, comments, validation]
  ladder: [direct, dc]
  on_pool_exhausted: degrade_to_direct
```

→ **Every key carries a comment explaining what it does and why that default was chosen.** This is
the standard the rest of `config.yaml` already holds; a key with no comment is a defect.

### Step 2 — The three policy values are documented

→ The comment above `policy:` names all three values and what each means. The comment above
`on_pool_exhausted:` names all three of *its* values.

### Step 3 — The app still starts with no `network:` block at all

Rename the section so the loader cannot see it: change `network:` to `network_disabled:` and save.
Restart the dashboard.

→ **Expected:** the dashboard starts normally, and `/health/proxies` still shows your 3 fake
proxies. The old `proxy:` block alone is enough — an installation that never gains a `network:`
block behaves exactly as it did before P4.

Change `network_disabled:` back to `network:` and restart.

**Possible failure**

| You see | Meaning |
|---|---|
| The app refuses to start without `network:` | The fallback path is broken; a machine upgrading from P3 would break on restart |
| Keys with no comments | Documentation standard not met |
| A fourth `policy` value not in the design | A design change was made without an amendment |

---

# T4 — Provider verification: every provider constructs from config

**Purpose:** prove the design's central claim — **swapping proxy vendors is a configuration change,
not a code change.**
**Preconditions:** T3 done.

### Step 1 — List what the running app built

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print(json.dumps({k:d[k] for k in ('policy','ladder','on_pool_exhausted','providers')}, indent=2))"

→ Something like:

```json
{
  "policy": "prefer_proxy",
  "ladder": ["direct", "dc"],
  "on_pool_exhausted": "degrade_to_direct",
  "providers": [
    {"name": "direct", "type": "direct",       "healthy": true,  "exposes_origin_ip": true,  "metered": false},
    {"name": "dc",     "type": "managed_list", "healthy": true,  "exposes_origin_ip": false, "metered": false}
  ]
}
```

→ **`exposes_origin_ip` is `true` for `direct` and `false` for every proxy provider.** That flag is
how the tool knows which providers reveal your home address; if a proxy reports `true` it is
misconfigured.

### Step 2 — Add a residential gateway with no code change

Edit `config.yaml` and add a third provider under `providers:`, and put it at the front of the
ladder:

```yaml
    - name: resi
      type: managed_gateway
      gateway: "gateway.example.com:7000"
      username: "gwuser"
      password: "GatewayP4ss"
      session_param: "-session-{key}"
      metered: true
      bandwidth_budget_gb: 1.0
      bandwidth_floor_gb: 0.05
      classes: [html, comments, validation]
  ladder: [resi, dc, direct]
```

Restart the dashboard and repeat Step 1.

→ **Expected:** three providers listed, `resi` first in the ladder, `"type": "managed_gateway"`,
`"metered": true`. **No Python file was edited.** That is N-AC6.

→ **`GatewayP4ss` appears nowhere in the response.** Check:

> .\.venv\Scripts\python.exe -c "import urllib.request; print('LEAK' if 'GatewayP4ss' in urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies').read().decode() else 'clean')"

→ `clean`

### Step 3 — Switch vendor by editing four lines

Change `gateway`, `username`, `password` and `session_param` to a different vendor's values (any
placeholder will do — nothing dials out). Restart.

→ **Expected:** the app starts and reports the new gateway. Four lines of YAML, zero lines of Python.

### Step 4 — The null provider

Add, temporarily, at the end of `providers:`:

```yaml
    - name: nothing
      type: null_provider
      classes: []
```

Restart.

→ **Expected:** the app starts and lists four providers. `nothing` reports `"healthy": false` — it
exists to prove a code path made no network call, so it is never selectable.

**Remove the `nothing` block and the `resi` block, and restore `ladder: [direct, dc]` before T5.**

**Possible failure**

| You see | Meaning |
|---|---|
| A `KeyError` or crash on an unknown provider type | Config errors must be readable, not stack traces |
| The password in the response | **Stop immediately.** R15 breach |
| Adding a provider required editing Python | The design's main economy has not been delivered |

---

# T5 — Direct-routing verification

**Purpose:** R18 — *"RSS, health checks and the customer's own website are always direct."* This is
frozen architecture, and it must hold **even when a healthy proxy pool exists and the policy prefers
proxies.**
**Preconditions:** T4 restored the two-provider ladder; `policy: prefer_proxy`.

### Step 1 — Ask the policy which provider each request class gets

> .\.venv\Scripts\python.exe -c "from src.config import load_config; from src.net.policy import build_policy_from_config; p=build_policy_from_config(load_config()); [print(f'{c:12} -> {p.provider_for(c).name}') for c in ('rss','health','website','html','comments','validation')]"

→ **Expected:**

```
rss          -> direct
health       -> direct
website      -> direct
html         -> direct
comments     -> direct
validation   -> direct
```

The last three say `direct` because your ladder is `[direct, dc]` (the P0-measured order). What
matters for R18 is the **first three**.

### Step 2 — Prove the first three ignore the policy entirely

Edit `config.yaml`: set `policy: proxy_only` and `ladder: [dc]`. Re-run the command in Step 1.

→ **Expected:**

```
rss          -> direct
health       -> direct
website      -> direct
html         -> dc
comments     -> dc
validation   -> dc
```

**This is the test.** Under the strictest possible policy, with `direct` removed from the ladder
altogether, RSS, health and website **still go direct**. They are not a ladder preference; they are
a rule.

### Step 3 — Prove it is not just a lookup table

Remove `rss` from `network.direct.classes`, leaving `classes: [health, website]`. Re-run Step 1.

→ **Expected:** the app **refuses to start**, or `rss` still reports `direct` with a logged warning
naming R18. It must **not** quietly route RSS through a proxy — the operator cannot switch off a
frozen architecture rule by editing a list.

**Restore `classes: [rss, health, website]`, `policy: prefer_proxy` and `ladder: [direct, dc]`.**

**Possible failure**

| You see | Meaning |
|---|---|
| `website -> dc` under any policy | **R18 breach.** Crawling a customer's own site from rotating datacenter IPs looks like an attack |
| Editing `classes` silently reroutes RSS | The rule is configuration, not architecture |

---

# T6 — Proxy-routing verification

**Purpose:** bulk HTML uses a proxy when one is healthy.
**Preconditions:** T5 restored the config.

### Step 1 — Put the proxy first in the ladder

Edit `config.yaml`: `ladder: [dc, direct]`. Restart the dashboard.

### Step 2 — Confirm the routing flipped

Re-run T5 Step 1.

→ **Expected:** `html`, `comments` and `validation` now say `dc`. `rss`, `health` and `website`
still say `direct`.

### Step 3 — Confirm the pool is the one being used

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print('pool size:', d['total']); print('requests so far:', sum(p['requests'] for p in d['proxies']))"

→ `pool size: 3`, `requests so far: 0`.

**Leave `ladder: [dc, direct]` in place for T7 — the degradation test needs the proxy to be tried
first so it can fail.**

---

# T7 — Degradation verification ⚠️ the headline behaviour

**Purpose:** when the proxy pool dies, the run **continues on the direct connection** and says so
**visibly** — instead of stopping, and instead of failing over silently.
**Preconditions:** T6 left `ladder: [dc, direct]`, `on_pool_exhausted: degrade_to_direct`, and the
three fake (unreachable) proxies loaded.

This test works because the fake proxies **cannot** be reached: every attempt through them fails,
the pool blacklists them, and the ladder must then step to `direct`.

### Step 1 — Start a run

In the browser, go to **http://127.0.0.1:5000** and press **Start scrape**.

→ You are taken to a run page at `/runs/<id>`.

### Step 2 — Watch the activity feed

→ When the subreddit finishes, among the `Scraping r/…` lines, a **warning-styled** entry appears:

> ⚠️ Egress degraded: dc → direct for html traffic (All 3 proxies are blacklisted. Check
> /health/proxies; they return to rotation after the cooldown.)

→ **The line names the provider it degraded *from* and the one it degraded *to*.** A message that
just says "degraded" tells the operator nothing.

→ **It appears once, not once per request, and not once per subreddit.** Scroll the whole feed:
there is exactly **one** such warning for the run, even with several subreddits.

> **Timing, and why it is not instant.** The entry appears when the *subreddit finishes*, not the
> instant the degradation happens. That is deliberate: writing to the database while a scrape is
> running would hold SQLite's single write lock across a multi-minute fetch, which is precisely the
> defect that blocked P3's sign-off. The application log gets the warning immediately — only the
> timeline row waits. See T14.

### Step 3 — Confirm the run completed rather than failing

→ The run reaches a finished state. It did **not** stop when the pool died. That is the whole point
of P4: *a truncated run is worse than a slower one.*

### Step 4 — Confirm the warning is stored, not just displayed

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/runs/<RUN_ID>/events')); [print(e['level'],'|',e['message']) for e in d['events'] if e['level']=='warning']"

(replace `<RUN_ID>` with the number from the URL)

→ At least one `warning | Proxy pool exhausted…` line.

### Step 5 — Confirm the proxies are marked, not silently ignored

Open **http://127.0.0.1:5000/health/proxies**.

→ All three fake proxies now show `blacklisted` (or `degraded`), with a non-empty `last error` and
a **failure count above zero**. A pool that reports itself healthy after failing every request is
the exact defect [29 §4.1](../29-network-and-proxy-strategy.md) exists to fix.

**Possible failure**

| You see | Meaning |
|---|---|
| The run fails with "proxy pool exhausted" | `on_pool_exhausted` is not being honoured, or the ladder never steps |
| No warning in the feed | **The operator cannot tell their home IP is now being used.** This is the criterion, not a nicety |
| Hundreds of identical warnings | The dedup in AS-7 is missing; the feed becomes unreadable |
| **An HTTP 500, or "database is locked" anywhere** | **STOP.** This is P3's F7 defect recreated by the degradation write. See T14 |

---

# T8 — Fallback verification: the three `on_pool_exhausted` values

**Purpose:** the three-value policy that replaced `fail_closed: true` is real, and you can see which
one is in force.
**Preconditions:** T7 done. Keep `ladder: [dc, direct]`, `policy: proxy_only` for steps 2–3.

> ⚠️ **Read this before you start, or step 3 will look like a bug.**
>
> `degrade_to_direct` is visibly different from the other two: the run collects leads. **`pause_run`
> and `fail_run` are *not* distinguishable from the run page in P4**, and that is a known,
> documented limit rather than a defect.
>
> The reason: `RedditClient._get` catches every transport failure and returns `None` instead of
> raising — a P2 decision, recorded in its own docstring and in
> [PHASE-03-HANDOVER T5](../PHASE-03-HANDOVER.md). So neither setting can reach the job handler as
> an exception, and both end the same way: the subreddit yields no pages and the job completes with
> zero leads. **This was true before P4 too** — the old `fail_closed: true` did not fail a job
> either, despite [08 §7](../08-proxy-service.md) implying it would.
>
> P4 carries the operator's answer correctly (`EgressExhausted.action` and `.retryable`); making the
> *run* respond to it needs the transport to raise, which is P5/P6's scope. Verified at the policy
> level by `pytest tests/test_network_policy.py -k on_pool_exhausted`.

### Step 1 — `degrade_to_direct` (the default)

Already proven in T7. → Run **completes and collects leads**, one warning in the feed.

### Step 2 — `proxy_only` + `pause_run`

Set `policy: proxy_only` and `on_pool_exhausted: pause_run`. Restart. Start a scrape.

→ **Expected:** the run completes with **zero leads**, and **no** "Egress degraded" warning appears —
because nothing degraded: the policy refused to use your address at all. Confirm on
`/api/health/proxies` that `direct_requests_this_hour` did **not** move.

### Step 3 — `proxy_only` + `fail_run` (the old `fail_closed` behaviour)

Set `on_pool_exhausted: fail_run`. Restart. Start a scrape.

→ **Expected:** identical to step 2 from the run page — zero leads, no degradation warning, your own
address unused. That identity is the documented limit above, not a failure.

→ **The difference is visible on the health page**, which is where P4 puts it:

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print(d['on_pool_exhausted'], '| fail_closed =', d['fail_closed'])"

→ `pause_run | fail_closed = False` in step 2, and `fail_run | fail_closed = True` in step 3.

### Step 4 — Confirm the setting actually changes behaviour where it can

→ Compare step 1 against steps 2–3: leads collected versus none, warning present versus absent,
`direct_requests_this_hour` moved versus unmoved. **That** is the behavioural difference P4 delivers.

**Restore `policy: prefer_proxy` and `on_pool_exhausted: degrade_to_direct`.**

---

# T9 — The hourly governor on your own connection

**Purpose:** degradation is **bounded**. The original objection to falling back to direct was that it
was *unbounded and silent*; P4's answer is a hard per-hour cap plus a visible warning. Prove the cap
exists.
**Preconditions:** T8 restored `degrade_to_direct`.

### Step 1 — Lower the cap so it can be reached

Edit `config.yaml`: `max_requests_per_hour: 3`. Restart the dashboard.

### Step 2 — Check the counter is exposed

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print(d['direct_requests_this_hour'], '/', d['direct_max_requests_per_hour'])"

→ `0 / 3`

### Step 3 — Spend the budget

Start a scrape and let it run for a minute.

→ Re-run Step 2. The counter climbs and **stops at 3**.

### Step 4 — Confirm hitting the cap is visible, not silent

Set `ladder: [direct, dc]` for this step, so there is a rung below direct to fall to. Restart and
scrape.

→ On the run page a warning appears naming the cap as the reason:

> ⚠️ Egress degraded: direct → dc for html traffic (direct-connection hourly limit reached (3 of 3).
> This cap bounds how much traffic can reach the target from this machine's own address; it resets
> as the oldest requests age out of the hour.)

→ The health page shows the same thing without needing a run:

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print([p for p in d['providers'] if p['name']=='direct'])"

→ the `direct` row reports `"healthy": false` with `"reason": "hourly limit reached (3 of 3)"`.

→ The run does not silently produce zero leads and report success. **A cap that is invisible is a
cap that gets blamed on Reddit.**

### Step 5 — Confirm one counter, not one per subreddit

This is the subtle one. Start a scrape with **at least three subreddits** configured.

→ **Expected:** the counter reaches 3 across the *whole run* and stops. If instead each subreddit
were allowed 3, you would see 9 — meaning the frozen 120/hour budget is really 120 × (number of
subreddits). Re-run Step 2 after the run finishes and confirm the total is **≤ 3**.

**Restore `max_requests_per_hour: 120`.**

**Possible failure**

| You see | Meaning |
|---|---|
| The counter exceeds the cap | The governor is advisory, not enforced |
| The counter resets between subreddits | The policy is being rebuilt per job — the cap is unenforced at N× (§7.1 P-2 of the review) |
| No warning at the cap | Silent throttling |

---

# T10 — Credential leakage verification

**Purpose:** R15 — *"Secrets never enter the database, a log, an API response, a template, or the
repository."* P4 adds a **new** credential path: gateway providers take their username and password
from configuration, not from the proxy file the existing protections were built around.
**Preconditions:** T4's `resi` gateway block re-added to `config.yaml` (with `password: "GatewayP4ss"`).

You are hunting two strings: `S3cretPassw0rd` (the fake proxy file) and `GatewayP4ss` (the gateway).

### Step 1 — Run with logging to a file

Edit `config.yaml`: set `logging.file: 'p4-test.log'` and `logging.level: DEBUG`. Restart, start a
scrape, let it finish.

### Step 2 — Search the log

> .\.venv\Scripts\python.exe -c "import pathlib; t=pathlib.Path('p4-test.log').read_text(errors='replace'); print('LEAK' if ('S3cretPassw0rd' in t or 'GatewayP4ss' in t) else 'clean'); print('lines:', t.count(chr(10)))"

→ **`clean`**, with a non-zero line count. (A zero line count means nothing was logged and the test
proved nothing — check `logging.file` took effect.)

### Step 3 — Search every API response

> .\.venv\Scripts\python.exe -c "import urllib.request; bad=[]; [bad.append(u) for u in ('/api/health','/api/health/proxies','/api/health/ai','/api/stats','/api/runs','/api/settings') if any(s in urllib.request.urlopen('http://127.0.0.1:5000'+u).read().decode() for s in ('S3cretPassw0rd','GatewayP4ss'))]; print('LEAK in: '+str(bad) if bad else 'clean')"

→ **`clean`**

### Step 4 — Search the rendered pages

Open each of `/`, `/health/proxies`, `/health`, `/runs` in the browser, press **Ctrl+U** (view
source) and **Ctrl+F** for `S3cretPassw0rd` and for `GatewayP4ss`.

→ **Zero matches on every page.**

### Step 5 — Search the database

> .\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/leads.db'); names=[r[1] for r in c.execute('select * from sqlite_master') if r[0]=='table']; hits=sorted({n for n in names for r in c.execute('select * from [' + n + ']') if any(s in str(r) for s in ('S3cretPassw0rd','GatewayP4ss'))}); print('LEAK in: '+str(hits) if hits else 'clean')"

→ **`clean`**

### Step 6 — Search the repository

> ⚠️ **Restore your configuration first, or this step lies to you.** In T4 you typed
> `password: "GatewayP4ss"` into `config.yaml`, which **is a tracked file** — so the search will
> match your own test fixture and you will not be able to tell it from a real leak. Restore first:
>
> > Copy-Item config.yaml.backup config.yaml -Force

Now search:

> git grep -n "S3cretPassw0rd" ; git grep -n "GatewayP4ss"

→ **The only match is this guide** (`docs/testing/P04-testing.md`), which names both strings on
purpose. **Any other file is a leak** — including `config.yaml`, which you just restored.

Re-apply your `network:` block and the fake proxy path afterwards if you are continuing to T11.

### Step 7 — Clean up

Delete `p4-test.log`, restore `logging.file: ''` and `logging.level: INFO`.

**Possible failure**

| You see | Meaning |
|---|---|
| Any `LEAK` | **STOP. Do not sign off.** R15 is one of the freeze's hard rules |
| The log file is empty | The search proved nothing — fix the logging config and redo |

---

# T11 — Health endpoint verification

**Purpose:** the operator can see, without reading code, which egress path is in use and whether it
is working.
**Preconditions:** dashboard running.

### Step 1 — The page renders the new information

Open **http://127.0.0.1:5000/health/proxies**.

→ In addition to the per-proxy table that existed before, the page shows:

- the **policy** in force (`prefer_proxy`)
- the **ladder**, in order
- the **`on_pool_exhausted`** setting, in words a non-developer can act on
- the **direct-connection counter**, `N / 120 this hour`
- one row **per provider**, with its type and whether it is currently healthy

### Step 2 — The old field is still there

> .\.venv\Scripts\python.exe -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies')); print('fail_closed:', d['fail_closed'], '| on_pool_exhausted:', d['on_pool_exhausted'])"

→ `fail_closed: False | on_pool_exhausted: degrade_to_direct`

Now set `on_pool_exhausted: fail_run`, restart, and re-run.

→ `fail_closed: True | on_pool_exhausted: fail_run`

**`fail_closed` is now derived from the new setting.** Nothing that read the old field breaks.
**Restore `degrade_to_direct`.**

### Step 3 — Target acceptance is reported

After the T7 run, re-open `/health/proxies`.

→ Each proxy row shows an **acceptance rate** — the share of *real target requests* it got through,
separate from whether the proxy is reachable at all.

→ Your three fake proxies show an acceptance rate of **0%**.

### Step 4 — A reachable-but-blocked proxy reports *degraded*, not healthy

This is N-AC5, and it is the reason acceptance exists. It cannot be produced with unreachable fake
proxies, so it is verified by the automated test instead:

> .\.venv\Scripts\python.exe -m pytest -k "acceptance or degraded" -v

→ All pass. Read the test names: one of them says, in words, that a proxy which passes the health
probe but is blocked by the target is reported degraded.

### Step 5 — The live check still detects a leak *(optional; needs real proxies)*

**Skip this step if you have no real proxy file.** With a real one configured, press **Check all
proxies** on `/health/proxies`.

→ The result reports `local_ip_known: true` and `leaking: []`. If any proxy's exit IP equalled your
own address, it would be listed — and that condition is still **fatal**, not a warning. P4 does not
soften it.

---

# T12 — Boundary and fence verification

**Purpose:** prove P4 stayed inside its own phase and did not break the four architectural
boundaries or the legacy contract.
**Preconditions:** T1 passed.

### Step 1 — Fence 4: the network layer knows nothing about Reddit

This is **new in P4** and is the one that did not previously exist.

> .\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py -v

→ All pass, including a test whose name mentions the network layer and Reddit. That test reads
every Python file under `src/net/` and fails if any *executable* code — a variable name, a string
used at runtime — mentions Reddit. Comments and docstrings are allowed and expected: `user_agents.py`
must be free to explain that it exists because of `old.reddit.com` 403s.

### Step 2 — Prove the fence actually bites

> **Why this step is safe to write down.** The fence scans **`src/net/` only** — that scope is stated
> in the test's own docstring. This guide lives in `docs/`, so the word it tells you to plant does
> not trip the fence from here. If the fence is ever widened beyond `src/net/`, this step must be
> rewritten; that is noted in the test.
>
> **No production file is edited.** You add one temporary file to `src/net/` and delete it again.
> That exercises the fence exactly as editing a shipped module would — the fence reads every `.py`
> under the tree — while leaving every tracked file untouched, so there is nothing to restore
> incorrectly and no chance of ending the test with a modified source file.

Plant the marker:

> Set-Content -Path src\net\_fence_probe.py -Value 'REDDIT_MARKER = "reddit"' -Encoding ascii

> .\.venv\Scripts\python.exe -m pytest tests\test_boundaries.py -k net -q

→ **Expected: FAILS**, and the message names the file and the tokens:

```
AssertionError: src/net/ is a reusable egress layer and must contain no Reddit knowledge
in executable code (R5). Offenders: ["src\net\_fence_probe.py: ['REDDIT_MARKER', 'reddit']"]
```

→ **Check the reason, not just the red.** It must be that `AssertionError`. If you see
`SyntaxError` instead, the file was written with a byte-order mark — see the warning below — and the
test failed for a reason that proves nothing about the fence.

Undo it:

> Remove-Item src\net\_fence_probe.py -Force

> .\.venv\Scripts\python.exe -m pytest tests\test_boundaries.py -k net -q

→ Passes again. Confirm nothing was left behind:

> git status --short

→ `src/net/` shows no changes. **A fence you have not seen fail is a fence you have not tested.**

> ⚠️ **`-Encoding ascii` is not optional, and this is the one place in the guide where the flag
> matters.** Windows PowerShell 5.1's `-Encoding utf8` writes a **byte-order mark**. Python's `ast`
> module then rejects the file with `SyntaxError: invalid non-printable character U+FEFF`, so the
> test fails — but for the wrong reason, and you would learn nothing about the fence. The marker is
> pure ASCII, so `ascii` is both correct and BOM-free. The same trap has bitten this project before
> (`docs/PHASE-03-COMPLETION-REPORT.md` §5.2, an encoding defect that sat latent for three phases).

### Step 3 — The other three fences

> .\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py -q

→ All pass. These cover: no AI-vendor coupling outside `src/ai/providers/`; deterministic modules
never import `src.ai`; `src/` never imports Hermes.

### Step 4 — The legacy contract

> .\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py tests/test_scrape_contract.py -q

→ All pass. These assert: the original **459 leads** are intact and unaltered, `GET /` renders
byte-identically, the CSV export has **13 columns**, and all **17 legacy endpoints** are present
with unchanged shapes.

### Step 5 — Nothing from a later phase leaked in

> git diff --stat <P3-tag>..HEAD

→ Read the file list. **Every file must appear in [P4-IMPLEMENTATION-REVIEW §2 or §3](../P4-IMPLEMENTATION-REVIEW.md).**
Specifically, **none of these may appear**:

| Must NOT be touched | Belongs to |
|---|---|
| `src/discovery/*`, `feed_parser.py`, any Atom fixture | P5 |
| `migrations/versions/0005*`, `watermarks`, `prescores` | P6 |
| Any `bkb_*`, `projects`, `website_fetcher.py` | P12–P16 |
| Any file under `migrations/` | no phase before P6 |
| `requirements.txt` | P4 adds no dependency |

### Step 6 — `RedditClient`'s public API is unchanged

> .\.venv\Scripts\python.exe -c "import inspect; from src.reddit_client import RedditClient; [print(n, inspect.signature(getattr(RedditClient,n))) for n in ('get_new_posts','get_hot_posts','search_posts','get_post_comments','get_user_posts','get_subreddit_info')]"

→ Six lines, identical to before P4. AD-2 freezes this API; P4 changed the transport underneath it,
not the interface.

---

# T13 — Rollback verification ⚠️ required

**Purpose:** prove the phase can be undone on a running installation without a code change or a
database restore. [34 §P4](../34-implementation-plan.md)'s Rollback row makes a specific promise;
this test is that promise.
**Preconditions:** the fake proxy file is configured.

### Step 1 — The stated rollback

Edit `config.yaml`:

```yaml
network:
  policy: proxy_only
  on_pool_exhausted: fail_run
```

Restart the dashboard. Start a scrape.

→ **Expected — this is exactly pre-P4 behaviour:** the scrape job **fails** because the pool is
unusable, and it never touches your direct connection. Check the run page: no "continuing on the
direct connection" warning appears.

### Step 2 — Prove your own IP was not used

> .\.venv\Scripts\python.exe -c "import urllib.request,json; print('direct requests this hour:', json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies'))['direct_requests_this_hour'])"

→ **`0`** for the classes that were rolled back. (RSS/health/website remain direct by R18 — that is
architecture, not a P4 behaviour, and rolling back P4 does not change it.)

### Step 3 — The stronger rollback: remove the block entirely

Delete the whole `network:` section from `config.yaml`. Restart.

→ **Expected:** the app starts and behaves exactly as it did in P3 — the legacy `proxy:` block alone
drives a single proxy pool, and `proxy.fail_closed: true` stops a scrape when the pool dies.

### Step 4 — The code-level rollback is clean

> git revert --no-commit <first-P4-commit>..<last-P4-commit> ; git status

→ Files are staged for revert; **no migration file and no data file appears**. Abort it:

> git revert --abort

→ Nothing was changed. **P4 writes no row and adds no table, so reverting it leaves nothing behind.**

### Step 5 — Restore

> Copy-Item config.yaml.backup config.yaml -Force

Then re-apply your `network:` block and the fake proxy path, and restart.

> ⚠️ **Do not leave the config in a rolled-back state and then re-run T1.** As in P3, a test asserts
> the *shipped* configuration, so the suite reports failures for as long as the file is rolled back.
> That is the test doing its job.

---

# T14 — The P3 regression that must not come back ⚠️ critical

**Purpose:** P3's sign-off was blocked by an HTTP 500 — cancelling a run mid-scrape returned
`database is locked`, because the scrape handler held SQLite's single write lock across a
multi-minute network call. **P4 adds a new write inside that same window** (the degradation
warning). This test proves it did not reopen the hole.
**Preconditions:** the fake proxy file configured, `ladder: [dc, direct]`,
`on_pool_exhausted: degrade_to_direct` — so degradation *definitely* happens during the run.

### Step 1 — Start a run that will degrade

Press **Start scrape**. Wait until you see the first `Scraping r/…` line.

### Step 2 — Cancel it while it is running

Press **Cancel run** on the run page.

→ **Expected:** the page responds normally. The run moves to a cancelled state. Queued subreddits
show as cancelled.

→ **NOT expected:** an HTTP 500, a red error banner, or anything mentioning `database is locked`.

### Step 3 — Repeat three times

Cancel at three different moments: immediately after the first subreddit starts, midway, and just as
the degradation warning appears (that last one is the new risk).

→ **All three behave identically.** Zero 500s.

### Step 4 — Confirm the automated guard exists

> .\.venv\Scripts\python.exe -m pytest tests/test_handlers_scrape.py -v

→ All pass, including a test asserting the handler's database session is **clean** at the moment the
scrape starts *and* after a scrape that degraded. That test is what stops this from regressing
silently — the manual run above is the backstop, not the guarantee.

**Possible failure**

| You see | Meaning |
|---|---|
| `database is locked`, or any HTTP 500 | **STOP. Do not sign off.** P3's F7 has been recreated by P4's new write |
| Cancel works but the degradation warning never appeared | The test did not exercise the risky path — retry with a longer scrape |

---

# T15 — One real scrape ⚠️ the only test that uses the internet

**Purpose:** the whole path works against the real target, on the real network, with the real header
profiles.
**Preconditions:** everything above passed. **This writes leads to your live database**, exactly as
pressing the button has always done.

### Step 1 — Use the direct-first ladder

Set `ladder: [direct, dc]`, `policy: prefer_proxy`, `max_requests_per_hour: 120`. Restart.

### Step 2 — Scrape

Press **Start scrape** and let it finish.

→ **Expected:** the run completes and collects leads. No degradation warning (the direct path is
first and works — that is what P0 measured at 100% success).

### Step 3 — Confirm the counter moved

> .\.venv\Scripts\python.exe -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health/proxies'))['direct_requests_this_hour'])"

→ A number greater than zero and well under 120.

### Step 4 — Confirm the database is intact

> .\.venv\Scripts\python.exe scripts\check_schema.py --db data\leads.db

→ `OK — all 25 checks passed.` The original 459 leads are untouched; new leads sit above them.

---

# T16 — Documentation verification

**Purpose:** [35 §2.1](../35-testing-strategy.md) check 18 — every documentation edit this phase owns
has landed, and no internal link is broken.
**Preconditions:** none.

### Step 1 — Each owned document was edited

> git diff --stat <P3-tag>..HEAD -- docs/

→ The list must include **all** of:

| Document | What to look for |
|---|---|
| [08 §3a](../08-proxy-service.md) | A new section on target-acceptance as the third health signal |
| [08 §7](../08-proxy-service.md) | `fail_closed: true` replaced by the three-value `on_pool_exhausted`, **with the original reasoning kept, not deleted** |
| [08 §10](../08-proxy-service.md) | `WebsiteFetcher` moved off the proxy pool |
| [08 §3.1](../08-proxy-service.md) | LRU recorded as the shipped strategy; `exclude=tried` now explicit |
| [07 §1](../07-scraping-pipeline.md) | *"All traffic via rotating proxy"* replaced by the per-request-class wording |
| [03 §6](../03-architecture.md) | **AD-25** present in the decision register |
| [03 §8](../03-architecture.md) | A **network provider** row in the technology table |
| [12 §14](../12-phase-02.md) | `exclude=tried` moved out of "deliberately not built" |
| [34 §P4](../34-implementation-plan.md) | A ✅ DELIVERED marker with the date and the decisions taken |
| [CHANGELOG.md](../../CHANGELOG.md) | A P4 entry |
| [PHASE-04-COMPLETION-REPORT.md](../PHASE-04-COMPLETION-REPORT.md) | Exists |
| [PHASE-04-HANDOVER.md](../PHASE-04-HANDOVER.md) | Exists |
| [progress/P04-COMPLETE.md](../progress/P04-COMPLETE.md) | Exists |

### Step 2 — The completion report is honest about what changed

Open [PHASE-04-COMPLETION-REPORT.md](../PHASE-04-COMPLETION-REPORT.md).

→ It states the **measured** test baseline before and after, not the doc's unverifiable "251".
→ It **justifies every changed existing test** — P4's acceptance allows changes only if justified.
→ It records any defect found during implementation, including ones found by this guide.

### Step 3 — No broken internal links

> .\.venv\Scripts\python.exe -m pytest -k "doc or link" -q

→ Passes (or reports that no such test exists, in which case spot-check five links in the documents
above by clicking them on GitHub).

---

# Sign-off

Complete this table. **A phase is not done until a human has run this guide** — see
[EXECUTION_MODE_LOCK §4](../EXECUTION_MODE_LOCK.md).

| Test | What it proves | Pass / Fail | Tester | Date | Notes |
|---|---|---|---|---|---|
| T1 | The automated gate is green: lint, format, tests, no deprecations, coverage ≥85%, schema and migration untouched | | | | |
| T2 | Environment set up; fake pool loads; no credential on the page | | | | |
| T3 | The `network:` config block exists, is documented, and is optional | | | | |
| T4 | Every provider constructs from config; a vendor swap is four YAML lines | | | | |
| T5 | RSS, health and website go **direct** even under `proxy_only` (R18) | | | | |
| T6 | Bulk HTML uses the proxy when the ladder prefers it | | | | |
| T7 | Pool death degrades to direct, the run completes, and the warning is **visible** | | | | |
| T8 | `degrade_to_direct` collects leads where `proxy_only` does not; the setting is visible on the health page | | | | |
| T9 | The hourly direct cap is enforced, visible, and shared across the whole run | | | | |
| T10 | No credential in any log, response, page, table or file | | | | |
| T11 | The health surface shows policy, ladder, providers and acceptance | | | | |
| T12 | Fence 4 exists **and was seen to fail**; all four fences and the legacy contract hold; no later-phase file touched | | | | |
| T13 | The documented rollback reproduces pre-P4 behaviour, in config alone | | | | |
| T14 | **Cancel mid-scrape does not return HTTP 500** — P3's F7 has not returned | | | | |
| T15 | One real scrape works end to end on the live network | | | | |
| T16 | Every owned document landed; the completion report is honest | | | | |

**Blocking tests.** T5, T7, T10, T12, T13 and T14 are **not optional and not negotiable**. T5 and
T12 protect frozen architecture, T10 protects credentials, T13 protects the ability to undo, and
T14 protects against the defect that blocked the previous phase's sign-off. A phase with any of
these failing does not ship, regardless of schedule.

**Cleanup after sign-off**

> Copy-Item config.yaml.backup config.yaml -Force
> Remove-Item config.yaml.backup -Force
> Remove-Item $env:USERPROFILE\p4-fake-proxies.txt -Force
> Remove-Item p4-test.log -Force -ErrorAction SilentlyContinue
> Remove-Item src\net\_fence_probe.py -Force -ErrorAction SilentlyContinue

Then confirm nothing is left behind:

> git status --short

→ Only `config.yaml` may differ, and only if you chose to keep a setting you changed. **No file
under `src/` or `tests/` may appear.**

**Signed:** ______________________  **Date:** ______________
