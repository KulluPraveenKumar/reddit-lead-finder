# P4 DECISION ANALYSIS — D-A, D-B, D-C

**Companion to** [P4-IMPLEMENTATION-REVIEW.md](P4-IMPLEMENTATION-REVIEW.md) §9.
**Status:** awaiting decision. **No source file has been modified.**

Three decisions block stage 1. Each is analysed below across seven dimensions: recommendation,
alternatives, trade-offs, implementation impact, testing impact, rollback impact, and future-phase
impact — with the reasoning that makes the recommendation the *best* option rather than merely the
first one listed.

---

# D-A — The shipped default policy and ladder

## A.0 The conflict, precisely

Three frozen documents disagree about what P4 should ship as its default.

| Source | Says | Authority |
|---|---|---|
| [29 §2.2](29-network-and-proxy-strategy.md) | `policy: prefer_proxy`, and enumerates **exactly three** values: `direct_only \| prefer_proxy \| proxy_only` | Frozen design doc |
| [29 §5.4](29-network-and-proxy-strategy.md) | `ladder: [resi, dc, direct]` — degrade proxy → proxy → direct | Frozen design doc |
| [29 §5.3](29-network-and-proxy-strategy.md) | *"✅ **CONFIRMED BY MEASUREMENT, P0 2026-08-05.** … **Buy nothing.**"* — stamped **into the frozen doc itself** by P0 | Measurement |
| [SPRINT-0 §1.6](SPRINT-0-MEASUREMENTS.md) | *"▶ **DIRECT**, with Webshare retained as a configured fallback… the ladder — `direct → webshare` — is what P4 implements"* | Measurement, reproduced twice |
| [34 §P4](34-implementation-plan.md) Depends-on | *"P0 (U8 block-rate result)"* | The plan makes the measurement a **dependency**, not a suggestion |
| [ARCHITECTURE_FREEZE §2 R18](ARCHITECTURE_FREEZE.md) | Egress per request class; RSS/health/website always direct | Frozen rule |

The measured numbers: **direct 100% success / 0% blocks / 1,342 ms**; **Webshare 71.4% / 28.6% /
2,081 ms**. Direct also won on CPU (2.55×) and posts extracted (175 vs 125). Reproduced twice with
identical success and block rates. There is **no dimension on which the datacenter pool is better.**

`resi` does not exist — no residential proxy has been purchased, and [ARCHITECTURE_FREEZE §9](ARCHITECTURE_FREEZE.md)
lists the purchase as *deferred*, triggered by *"P0's U8 shows an unacceptable block rate"*. P0
showed the opposite. So `[resi, dc, direct]` cannot ship as written regardless of the rest of this
analysis: its first rung is a provider with no credentials.

The residue is a naming problem. The three-value enum has no way to say **"direct first, proxy as
fallback"** — which is precisely what the measurement prescribes.

## A.1 Recommendation

> ## ▶ **A1 — the `ladder` is the sole ordering authority. Ship `policy: prefer_proxy` with `ladder: [direct, dc]`.**

`policy` keeps its three documented values and answers one question only: **which providers are
*eligible*.** `ladder` answers a different question: **in what order eligible providers are tried.**

```yaml
network:
  policy: prefer_proxy          # which providers are ELIGIBLE
  ladder: [direct, dc]          # what ORDER they are tried in  ← P0's measured order
  on_pool_exhausted: degrade_to_direct
  direct:
    classes: [rss, health, website]   # R18 — unconditional, not a ladder preference
```

| `policy` | Eligible providers | Ladder honoured? |
|---|---|---|
| `direct_only` | `direct` only | Trivially |
| `prefer_proxy` | all | **Yes — this is where the ladder lives** |
| `proxy_only` | proxies only (`direct` filtered out) | Yes, over the proxies |

## A.2 Why this is the best option, not just an available one

**1. It is the only option that ships the measurement without contradicting a frozen document.**
[ARCHITECTURE_FREEZE §11](ARCHITECTURE_FREEZE.md) permits amendment only when *"a Validation Sprint
or a phase's acceptance testing proves a stated assumption false."* P0 did not prove AD-25 false —
[SPRINT-0 §1.6](SPRINT-0-MEASUREMENTS.md) says explicitly *"AD-25 is validated exactly as written:
egress is a policy, chosen per request class, with a degradation ladder. **The measurement sets the
default**, and the ladder … is what P4 implements."* A1 changes only the default ordering — the
thing the measurement is *for*. Nothing about the mechanism moves.

