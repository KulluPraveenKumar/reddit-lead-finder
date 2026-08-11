"""P7 Stage 5 -- the dispatcher: read the timeline, decide, render, send, record.

The load-bearing test in this file is the one about the write lock. Everything
else is behaviour; that one is trap **T0**, which ``PHASE-06-HANDOVER`` §5 names as
*"the write lock, again, and P7 is where it returns"* -- P3 lost a sign-off to it,
and P4, P5 and P6 each had to prove they had not re-opened it.

No network: the transport is a fake that records what it was asked to send. That
is deliberate rather than convenient -- a real transport here would be testing
Stage 4 again, and Stage 4 already asserts its own captured requests.
"""

from __future__ import annotations

import json
from datetime import datetime, time

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run, RunEvent, ScrapeRun
from src.notify import (
    DISPATCH_ORDER,
    EVENT_KINDS,
    FAILED_EVENT,
    SENT_EVENT,
    TRANSITION_KINDS,
    Kind,
    NotificationService,
    NotifySettings,
    hash_chat_id,
)
from src.notify.transport import SendError
from src.orchestration.handlers.finalize import handle_finalize_run
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import FINALIZE_JOB, SCRAPE_JOB, RunOptions, RunService
from src.orchestration.states import IllegalTransition, JobState, RunState

NOON = datetime(2026, 8, 10, 12, 0)
THREE_AM = datetime(2026, 8, 10, 3, 0)

ON = NotifySettings(enabled=True, transport="fake", telegram_chat_id="42")


@pytest.fixture
def session(temp_db):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


class FakeTransport:
    """Records sends. Optionally fails, so the failure path is exercised."""

    name = "fake"

    def __init__(self, fail_with: Exception | None = None, on_send=None) -> None:
        self.fail_with = fail_with
        self.on_send = on_send
        self.sends: list[tuple[str, str]] = []

    def send(self, *, chat_id: str, markdown: str) -> str:
        self.sends.append((chat_id, markdown))
        if self.on_send is not None:
            self.on_send()
        if self.fail_with is not None:
            raise self.fail_with
        return f"fake-{len(self.sends)}"


def svc(session, transport=None, settings=ON):
    return NotificationService(session, transport or FakeTransport(), settings)


# ------------------------------------------------------------------- builders


def complete_run(session, *, leads=5, failed=0, cancelled=0):
    """A run that walked to COMPLETE, with the timeline a real run would leave."""
    run = Run(state=RunState.COMPLETE.value, started_at=NOON, updated_at=NOON, finished_at=NOON)
    session.add(run)
    session.commit()
    _transition(session, run.id, RunState.COMPLETE.value)
    session.add(
        ScrapeRun(
            scraper_type="subreddit", leads_found=leads, posts_found=leads * 10, run_id=run.id
        )
    )
    for state in [JobState.DONE] + [JobState.FAILED] * failed + [JobState.CANCELLED] * cancelled:
        session.add(Job(run_id=run.id, job_type=SCRAPE_JOB, state=state.value, payload_json="{}"))
    session.commit()
    return run


def failed_run(session, *, error="boom"):
    run = Run(
        state=RunState.FAILED.value, started_at=NOON, updated_at=NOON, finished_at=NOON, error=error
    )
    session.add(run)
    session.commit()
    _transition(session, run.id, RunState.FAILED.value)
    return run


def _transition(session, run_id, to_state, from_state="scraping"):
    session.add(
        RunEvent(
            run_id=run_id,
            event="run.transition",
            level="error" if to_state == "failed" else "info",
            message=f"{from_state} -> {to_state}",
            data_json=json.dumps({"from_state": from_state, "to_state": to_state}),
        )
    )
    session.commit()


def add_event(session, run_id, name, **data):
    session.add(RunEvent(run_id=run_id, event=name, data_json=json.dumps(data) if data else None))
    session.commit()


def events_of(session, run_id, name):
    return (
        session.query(RunEvent)
        .filter(RunEvent.run_id == run_id, RunEvent.event == name)
        .order_by(RunEvent.id)
        .all()
    )


def sent_kinds(session, run_id):
    return [json.loads(e.data_json)["kind"] for e in events_of(session, run_id, SENT_EVENT)]


# ------------------------------------------------- evidence -> kind mapping


