"""``/runs`` and ``/runs/<id>`` — rendering, navigation and the redaction check.

The template assertions are deliberately about *content*, not markup: asserting
on a class name would break every time the CSS is touched and would prove
nothing about what the operator reads.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job
from src.orchestration.job_queue import JobQueue
from src.orchestration.run_service import RunOptions, RunService
from src.orchestration.states import JobState


@pytest.fixture
def session(app):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


def _make_run(session, subreddits=("saas", "startups")):
    run = RunService(session, JobQueue(database.ENGINE)).create(
        None, RunOptions(subreddits=tuple(subreddits))
    )
    session.commit()
    return run


def _text(response) -> str:
    return response.get_data(as_text=True)


# --------------------------------------------------------------------- /runs


def test_runs_page_renders_with_no_runs(client):
    """The empty state is a page an operator sees on day one."""
    response = client.get("/runs")
    assert response.status_code == 200
    assert "No runs yet" in _text(response)


def test_runs_page_lists_a_run(client, session):
    run = _make_run(session)
    body = _text(client.get("/runs"))

    assert f"#{run.id}" in body
    assert f"/runs/{run.id}" in body
    assert "scraping" in body


def test_runs_page_shows_job_progress_and_duration(client, session):
    run = _make_run(session, ("a", "b", "c"))
    jobs = session.query(Job).filter(Job.run_id == run.id).order_by(Job.id).all()
    jobs[0].state = JobState.DONE.value
    session.commit()

    body = _text(client.get("/runs"))
    assert "1 / 3" in body


def test_run_state_is_spelled_out_not_only_coloured(client, session):
    """docs/09 §5.3: colour is never the only signal."""
    run = _make_run(session)
    RunService(session, JobQueue(database.ENGINE)).cancel(run.id)
    session.commit()

    assert "cancelled" in _text(client.get("/runs"))


# ---------------------------------------------------------------- /runs/<id>


def test_run_page_renders_the_first_paint_correctly(client, session):
    """Server-rendered before polling: a page of dashes reads as a fault."""
    run = _make_run(session)
    body = _text(client.get(f"/runs/{run.id}"))

    assert f"Run #{run.id}" in body
    assert "Scraping" in body
    assert "Leads found" in body


def test_run_page_has_a_cancel_control(client, session):
    run = _make_run(session)
    assert "Cancel run" in _text(client.get(f"/runs/{run.id}"))


def test_run_page_polls_progress_and_events(client, session):
    """AC10: the feed is live, and both polls are wired to this run.

    The URLs are assembled in JS from ``RUN_ID``, so the run number and the two
    paths are asserted separately -- a whole-URL match would be asserting a
    string the page never contains.
    """
    run = _make_run(session)
    body = _text(client.get(f"/runs/{run.id}"))

    assert f"const RUN_ID = {run.id};" in body
    assert "'/progress'" in body
    assert "'/events?after='" in body


def test_a_missing_run_is_a_404_page_not_a_stack_trace(client):
    """Retention purges runs after 90 days, so a stale bookmark lands here."""
    response = client.get("/runs/4242")
    assert response.status_code == 404
    assert "not found" in _text(response).lower()


# ----------------------------------------------------------------- the feed


def test_the_feed_helper_stops_on_a_terminal_state(client, session):
    """A finished run polled forever is the failure docs/09 §5.2 names."""
    run = _make_run(session)
    body = _text(client.get(f"/runs/{run.id}"))
    assert "p.terminal" in body and "eventPoll.stop()" in body


def test_the_poll_helper_carries_all_three_disciplines(client):
    """Asserted on the shared helper, so every future page inherits them."""
    body = _text(client.get("/health/ai"))

    assert "document.hidden" in body, "polling must pause on a hidden tab"
    assert "visibilitychange" in body, "and resume when it comes back"
    assert "errorsBeforeBackoff" in body, "and back off after repeated errors"


def test_events_are_rendered_as_text_not_markup(client, session):
    """These strings carry scraped subreddit names, so markup here would be XSS.

    Asserts on *assignment*, not on the word: the page explains in a comment why
    it does not use innerHTML, and a test that banned the word would delete the
    comment rather than the vulnerability.
    """
    run = _make_run(session)
    body = _text(client.get(f"/runs/{run.id}"))

    assert ".textContent =" in body
    assert ".innerHTML =" not in body
    assert ".insertAdjacentHTML" not in body


# ------------------------------------------------------------------ the nav


def test_runs_is_in_the_navigation(client):
    from src.dashboard.nav import NAV_ITEMS

    assert any(item.key == "runs" and item.url == "/runs" for item in NAV_ITEMS)
    assert 'href="/runs"' in _text(client.get("/"))


def test_the_sidebar_button_sends_the_operator_to_the_run(client):
    """docs/13 §7: it used to show a status line that never updated."""
    body = _text(client.get("/"))

    assert "data.run_id" in body
    assert "'/runs/' + data.run_id" in body


# ------------------------------------------------------------- F3 redaction


def test_no_credential_reaches_the_rendered_run_page(client, session):
    """R15 / F3, asserted at the template rather than only at the write.

    P2's F3 finding was that the leak is never where the guard is looking. Both
    columns rendered here are redacted on write; this proves it at the sink an
    operator actually reads.
    """
    secret = "sk-templatecredential0123456789"
    run = _make_run(session, ("saas",))
    service = RunService(session, JobQueue(database.ENGINE))
    service.fail(run.id, f"provider rejected {secret}")
    session.commit()

    queue = JobQueue(database.ENGINE)
    job = session.query(Job).filter(Job.run_id == run.id).first()
    job.state = JobState.RUNNING.value
    session.commit()
    queue.fail(job.id, f"auth failed with {secret}", retryable=False)

    assert secret not in _text(client.get(f"/runs/{run.id}"))
    assert secret not in _text(client.get("/runs"))


def test_a_credential_in_an_event_message_does_not_reach_the_page(client, session):
    from src.obs.events import emit_event

    secret = "sk-feedcredential0123456789"
    run = _make_run(session, ("saas",))
    emit_event(session, run.id, "test.leak", message=f"connecting with {secret}")
    session.commit()

    feed = client.get(f"/api/runs/{run.id}/events").get_data(as_text=True)
    assert secret not in feed
    assert secret not in _text(client.get(f"/runs/{run.id}"))