**2. The two-axis split is already in the design, not invented here.** [29 §5.4](29-network-and-proxy-strategy.md)
ships `policy` and `ladder` as **separate keys** in the same block. If `policy` fully determined
order, `ladder` would be redundant — the design would not carry both. A1 is a reading of the existing
config schema, not an extension of it.

**3. It makes vendor swap and re-measurement a one-line change, which is the phase's stated point.**
When residential proxies are eventually bought, the change is `ladder: [resi, direct, dc]` — one
line. Under any scheme where ordering is encoded in an enum, a re-measurement means a new enum value
and a code change, which is exactly the coupling [29 §5.4](29-network-and-proxy-strategy.md) says
must not exist.

**4. It preserves the Rollback row *exactly*.** [34 §P4](34-implementation-plan.md) promises
`policy: proxy_only` + `on_pool_exhausted: fail_run` reproduces pre-P4 behaviour. Under A1 that is
literally true: `proxy_only` filters `direct` out of eligibility, so the ladder cannot reach it, and
`fail_run` stops on exhaustion — which is `fail_closed: true`. Under A2 (a fourth value) the same
promise holds, but under A3 the rollback row becomes untestable because there was never a fallback
to roll back.

**5. The one real cost is a name, and the name is already inherited.** `prefer_proxy` reading oddly
beside a direct-first ladder is a documentation wart, mitigated by a comment in `config.yaml` and a
line in [08 §7](08-proxy-service.md). Weighed against a fourth enum value in a frozen document, or
against shipping a measured-worse default, a wart is the cheapest of the three.

## A.3 Alternatives and trade-offs

| | **A1 — ladder is authority** ▶ | **A2 — add `prefer_direct`** | **A3 — `direct_only`** |
|---|---|---|---|
| Ships P0's measured order | ✅ | ✅ | ✅ |
| Enum matches [29 §2.2](29-network-and-proxy-strategy.md) | ✅ three values | ❌ four | ✅ |
| Names things honestly | ⚠️ `prefer_proxy` reads oddly | ✅ | ✅ |
| Fallback exists when direct is spent | ✅ steps to `dc` | ✅ | ❌ **none** |
| Rollback row testable | ✅ | ✅ | ❌ nothing to roll back |
| Requires a doc reconciliation | ❌ | ✅ §11.1 entry | ❌ |
| Exercises the ladder in production | ✅ | ✅ | ❌ ladder is dead code |
| Re-measurement cost | 1 config line | 1 config line | code + config |

**A3's fatal flaw.** `direct_only` means the Webshare pool is configured and never consulted. When
the hourly governor is spent — 120 requests, a frozen budget — there is **no second rung**. The run
stalls, and P4's entire ladder mechanism (`on_pool_exhausted`, the degradation warning, the
provider ABC's `health()`) becomes untested, unexercised code shipped for no current caller. That is
precisely the "placeholder implementation" the quality bar forbids. A3 also cannot satisfy
acceptance A2 (*"degrades per policy"*) because nothing to degrade *to* is eligible.

**A2's cost is small but real.** Adding `prefer_direct` is honest and I would not argue against it.
It requires an [ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) reconciliation entry (a
documentation inconsistency, not an amendment — no technology, table or decision changes), plus
edits to [29 §2.2](29-network-and-proxy-strategy.md) and its behaviour table. **If you prefer clear
naming over a minimal diff, take A2 — the implementation cost difference is roughly ten lines and
one doc entry.** A1 wins on strict-minimum-change; A2 wins on legibility.

## A.4 Implementation impact

| | A1 | A2 |
|---|---|---|
| `src/net/policy.py` | `eligible_providers(policy)` + ordered walk of `ladder` | + one enum member and one branch |
| `config.yaml` | `network:` block with a comment explaining the two axes | Same, plus the fourth value documented |
| Doc edits | [08 §7](08-proxy-service.md) records the two axes | Same + [29 §2.2](29-network-and-proxy-strategy.md) + a §11.1 entry |
| Estimated LOC | ~35 in `policy.py` | ~45 |

Neither touches `ProxyManager`, `http_client`'s request loop, or any consumer.

## A.5 Testing impact

Both options are tested identically — the tests assert **behaviour**, not the enum spelling:

- `prefer_proxy` + `ladder: [direct, dc]` → `html` resolves to `direct`; kill direct → resolves to `dc`.
- `proxy_only` → `html` resolves to `dc`; direct is **never** returned, even when `dc` is exhausted
  (instead `on_pool_exhausted` fires). **This is the rollback test and it is the important one.**
- `direct_only` → `html` resolves to `direct`; `dc` never selected.
- Under **all three**, `rss`/`health`/`website` resolve to `direct` — R18, asserted separately
  (T5 in the manual guide, and a unit test).
- Mutation: make `ladder` ignored → the `prefer_proxy` ordering test must fail.

No existing test changes under either option. `TestFailClosed` in `tests/test_net.py` keeps passing
because the legacy `proxy.fail_closed` path is untouched.

## A.6 Rollback impact

**A1 makes the documented rollback exactly true**, which is the strongest single argument for it.
Three levels, all config-only, all verified by T13 in the manual guide:

1. `policy: proxy_only` + `on_pool_exhausted: fail_run` → pre-P4 behaviour.
2. Delete the `network:` block → the legacy `proxy:` block drives one pool, exactly as in P3.
3. `git revert` → nothing left behind; P4 owns no migration and writes no row.

A3 breaks level 1: you cannot roll back to "proxy required" from a state where the proxy was never
reachable in the first place.

## A.7 Future-phase impact

| Phase | Effect |
|---|---|
| **P5** (RSS) | RSS is a `direct.classes` member under every policy. P5 inherits routing and writes none |
| **P6** (discovery) | The steady-state ≤80 req/day budget lives comfortably under the 120/hour governor |
| **P13** (WebsiteFetcher) | `website` is already direct-by-rule — P13 adds a consumer, not a routing decision. This is the [29 §2](29-network-and-proxy-strategy.md) design error P4 fixes before it can be made |
| **P17** (subreddit validation) | The burstiest class in the system; it is proxy-preferred, and A1 lets an operator flip `ladder: [dc, direct]` for that alone if a burst gets blocked |
| **Residential purchase** | `ladder: [resi, direct, dc]` — one line. Under A2, one line. Under A3, a code change |

---

# D-B — Fence 4 does not exist, and writing it fails

## B.0 The finding

[35 §2.1](35-testing-strategy.md) check **11** — *"Fence 4 — no Reddit knowledge in `src/net/`"* — is
one of **four checks the strategy names non-negotiable**: *"A phase does not merge with any of them
failing, regardless of schedule."* [12 §14](12-phase-02.md) ticks it as delivered:
`[x] src/net/ with no Reddit identifiers (grep test)`. [ARCHITECTURE_FREEZE §2 R5](ARCHITECTURE_FREEZE.md)
states the rule. [34 §P4](34-implementation-plan.md)'s own Acceptance row repeats it.

**No such test exists.** `tests/test_boundaries.py` implements fences 1–3 and nothing for `src/net/`.

Running the specified check (AST-based, executable tokens only — per the
[ARCHITECTURE_FREEZE §11.1](ARCHITECTURE_FREEZE.md) reconciliation that made fences 1 and 4
AST-based rather than `grep -ri`) produces **seven hits, all in `src/net/blocks.py`**:

```
_NEW_REDDIT_MARKERS                                  (identifier, twice)
"shreddit-app"                                       (runtime string)
"shreddit-async-loader"                              (runtime string)
"welcome to reddit"                                  (runtime string)
"Reddit rate-limit interstitial"                     (runtime string)
"served the new Reddit app instead of old HTML"      (runtime string)
```

Every other file under `src/net/` is clean — including `user_agents.py`, whose docstring explains
`old.reddit.com` 403s at length and is correctly ignored by an AST-based scan.

This is a **pre-existing defect inherited from P2**, not something P4 introduced. But P4's acceptance
row claims it, so P4 must resolve it.

## B.1 Recommendation

> ## ▶ **B1 — move the Reddit-specific block signatures out of `src/net/` and inject them from `RedditClient`.**

```python
# src/net/blocks.py — stays generic
@dataclass(frozen=True)
class BlockSignatures:
    soft_markers:  tuple[tuple[str, str], ...] = GENERIC_SOFT_MARKERS
    bad_titles:    tuple[str, ...]             = GENERIC_BAD_TITLES
    app_markers:   tuple[str, ...]             = ()

def classify(status_code, html, *, expect_selector_hits=None,
             signatures: BlockSignatures = DEFAULT_SIGNATURES) -> BlockVerdict: ...
```