def test_a_kind_is_not_a_timeline_event_name():
    """The correction Stage 5 had to make.

    ``docs/P7-IMPLEMENTATION-REVIEW.md`` §8 claimed *"a kind and the timeline row
    that carries it are the same identifier"*. ``run_service.transition`` emits
    **one** name -- ``run.transition`` -- for every hop, so that is true for one
    kind in five. This pins the real mapping so the claim cannot drift back.
    """
    assert set(EVENT_KINDS) == {"discovery.overflow", "net.degraded"}
    assert set(TRANSITION_KINDS) == {
        RunState.COMPLETE.value,
        RunState.FAILED.value,
        RunState.AWAITING_SUBREDDIT_REVIEW.value,
        RunState.AWAITING_KEYWORD_REVIEW.value,
        RunState.AWAITING_OPTIONS.value,
    }
    # Every kind is reachable from some evidence, or it can never fire.
    reachable = set(TRANSITION_KINDS.values()) | set(EVENT_KINDS.values())
    assert reachable == set(Kind)
    assert set(DISPATCH_ORDER) == set(Kind), "the dispatch order must be total"


def test_run_complete_is_derived_from_the_transition_event(session):
    run = complete_run(session, leads=3)
    fake = FakeTransport()
    sent = svc(session, fake).dispatch_pending(run.id, now=NOON)

    assert [s.kind for s in sent] == [Kind.RUN_COMPLETE]
    assert len(fake.sends) == 1
    assert "3" in fake.sends[0][1], "the rendered body carries the SQL-sourced count"


def test_run_failed_is_derived_and_always_sent(session):
    run = failed_run(session)
    fake = FakeTransport()
    sent = svc(session, fake).dispatch_pending(run.id, now=NOON)
    assert [s.kind for s in sent] == [Kind.RUN_FAILED]


def test_a_gate_transition_yields_the_gate_kind_with_its_number(session):
    run = Run(state=RunState.AWAITING_SUBREDDIT_REVIEW.value, started_at=NOON, updated_at=NOON)
    session.add(run)
    session.commit()
    _transition(session, run.id, RunState.AWAITING_SUBREDDIT_REVIEW.value, from_state="discovering")

    fake = FakeTransport()
    sent = svc(session, fake).dispatch_pending(run.id, now=NOON)
    assert [s.kind for s in sent] == [Kind.GATE_REACHED]


def test_degradations_are_counted_not_merely_detected(session):
    run = complete_run(session)
    for _ in range(3):
        add_event(session, run.id, "net.degraded", from_provider="dc", to_provider="direct")

    fake = FakeTransport()
    sent = svc(session, fake).dispatch_pending(run.id, now=NOON)
    kinds = [s.kind for s in sent]
    assert Kind.PROXY_POOL_DEGRADED in kinds
    body = next(b for _c, b in fake.sends if "egress degraded" in b)
    assert "Degradations: 3" in body


def test_intermediate_transitions_do_not_trigger_anything(session):
    """A run that merely started must not notify.

    ``run.transition`` fires for all seven hops. Only the destinations in
    ``TRANSITION_KINDS`` are notifiable; ``profiling`` or ``scraping`` are not.
    """
    run = Run(state=RunState.SCRAPING.value, started_at=NOON, updated_at=NOON)
    session.add(run)
    session.commit()
    # Leads and a shortfall on purpose: with none, the run.complete rule would
    # suppress anyway and this test would pass even if every hop were
    # misclassified as run.complete. A surviving mutation found exactly that.
    session.add(ScrapeRun(scraper_type="subreddit", leads_found=9, posts_found=90, run_id=run.id))
    session.add(
        Job(run_id=run.id, job_type=SCRAPE_JOB, state=JobState.FAILED.value, payload_json="{}")
    )
    session.commit()
    for state in ("profiling", "discovering", "generating_keywords", "scraping"):
        _transition(session, run.id, state)

    fake = FakeTransport()
    assert svc(session, fake).dispatch_pending(run.id, now=NOON) == []
    assert fake.sends == []


def test_the_evidence_payload_comes_from_sql_not_from_a_caller(session):
    """A clean 0-lead run is suppressed; the same run with a failure is not.

    The policy's inputs are queried here, so ``leads`` and the shortfall cannot be
    supplied by whoever called ``dispatch_pending``.
    """
    quiet = complete_run(session, leads=0)
    assert svc(session).dispatch_pending(quiet.id, now=NOON) == []

    loud = complete_run(session, leads=0, failed=2)
    assert [s.kind for s in svc(session).dispatch_pending(loud.id, now=NOON)] == [Kind.RUN_COMPLETE]


