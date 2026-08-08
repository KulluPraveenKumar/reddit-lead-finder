"""``discover`` — one poll of one channel.

Stages 1–4 of [28 §3](../../../docs/28-discovery-redesign.md), and the first
handler in the system that both fetches and writes. That combination is why the
ordering below is written out rather than left to read naturally:

**The write lock is never held across the fetch.** SQLite has one write lock; a
session with pending writes takes it at the next flush and holds it until
commit. This handler therefore commits its "starting" bookkeeping *before* the
network call and does every write *after* it. Emitting the start event without
that commit is exactly the defect that returned HTTP 500 when a run was
cancelled mid-scrape in P3 (``PHASE-05-HANDOVER`` T0), and it is the trap the
handover names as the most expensive one waiting in this phase.

**Idempotence** (R9) comes from three places, none of them a flag: the watermark
is *assigned* from a computed state rather than incremented, ``prescore_exists``
guards the triage write, and ``known_ids`` filters against leads already stored.
A lease that expires mid-poll and is re-claimed re-runs the whole thing and
lands in the same place.

**Overflow is an error, not a shrug** (R19). When the feed's oldest entry is
newer than everything we have seen, posts existed in between and are gone from
the feed forever. The handler logs at ``error``, puts it on the run's timeline,
shortens the interval, and asks for an HTML listing walk to recover the ids.

> ⚠️ **The HTML fallback restores discovery, not bodies.** Overflow-recovered
> posts have aged out of the feed, and P5 measured that an HTML *listing* page
> carries no selftext at all (freeze §11, 2026-08-08). They arrive with
> ``body_source='absent'`` and a permalink fetch is the only remaining source —
> which is P11's, with comments. This is a documented degradation rather than a
> silent one, and [28 §9 D3](../../../docs/28-discovery-redesign.md)'s "fall
> back to HTML listing automatically" is corrected to say so.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job
from src.db.repositories.discovery import DiscoveryRepository
from src.discovery import policy as policy_module
from src.discovery.triage import TriageConfig, triage
from src.discovery.watermarks import advance, diff
from src.obs.events import emit_event
from src.orchestration.job_queue import RetryableError, payload_of

log = logging.getLogger(__name__)

DISCOVER_JOB = "discover"

#: Where a post's body came from. `feed` is the ordinary case (P5 measured
#: 97-100 of 100); `absent` is a link/media post, or one recovered by the HTML
#: fallback after the feed window moved past us. Recorded rather than assumed,
#: so the share is counted instead of believed.
BODY_FROM_FEED = "feed"
BODY_ABSENT = "absent"


def handle_discover(session: Session, job: Job) -> dict[str, Any]:
    """Poll one channel, triage what is new, advance the watermark."""
    payload = payload_of(job)
    subreddits = _subreddits_of(payload)
    channel = str(payload.get("channel") or "listing")
    query = payload.get("query") or None
    run_id = job.run_id

    if run_id is None:
        raise ValueError(f"job {job.id} has no run_id; discover jobs must belong to a run")
    if not subreddits:
        raise ValueError(f"job {job.id} has no subreddits in its payload")

    config = _load_config()
    repo = DiscoveryRepository(session)
    cfg = _policy_config(config)

    # **One watermark per subreddit, even though the request is combined.**
    #
    # U1 makes multireddit combining mandatory, so one request covers every
    # subreddit in the payload -- but [28 §3.1] keeps "one row per (subreddit,
    # channel, query)" and stage 2 diffs "per subreddit", and both are right.
    # A single row keyed on the first subreddit would leave the other nine
    # without a watermark: never in the due-queue, never rate-measured, and --
    # worst -- never able to detect overflow, because overflow is a per-subreddit
    # fact. A busy subreddit sharing a feed with nine quiet ones is exactly the
    # case where posts scroll away unseen.
    #
    # States are read as detached values, so nothing below holds a row.
    states = {sub: repo.state_of(sub, channel, query) for sub in subreddits}
    polled_at = {sub: _last_polled_at(repo, sub, channel, query) for sub in subreddits}

    emit_event(
        session,
        run_id,
        "discovery.poll.start",
        message=f"Polling {channel} for {', '.join(subreddits)}…",
        channel=channel,
        subreddits=subreddits,
    )

    # **Commit before the fetch, and never remove this.** See the module
    # docstring: the event above leaves the session dirty, and the fetch below
    # spends seconds to a minute on the network.
    session.commit()

    posts = _fetch(config, subreddits, channel, query)

    # Per-subreddit diffs off the one combined response.
    known = repo.known_ids([p["id"] for p in posts if p.get("id")])
    by_sub = _group_by_subreddit(posts, subreddits)
    results = {sub: diff(by_sub[sub], known, states[sub]) for sub in subreddits}
    overflowed = [sub for sub in subreddits if results[sub].overflow]

    # ---- the recovery walk, while the session is still clean ---------------
    #
    # Deliberately here and not after the events below: `_report_overflow`
    # dirties the session, and this is a second network call (B1/T0).
    recovered: list[dict] = []
    if overflowed:
        recovered = _recover_by_html(config, overflowed, query)
        if recovered:
            known = known | repo.known_ids([p["id"] for p in recovered if p.get("id")])
            posts = _merge(posts, recovered)
            by_sub = _group_by_subreddit(posts, subreddits)
            results = {sub: diff(by_sub[sub], known, states[sub]) for sub in subreddits}

    # ---- everything from here is local; the lock is safe to take -----------

    now = _utcnow()
    new_posts = [p for sub in subreddits for p in results[sub].new_posts]
    seen = len(posts)

    for sub in overflowed:
        _report_overflow(session, run_id, channel, sub, results[sub], states[sub], len(recovered))

    admitted, rejected, reasons = _triage_all(new_posts, config)

    intervals: dict[str, int] = {}
    for sub in subreddits:
        elapsed_hours = None
        if polled_at[sub] is not None:
            elapsed_hours = (now - polled_at[sub]).total_seconds() / 3600

        new_state = advance(states[sub], by_sub[sub], results[sub], elapsed_hours=elapsed_hours)
        interval = policy_module.next_interval(new_state, cfg)
        if results[sub].overflow:
            interval = policy_module.shortened_after_overflow(interval, cfg)

        repo.save_watermark(
            sub,
            channel,
            new_state,
            query=query,
            polled_at=now,
            next_poll_at=now + interval,
        )
        intervals[sub] = int(interval.total_seconds())

    emit_event(
        session,
        run_id,
        "discovery.poll.done",
        message=(
            f"{channel}: {len(new_posts)} new of {seen} seen "
            f"({admitted} admitted, {rejected} rejected)."
        ),
        channel=channel,
        seen=seen,
        new=len(new_posts),
        admitted=admitted,
        rejected=rejected,
        # Every rejection reason, counted. This is the funnel's auditable half
        # in P6 — see `_triage_all` for why it is counters and not prescores.
        rejected_by_reason=reasons,
        overflow=bool(overflowed),
        next_interval_seconds=intervals,
    )

    return {
        "channel": channel,
        "seen": seen,
        "new": len(new_posts),
        "admitted": admitted,
        "rejected": rejected,
        "rejected_by_reason": reasons,
        "overflow": bool(overflowed),
        "overflowed_subreddits": overflowed,
        "html_recovered": len(recovered),
        "next_interval_seconds": intervals,
        "body_source_counts": _body_source_counts(new_posts),
    }


def _group_by_subreddit(posts: list[dict], subreddits: list[str]) -> dict[str, list[dict]]:
    """Split one combined feed into per-subreddit batches.

    Matched case-insensitively because a payload says ``SaaS`` and a feed's
    ``<category term=>`` may not agree on case. A post whose subreddit matches
    nothing in the payload is dropped from the per-subreddit view rather than
    guessed at -- it still counts in ``seen``.
    """
    index = {sub.lower(): sub for sub in subreddits}
    grouped: dict[str, list[dict]] = {sub: [] for sub in subreddits}
    for post in posts:
        key = index.get(str(post.get("subreddit") or "").lower())
        if key is not None:
            grouped[key].append(post)
    return grouped


def _merge(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Union by post id, keeping the feed's copy where both carry one.

    The feed's copy wins because it has a body and the HTML listing's does not.
    """
    seen = {p["id"] for p in primary if p.get("id")}
    return primary + [p for p in extra if p.get("id") and p["id"] not in seen]