`GENERIC_SOFT_MARKERS` keeps what is genuinely target-agnostic — `"just a moment"` (Cloudflare),
`"checking your browser"`, `"enable javascript and cookies to continue"`, `"verifying you are
human"`, `"access to this page has been denied"`. These describe **challenge pages**, which any
target may serve; none names a target.

The Reddit set — `shreddit-*`, `"welcome to reddit"`, `"whoa there, pardner"` — moves to
`src/reddit_client.py` as `REDDIT_SIGNATURES`, passed into `ProxiedHTTPClient(block_signatures=…)`
at construction.

## B.2 Why this is the best option

**1. It is the only option that makes the fence *mean* what it says.** The rule exists because
[08](08-proxy-service.md)'s opening line is *"`src/net/` knows nothing about subreddits, leads, or
Reddit markup"* — and the payoff is named: *"That separation is what lets Phase 4's website fetcher
inherit the whole thing for free."* A block detector that hard-codes Reddit's interstitial markup
**is Reddit markup knowledge in the transport layer.** The fence is not a spelling rule; `blocks.py`
is the one file where it currently fails, and it fails for the substantive reason, not an incidental
one.

**2. It is load-bearing for P13, and cheaper now than then.** [29 §2.1](29-network-and-proxy-strategy.md)
routes the customer's own website through this same client. Today, fetching `acme.com` and getting a
page whose title happens to read *"Welcome to Reddit"* is impossible — but fetching a customer site
that serves a Cloudflare challenge is entirely likely, and `blocks.py` must classify that while
**not** applying Reddit's `shreddit` heuristics to a page that has nothing to do with Reddit. The
`expect_selector_hits == 0 and new-Reddit-marker` rule is actively wrong for a non-Reddit target.
Injection makes the per-target signature set explicit, which is what P13 needs anyway.

**3. It is the root-cause fix, and the quality bar for this project forbids the others.** B2 (an
allowlist) makes the single most-likely-to-break file exempt from the check that would catch it.
B3 (defer) means P4 cannot claim its own acceptance row. The project's stated standard — *"root-cause
fixes only, no hacks"* — selects B1 without needing the other arguments.

**4. It deletes nothing.** Every signature that exists today still exists and is still applied to
Reddit traffic. The change is *where the list is declared*, not *what is detected*. The risk is
mis-wiring, not loss of capability — and mis-wiring is exactly what a mutation test catches.

## B.3 Alternatives and trade-offs

| | **B1 — inject signatures** ▶ | **B2 — allowlist `blocks.py`** | **B3 — defer fence 4** |
|---|---|---|---|
| Fence 4 passes | ✅ honestly | ⚠️ by exemption | ❌ |
| P4 can claim its acceptance row | ✅ | ⚠️ arguable | ❌ |
| R5 actually enforced | ✅ | ❌ on the one file that breaks it | ❌ |
| Touches shipped block detection | ⚠️ **yes — the real cost** | ❌ | ❌ |
| Existing tests changed | ~2, justified under A6 | 0 | 0 |
| P13 inherits a correct detector | ✅ | ❌ applies Reddit heuristics to customer sites | ❌ |
| Effort | ~60 LOC + test moves | ~5 LOC | 0 |

**B1's honest cost.** `blocks.py` is the module whose own docstring says a false negative *"poisons
the cache and the lead table"* — a silent, plausible, completely wrong answer. Refactoring it is not
free, and this is the strongest argument *against* B1. It is answered rather than dismissed: the
signatures are **moved, not rewritten**; the existing detection tests move with them and must still
pass byte-for-byte on the same fixtures; and a mutation test (remove the injection from
`RedditClient`) must make those tests fail. If that mutation does **not** fail, the wiring is wrong
and we find out in stage 10 rather than in production.

**If you judge that risk unacceptable**, B2 is the fallback — but then the completion report must
state plainly that fence 4 ships with an exemption on the one file it was written for, and the
[12 §14](12-phase-02.md) tick stays wrong. I do not recommend it.

## B.4 Implementation impact