# ----------------------------------------------------------------- ordering


def test_a_failure_is_sent_before_anything_else(session):
    """If a transport dies part-way, the message that mattered has gone first."""
    run = failed_run(session)
    _transition(session, run.id, RunState.AWAITING_OPTIONS.value)
    add_event(session, run.id, "discovery.overflow", subreddit="SaaS", seen=100)
    add_event(session, run.id, "net.degraded", from_provider="dc", to_provider="direct")

    fake = FakeTransport()
    sent = [s.kind for s in svc(session, fake).dispatch_pending(run.id, now=NOON)]
    assert sent[0] == Kind.RUN_FAILED
    assert sent == [k for k in DISPATCH_ORDER if k in set(sent)]


# ------------------------------------------------------------------- dedup


def test_a_second_dispatch_sends_nothing(session):
    run = complete_run(session)
    fake = FakeTransport()
    service = svc(session, fake)

    assert len(service.dispatch_pending(run.id, now=NOON)) == 1
    assert service.dispatch_pending(run.id, now=NOON) == []
    assert len(fake.sends) == 1
    assert len(events_of(session, run.id, SENT_EVENT)) == 1


def test_twenty_replays_send_exactly_one_message(session):
    """AC4 / M2. Duplicate rate 0 over 20 lease-expiry replays."""
    run = complete_run(session)
    fake = FakeTransport()
    for _ in range(20):
        svc(session, fake).dispatch_pending(run.id, now=NOON)

    assert len(fake.sends) == 1
    assert len(events_of(session, run.id, SENT_EVENT)) == 1


def test_two_different_kinds_on_one_run_both_send(session):
    """Dedup is keyed on ``(run_id, kind)``, not on ``run_id`` alone.

    Keyed on ``run_id`` alone, a run would get one message ever -- so a run that
    completed *and* lost posts to an overflow would report only the first.
    """
    run = complete_run(session)
    add_event(session, run.id, "discovery.overflow", subreddit="SaaS", seen=100)

    fake = FakeTransport()
    sent = {s.kind for s in svc(session, fake).dispatch_pending(run.id, now=NOON)}
    assert sent == {Kind.RUN_COMPLETE, Kind.DISCOVERY_OVERFLOW}
    assert len(fake.sends) == 2


def test_a_second_run_is_notified_independently(session):
    """Dedup is not keyed on ``kind`` alone, or later runs would be silent."""
    first = complete_run(session)
    fake = FakeTransport()
    svc(session, fake).dispatch_pending(first.id, now=NOON)

    second = complete_run(session)
    assert len(svc(session, fake).dispatch_pending(second.id, now=NOON)) == 1
    assert len(fake.sends) == 2


def test_a_corrupt_sent_row_does_not_resend_everything(session):
    """A ``notify.sent`` row whose JSON is unreadable is skipped, not fatal."""
    run = complete_run(session)
    session.add(RunEvent(run_id=run.id, event=SENT_EVENT, data_json="{not json"))
    session.commit()
    fake = FakeTransport()
    assert len(svc(session, fake).dispatch_pending(run.id, now=NOON)) == 1


# ------------------------------------------------------- the off switch


def test_disabled_sends_nothing_and_records_nothing(session):
    run = complete_run(session)
    fake = FakeTransport()
    off = NotifySettings(enabled=False, transport="fake", telegram_chat_id="42")

    assert NotificationService(session, fake, off).dispatch_pending(run.id, now=NOON) == []
    assert fake.sends == []
    assert events_of(session, run.id, SENT_EVENT) == []
    assert events_of(session, run.id, FAILED_EVENT) == []


def test_disabled_short_circuits_before_touching_the_database(session):
    """The off switch is a guard, not merely a filter.

    ``decide`` refuses a disabled tier too, so removing the check here changed
    nothing a behavioural test could see -- a surviving mutation said so. The
    check earns its place by making a disabled tier cost **nothing**: no
    timeline read, no aggregate, no render. Asserted by counting statements.
    """
    run = complete_run(session)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    off = NotifySettings(enabled=False, transport="fake", telegram_chat_id="42")
    service = NotificationService(session, FakeTransport(), off)

    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        assert service.dispatch_pending(run.id, now=NOON) == []
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)

    assert statements == [], f"a disabled tier queried the database: {statements}"