# ---------------------------------------------------------------- the fetch


def _fetch(
    config: dict[str, Any], subreddits: list[str], channel: str, query: str | None
) -> list[dict]:
    """Stage 1. One request, or the HTML path when RSS is switched off.

    A transport failure **raises** rather than returning ``[]`` (N2, closed
    here): a poller that reads a blocked request as "nothing new" advances
    nothing, reports silence, and is believed forever. ``TransportError``
    carries the operator's ``on_pool_exhausted`` answer through, so a retryable
    exhaustion becomes ``RetryableError`` and a block does not.
    """
    from src.reddit_client import FeedDisabled, TransportError

    client = _build_client(config)
    try:
        return client.fetch_feed(subreddits, query=query)
    except FeedDisabled:
        # Rollback level 1. The HTML path is untouched and must keep working
        # (T6, and an acceptance criterion of its own).
        return _fetch_html(client, subreddits, query)
    except TransportError as exc:
        if exc.retryable:
            raise RetryableError(str(exc)) from exc
        raise


def _fetch_html(client, subreddits: list[str], query: str | None) -> list[dict]:
    """The HTML listing walk. Discovery only — it carries no bodies.

    Used for two things: ``rss_enabled: false`` (rollback) and overflow
    recovery. In both cases it returns ids, titles, authors and timestamps, and
    every post it produces has ``body_source='absent'`` because an old-Reddit
    listing renders its expandos lazily and serves no selftext at all.
    """
    posts: list[dict] = []
    for subreddit in subreddits:
        if query:
            posts.extend(client.search_posts(subreddit, query))
        else:
            posts.extend(client.get_new_posts(subreddit))
    return posts