| File | Change | LOC |
|---|---|---|
| `src/net/blocks.py` | `BlockSignatures` dataclass; `classify(..., signatures=)`; generic defaults | ~35 changed |
| `src/net/http_client.py` | `__init__(..., block_signatures=None)`; pass through to `classify` | ~6 |
| `src/net/__init__.py` | Export `BlockSignatures` | ~2 |
| `src/reddit_client.py` | `REDDIT_SIGNATURES` constant; pass into the client in `_default_client` | ~20 |
| `tests/test_boundaries.py` | The fence test | ~30 |
| `tests/test_net.py` | ~2 tests in `TestBlockClassification` construct with the Reddit set | ~10 |

**No interface is removed.** `classify(status, html, expect_selector_hits=…)` keeps working with
generic defaults; the parameter is additive.

## B.5 Testing impact

- **Fence test** (new): AST-parse every file under `src/net/`, collect identifiers and non-docstring
  string constants, fail on `reddit`/`subreddit` case-insensitively. Named so its failure message
  says which file and which token.
- **Fence bites** (mutation, T12 Step 2 in the manual guide): inject `REDDIT_MARKER = "reddit"` into
  `src/net/metrics.py` → the fence must fail; revert → pass. *A fence you have not seen fail is a
  fence you have not tested.*
- **Detection unchanged**: every existing soft-block fixture (the 311 KB interstitial, `"just a
  moment"`, the bad-title cases) still classifies identically — asserted on the same fixtures.
- **Detection mutation**: remove the signature injection from `RedditClient` → the Reddit
  interstitial tests must fail. This is the guard against silent mis-wiring, and it is the one test
  that proves B1 was done correctly rather than merely done.
- **Generic still works**: a Cloudflare challenge is detected with *no* signatures injected — the
  case P13 will rely on.

> ⚠️ [35 §2.4](35-testing-strategy.md) records that mutation testing already caught *"a soft-block
> fixture that tripped two independent detection paths"* in this exact module. Any new fixture must
> trip **one** path, or the test passes for the wrong reason.

## B.6 Rollback impact

None beyond the phase's own revert. No config key, no schema, no data. Reverting P4 restores the
hard-coded signatures and removes the fence — a clean, complete undo.

## B.7 Future-phase impact

| Phase | Effect |
|---|---|
| **P5** (RSS/Atom) | A malformed feed must raise `ParseError`, never a silent empty list. Feed responses are XML and hit none of these HTML heuristics — but P5 may add an Atom-specific signature set through the same seam rather than by editing `src/net/` |
| **P6** | Discovery bypasses `http_cache` (D5); block classification is unaffected |
| **P13** (WebsiteFetcher) | **The main beneficiary.** Fetches customer sites with the generic set only — no Reddit heuristic is applied to a page that is not Reddit |
| **P30** (security review / CI) | Fence 4 becomes a standing CI check rather than a documentation claim |
| Standing | The fence prevents the next engineer from putting a Reddit selector back into the transport by reflex |

---

# D-C — Where the degradation `run_events` warning is written

## C.0 The constraint that makes this hard

Two requirements point in opposite directions.

**Requirement 1 — the warning must exist and be visible.** [34 §P4](34-implementation-plan.md)
Acceptance: *"degradation emits a **visible `run_events` warning**"*. [29 §2.2](29-network-and-proxy-strategy.md)
is emphatic that this is what makes bounded degradation acceptable at all: *"What changes is that
degradation is now **bounded and visible** … rather than an unbounded silent fallback. ▶ A capped,
logged fallback is a different thing from the uncapped one that decision rejected."* Without the
warning, P4 has shipped the thing [08 §7](08-proxy-service.md) rejected.

**Requirement 2 — the scrape handler's session must stay clean across the network call.** This is
P3's F7, the defect that blocked the previous phase's sign-off:

```
sqlite3.OperationalError: database is locked
[SQL: UPDATE jobs SET state=? WHERE jobs.run_id = ? AND jobs.state = ?]
  job_queue.py:385 cancel_queued  <-  run_service.py:374 cancel
```

`emit_event()` (`src/obs/events.py`) **adds to the caller's session and does not commit** — by
design, so a timeline entry can never claim a stage completed in a transaction that rolled back.
`handle_scrape_subreddit` therefore commits its bookkeeping *before* calling the scraper, and
`tests/test_handlers_scrape.py` asserts the session is clean at that moment.

**Degradation happens deep inside `src/net/`, which has no session and no `run_id`, and it happens
in the middle of `scraper.run()` — inside exactly the window F7 made dangerous.** A naive
`emit_event(session, run_id, "net.degraded", …)` from the policy would need the handler's session,
would dirty it mid-scrape, and would recreate the HTTP 500.