def test_a_missing_chat_id_sends_nothing_and_records_nothing(session):
    """Nothing attempted, nothing recorded -- so configuring it later delivers."""
    run = complete_run(session)
    fake = FakeTransport()
    settings = NotifySettings(enabled=True, transport="fake", telegram_chat_id=None)

    assert NotificationService(session, fake, settings).dispatch_pending(run.id, now=NOON) == []
    assert fake.sends == []
    assert events_of(session, run.id, SENT_EVENT) == []


def test_quiet_hours_suppress_without_recording_so_a_later_pass_delivers(session):
    run = complete_run(session)
    fake = FakeTransport()
    quiet = NotifySettings(
        enabled=True,
        transport="fake",
        telegram_chat_id="42",
        quiet_window=(time(22, 0), time(7, 0)),
    )

    assert NotificationService(session, fake, quiet).dispatch_pending(run.id, now=THREE_AM) == []
    assert events_of(session, run.id, SENT_EVENT) == [], "suppression must not record a send"

    # The same run, outside quiet hours, still delivers.
    assert len(NotificationService(session, fake, quiet).dispatch_pending(run.id, now=NOON)) == 1


# ------------------------------------------------ ⚠️ T0: the write lock


def test_dispatch_refuses_a_dirty_session(session):
    """The precondition is enforced, not documented.

    A session with pending writes holds SQLite's single write lock until commit,
    so sending from here would hold it across a network call. Mutation M1 moves
    the dispatch above the caller's commit; this is what catches it.
    """
    run = complete_run(session)
    session.add(RunEvent(run_id=run.id, event="run.partial", message="pending"))
    assert session.new, "the session must actually be dirty for this to prove anything"

    fake = FakeTransport()
    with pytest.raises(RuntimeError, match="committed session"):
        svc(session, fake).dispatch_pending(run.id, now=NOON)
    assert fake.sends == [], "nothing may be sent while writes are pending"


def test_no_write_lock_is_held_while_the_transport_blocks(session):
    """Inspected **from inside the transport**, which is P6's own technique.

    A second connection must be able to write while the send is in flight. If the
    caller's transaction were still open, this INSERT would block or fail.
    """
    run = complete_run(session)
    observed: dict[str, object] = {}

    def during_send():
        observed["dirty"] = bool(session.dirty or session.new or session.deleted)
        with Session(bind=database.ENGINE) as other:
            other.add(RunEvent(run_id=run.id, event="probe.write", message="from another session"))
            other.commit()
            observed["second_writer_ok"] = True

    fake = FakeTransport(on_send=during_send)
    svc(session, fake).dispatch_pending(run.id, now=NOON)

    assert observed["dirty"] is False, "the session was dirty during the send"
    assert observed["second_writer_ok"] is True
    assert len(events_of(session, run.id, "probe.write")) == 1


def test_the_terminal_state_is_visible_to_another_connection_before_the_send(session):
    """The commit really happened, not merely the flush."""
    run = complete_run(session)
    seen: dict[str, str] = {}

    def during_send():
        with Session(bind=database.ENGINE) as other:
            seen["state"] = other.get(Run, run.id).state

    svc(session, FakeTransport(on_send=during_send)).dispatch_pending(run.id, now=NOON)
    assert seen["state"] == RunState.COMPLETE.value


# ------------------------------------------------------- failure recording


def test_a_transport_failure_is_recorded_never_silent(session):
    """AC5 / M10."""
    run = complete_run(session)
    fake = FakeTransport(fail_with=SendError("telegram is down", retryable=True))

    assert svc(session, fake).dispatch_pending(run.id, now=NOON) == []

    failures = events_of(session, run.id, FAILED_EVENT)
    assert len(failures) == 1
    assert failures[0].level == "error"
    payload = json.loads(failures[0].data_json)
    assert payload["kind"] == Kind.RUN_COMPLETE.value
    assert payload["retryable"] is True
    assert payload["transport"] == "fake"


def test_a_failure_records_no_sent_row_so_a_later_pass_can_deliver(session):
    run = complete_run(session)
    fake = FakeTransport(fail_with=SendError("down", retryable=True))
    svc(session, fake).dispatch_pending(run.id, now=NOON)
    assert events_of(session, run.id, SENT_EVENT) == []

    # Retry is NOT implemented in this stage, so delivery happens on the next
    # dispatch for this run rather than inside this call. docs/P7-STAGE5-FLOW §4.
    ok = FakeTransport()
    assert len(svc(session, ok).dispatch_pending(run.id, now=NOON)) == 1


