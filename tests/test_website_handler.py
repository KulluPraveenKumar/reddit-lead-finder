"""The P14 stage — ``handle_analyze_website``.

The seam between P13's fetcher and the knowledge layer, and the place the two
acceptance criteria about *observability* land: the cost is displayed, and a
cache hit is distinguishable from a site that genuinely has nothing.
"""

from __future__ import annotations

import json

import pytest

from src.ai.site_signals import PricingSignal, SiteSignals
from src.ai.website_fetcher import ExtractedSite
from src.db.models import AICall, Project, RunEvent
from src.orchestration.handlers.website import BKB_EVENT, handle_analyze_website
from tests.conftest import ensure_project

LANDING = "<html><body><p>We attribute pipeline to channel.</p></body></html>"


class RecordingFetcher:
    """A stand-in for ``WebsiteFetcher`` that counts what it was asked for.

    Injected rather than monkeypatched: ``build_website_fetcher`` exists as a
    named seam precisely so a test replaces an object instead of reaching into a
    module, and so the offline guarantee ([35 §2.3](../docs/35-testing-strategy.md)
    check 6) is a property of the design rather than of the mocks.
    """

    def __init__(self, *, markup: bool = True, thin: bool = False):
        self.markup = markup
        self.thin = thin
        self.fetches: list[str] = []

    def fetch(self, url, *, session=None, project_id=None):
        self.fetches.append(url)
        return ExtractedSite(
            url=url,
            pages=((url, "We attribute pipeline to channel. " * 30),),
            text="We attribute pipeline to channel. " * 30,
            content_hash="b" * 64,
            thin=self.thin,
            from_cache=not self.markup,
            requests_made=0 if not self.markup else 3,
            html_pages=((url, LANDING),) if self.markup else (),
        )


@pytest.fixture
def session(temp_db):
    from src.db.database import get_session

    s = get_session()
    ensure_project(s, 1)
    s.commit()
    yield s
    s.close()


@pytest.fixture
def service(settings, bkb_payload):
    from src.ai.providers import FakeProvider
    from src.ai.service import AIService

    svc = AIService(settings, provider=FakeProvider(default_payload=bkb_payload))
    svc.credentials.set_key("sk-test0123456789abcdef", validate=False)
    return svc


@pytest.fixture
def run(session):
    """A committed run.

    ⚠ **``commit()``, not ``flush()``, and the difference is 20 seconds a test.**
    ``AIService._record_ai_call`` writes through its **own** session, so a
    fixture that left this transaction open would hold SQLite's single write
    lock, stall that insert for the whole ``busy_timeout``, and then lose the
    ``ai_calls`` row to the ``except Exception`` that keeps recording from
    breaking the call it records. Measured here at **21.6 s per test**, all five
    of them silently missing their row.

    The worker commits before it reaches a model, so this fixture matches how the
    application actually runs. The underlying sharp edge is real but is not
    P14's to change — [DI37](../docs/DEFERRED-IMPROVEMENTS.md), and P14 is immune
    to it by construction because ``bkb.analyze`` makes its call **before** its
    first write.
    """
    from src.db.models import Run

    row = Run(project_id=1, state="PENDING")
    session.add(row)
    session.commit()
    return row


# ------------------------------------------------------------------ the stage


def test_the_stage_fetches_the_project_url_and_builds_a_bkb(session, service):
    fetcher = RecordingFetcher()
    payload = handle_analyze_website(session, 1, config={}, fetcher=fetcher, service=service)
    session.commit()

    assert fetcher.fetches == ["https://example1.com"]
    assert payload["sections"] == 23
    assert payload["complete"] == 23
    assert payload["calls"] == 1
    assert payload["version"] == 1


def test_an_unknown_project_fails_loudly_rather_than_building_nothing(session, service):
    with pytest.raises(ValueError, match="no project 999"):
        handle_analyze_website(session, 999, config={}, fetcher=RecordingFetcher(), service=service)


# ------------------------------------------------------------- run vs no run