def _build_client(config: dict[str, Any]):
    """The one line that opens a network client, named so a test can replace it."""
    from src.reddit_client import RedditClient

    return RedditClient(config)


# ------------------------------------------------------------------ stage 3


def _triage_all(posts: list[dict], config: dict[str, Any]) -> tuple[int, int, dict[str, int]]:
    """Stage 3. Judge every new post from metadata alone, and count the reasons.

    **P6 records the funnel as counters, not as ``prescores`` rows, and that is
    a deliberate narrowing with a schema reason behind it.**
    [34 §P6](../../../docs/34-implementation-plan.md) task 4 says triage writes
    "a provisional prescore with ``stage='metadata'``". It cannot, yet:
    ``prescores`` carries ``CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT
    NULL))`` ([05 §5.4](../../../docs/05-database-plan.md)), so every row must
    point at a stored ``Lead`` -- and a triage *rejection* is by definition a
    post that was never stored (``subreddit_scraper.py`` only persists a lead
    that clears ``is_lead(min_score=3)``).

    Writing prescores only for admissions would be worse than writing none: it
    would produce a funnel that looks auditable and silently omits every
    rejection, which is the precise failure [AD-10b](../../../docs/03-architecture.md)
    names. So P6 counts by reason, on the run's timeline, and the per-item
    audit stays with **P11** -- which owns full prescoring, the 2% stage-3
    holdout and ``gate.metadata_holdout_rate`` already.

    The table and its repository still ship: [freeze §4.1](../../../docs/ARCHITECTURE_FREEZE.md)
    puts ``prescores`` in ``0005``, and P11 needs it the moment it lands.
    """
    cfg = _triage_config(config)
    admitted = rejected = 0
    reasons: dict[str, int] = {}

    for post in posts:
        judgement = triage(post, cfg)
        post["body_source"] = _body_source(post)

        if judgement.admitted:
            admitted += 1
        else:
            rejected += 1
            reason = judgement.reason or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1

    return admitted, rejected, reasons


def _body_source(post: dict) -> str:
    """Where this post's body came from — counted, never assumed.

    Stage 4 in P6 is this line and its counter, and nothing else. The
    density-adaptive fetch the plan specified chose between an HTML listing page
    and a permalink for bodies; P5 measured the listing carries none, so the
    branch had one reachable arm and was removed. The feed already supplies the
    body for ~97% of posts in the request stage 1 makes anyway, and the ~3% that
    lack one are link and media posts with no selftext to fetch on any path.
    """
    return BODY_FROM_FEED if (post.get("body") or "").strip() else BODY_ABSENT


def _body_source_counts(posts: list[dict]) -> dict[str, int]:
    counts = {BODY_FROM_FEED: 0, BODY_ABSENT: 0}
    for post in posts:
        counts[post.get("body_source") or _body_source(post)] += 1
    return counts


# ----------------------------------------------------------------- overflow