def test_a_failure_does_not_stop_the_other_kinds(session):
    """One dead render or send must not silence the rest of the run's news."""
    run = failed_run(session)
    add_event(session, run.id, "discovery.overflow", subreddit="SaaS", seen=100)

    class FlakyOnce:
        name = "flaky"

        def __init__(self):
            self.calls = 0
            self.sends = []

        def send(self, *, chat_id, markdown):
            self.calls += 1
            if self.calls == 1:
                raise SendError("first one fails", retryable=True)
            self.sends.append((chat_id, markdown))
            return "ok"

    flaky = FlakyOnce()
    sent = svc(session, flaky).dispatch_pending(run.id, now=NOON)
    assert [s.kind for s in sent] == [Kind.DISCOVERY_OVERFLOW]
    assert len(events_of(session, run.id, FAILED_EVENT)) == 1


def test_exactly_one_attempt_is_made_because_retry_is_out_of_scope(session):
    """M49. Retry was scoped out of Stage 5 by the operator.

    ``docs/34`` §P7 task 6's *"failures recorded, never silent"* half is delivered
    above; the *"retry on failure"* half is not, and the gap is recorded in
    ``docs/P7-STAGE5-FLOW.md`` §4. This asserts the current contract so that
    adding retry later is a visible change rather than a silent one.
    """
    run = complete_run(session)
    fake = FakeTransport(fail_with=SendError("down", retryable=True))
    svc(session, fake).dispatch_pending(run.id, now=NOON)
    assert len(fake.sends) == 1, "one attempt, no retry in this stage"


# ------------------------------------------------------------- what is recorded


def test_a_sent_row_carries_the_evidence_of_delivery(session):
    """T2a: the record must be the effect, not a flag."""
    run = complete_run(session)
    fake = FakeTransport()
    svc(session, fake).dispatch_pending(run.id, now=NOON)

    payload = json.loads(events_of(session, run.id, SENT_EVENT)[0].data_json)
    assert payload["kind"] == Kind.RUN_COMPLETE.value
    assert payload["transport"] == "fake"
    assert payload["message_id"] == "fake-1"


def test_the_raw_chat_id_never_reaches_the_timeline(session):
    """R15: ``run_events.data_json`` is rendered into an HTML page."""
    run = complete_run(session)
    svc(session, FakeTransport()).dispatch_pending(run.id, now=NOON)

    row = events_of(session, run.id, SENT_EVENT)[0]
    assert "42" not in (row.data_json or "").replace('"message_id": "fake-1"', "")
    payload = json.loads(row.data_json)
    assert payload["chat_id_hash"] == hash_chat_id("42")
    assert payload.get("chat_id") is None


def test_the_chat_id_hash_is_stable_and_short():
    assert hash_chat_id("42") == hash_chat_id("42")
    assert hash_chat_id("42") != hash_chat_id("43")
    assert len(hash_chat_id("42")) == 12


# ============================================================================
# Regression tests required before commit (operator's Stage 5 conditions)
# ============================================================================


def _run_service(session):
    return RunService(session, JobQueue(database.ENGINE))


def test_finalize_run_is_enqueued_exactly_once_for_a_failed_run(session):
    """D7, condition 1. One drain, not one per call site.

    Without it the ``run.failed`` notification has no delivery path at all:
    ``finalize_run`` does not run on a failed run, and nothing enqueues
    ``maintenance`` (DI17).
    """
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()

    service.fail(run.id, "boom")
    session.commit()

    finalisers = session.query(Job).filter(Job.run_id == run.id, Job.job_type == FINALIZE_JOB).all()
    assert len(finalisers) == 1
    assert finalisers[0].state == JobState.QUEUED.value


def test_cancelling_after_the_finaliser_is_queued_enqueues_no_duplicate(session):
    """Condition 2. ``cancel`` must not add a second drain.

    It cancels queued work and transitions; it does not enqueue. A second
    finaliser would be claimed against a cancelled run and, being idempotent,
    would do nothing -- but the job row itself would be a lie about what is
    pending.
    """
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a", "b")))
    session.commit()
    service.fail(run.id, "boom")
    session.commit()

    before = session.query(Job).filter(Job.run_id == run.id).count()
    with pytest.raises(IllegalTransition):
        # FAILED -> CANCELLED is not a legal edge; the guard is what prevents the
        # duplicate, and asserting the raise is what proves the guard ran.
        service.cancel(run.id)
    session.rollback()

    with Session(bind=database.ENGINE) as fresh:
        finalisers = (
            fresh.query(Job).filter(Job.run_id == run.id, Job.job_type == FINALIZE_JOB).all()
        )
        assert len(finalisers) == 1, "no duplicate finaliser"
        assert fresh.query(Job).filter(Job.run_id == run.id).count() == before