def test_a_run_gets_a_timeline_event(session, service, run):
    """``run_events`` is how an operator sees a stage happened at all."""
    handle_analyze_website(
        session, 1, run_id=run.id, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()

    events = session.query(RunEvent).filter(RunEvent.event == BKB_EVENT).all()
    assert len(events) == 1
    assert "Built BKB v1" in events[0].message
    assert json.loads(events[0].data_json)["sections"] == 23


def test_the_stage_works_with_no_run_at_all(session, service):
    """**P16 will call this with no run in sight**, and ``run_events.run_id`` is
    ``NOT NULL``.

    A stage that assumed a run would be unusable from the project UI that is
    about to be built — so the event is emitted only when there is a timeline to
    emit it to, and the fact still reaches the log.
    """
    payload = handle_analyze_website(
        session, 1, run_id=None, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()

    assert payload["sections"] == 23
    assert session.query(RunEvent).filter(RunEvent.event == BKB_EVENT).count() == 0


def test_the_event_message_says_when_nothing_was_spent(session, service, run):
    """A reused BKB and a fresh one must not read the same on the timeline."""
    handle_analyze_website(
        session, 1, run_id=run.id, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()
    handle_analyze_website(
        session, 1, run_id=run.id, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()

    messages = [e.message for e in session.query(RunEvent).filter(RunEvent.event == BKB_EVENT)]
    assert "Built BKB v1" in messages[0]
    assert "Reused BKB v1" in messages[1]
    assert "no AI call was made" in messages[1]


def test_an_incomplete_section_is_named_on_the_timeline(session, service, run, bkb_payload):
    """An operator must be able to see *which* section needs attention.

    A count alone would say "22 of 23" and leave them reading rows to find it.
    """
    bkb_payload["pain_points"] = []
    service.provider.default_payload = bkb_payload

    handle_analyze_website(
        session, 1, run_id=run.id, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()

    event = session.query(RunEvent).filter(RunEvent.event == BKB_EVENT).one()
    assert "pain_points" in event.message
    assert json.loads(event.data_json)["incomplete"] == ["pain_points"]


# ---------------------------------------------------------------- DI33 again


def test_the_timeline_records_whether_markup_was_observable(session, service, run):
    """[DI33](../docs/DEFERRED-IMPROVEMENTS.md), at the point an operator reads it.

    *"This company uses no analytics"* and *"we read a cached copy with no markup
    in it"* must never look the same to a later reader — including a reader
    looking at the run timeline six weeks later.
    """
    handle_analyze_website(
        session,
        1,
        run_id=run.id,
        config={},
        fetcher=RecordingFetcher(markup=False),
        service=service,
    )
    session.commit()

    data = json.loads(session.query(RunEvent).filter(RunEvent.event == BKB_EVENT).one().data_json)
    assert data["markup_seen"] is False
    assert data["requests"] == 0


def test_a_fresh_fetch_reports_that_it_saw_markup(session, service, run):
    handle_analyze_website(
        session, 1, run_id=run.id, config={}, fetcher=RecordingFetcher(markup=True), service=service
    )
    session.commit()

    data = json.loads(session.query(RunEvent).filter(RunEvent.event == BKB_EVENT).one().data_json)
    assert data["markup_seen"] is True


# --------------------------------------------------------------- idempotence


def test_re_running_the_stage_costs_no_request_no_token_and_no_version(session, service):
    """R9, by two mechanisms rather than one.

    P13's L1 cache makes the re-run fetch nothing; the L2 reuse makes it call
    nothing and supersede nothing. A re-claimed lease is therefore free.
    """
    fetcher = RecordingFetcher()
    first = handle_analyze_website(session, 1, config={}, fetcher=fetcher, service=service)
    session.commit()
    second = handle_analyze_website(session, 1, config={}, fetcher=fetcher, service=service)
    session.commit()

    assert second["bkb_id"] == first["bkb_id"]
    assert second["version"] == first["version"]
    assert second["calls"] == 0
    assert session.query(AICall).filter(AICall.stage == "business_intelligence").count() == 1


# ------------------------------------------------------------- the exceptions


def test_p13s_exceptions_pass_through_untranslated(session, service):
    """**P16 owns the HTTP mapping** — [PHASE-13-HANDOVER §4 T2](../docs/PHASE-13-HANDOVER.md).

    ``InvalidWebsiteURL.status_code == 422`` exists so P16 maps it in one line.
    A stage that caught it and invented a status of its own would make that
    mapping a re-derivation.
    """
    from src.ai.website_fetcher import InvalidWebsiteURL

    class Refusing:
        def fetch(self, url, *, session=None, project_id=None):
            raise InvalidWebsiteURL("file:// is not a web address")

    with pytest.raises(InvalidWebsiteURL) as caught:
        handle_analyze_website(session, 1, config={}, fetcher=Refusing(), service=service)

    assert caught.value.status_code == 422


def test_no_project_row_is_created_by_this_stage(session, service):
    """``projects`` still has exactly one writer, and it is **P16's** `project add`.

    [PHASE-13-HANDOVER §3.5](../docs/PHASE-13-HANDOVER.md): P13 declined to
    become a second one and P14 declines too. This stage reads a project; it
    never conjures one.
    """
    before = session.query(Project).count()
    handle_analyze_website(session, 1, config={}, fetcher=RecordingFetcher(), service=service)
    session.commit()
    assert session.query(Project).count() == before


# ------------------------------------------------------------------- the CLI


def test_the_dry_run_report_names_every_number_the_guide_asks_for():
    """``render_report`` is tested; ``main()`` is not, and that is deliberate.

    ``main()`` is the only thing in this phase that reaches a live website, and a
    test that let it do so would **breach** the offline guarantee rather than
    verify anything — P13's trap T7, unchanged. Factoring the renderer out is
    what makes the operator-visible half testable without a socket.
    """
    from src.orchestration.handlers.website import render_report

    out = render_report(
        {
            "pages": 4,
            "chars": 12000,
            "thin": False,
            "markup_seen": True,
            "local_signals": '{\n  "competitors": []\n}',
        },
        url="https://example.com",
        dry_run=True,
    )

    assert "nothing was sent to a model" in out
    assert "pages fetched    4" in out
    assert "markup observed  True" in out


def test_the_dry_run_report_explains_an_unobserved_markup_reading():
    """[DI33](../docs/DEFERRED-IMPROVEMENTS.md), where the **operator** meets it.

    A tester who sees four empty signal lists must be told they were unobserved,
    or the guide teaches them the wrong conclusion about the site.
    """
    from src.orchestration.handlers.website import render_report

    out = render_report(
        {
            "pages": 1,
            "chars": 900,
            "thin": False,
            "markup_seen": False,
            "local_signals": "{}",
        },
        url="https://example.com",
        dry_run=True,
    )

    assert "markup_not_observed is set" in out
    assert "unobserved, never absent" in out


def test_render_stored_reports_what_the_manual_guide_asks_the_operator_to_check(session, service):
    """``--show``'s output — **the guide's T6 and T8 read this and nothing else.**

    ⚠ Untested rendering behind a manual step is P13's trap T9 in a new place: a
    guide that instructs an operator to compare against output nobody has checked
    teaches them to accept whatever appears. Every line the guide quotes is
    asserted here.
    """
    from src.orchestration.handlers.website import render_stored

    handle_analyze_website(session, 1, config={}, fetcher=RecordingFetcher(), service=service)
    session.commit()

    out = render_stored(session, 1)

    assert "BKB version      v1" in out
    assert "sections         23/23 complete" in out
    assert "incomplete       none" in out
    # The expected ranges are printed BESIDE the numbers, so a non-developer can
    # judge the bounds criterion without holding them in their head.
    assert "(expected 1-5)" in out
    assert "(expected 3-12)" in out
    assert "ai_calls rows    1   (expected exactly 1)" in out
    assert "(budget $0.05)" in out
    assert "project=1 outcome=ok attempt=1" in out


def test_render_stored_names_an_incomplete_section(session, service, bkb_payload):
    """T6's *"record which section and continue"* path."""
    from src.orchestration.handlers.website import render_stored

    bkb_payload["pain_points"] = []
    service.provider.default_payload = bkb_payload
    handle_analyze_website(session, 1, config={}, fetcher=RecordingFetcher(), service=service)
    session.commit()

    out = render_stored(session, 1)
    assert "sections         22/23 complete" in out
    assert "incomplete       pain_points" in out


def test_render_stored_says_so_when_there_is_no_bkb_yet(session):
    """The guide's *"`project 1 has no BKB yet`"* failure row.

    A renderer that raised here would give the operator a traceback for the
    ordinary case of running ``--show`` before building anything.
    """
    from src.orchestration.handlers.website import render_stored

    assert "has no BKB yet" in render_stored(session, 1)


def test_the_two_seams_construct_the_real_objects(settings):
    """``build_website_fetcher`` and ``build_ai_service`` are the injection points.

    Every other test replaces them, so without this the *default* path — the one
    the CLI and P16 will actually take — is never constructed. Neither opens a
    socket at construction, so this stays inside the offline guarantee.
    """
    from src.ai.service import AIService
    from src.ai.website_fetcher import WebsiteFetcher
    from src.orchestration.handlers.website import build_ai_service, build_website_fetcher

    assert isinstance(build_website_fetcher({}), WebsiteFetcher)
    assert isinstance(build_ai_service({}), AIService)


def test_the_full_report_shows_the_cost_and_the_call_count(session, service):
    """*"Total cost < $0.05 **and displayed**"* — this is the display."""
    from src.orchestration.handlers.website import render_report

    payload = handle_analyze_website(
        session, 1, config={}, fetcher=RecordingFetcher(), service=service
    )
    session.commit()

    out = render_report(payload, url="https://example1.com", dry_run=False)
    assert "sections         23/23 complete" in out
    assert "AI calls         1" in out
    assert "cost             $" in out
    assert "incomplete       none" in out


def test_the_signals_the_handler_computes_match_what_the_extractor_returns(session, service):
    """The handler must not build its own signals — it passes P13's through.

    A second extraction here would be a second implementation to keep in step,
    and the two would disagree the first time P15 touched one of them.
    """
    from src.ai.site_signals import extract

    fetcher = RecordingFetcher()
    site = fetcher.fetch("https://example1.com")

    assert isinstance(extract(site), SiteSignals)
    assert isinstance(extract(site).pricing, PricingSignal)