## C.1 Recommendation

> ## ▶ **C1 — the policy accumulates degradation notices in memory; the handler drains them into `run_events` after `scraper.run()` returns.**

```python
# src/net/policy.py — no session, no run_id, no ORM import
@dataclass(frozen=True)
class DegradationNotice:
    from_provider: str
    to_provider: str
    reason: str
    at_request: int

class NetworkPolicy:
    def drain_notices(self) -> list[DegradationNotice]: ...   # returns and clears
```

```python
# src/orchestration/handlers/scrape.py
session.commit()                    # unchanged — F7's fix, do not touch

scraper = build_scraper(load_config())
leads = scraper.run(session, subreddits=[subreddit], run_id=run_id)

for notice in get_network_policy().drain_notices():          # ← after the network call
    emit_event(session, run_id, "net.degraded", level="warning",
               message=f"Proxy pool exhausted — continuing on {notice.to_provider} …",
               **notice.as_data())

service.note_subreddit_finished(run_id, leads)               # existing, unchanged
```

The notices land in the transaction the handler already commits after the scrape — the same
transaction as `note_subreddit_finished` and the finalise enqueue. G1 is untouched.

## C.2 Why this is the best option

**1. It cannot recreate F7, and that is provable rather than argued.** The write happens strictly
after `scraper.run()` returns — outside the network window entirely. The existing assertion (*the
session is clean when the scrape starts*) is not merely still true; it is true for the same reason it
was before, because nothing was added between the commit and the scraper call. C2 keeps the handler's
session clean too, but does so by *introducing a second concurrent writer during the scrape* — which
is a new claim requiring new evidence, at the exact point in the codebase where the previous phase's
sign-off was blocked. **Given a choice between "no new write during the risky window" and "a new
write that we believe is safe", the phase that was blocked by exactly this should take the former.**

**2. `src/net/` stays session-free, which is R5's actual purpose.** Under C1, the network layer
returns *data* — a list of value objects — and the orchestration layer decides what to do with it.
Under C2, `src/net/` (or the seam that builds it) holds a callback that opens database sessions,
putting a persistence dependency into the layer whose whole justification is that it is reusable
infrastructure knowing nothing about the application. P13's `WebsiteFetcher` and P5's feed client
both reuse this layer; neither should inherit a database dependency to get a warning.

**3. The delay is bounded by one subreddit, and the log is immediate.** The cost — the warning
appears on `/runs/<id>` when the subreddit finishes rather than the instant it degrades — is real
but small: one subreddit, typically well under a minute. And it is only the *timeline row* that
waits. The application log gets the warning immediately, because degradation logs at `WARNING` in
`src/net/` regardless. An operator watching the log sees it in real time; an operator watching the
run page sees it a subreddit later.

**4. It composes with the dedup requirement for free.** AS-7 requires one event per run per ladder
step, not one per request. An accumulator that dedups on `(from, to)` before draining is the natural
shape. Under C2, dedup means the callback holds state anyway — so C2 ends up carrying an accumulator
*and* a session factory.

**5. Rollback is trivial.** If draining turns out to be wrong, deleting four lines from the handler
removes the feature and leaves the transport untouched.

## C.3 Alternatives and trade-offs

| | **C1 — drain after return** ▶ | **C2 — callback with its own session** | **C3 — log only, no `run_events`** |
|---|---|---|---|
| Satisfies "visible `run_events` warning" | ✅ | ✅ | ❌ **fails acceptance** |
| Cannot recreate F7 | ✅ structurally — no write in the window | ⚠️ believed safe; new writer in the window | ✅ |
| `src/net/` stays session-free | ✅ | ❌ callback carries a session factory | ✅ |
| Real-time on the run page | ❌ one subreddit late | ✅ | ❌ |
| Real-time in the log | ✅ | ✅ | ✅ |
| Survives a handler failure | ❌ rolled back with the transaction | ✅ committed independently | ✅ log persists |
| New code | ~25 LOC | ~45 LOC + a session factory at the seam | ~5 LOC |

**C1's honest cost, stated plainly.** If the handler raises *after* the scrape — say the finalise
enqueue fails — the drained notices roll back with it, and the timeline loses the warning for that
attempt. Three things make this acceptable: the log line survives regardless; the job is retried and
the notice is re-emitted (the accumulator is per-policy, and a retry re-degrades if the pool is still
dead); and a handler that raises produces a *louder* signal than a missing warning. **If you weigh
warning durability above F7 risk, C2 is the correct choice** — it is the only option where the
warning survives a rolled-back handler.