def test_a_cancelled_run_gets_no_second_finaliser_from_the_normal_path(session):
    """The reachable half of condition 2: cancel a run that is still scraping."""
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a", "b")))
    session.commit()

    service.cancel(run.id)
    session.commit()

    with Session(bind=database.ENGINE) as fresh:
        finalisers = (
            fresh.query(Job).filter(Job.run_id == run.id, Job.job_type == FINALIZE_JOB).all()
        )
        assert finalisers == [], "cancel enqueues nothing; CANCELLED is terminal"


def test_dispatch_happens_only_after_the_handler_commits(session):
    """Condition 3, end to end through the real handler.

    ``handle_finalize_run`` transitions the run and then commits *before*
    dispatching. Observed from inside the transport: the session is clean and the
    terminal state is already durable on another connection.
    """
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    session.add(ScrapeRun(scraper_type="subreddit", leads_found=4, posts_found=40, run_id=run.id))
    job = Job(run_id=run.id, job_type=FINALIZE_JOB, state=JobState.RUNNING.value, payload_json="{}")
    session.add(job)
    session.commit()

    observed: dict[str, object] = {}

    def during_send():
        observed["dirty"] = bool(session.dirty or session.new or session.deleted)
        with Session(bind=database.ENGINE) as other:
            observed["state"] = other.get(Run, run.id).state

    fake = FakeTransport(on_send=during_send)
    import src.notify.service as notify_service

    original = notify_service.NotificationService.__init__

    def patched(self, s, transport=None, settings=None):
        original(
            self, s, fake, NotifySettings(enabled=True, transport="fake", telegram_chat_id="42")
        )

    notify_service.NotificationService.__init__ = patched  # type: ignore[method-assign]
    try:
        result = handle_finalize_run(session, job)
    finally:
        notify_service.NotificationService.__init__ = original  # type: ignore[method-assign]

    assert observed["dirty"] is False, "the handler had not committed before dispatching"
    assert observed["state"] == RunState.COMPLETE.value

    # BOTH, and in DISPATCH_ORDER. `create()` walks the run through both review
    # gates, so `gate.reached` is genuine evidence -- delivered late, at finalise,
    # which is exactly the cost assumption A9 records and P18 will inherit.
    assert result["notified"] == [Kind.RUN_COMPLETE.value, Kind.GATE_REACHED.value]


def test_a_notification_failure_changes_neither_the_run_nor_the_transaction(session):
    """Condition 4. AD-9 applied to the notification tier.

    A run that collected leads must not be reported as failed because Telegram
    was unreachable -- and the transaction that recorded the run's completion must
    already be committed and unaffected.
    """
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    job = Job(run_id=run.id, job_type=FINALIZE_JOB, state=JobState.RUNNING.value, payload_json="{}")
    session.add(job)
    session.commit()

    import src.notify.service as notify_service

    original = notify_service.NotificationService.__init__

    def patched(self, s, transport=None, settings=None):
        original(
            self,
            s,
            FakeTransport(fail_with=SendError("telegram is down", retryable=True)),
            NotifySettings(enabled=True, transport="fake", telegram_chat_id="42"),
        )

    notify_service.NotificationService.__init__ = patched  # type: ignore[method-assign]
    try:
        result = handle_finalize_run(session, job)
    finally:
        notify_service.NotificationService.__init__ = original  # type: ignore[method-assign]

    assert result["notified"] == [], "nothing was delivered"
    with Session(bind=database.ENGINE) as fresh:
        reloaded = fresh.get(Run, run.id)
        assert reloaded.state == RunState.COMPLETE.value, "the run still completed"
        assert reloaded.error is None, "a notification failure is not a run error"
        assert len(events_of(fresh, run.id, FAILED_EVENT)) == 1, "and it was recorded"


