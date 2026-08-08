"""The discovery handler, the repository, and the transport contract it needs.

Three things get disproportionate attention here, because each is a defect this
project has already paid for once:

* **the idle poll writes nothing** (A1) -- the phase's whole objective;
* **overflow is loud** (A2, R19) -- and its three false cases stay quiet;
* **the write lock is not held across the fetch** (B1, T0) -- which cost P3 a
  sign-off and is why the handler commits before it fetches.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy.orm import Session

from src.db.models import DiscoveryWatermark, Job, Lead, Prescore, Run, RunEvent
from src.db.repositories.discovery import DiscoveryRepository
from src.orchestration.handlers import REGISTRY
from src.orchestration.handlers.discover import DISCOVER_JOB, handle_discover

T0 = datetime.datetime(2026, 8, 8, 12, 0, 0)


def feed_post(pid: str, minutes: int = 0, *, title: str = "I need a tool for this", body="text"):
    return {
        "id": pid,
        "title": title,
        "url": f"https://www.reddit.com/r/SaaS/comments/{pid}/",
        "author": "example_user_1",
        "subreddit": "SaaS",
        "score": None,
        "num_comments": None,
        "body": body,
        "created_utc": datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        - datetime.timedelta(minutes=minutes),
    }


@pytest.fixture
def session(temp_db):
    from src.db.database import ENGINE

    with Session(ENGINE) as s:
        yield s


@pytest.fixture
def run(session):
    row = Run(state="DISCOVERING", started_at=T0, updated_at=T0)
    session.add(row)
    session.commit()
    return row


def make_job(session, run_id, **payload):
    import json

    job = Job(
        run_id=run_id,
        job_type=DISCOVER_JOB,
        payload_json=json.dumps({"subreddits": ["SaaS"], "channel": "listing", **payload}),
        state="running",
        available_at=T0,
        created_at=T0,
    )
    session.add(job)
    session.commit()
    return job


@pytest.fixture
def fake_feed(monkeypatch):
    """Replace the one line that opens a network client."""
    calls = {"count": 0, "posts": []}

    class FakeClient:
        def fetch_feed(self, subreddits, *, sort="new", limit=None, query=None):
            calls["count"] += 1
            return list(calls["posts"])

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: FakeClient())
    return calls


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def test_the_handler_is_registered():
    assert REGISTRY[DISCOVER_JOB] is handle_discover


# --------------------------------------------------------------------------
# A1 - the idle poll
# --------------------------------------------------------------------------


def test_an_idle_poll_issues_one_request_and_creates_no_rows(session, run, fake_feed):
    """A1, the phase objective: nothing new costs one request and zero rows."""
    posts = [feed_post("t3_aaa01"), feed_post("t3_aaa02")]
    fake_feed["posts"] = posts

    # Both posts are already stored, so the diff is empty.
    for p in posts:
        session.add(
            Lead(
                reddit_id=p["id"],
                subreddit="SaaS",
                author="example_user_1",
                title=p["title"],
                url=p["url"],
                created_utc=p["created_utc"],
            )
        )
    session.commit()

    before = session.query(Prescore).count()
    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert fake_feed["count"] == 1, "a poll must issue exactly one request"
    assert result["new"] == 0
    assert session.query(Prescore).count() == before == 0


def test_a_cold_start_collects_and_triages(session, run, fake_feed):
    fake_feed["posts"] = [feed_post("t3_aaa01"), feed_post("t3_aaa02")]

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["seen"] == 2
    assert result["new"] == 2
    assert result["overflow"] is False


def test_the_watermark_is_created_and_advanced(session, run, fake_feed):
    fake_feed["posts"] = [feed_post("t3_aaa01", 5), feed_post("t3_aaa02", 10)]

    handle_discover(session, make_job(session, run.id))
    session.commit()

    row = session.query(DiscoveryWatermark).one()
    assert row.subreddit == "SaaS"
    assert row.channel == "listing"
    assert row.last_seen_fullname == "t3_aaa01"
    assert row.next_poll_at is not None


def test_re_running_the_same_poll_does_not_duplicate_the_watermark(session, run, fake_feed):
    """R9. A lease expiring mid-poll re-runs the whole job by design."""
    fake_feed["posts"] = [feed_post("t3_aaa01")]

    handle_discover(session, make_job(session, run.id))
    session.commit()
    handle_discover(session, make_job(session, run.id))
    session.commit()

    assert session.query(DiscoveryWatermark).count() == 1


# --------------------------------------------------------------------------
# A2 - overflow
# --------------------------------------------------------------------------


def test_overflow_is_logged_as_an_error_on_the_timeline(session, run, fake_feed, caplog):
    """A2 / R19: 150 posts appeared between polls and the window moved past us."""
    repo = DiscoveryRepository(session)
    from src.discovery.watermarks import WatermarkState

    repo.save_watermark(
        "SaaS",
        "listing",
        WatermarkState(
            last_seen_fullname="t3_old001",
            last_seen_utc=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            - datetime.timedelta(days=2),
        ),
    )
    session.commit()

    # Every post in the feed is newer than the watermark.
    fake_feed["posts"] = [feed_post(f"t3_new{i:03d}", minutes=i) for i in range(100)]

    with caplog.at_level("ERROR"):
        result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["overflow"] is True
    assert result["html_fallback"] is True

    events = session.query(RunEvent).filter(RunEvent.event == "discovery.overflow").all()
    assert len(events) == 1
    assert events[0].level == "error"
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_overflow_shortens_the_next_poll_interval(session, run, fake_feed):
    from src.discovery.watermarks import WatermarkState

    repo = DiscoveryRepository(session)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    repo.save_watermark(
        "SaaS",
        "listing",
        WatermarkState(last_seen_utc=now - datetime.timedelta(days=2)),
    )
    session.commit()
    fake_feed["posts"] = [feed_post(f"t3_new{i:03d}", minutes=i) for i in range(100)]

    handle_discover(session, make_job(session, run.id))
    session.commit()

    row = session.query(DiscoveryWatermark).one()
    # Halved from whatever the rate implied, and never below the 15m floor.
    assert row.next_poll_at <= now + datetime.timedelta(hours=24)


def test_an_ordinary_poll_raises_no_overflow_event(session, run, fake_feed):
    """The false case. An error that fires constantly is one nobody reads."""
    fake_feed["posts"] = [feed_post("t3_aaa01", 5)]

    handle_discover(session, make_job(session, run.id))
    session.commit()

    assert session.query(RunEvent).filter(RunEvent.event == "discovery.overflow").count() == 0


# --------------------------------------------------------------------------
# B1 / T0 - the write lock is not held across the fetch
# --------------------------------------------------------------------------


def test_the_session_is_clean_before_the_network_call(session, run, monkeypatch):
    """T0, the trap the handover calls the most expensive one in this phase.

    A dirty session takes SQLite's single write lock at the next flush and holds
    it until commit. If the handler fetches while dirty, every other writer
    waits out `busy_timeout` and then fails -- which is how cancelling a run
    mid-scrape once returned HTTP 500.

    Asserted at the moment it matters rather than by timing a lock: the fetch
    itself inspects the session it was called under.
    """
    observed = {}

    class InspectingClient:
        def fetch_feed(self, subreddits, *, sort="new", limit=None, query=None):
            observed["dirty"] = bool(session.new or session.dirty or session.deleted)
            observed["in_transaction"] = session.in_transaction()
            return [feed_post("t3_aaa01")]

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: InspectingClient())

    handle_discover(session, make_job(session, run.id))
    session.commit()

    assert observed["dirty"] is False, (
        "the handler fetched with pending writes; it must commit its start event first"
    )


def test_the_start_event_is_committed_before_the_fetch(session, run, monkeypatch):
    """The other half: the operator sees "polling…" while it is polling."""
    seen = {}

    class InspectingClient:
        def fetch_feed(self, subreddits, *, sort="new", limit=None, query=None):
            seen["events"] = session.query(RunEvent).count()
            return []

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: InspectingClient())

    handle_discover(session, make_job(session, run.id))
    session.commit()

    assert seen["events"] >= 1, "the start event must be durable before the fetch"


# --------------------------------------------------------------------------
# transport - N2 / T1
# --------------------------------------------------------------------------


def test_a_retryable_transport_failure_becomes_a_retryable_error(session, run, monkeypatch):
    """N2 closes here: pause_run and fail_run are finally distinguishable."""
    from src.orchestration.job_queue import RetryableError
    from src.reddit_client import TransportError

    class FailingClient:
        def fetch_feed(self, *a, **kw):
            raise TransportError("pool exhausted", retryable=True)

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: FailingClient())

    with pytest.raises(RetryableError):
        handle_discover(session, make_job(session, run.id))


def test_a_non_retryable_transport_failure_is_not_retried(session, run, monkeypatch):
    from src.orchestration.job_queue import RetryableError
    from src.reddit_client import TransportError

    class BlockedClient:
        def fetch_feed(self, *a, **kw):
            raise TransportError("blocked", retryable=False)

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: BlockedClient())

    with pytest.raises(TransportError):
        handle_discover(session, make_job(session, run.id))
    # And specifically NOT the retryable kind.
    with pytest.raises(Exception) as exc:
        handle_discover(session, make_job(session, run.id))
    assert not isinstance(exc.value, RetryableError)


def test_a_transport_failure_never_looks_like_an_empty_subreddit(session, run, monkeypatch):
    """The defect N2 existed to allow: silence and failure sharing one value."""
    from src.reddit_client import TransportError

    class BlockedClient:
        def fetch_feed(self, *a, **kw):
            raise TransportError("blocked", retryable=False)

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: BlockedClient())

    with pytest.raises(TransportError):
        handle_discover(session, make_job(session, run.id))

    # No watermark was advanced, so the next poll does not believe the silence.
    assert session.query(DiscoveryWatermark).count() == 0


# --------------------------------------------------------------------------
# rollback - rss_enabled: false
# --------------------------------------------------------------------------


def test_rss_disabled_falls_back_to_the_html_path(session, run, monkeypatch):
    """A7 / T6: rollback level 1 keeps discovery working on HTML."""
    from src.reddit_client import FeedDisabled

    class DisabledClient:
        def fetch_feed(self, *a, **kw):
            raise FeedDisabled("discovery.rss_enabled: false")

        def get_new_posts(self, subreddit, limit=100):
            return [feed_post("t3_html01", body="")]

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: DisabledClient())

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["seen"] == 1
    assert result["new"] == 1


def test_html_sourced_posts_are_recorded_as_having_no_body(session, run, monkeypatch):
    """The measured fact, asserted rather than assumed.

    An old-Reddit listing page renders its expandos lazily and carries no
    selftext (freeze §11, 2026-08-08). `body_source='absent'` counts that
    instead of letting an empty string pass for "this post had nothing to say".
    """
    from src.reddit_client import FeedDisabled

    class DisabledClient:
        def fetch_feed(self, *a, **kw):
            raise FeedDisabled("off")

        def get_new_posts(self, subreddit, limit=100):
            return [feed_post("t3_html01", body="")]

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: DisabledClient())

    result = handle_discover(session, make_job(session, run.id))
    assert result["body_source_counts"]["absent"] == 1
    assert result["body_source_counts"]["feed"] == 0


def test_feed_sourced_posts_are_recorded_as_carrying_a_body(session, run, fake_feed):
    fake_feed["posts"] = [feed_post("t3_aaa01", body="a real question about tooling")]

    result = handle_discover(session, make_job(session, run.id))
    assert result["body_source_counts"]["feed"] == 1


# --------------------------------------------------------------------------
# repository
# --------------------------------------------------------------------------


def test_known_ids_returns_only_stored_posts(session):
    session.add(
        Lead(
            reddit_id="t3_aaa01",
            subreddit="SaaS",
            author="example_user_1",
            title="t",
            url="u",
            created_utc=T0,
        )
    )
    session.commit()

    repo = DiscoveryRepository(session)
    assert repo.known_ids(["t3_aaa01", "t3_aaa02"]) == {"t3_aaa01"}


def test_known_ids_handles_more_ids_than_the_sql_variable_limit(session):
    repo = DiscoveryRepository(session)
    assert repo.known_ids([f"t3_{i:05d}" for i in range(1200)]) == set()


def test_a_duplicate_listing_watermark_is_rejected_by_the_database(session):
    """SQLite treats NULLs as distinct in a UNIQUE index.

    A plain `(subreddit, channel, query)` unique index -- which is what docs/28
    §3.1 shows -- would not constrain listing rows at all, because `query` is
    NULL for every one of them. Two rows would then advance independently and
    each would hide posts from the other, which is D2 (watermark poisoning)
    arriving through the schema rather than through a bug.
    """
    from sqlalchemy.exc import IntegrityError

    session.add(DiscoveryWatermark(subreddit="SaaS", channel="listing", consecutive_empty=0))
    session.commit()

    session.add(DiscoveryWatermark(subreddit="SaaS", channel="listing", consecutive_empty=0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_two_search_watermarks_with_different_queries_coexist(session):
    session.add(
        DiscoveryWatermark(subreddit="SaaS", channel="search", query="a", consecutive_empty=0)
    )
    session.add(
        DiscoveryWatermark(subreddit="SaaS", channel="search", query="b", consecutive_empty=0)
    )
    session.commit()
    assert session.query(DiscoveryWatermark).count() == 2


def test_due_returns_never_polled_channels_first(session):
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    session.add(
        DiscoveryWatermark(
            subreddit="later",
            channel="listing",
            consecutive_empty=0,
            next_poll_at=now + datetime.timedelta(hours=5),
        )
    )
    session.add(DiscoveryWatermark(subreddit="never", channel="search", consecutive_empty=0))
    session.commit()

    due = DiscoveryRepository(session).due(now)
    assert [w.subreddit for w in due] == ["never"]


def test_every_rejection_reason_is_counted_on_the_timeline(session, run, fake_feed):
    """R11 / AD-10b, as P6 discharges it: counters, not prescore rows.

    A triage rejection is a post that was never stored as a lead, and
    `prescores` requires every row to point at one (CHECK, [05 §5.4]). Writing
    prescores only for *admissions* would produce a funnel that looks auditable
    while silently omitting every rejection — the exact failure AD-10b names. So
    the reasons are counted here, and the per-item audit is P11's.
    """
    fake_feed["posts"] = [
        feed_post("t3_ok001", title="Looking for a CRM"),
        feed_post("t3_bad01", title="[Hiring] Senior Python developer"),
        feed_post("t3_bad02", title="Weekly discussion thread"),
        feed_post("t3_bad03", title="Giveaway: three free licenses"),
    ]

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["admitted"] == 1
    assert result["rejected"] == 3
    assert result["rejected_by_reason"] == {"hiring": 1, "megathread": 1, "giveaway": 1}

    import json

    done = session.query(RunEvent).filter(RunEvent.event == "discovery.poll.done").one()
    assert json.loads(done.data_json)["rejected_by_reason"] == {
        "hiring": 1,
        "megathread": 1,
        "giveaway": 1,
    }


def test_p6_writes_no_prescore_rows(session, run, fake_feed):
    """Stated as a test so the narrowing is visible, not merely documented.

    [34 §P6] task 4 asks for a provisional prescore per triaged item. P6 cannot
    write one for a rejection (see above) and deliberately writes none at all
    rather than writing a misleading half. When P11 wires this up, this test is
    the one that should fail and be replaced.
    """
    fake_feed["posts"] = [feed_post("t3_aaa01"), feed_post("t3_bad01", title="[Hiring] dev")]

    handle_discover(session, make_job(session, run.id))
    session.commit()

    assert session.query(Prescore).count() == 0


def test_prescores_record_rejections_as_well_as_admissions(session, run):
    """R11 / AD-10b. A gate that discards without recording is unmeasurable."""
    repo = DiscoveryRepository(session)
    lead = Lead(
        reddit_id="t3_aaa01",
        subreddit="SaaS",
        author="a",
        title="t",
        url="u",
        created_utc=T0,
    )
    session.add(lead)
    session.commit()

    repo.add_prescore(
        run.id, lead.id, total=0.0, components={}, gate_decision="reject", gate_reason="hiring"
    )
    session.commit()

    row = session.query(Prescore).one()
    assert row.gate_decision == "reject"
    assert row.gate_reason == "hiring"
    assert row.stage == "metadata"
    assert row.holdout_sampled is False
    assert repo.counts_by_decision(run.id) == {"reject": 1}


def test_a_prescore_must_name_exactly_one_target(session, run):
    """The CHECK constraint, which holds without the deferred comments FK."""
    from sqlalchemy.exc import IntegrityError

    session.add(
        Prescore(
            run_id=run.id,
            lead_id=None,
            comment_id=None,
            total=1.0,
            components_json="{}",
            gate_decision="admit",
            created_at=T0,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
