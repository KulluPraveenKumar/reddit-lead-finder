"""P7 Stage 3 -- Markdown bodies built from SQL.

Two kinds of assertion, deliberately both:

* **Golden fixtures** (``tests/fixtures/notify/*.md``) compared for exact equality,
  so a change to any character of a shipped message is a visible diff rather than
  a passing test.
* **Field-by-field**, by parsing the body back into a mapping. Substring matching
  would pass while a label was renamed, a value was moved to the wrong line, or a
  figure was rendered twice -- and the labels are the part an operator reads.

Every field is additionally proved to come from **SQL** by changing the database
and asserting the field changes. A renderer that hard-coded a value would satisfy
a golden fixture forever.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run, RunEvent, ScrapeRun
from src.notify import Kind
from src.notify.renderers import (
    GATE_LABELS,
    RENDERERS,
    SCRAPE_JOB,
    render,
    render_run_complete,
)
from src.orchestration.states import JobState, RunState

FIXTURES = Path(__file__).parent / "fixtures" / "notify"

STARTED = datetime(2026, 8, 10, 12, 0, 0)
FINISHED = datetime(2026, 8, 10, 12, 4, 12)


@pytest.fixture
def session(temp_db):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


def parse(body: str) -> dict[str, str]:
    """``- Label: value`` lines back into a mapping.

    Field-level assertions need the label and the value separately; a substring
    check cannot tell "Leads: 12" from "Leads kept: 12" or notice that a label
    was renamed. ``split(": ", 1)`` keeps colons inside values intact -- error
    messages contain them.
    """
    fields = {}
    for line in body.splitlines():
        if line.startswith("- ") and ": " in line:
            label, value = line[2:].split(": ", 1)
            fields[label] = value
    return fields


def title_of(body: str) -> str:
    return body.splitlines()[0]


def read_fixture(name: str) -> str:
    """A golden body, with line endings normalised to ``\\n``.

    Not cosmetic. ``.gitattributes`` marks ``*.md`` as ``text`` and this machine
    has ``core.autocrlf=true``, so a fresh checkout on Windows rewrites every
    fixture to CRLF while a renderer always joins with ``\\n``. Comparing raw
    bytes would therefore pass on Linux CI and fail on Windows -- a
    platform-dependent failure that looks like a code defect and is not one.

    Normalising here rather than marking the fixtures ``-text`` keeps the repo's
    line-ending policy untouched: the fixtures are genuinely text and should be
    diffable and checked out natively like everything else.
    """
    return (FIXTURES / name).read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")


# ------------------------------------------------------------------- builders


def make_run(session, *, state=RunState.COMPLETE, error=None, cost=0.0, finished=FINISHED):
    run = Run(
        state=state.value,
        started_at=STARTED,
        updated_at=finished or STARTED,
        finished_at=finished,
        llm_cost_usd=cost,
        error=error,
    )
    session.add(run)
    session.commit()
    return run


def add_scrape_rows(session, run_id, rows):
    for leads, posts in rows:
        session.add(
            ScrapeRun(scraper_type="subreddit", leads_found=leads, posts_found=posts, run_id=run_id)
        )
    session.commit()


def add_jobs(session, run_id, states):
    for state in states:
        session.add(Job(run_id=run_id, job_type=SCRAPE_JOB, state=state.value, payload_json="{}"))
    session.commit()


def add_event(session, run_id, event_name, *, level="info", message=None, **data):
    session.add(
        RunEvent(
            run_id=run_id,
            event=event_name,
            level=level,
            message=message,
            data_json=json.dumps(data) if data else None,
        )
    )
    session.commit()


# ------------------------------------------------------------- table totality


def test_every_kind_has_a_renderer_and_no_renderer_is_orphaned():
    assert set(RENDERERS) == set(Kind)
    assert len(RENDERERS) == 5


def test_render_rejects_anything_that_is_not_a_kind():
    """Unlike ``decide``, reaching here with an unknown event is a bug.

    ``decide`` is handed every timeline row and suppresses what it does not
    recognise; ``render`` is called only for what the policy already approved.
    """
    for bad in ("run.created", "", "lead.high_confidence"):
        with pytest.raises(ValueError, match="not a notification kind"):
            render(bad, None, 1)  # type: ignore[arg-type]


def test_the_scrape_job_constant_matches_run_service():
    """The literal is duplicated to keep the import graph read-only.

    Importing ``SCRAPE_JOB`` from ``run_service`` would pull ``RunService`` and
    ``JobQueue`` -- the enqueue path -- into a module whose contract is that it
    only reads. The duplication is safe only while this assertion holds.
    """
    from src.orchestration.run_service import SCRAPE_JOB as CANONICAL

    assert SCRAPE_JOB == CANONICAL


# ------------------------------------------------------------- run.complete


def test_run_complete_matches_its_golden_fixture(session):
    run = make_run(session, cost=0.0123)
    add_scrape_rows(session, run.id, [(7, 200), (5, 140)])
    add_jobs(session, run.id, [JobState.DONE] * 6 + [JobState.FAILED])

    body = render(Kind.RUN_COMPLETE, session, run.id)
    assert body == read_fixture("run_complete.md")


def test_run_complete_every_field_individually(session):
    run = make_run(session, cost=0.0123)
    add_scrape_rows(session, run.id, [(7, 200), (5, 140)])
    add_jobs(session, run.id, [JobState.DONE] * 6 + [JobState.FAILED])

    fields = parse(render(Kind.RUN_COMPLETE, session, run.id))
    assert title_of(render(Kind.RUN_COMPLETE, session, run.id)) == f"*Run {run.id} complete*"
    assert fields["Leads"] == "12"
    assert fields["Posts scanned"] == "340"
    assert fields["Subreddits"] == "6 of 7"
    assert fields["Failed"] == "1"
    assert fields["Duration"] == "4m 12s"
    assert fields["AI cost"] == "$0.0123"
    assert "Cancelled" not in fields, "a zero count must be omitted, not printed as 0"


def test_leads_come_from_scrape_runs_not_from_the_stats_blob(session):
    """The aggregate is SQL over ``scrape_runs``, not ``runs.stats_json``.

    ``stats_json`` is a rolling counter a handler writes for the progress
    endpoint. Rendering from it would report what a handler last remembered
    rather than what was recorded -- and it is the caller-supplied aggregate this
    stage exists to avoid. Here it says 999 and the message must ignore it.
    """
    run = make_run(session)
    run.stats_json = json.dumps({"leads_found": 999})
    session.commit()
    add_scrape_rows(session, run.id, [(4, 10)])

    assert parse(render_run_complete(session, run.id))["Leads"] == "4"


def test_changing_the_database_changes_every_sourced_field(session):
    """The proof that nothing is hard-coded.

    A renderer returning a constant would satisfy the golden fixture forever, so
    each figure is moved in the database and the body must move with it.
    """
    run = make_run(session, cost=0.5)
    add_scrape_rows(session, run.id, [(1, 2)])
    add_jobs(session, run.id, [JobState.DONE])
    before = parse(render_run_complete(session, run.id))

    add_scrape_rows(session, run.id, [(9, 30)])
    add_jobs(session, run.id, [JobState.FAILED, JobState.CANCELLED])
    run.llm_cost_usd = 1.25
    run.finished_at = STARTED + timedelta(seconds=90)
    session.commit()
    after = parse(render_run_complete(session, run.id))

    assert before["Leads"] == "1" and after["Leads"] == "10"
    assert before["Posts scanned"] == "2" and after["Posts scanned"] == "32"
    assert before["Subreddits"] == "1 of 1" and after["Subreddits"] == "1 of 3"
    assert before["AI cost"] == "$0.5000" and after["AI cost"] == "$1.2500"
    assert before["Duration"] == "4m 12s" and after["Duration"] == "1m 30s"
    assert "Failed" not in before and after["Failed"] == "1"
    assert "Cancelled" not in before and after["Cancelled"] == "1"


def test_collection_totals_from_another_run_are_not_counted(session):
    """The aggregate is scoped to one run, not to the whole audit table.

    ``scrape_runs`` accumulates a row per scraper per run for the life of the
    installation, and ten pre-existing rows carry ``run_id IS NULL`` because they
    predate orchestration. A missing ``WHERE run_id`` would report the sum of
    everything ever collected as this run's result -- and it would grow, quietly
    and plausibly, with every run.

    Added after a surviving mutation: dropping the run filter left every other
    test in this file green.
    """
    mine = make_run(session)
    theirs = make_run(session)
    add_scrape_rows(session, mine.id, [(4, 10)])
    add_scrape_rows(session, theirs.id, [(500, 9000)])
    # A pre-orchestration row, exactly as the ten live ones look.
    session.add(ScrapeRun(scraper_type="subreddit", leads_found=77, posts_found=88, run_id=None))
    session.commit()

    fields = parse(render_run_complete(session, mine.id))
    assert fields["Leads"] == "4"
    assert fields["Posts scanned"] == "10"


def test_job_counts_from_another_run_are_not_counted(session):
    """Same scoping question, on the ``jobs`` side."""
    mine = make_run(session)
    theirs = make_run(session)
    add_jobs(session, mine.id, [JobState.DONE])
    add_jobs(session, theirs.id, [JobState.DONE] * 9)
    assert parse(render_run_complete(session, mine.id))["Subreddits"] == "1 of 1"


def test_only_scrape_jobs_are_counted_as_subreddits(session):
    """``finalize_run`` and any other job type are not subreddits.

    Counting them would make "6 of 7" read as one more subreddit than the run
    ever had.
    """
    run = make_run(session)
    add_jobs(session, run.id, [JobState.DONE, JobState.DONE])
    session.add(
        Job(run_id=run.id, job_type="finalize_run", state=JobState.DONE.value, payload_json="{}")
    )
    session.add(
        Job(run_id=run.id, job_type="maintenance", state=JobState.DONE.value, payload_json="{}")
    )
    session.commit()
    assert parse(render_run_complete(session, run.id))["Subreddits"] == "2 of 2"


def test_a_zero_is_printed_when_it_is_a_real_answer(session):
    """``None`` means "cannot be sourced"; ``0`` is a fact and must be shown.

    A renderer that dropped falsey values would silently omit ``Leads: 0`` -- the
    single most important number on a run that found nothing.
    """
    run = make_run(session)
    fields = parse(render_run_complete(session, run.id))
    assert fields["Leads"] == "0"
    assert fields["Posts scanned"] == "0"
    assert fields["AI cost"] == "$0.0000"


def test_a_run_with_no_collection_rows_renders_zeroes_not_a_crash(session):
    run = make_run(session)
    fields = parse(render(Kind.RUN_COMPLETE, session, run.id))
    assert fields["Leads"] == "0"
    assert fields["Posts scanned"] == "0"
    assert "Subreddits" not in fields, "no jobs means the line cannot be sourced"


def test_a_missing_run_raises_rather_than_rendering_a_hollow_message(session):
    with pytest.raises(LookupError, match="does not exist"):
        render(Kind.RUN_COMPLETE, session, 4242)


# --------------------------------------------------------------- run.failed


def test_run_failed_matches_its_golden_fixture(session):
    run = make_run(session, state=RunState.FAILED, error="every proxy was blocked")
    add_scrape_rows(session, run.id, [(3, 80)])
    add_jobs(session, run.id, [JobState.DONE, JobState.DONE, JobState.FAILED])

    body = render(Kind.RUN_FAILED, session, run.id)
    assert body == read_fixture("run_failed.md")


def test_run_failed_every_field_individually(session):
    run = make_run(session, state=RunState.FAILED, error="every proxy was blocked")
    add_scrape_rows(session, run.id, [(3, 80)])
    add_jobs(session, run.id, [JobState.DONE, JobState.DONE, JobState.FAILED])

    body = render(Kind.RUN_FAILED, session, run.id)
    fields = parse(body)
    assert title_of(body) == f"*Run {run.id} FAILED*"
    assert fields["Error"] == "every proxy was blocked"
    assert fields["Leads kept"] == "3"
    assert fields["Posts scanned"] == "80"
    assert fields["Subreddits done"] == "2"
    assert fields["Subreddits failed"] == "1"
    assert "Collected work has been kept." in body


def test_run_failed_reports_what_survived_because_ad9_promises_it(session):
    """AD-9: *a failure never discards completed work.*

    The operator can only verify that promise if the message says how much
    survived, so the salvage figures are not decoration.
    """
    run = make_run(session, state=RunState.FAILED, error="boom")
    add_scrape_rows(session, run.id, [(11, 400)])
    assert parse(render(Kind.RUN_FAILED, session, run.id))["Leads kept"] == "11"


def test_a_failure_with_no_recorded_error_says_so_rather_than_printing_none(session):
    for error in (None, "", "   "):
        run = make_run(session, state=RunState.FAILED, error=error)
        fields = parse(render(Kind.RUN_FAILED, session, run.id))
        assert fields["Error"] == "no error was recorded"
        assert "None" not in fields["Error"]


def test_the_error_text_is_taken_from_the_run_row(session):
    run = make_run(session, state=RunState.FAILED, error="first")
    assert parse(render(Kind.RUN_FAILED, session, run.id))["Error"] == "first"
    run.error = "second: with a colon"
    session.commit()
    assert parse(render(Kind.RUN_FAILED, session, run.id))["Error"] == "second: with a colon"


# ------------------------------------------------------------- gate.reached


def test_gate_reached_matches_its_golden_fixture(session):
    run = make_run(session, state=RunState.AWAITING_SUBREDDIT_REVIEW, finished=None)
    body = render(Kind.GATE_REACHED, session, run.id)
    assert body == read_fixture("gate_reached.md")


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (RunState.AWAITING_SUBREDDIT_REVIEW, "Gate 1 — subreddit review"),
        (RunState.AWAITING_KEYWORD_REVIEW, "Gate 2 — keyword review"),
        (RunState.AWAITING_OPTIONS, "Run options"),
    ],
)
def test_each_waiting_state_names_its_own_gate(session, state, label):
    run = make_run(session, state=state, finished=None)
    fields = parse(render(Kind.GATE_REACHED, session, run.id))
    assert fields["Waiting at"] == label


def test_gate_reached_degrades_gracefully_with_no_p17_data(session):
    """Revision ``0008`` does not exist, so there is nothing to count.

    ``docs/34`` §P18 owns the rich card -- candidates, rejects, estimate, deep
    link -- because it is the first phase with candidates to count. Those figures
    live in ``project_subreddits`` / ``project_keywords``, created by ``0008``.
    The renderer must omit them rather than print zeroes, which would read as
    "nothing was found" and send the operator looking for a bug.
    """
    run = make_run(session, state=RunState.AWAITING_SUBREDDIT_REVIEW, finished=None)
    body = render(Kind.GATE_REACHED, session, run.id)
    fields = parse(body)

    assert set(fields) == {"Waiting at", "Since"}
    for absent in ("Candidates", "Validated", "Rejected", "Estimate", "Estimated cost", "Link"):
        assert absent not in fields
    assert "0 candidates" not in body


def test_gate_reached_does_not_query_tables_that_do_not_exist_yet(session):
    """A guard against a later reader adding the P17 queries early.

    ``project_subreddits`` and ``project_keywords`` arrive in ``0008``. A query
    against either would raise ``OperationalError`` here, so this asserts the
    statements actually issued name neither.
    """
    run = make_run(session, state=RunState.AWAITING_KEYWORD_REVIEW, finished=None)
    with captured_sql(session) as sql:
        render(Kind.GATE_REACHED, session, run.id)
    joined = " ".join(sql).lower()
    assert "project_subreddits" not in joined
    assert "project_keywords" not in joined


def test_a_run_no_longer_at_a_gate_still_renders(session):
    """A late notification must not become a failed one.

    The dispatcher decides *when* to send. By the time it does, the run may have
    moved on -- and a renderer that raised would turn "you were told late" into
    "you were never told".
    """
    run = make_run(session, state=RunState.SCRAPING, finished=None)
    body = render(Kind.GATE_REACHED, session, run.id)
    assert "no longer at a gate" in body
    assert parse(body)["Waiting at"] == "state scraping"


def test_gate_labels_cover_every_awaiting_state_the_machine_defines(session):
    """A thirteenth state added later must not silently render as raw text."""
    awaiting = {s.value for s in RunState if s.value.startswith("awaiting_")}
    assert set(GATE_LABELS) == awaiting


# ------------------------------------------------------ proxy.pool_degraded


def test_proxy_pool_degraded_matches_its_golden_fixture(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(
        session,
        run.id,
        "net.degraded",
        level="warning",
        message="Egress degraded: dc → direct",
        request_class="html",
        from_provider="dc",
        to_provider="direct",
        reason="no healthy proxy",
    )
    body = render(Kind.PROXY_POOL_DEGRADED, session, run.id)
    assert body == read_fixture("proxy_pool_degraded.md")


def test_proxy_pool_degraded_lists_every_ladder_step_individually(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(
        session,
        run.id,
        "net.degraded",
        request_class="html",
        from_provider="dc",
        to_provider="direct",
        reason="no healthy proxy",
    )
    add_event(
        session,
        run.id,
        "net.degraded",
        request_class="comments",
        from_provider="direct",
        to_provider="null",
        reason="hourly cap reached",
    )

    fields = parse(render(Kind.PROXY_POOL_DEGRADED, session, run.id))
    assert fields["Degradations"] == "2"
    assert fields["dc → direct"] == "no healthy proxy (html traffic)"
    assert fields["direct → null"] == "hourly cap reached (comments traffic)"


def test_proxy_degradation_reads_events_not_the_proxy_table(session):
    """D2b: an event that happened, not a pool that is small.

    ``config.yaml`` ships no proxy file, so ``proxies`` is empty on every run and
    a level-based rule would report the operator's own configuration back to
    them. The source must be ``run_events``.
    """
    run = make_run(session, state=RunState.COMPLETE)
    with captured_sql(session) as sql:
        render(Kind.PROXY_POOL_DEGRADED, session, run.id)
    joined = " ".join(sql).lower()
    assert "run_events" in joined
    assert "from proxies" not in joined


def test_no_degradation_renders_a_zero_count_rather_than_crashing(session):
    run = make_run(session, state=RunState.COMPLETE)
    assert parse(render(Kind.PROXY_POOL_DEGRADED, session, run.id))["Degradations"] == "0"


def test_a_degradation_with_missing_fields_still_renders(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(session, run.id, "net.degraded", from_provider="dc")
    fields = parse(render(Kind.PROXY_POOL_DEGRADED, session, run.id))
    assert fields["dc → ?"] == "no reason recorded"


# ------------------------------------------------------- discovery.overflow


def test_discovery_overflow_matches_its_golden_fixture(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(
        session,
        run.id,
        "discovery.overflow",
        level="error",
        channel="listing",
        subreddit="SaaS",
        seen=100,
        html_recovered=37,
    )
    add_event(
        session,
        run.id,
        "discovery.overflow",
        level="error",
        channel="listing",
        subreddit="startups",
        seen=100,
        html_recovered=12,
    )
    body = render(Kind.DISCOVERY_OVERFLOW, session, run.id)
    assert body == read_fixture("discovery_overflow.md")


def test_discovery_overflow_names_every_overflowed_subreddit(session):
    """P6's G5. Overflow is detected **per subreddit** and must be reported so.

    A combined multireddit request keyed on ``subreddits[0]`` would leave the
    others unable to detect overflow at all, which is why P6 made it
    per-subreddit. Summarising here as "3 subreddits overflowed" would undo that
    in the message and leave the operator without the one fact they can act on.
    """
    run = make_run(session, state=RunState.COMPLETE)
    subs = ["SaaS", "startups", "entrepreneur", "smallbusiness", "marketing"]
    for i, sub in enumerate(subs):
        add_event(
            session,
            run.id,
            "discovery.overflow",
            level="error",
            subreddit=sub,
            seen=100,
            html_recovered=i,
        )

    body = render(Kind.DISCOVERY_OVERFLOW, session, run.id)
    fields = parse(body)

    assert fields["Subreddits affected"] == "5"
    for i, sub in enumerate(subs):
        assert f"r/{sub}" in fields, f"{sub} was dropped from the message"
        assert fields[f"r/{sub}"] == f"100 seen, {i} recovered by HTML walk"


def test_overflow_of_one_subreddit_is_not_special_cased(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(session, run.id, "discovery.overflow", subreddit="SaaS", seen=100, html_recovered=4)
    fields = parse(render(Kind.DISCOVERY_OVERFLOW, session, run.id))
    assert fields["Subreddits affected"] == "1"
    assert fields["r/SaaS"] == "100 seen, 4 recovered by HTML walk"


def test_overflow_rows_from_other_runs_are_not_included(session):
    """The query is scoped to one run, not to the whole table."""
    mine = make_run(session, state=RunState.COMPLETE)
    theirs = make_run(session, state=RunState.COMPLETE)
    add_event(session, mine.id, "discovery.overflow", subreddit="SaaS", seen=100)
    add_event(session, theirs.id, "discovery.overflow", subreddit="OtherRun", seen=100)

    fields = parse(render(Kind.DISCOVERY_OVERFLOW, session, mine.id))
    assert fields["Subreddits affected"] == "1"
    assert "r/OtherRun" not in fields


def test_events_of_a_different_kind_are_not_included(session):
    run = make_run(session, state=RunState.COMPLETE)
    add_event(session, run.id, "discovery.poll.done", subreddit="Ignored", seen=5)
    add_event(session, run.id, "net.degraded", from_provider="dc", to_provider="direct")
    assert parse(render(Kind.DISCOVERY_OVERFLOW, session, run.id))["Subreddits affected"] == "0"


def test_a_corrupt_event_payload_does_not_stop_the_message(session):
    """A corrupt timeline row must not suppress the alert it was recording.

    R19 makes overflow an error; losing the message because one row's JSON is
    unreadable would convert a loud failure into the silent gap R19 forbids.
    """
    run = make_run(session, state=RunState.COMPLETE)
    session.add(RunEvent(run_id=run.id, event="discovery.overflow", data_json="{not json"))
    session.add(RunEvent(run_id=run.id, event="discovery.overflow", data_json="[1, 2]"))
    session.commit()

    fields = parse(render(Kind.DISCOVERY_OVERFLOW, session, run.id))
    assert fields["Subreddits affected"] == "2"
    assert fields["r/?"] == "no counts recorded"


# ------------------------------------------------------------------- duration


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (1, "1s"),
        (59, "59s"),
        (60, "1m 00s"),
        (252, "4m 12s"),
        (3599, "59m 59s"),
        (3600, "1h 00m"),
        (7625, "2h 07m"),
    ],
)
def test_duration_is_rendered_at_every_magnitude(session, seconds, expected):
    """Seconds, minutes and hours each have their own branch and their own test.

    The zero-padding matters: ``1m 0s`` and ``1m 00s`` sort differently by eye in
    a list of messages, and the run page already pads.
    """
    run = make_run(session, finished=STARTED + timedelta(seconds=seconds))
    assert parse(render_run_complete(session, run.id))["Duration"] == expected


def test_a_run_that_finished_before_it_started_omits_the_duration(session):
    """A clock that went backwards is not a negative duration.

    NTP steps, and a message reading ``-4m 12s`` would be reported as a bug in
    the notification tier rather than in the clock. Omitting the line is the
    honest answer.
    """
    run = make_run(session, finished=STARTED - timedelta(seconds=30))
    assert "Duration" not in parse(render_run_complete(session, run.id))


def test_a_run_with_no_finish_time_falls_back_to_updated_at(session):
    """``finished_at`` is nullable, and a gate message must still say "since".

    ``finalize_run`` sets it; a run notified before then has only ``updated_at``,
    which is maintained by ``onupdate`` on every transition.
    """
    run = make_run(session, finished=None)
    run.updated_at = STARTED + timedelta(seconds=120)
    session.commit()
    assert parse(render_run_complete(session, run.id))["Duration"] == "2m 00s"


# ------------------------------------------------------------------ read-only


@pytest.fixture
def captured_sql_factory():
    return captured_sql


class captured_sql:  # noqa: N801 - used as a context manager, not a type
    """Records every SQL statement a block issues, for read-only assertions."""

    def __init__(self, session: Session) -> None:
        self.engine = session.get_bind()
        self.statements: list[str] = []

    def __enter__(self) -> list[str]:
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self.statements

    def __exit__(self, *exc) -> None:
        event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)


WRITES = ("insert", "update", "delete", "replace", "create", "drop", "alter")


@pytest.mark.parametrize("kind", list(Kind))
def test_no_renderer_writes_to_the_database(session, kind):
    """Rendering runs between a commit and a network call (D3).

    A write here would dirty the session and hold SQLite's single write lock
    across the send -- trap T0, the defect P3 lost a sign-off to. Asserted by
    counting statements rather than by reading the code, because the next
    renderer is the one that would break it.
    """
    run = make_run(session, state=RunState.AWAITING_SUBREDDIT_REVIEW)
    add_scrape_rows(session, run.id, [(1, 2)])
    add_jobs(session, run.id, [JobState.DONE])
    add_event(session, run.id, "net.degraded", from_provider="dc", to_provider="direct")
    add_event(session, run.id, "discovery.overflow", subreddit="SaaS", seen=100)

    with captured_sql(session) as sql:
        render(kind, session, run.id)

    offenders = [s for s in sql if s.strip().split(" ", 1)[0].lower() in WRITES]
    assert offenders == [], f"{kind} issued a write: {offenders}"
    assert sql, "the renderer issued no SQL at all -- it cannot be reading anything"
    assert not session.dirty and not session.new and not session.deleted


@pytest.mark.parametrize("kind", list(Kind))
def test_rendering_twice_produces_the_same_body(session, kind):
    """Deterministic: no timestamps of its own, no counters, no randomness."""
    run = make_run(session, state=RunState.AWAITING_OPTIONS)
    add_scrape_rows(session, run.id, [(2, 5)])
    assert render(kind, session, run.id) == render(kind, session, run.id)


# ---------------------------------------------------------------- boundaries


def test_renderers_import_no_http_client_and_no_model():
    """Stage 1's fences, re-run here so this file fails if either is weakened.

    ``tests/test_boundaries.py`` owns them; repeating the assertion at the point
    of use means a reader of *this* module sees the constraint, and a future
    edit that adds ``requests`` to a renderer breaks a test in the file it
    edited rather than only in a file it may not have opened.
    """
    from src.notify import renderers

    source = Path(renderers.__file__).read_text(encoding="utf-8")
    imports = [
        line.strip()
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "import" in line
    ]
    joined = " ".join(imports)
    for banned in ("requests", "httpx", "urllib", "http.client", "aiohttp", "subprocess"):
        assert banned not in joined, f"{banned} must not be imported by renderers.py"
    assert "src.ai" not in joined
    assert "hermes" not in joined


def test_the_golden_fixtures_all_exist_and_are_not_empty():
    """A fixture that vanished would make its comparison test pass vacuously."""
    expected = {
        "run_complete.md",
        "run_failed.md",
        "gate_reached.md",
        "proxy_pool_degraded.md",
        "discovery_overflow.md",
    }
    present = {p.name for p in FIXTURES.glob("*.md")}
    assert present == expected
    for name in expected:
        assert (FIXTURES / name).read_text(encoding="utf-8").strip(), f"{name} is empty"