def test_a_raising_notification_tier_cannot_fail_the_run(session):
    """Belt and braces: even an unexpected exception is absorbed.

    ``_notify`` catches broadly on purpose -- telemetry must not fail a finished
    run -- and the catch is asserted rather than assumed.
    """
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    job = Job(run_id=run.id, job_type=FINALIZE_JOB, state=JobState.RUNNING.value, payload_json="{}")
    session.add(job)
    session.commit()

    import src.notify.service as notify_service

    original = notify_service.NotificationService.dispatch_pending

    def boom(self, run_id, *, now=None):
        raise RuntimeError("the notification tier exploded")

    notify_service.NotificationService.dispatch_pending = boom  # type: ignore[method-assign]
    try:
        result = handle_finalize_run(session, job)
    finally:
        notify_service.NotificationService.dispatch_pending = original  # type: ignore[method-assign]

    assert result["notified"] == []
    with Session(bind=database.ENGINE) as fresh:
        assert fresh.get(Run, run.id).state == RunState.COMPLETE.value


def test_the_handler_is_still_idempotent_and_does_not_resend(session):
    """A lease expiring near the end must not produce a second message."""
    service = _run_service(session)
    run = service.create(None, RunOptions(subreddits=("a",)))
    session.commit()
    session.add(ScrapeRun(scraper_type="subreddit", leads_found=4, posts_found=40, run_id=run.id))
    job = Job(run_id=run.id, job_type=FINALIZE_JOB, state=JobState.RUNNING.value, payload_json="{}")
    session.add(job)
    session.commit()

    fake = FakeTransport()
    import src.notify.service as notify_service

    original = notify_service.NotificationService.__init__

    def patched(self, s, transport=None, settings=None):
        original(
            self, s, fake, NotifySettings(enabled=True, transport="fake", telegram_chat_id="42")
        )

    notify_service.NotificationService.__init__ = patched  # type: ignore[method-assign]
    try:
        first = handle_finalize_run(session, job)
        second = handle_finalize_run(session, job)
    finally:
        notify_service.NotificationService.__init__ = original  # type: ignore[method-assign]

    assert first["notified"] == [Kind.RUN_COMPLETE.value, Kind.GATE_REACHED.value]
    assert "skipped" in second, "the second call takes the terminal path"
    assert second["notified"] == [], "and sends nothing"
    assert len(fake.sends) == 2, "one per kind on the first pass, none on the second"


# --------------------------------------------------------- AC1 / M3: timing


def test_dispatch_completes_within_ten_seconds(session):
    """AC1: *"A completed run delivers a message within 10 s."* M3: p95 < 10 s.

    Found missing during Stage 7's final validation: the criterion had no
    assertion at all, which is the same species as grep fence 3 -- a line claimed
    for six phases that nobody had checked.

    **Measured with a monotonic clock around the dispatch call alone**, not as
    wall-clock around a whole run. That distinction is deliberate: this project
    already has one wall-clock budget test that fails under machine load while
    testing nothing about correctness (DI18, observed twice on 2026-08-10 at
    105 ms against a 50 ms budget). Scoping the measurement to the call, with a
    fake transport, keeps it about the dispatcher.

    The budget is the phase's own 10 s. Real dispatch is milliseconds, so the
    headroom is enormous by design -- this exists to catch a regression that
    makes dispatch *pathologically* slow (an N+1 query per event, a retry loop
    that should not be here), not to police microseconds.
    """
    import time as _time

    run = complete_run(session)
    fake = FakeTransport()
    service = svc(session, fake)

    started = _time.monotonic()
    sent = service.dispatch_pending(run.id, now=NOON)
    elapsed = _time.monotonic() - started

    assert len(sent) == 1, "the message must actually have been dispatched"
    assert elapsed < 10.0, f"dispatch took {elapsed:.3f}s, budget is 10s (AC1)"


def test_the_p95_of_twenty_dispatches_is_within_budget(session):
    """M3, as a distribution rather than a single sample.

    Twenty runs, each dispatched once, 95th percentile under the budget. A single
    timing can be lucky; a p95 cannot be lucky twenty times.
    """
    import time as _time

    fake = FakeTransport()
    timings: list[float] = []
    for _ in range(20):
        run = complete_run(session)
        started = _time.monotonic()
        assert len(svc(session, fake).dispatch_pending(run.id, now=NOON)) == 1
        timings.append(_time.monotonic() - started)

    timings.sort()
    p95 = timings[int(0.95 * (len(timings) - 1))]
    assert p95 < 10.0, f"p95 was {p95:.3f}s over {len(timings)} dispatches, budget is 10s"
    assert len(fake.sends) == 20, "each run must have been notified exactly once"