**C3 is listed for completeness and is not viable.** It fails the acceptance criterion directly, and
it reintroduces exactly the "silent fallback" that [08 §7](08-proxy-service.md) rejected and
[29 §2.2](29-network-and-proxy-strategy.md) spent a section answering.

## C.4 Implementation impact

| File | Change | LOC |
|---|---|---|
| `src/net/policy.py` | `DegradationNotice`, accumulator with `(from, to)` dedup, `drain_notices()` | ~25 |
| `src/orchestration/handlers/scrape.py` | Drain loop after `scraper.run()` | ~8 |
| `src/dashboard/templates/run_progress.html` | None — `warning` level already renders distinctly | 0 |

The handler's `session.commit()` before the scrape is **not touched**, and neither is the ordering
around it. That comment block stays exactly as P3 left it, including its explanation.

## C.5 Testing impact

Three tests, and the first one is the phase's most important test:

**1. The session is clean after a degrading scrape** (`tests/test_handlers_scrape.py`). Extends the
existing clean-session assertion past the scrape. **The double must reproduce the property under
test** — P3's F4/F7 lesson, twice-learned:

> The fake scraper must **query the database** during `run()`, so SQLAlchemy autoflush fires and
> takes SQLite's write lock exactly as `LeadScorer` does in production. A fake that works without
> querying is how F7 passed 583 tests and failed in manual testing. The fake must also **cause a
> degradation** while it runs, or the test exercises the old path and proves nothing.

**2. Cancel-during-a-degrading-scrape returns 200, not 500.** The regression test P3 added, extended
so the run also degrades. A second connection cancels while the fake scraper holds its query. Must
fail with the production exception if the drain is moved before the scrape.

**3. The event is emitted, once, with both provider names.** Assert exactly one `run_events` row at
`warning`, naming the provider degraded from and to. A second degradation to the same rung adds no
row; a degradation to a *different* rung does.

**Mutation discipline:** move the drain loop to *before* `scraper.run()` → test 1 and test 2 must
both fail. If they pass, the doubles are easier than reality and the guard is worthless.

## C.6 Rollback impact

- **Config:** `on_pool_exhausted: fail_run` means degradation never happens, so no notice is ever
  produced. The code path is inert without being removed.
- **Code:** delete the drain loop — the transport is unaffected and the log warning remains.
- **Data:** `run_events` rows are append-only telemetry; no schema, no migration, nothing to undo.

## C.7 Future-phase impact

| Phase | Effect |
|---|---|
| **P5/P6** | Discovery handlers gain the same three-line drain. The pattern is copied, not redesigned |
| **P7** (notifications) | A degradation notice is a candidate notification kind. [R17](ARCHITECTURE_FREEZE.md) — notifications never invoke a model — is unaffected: this is a value object, not generated text |
| **P13** | `WebsiteFetcher` runs in a handler and drains identically. Under C2 it would need a session factory it has no other use for |
| **P18** (gates) | Gate handlers face the same clean-session constraint; C1 establishes the pattern for *any* handler needing to report something discovered during I/O |
| **P24/P26** | `run_events` is already the telemetry surface; no new sink is introduced |

---

# Summary

| Decision | Recommendation | Single strongest reason |
|---|---|---|
| **D-A** | **A1** — `ladder` is the ordering authority; ship `[direct, dc]` | The only option that ships P0's measurement *and* keeps the documented rollback literally true, with no frozen-document change |
| **D-B** | **B1** — inject block signatures from `RedditClient` | The only option under which fence 4 means what it says; and P13 needs a detector that does not apply Reddit heuristics to customer websites |
| **D-C** | **C1** — accumulate notices, drain after the scrape | Structurally cannot recreate F7 — no new write inside the window that blocked the previous phase — and keeps `src/net/` session-free for its two future reusers |

**Where I would accept a different answer:** **A2** if you value honest naming over a minimal diff
(cost: one §11.1 reconciliation entry), and **C2** if you value the warning surviving a rolled-back
handler over minimising new writes in the F7 window. **B1 I would argue for**; B2 ships a fence with
an exemption on the file it exists to police, and B3 forfeits P4's acceptance row.