def _recover_by_html(
    config: dict[str, Any], subreddits: list[str], query: str | None
) -> list[dict]:
    """The overflow recovery walk. **Actually performed, not merely flagged.**

    [28 §9 D1](../../../docs/28-discovery-redesign.md) requires overflow to fall
    back to an HTML listing walk, and it is the only way to reach posts that have
    already scrolled out of the feed's 100-item window.

    ⚠️ **It restores ids, not bodies.** An old-Reddit listing page renders its
    expandos lazily and carries no selftext (freeze §11), so every post recovered
    here has ``body_source='absent'``. That is a real degradation and it is
    recorded rather than hidden; a permalink fetch is the only remaining source,
    and it belongs to P11 with comments.

    Recovery failing must not fail the poll: the overflow has already been
    reported as an error, and losing the recovery on top of it should not also
    lose the posts the feed *did* carry.
    """
    try:
        client = _build_client(config)
        return _fetch_html(client, subreddits, query)
    except Exception as exc:  # noqa: BLE001 - recovery is best-effort by design
        log.error("overflow recovery walk failed for %s: %s", ", ".join(subreddits), exc)
        return []


def _report_overflow(
    session: Session,
    run_id: int,
    channel: str,
    subreddit: str,
    result,
    state,
    recovered: int,
) -> None:
    """R19: loud, on the timeline and in the log, never a silent gap."""
    message = (
        f"Watermark overflow on {channel} for r/{subreddit}: the feed's oldest "
        f"post is newer than the last one seen, so posts appeared and scrolled "
        f"out of the 100-item window between polls. Recovered {recovered} post(s) "
        f"by an HTML listing walk — which carries ids but no bodies — and halved "
        f"the poll interval."
    )
    log.error(message)
    emit_event(
        session,
        run_id,
        "discovery.overflow",
        level="error",
        message=message,
        channel=channel,
        subreddit=subreddit,
        seen=result.seen,
        html_recovered=recovered,
        last_seen_utc=state.last_seen_utc.isoformat() if state and state.last_seen_utc else None,
    )


# ------------------------------------------------------------------- config


def _subreddits_of(payload: dict) -> list[str]:
    raw = payload.get("subreddits") or payload.get("subreddit") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(s).strip() for s in raw if str(s).strip()]


def _load_config() -> dict[str, Any]:
    try:
        from src.config import load_config

        return load_config() or {}
    except Exception as exc:  # noqa: BLE001 - a config read must not fail a job
        log.warning("could not load config, using defaults: %s", exc)
        return {}


def _policy_config(config: dict[str, Any]) -> policy_module.PolicyConfig:
    """Build the policy config, falling back to [28 §8.1]'s defaults.

    An absent ``discovery:`` block reproduces every default, which is P4's
    ``network:`` discipline and is tested.
    """
    discovery = (config or {}).get("discovery", {}) or {}
    defaults = policy_module.PolicyConfig()

    def _duration(key: str, fallback: datetime.timedelta) -> datetime.timedelta:
        raw = discovery.get(key)
        if raw is None:
            return fallback
        return _parse_duration(raw, fallback)

    return policy_module.PolicyConfig(
        min_interval=_duration("min_interval", defaults.min_interval),
        max_interval=_duration("max_interval", defaults.max_interval),
        window_target=int(discovery.get("window_target", defaults.window_target)),
        empty_backoff=float(discovery.get("empty_backoff", defaults.empty_backoff)),
        empty_cap=int(discovery.get("empty_cap", defaults.empty_cap)),
        yield_boost=float(discovery.get("yield_boost", defaults.yield_boost)),
    )


def _parse_duration(raw: Any, fallback: datetime.timedelta) -> datetime.timedelta:
    """``15m`` / ``24h`` / ``90s`` / a bare number of seconds.

    A malformed value falls back rather than raising: a typo in an optional
    tuning key must not stop discovery, and the fallback is the documented
    default rather than something invented.
    """
    if isinstance(raw, (int, float)):
        return datetime.timedelta(seconds=float(raw))
    text = str(raw).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if text and text[-1] in units:
            return datetime.timedelta(seconds=float(text[:-1]) * units[text[-1]])
        return datetime.timedelta(seconds=float(text))
    except ValueError:
        log.warning("could not parse duration %r; using %s", raw, fallback)
        return fallback


def _triage_config(config: dict[str, Any]) -> TriageConfig:
    discovery = (config or {}).get("discovery", {}) or {}
    keywords = tuple(str(k) for k in (config or {}).get("keywords", []) or [])
    return TriageConfig(
        window_days=int(discovery.get("window_days", TriageConfig().window_days)),
        keywords=keywords,
        negative_terms=tuple(str(t) for t in (discovery.get("negative_terms") or [])),
    )


def _last_polled_at(
    repo: DiscoveryRepository, subreddit: str, channel: str, query: str | None
) -> datetime.datetime | None:
    row = repo.get_watermark(subreddit, channel, query)
    return row.last_polled_at if row is not None else None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