# ------------------------------------------------- the production wiring


def test_the_transport_is_built_from_config_when_none_is_injected(session):
    """The path production actually takes, which every other test bypasses.

    Injecting a fake everywhere would leave ``build_transport`` unexercised from
    the service -- and that is the line an operator's config flows through.
    """
    run = complete_run(session)
    service = NotificationService(
        session, settings=NotifySettings(enabled=True, transport="null", telegram_chat_id="42")
    )
    assert service.transport.name == "null"
    assert len(service.dispatch_pending(run.id, now=NOON)) == 1
    payload = json.loads(events_of(session, run.id, SENT_EVENT)[0].data_json)
    assert payload["transport"] == "null"
    assert payload["message_id"].startswith("null:")


def test_building_the_transport_is_lazy_so_construction_never_raises(session, monkeypatch):
    """A missing token is a timeline entry, not a reason to fail a finished run.

    ``bot_api`` without ``TELEGRAM_BOT_TOKEN`` raises at construction (Stage 4).
    If the service built its transport eagerly, merely *constructing* it inside
    ``finalize_run`` would raise -- so the raise must wait until the transport is
    used, where ``_notify`` can absorb it.

    ⚠️ **The token is deleted explicitly, and that is the point of the line.**
    This test asserts on the *absence* of ``TELEGRAM_BOT_TOKEN``, which until
    2026-08-11 was accidental: no token existed on any machine, so nothing had to
    arrange it. Closing blocker **B1** put a real token in ``.env``, and
    ``settings.load_env`` loads that file **once per process, lazily** -- so as
    soon as any earlier test touches settings, the token is in ``os.environ`` for
    the rest of the session and this test's premise silently evaporates. It then
    passes alone and fails in the full suite.

    ``monkeypatch.delenv`` makes the precondition explicit rather than ambient,
    which *strengthens* the assertion: it now proves what its name claims on a
    machine that has done the live Telegram test as well as on one that has not.
    Recorded in ``PHASE-07-COMPLETION-REPORT`` §7a.
    """
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    service = NotificationService(
        session, settings=NotifySettings(enabled=True, transport="bot_api", telegram_chat_id="42")
    )
    with pytest.raises(SendError, match="TELEGRAM_BOT_TOKEN"):
        _ = service.transport


def test_an_unrecognised_kind_in_a_sent_row_is_ignored_not_fatal(session):
    """Forward compatibility: a row written by a version with more kinds.

    ``freeze §7`` allows expansion to nine. A ``notify.sent`` row naming a kind
    this version does not know must not crash the dedup read -- it simply is not
    one of *our* five.
    """
    run = complete_run(session)
    session.add(
        RunEvent(
            run_id=run.id,
            event=SENT_EVENT,
            data_json=json.dumps({"kind": "lead.high_confidence", "transport": "bot_api"}),
        )
    )
    session.commit()

    fake = FakeTransport()
    assert len(svc(session, fake).dispatch_pending(run.id, now=NOON)) == 1


def test_a_non_object_event_payload_is_ignored(session):
    """Valid JSON that is not an object -- the timeline is not schema-enforced."""
    run = complete_run(session)
    session.add(RunEvent(run_id=run.id, event="net.degraded", data_json="[1, 2, 3]"))
    session.add(RunEvent(run_id=run.id, event="discovery.overflow", data_json='"a string"'))
    session.commit()

    fake = FakeTransport()
    kinds = {s.kind for s in svc(session, fake).dispatch_pending(run.id, now=NOON)}
    # Both still count as evidence -- losing an overflow alert to a malformed row
    # is the silent gap R19 forbids -- but neither crashes the read.
    assert Kind.DISCOVERY_OVERFLOW in kinds
    assert Kind.PROXY_POOL_DEGRADED in kinds


# ------------------------------------------------------------------- read-only


WRITES = ("insert", "update", "delete", "replace")


def test_the_read_half_of_dispatch_issues_no_writes(session):
    """Reads happen before the send; the only write is the outcome, after it."""
    run = complete_run(session)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    service = svc(session, FakeTransport())
    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        service._evidence(run.id)
        service._already_sent(run.id)
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)

    offenders = [s for s in statements if s.strip().split(" ", 1)[0].lower() in WRITES]
    assert offenders == [], f"the read path wrote: {offenders}"
    assert statements, "it issued no SQL at all"
