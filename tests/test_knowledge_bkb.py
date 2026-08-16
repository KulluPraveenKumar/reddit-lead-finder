"""``analyze_business`` end to end — the criteria that are about the CALL.

[34 §P14](../docs/34-implementation-plan.md)'s Acceptance row, in order:

* **Exactly one** ``ai_calls`` row with ``stage='business_intelligence'``
* all 23 sections persist
* total cost **< $0.05** and displayed
* re-analysis of an unchanged fingerprint makes **zero** calls
* a forced schema failure in one section leaves the other 22 persisted
* 1–5 personas, 3–12 pains, 3–12 signals
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.ai.site_signals import PricingSignal, SiteSignals
from src.db.models import AICall
from src.db.repositories.knowledge import KnowledgeRepository
from src.knowledge.bkb import COST_BUDGET_USD, MARKUP_ABSENT_KEY, analyze, build_local_signals
from tests.conftest import ensure_project

STAGE = "business_intelligence"


@dataclass
class FakeSite:
    """Stands in for ``ExtractedSite``, which P13 owns and this phase only reads."""

    url: str = "https://example.com"
    text: str = "We help B2B SaaS teams attribute pipeline to channel. " * 20
    content_hash: str = "a" * 64
    thin: bool = False
    from_cache: bool = False
    requests_made: int = 3


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
    """An ``AIService`` whose provider always returns the 23-section fixture."""
    from src.ai.providers import FakeProvider
    from src.ai.service import AIService

    provider = FakeProvider(default_payload=bkb_payload)
    svc = AIService(settings, provider=provider)
    svc.credentials.set_key("sk-test0123456789abcdef", validate=False)
    return svc


def _signals(markup_seen=True):
    return SiteSignals(
        competitors=("Segment",),
        pricing=PricingSignal(currencies=("USD",), amounts=("$99",)),
        tech_markers=("HubSpot",) if markup_seen else (),
        structured_data=({"@type": "Product"},) if markup_seen else (),
        social_links=(("twitter", "https://x.com/example"),) if markup_seen else (),
        nav_taxonomy=("Pricing",) if markup_seen else (),
        markup_seen=markup_seen,
    )


def _run(session, service, site=None, signals=None, config=None):
    return analyze(
        session,
        project_id=1,
        site=site or FakeSite(),
        signals=signals if signals is not None else _signals(),
        service=service,
        config=config,
    )


def _calls(session):
    return session.query(AICall).filter(AICall.stage == STAGE).all()


# ------------------------------------------------------- ONE call, 23 sections


def test_exactly_one_ai_call_row_is_written_per_analysis(session, service):
    """**The headline acceptance criterion.**

    It is also the one a strict envelope would have broken silently: a validation
    failure sends the response down ``_execute``'s repair ladder, and each
    attempt writes its own row. See ``BusinessKnowledgeOut``'s docstring and
    [P14-DECISION-ANALYSIS §D4](../docs/P14-DECISION-ANALYSIS.md).
    """
    _run(session, service)
    session.commit()

    rows = _calls(session)
    assert len(rows) == 1
    assert rows[0].outcome == "ok"
    assert rows[0].attempt == 1
    assert len(service.provider.calls) == 1, "one provider call, not one row per attempt"


def test_one_call_still_holds_when_a_section_fails_validation(session, service, bkb_payload):
    """The two criteria that pull against each other, asserted together.

    A malformed persona slug must cost **that section's status** and nothing
    else — not 22 sections, and not two extra billed attempts.
    """
    bkb_payload["buyer_personas"][0]["slug"] = "Not A Slug"
    service.provider.default_payload = bkb_payload

    result = _run(session, service)
    session.commit()

    assert len(_calls(session)) == 1
    assert result.incomplete == ("buyer_personas",)
    assert result.complete_count == 22

    rows = KnowledgeRepository(session).sections_for(result.bkb_id)
    assert len(rows) == 23, "all 23 rows persist; one of them says it is incomplete"


def test_all_twenty_three_sections_persist(session, service):
    result = _run(session, service)
    session.commit()

    assert len(KnowledgeRepository(session).sections_for(result.bkb_id)) == 23
    assert result.status == "complete"


def test_the_call_is_attributed_to_the_project(session, service):
    """``ai_calls.project_id`` — the FK `0007` closed, used for the first time.

    It is what makes *"this project's BKB cost $0.0x"* a query rather than a
    time window.
    """
    _run(session, service)
    session.commit()
    assert _calls(session)[0].project_id == 1


def test_the_typed_tables_are_populated_within_their_stated_bounds(session, service):
    """*"1–5 personas, 3–12 pains, 3–12 signals"*, at the end of the pipeline."""
    result = _run(session, service)
    session.commit()
    repo = KnowledgeRepository(session)

    assert 1 <= len(repo.personas_for(result.bkb_id)) <= 5
    assert 3 <= len(repo.pain_points_for(result.bkb_id)) <= 12
    assert 3 <= len(repo.intent_signals_for(result.bkb_id)) <= 12


# ------------------------------------------------------------------- the cost


def test_the_cost_is_measured_and_reported(session, service):
    """*"total cost < $0.05 **and displayed**"* — the second half needs a number.

    ``to_dict()`` is what the handler puts on the timeline and what P16's cost
    chip renders, so the figure has to survive the whole way out.
    """
    result = _run(session, service)

    assert result.cost_usd >= 0.0
    assert result.cost_usd < COST_BUDGET_USD
    assert result.to_dict()["cost_usd"] == round(result.cost_usd, 6)
    assert result.to_dict()["calls"] == 1


def test_going_over_budget_is_loud_and_not_fatal(session, service, caplog, monkeypatch):
    """The budget guard in ``src/ai/cost.py`` owns *stopping* spend; this measures.

    A second gate that could refuse an already-paid-for answer would throw away
    knowledge the operator was billed for.
    """
    import src.knowledge.bkb as bkb_module

    monkeypatch.setattr(bkb_module, "COST_BUDGET_USD", -1.0)
    with caplog.at_level("WARNING"):
        result = _run(session, service)

    assert result.bkb_id is not None, "the analysis still completed"
    assert any("over the" in r.message for r in caplog.records)


# ------------------------------------------------------------ the L2 reuse


def test_a_second_analysis_of_an_unchanged_site_makes_zero_calls(session, service):
    """**"Re-analysis of an unchanged fingerprint makes zero calls."**

    The L2 profile cache is ``ai_cache``, keyed on the content hash of the site
    text plus the stage and prompt version — so the second pass never reaches the
    provider and never writes a row.
    """
    first = _run(session, service)
    session.commit()
    assert first.calls_made == 1

    second = _run(session, service)
    session.commit()

    assert second.calls_made == 0
    assert second.reused is True
    assert len(_calls(session)) == 1, "no second ai_calls row"
    assert len(service.provider.calls) == 1, "the provider was not reached a second time"


def test_a_reused_analysis_does_not_burn_a_bkb_version(session, service):
    """Zero calls **and** zero churn.

    Superseding on a cache hit would burn a version number and re-point every
    typed row for an analysis that learned nothing new — and "BKB v7" would stop
    meaning "the seventh thing we thought".
    """
    first = _run(session, service)
    session.commit()
    second = _run(session, service)
    session.commit()

    assert second.bkb_id == first.bkb_id
    assert second.version == first.version == 1


def test_changed_site_text_produces_a_new_version_and_a_new_call(session, service):
    """The cache must not be stickier than the fingerprint it is keyed on."""
    _run(session, service)
    session.commit()

    changed = FakeSite(text="An entirely different business, selling something else. " * 20)
    second = _run(session, service, site=changed)
    session.commit()

    assert second.calls_made == 1
    assert second.reused is False
    assert second.version == 2
    assert len(_calls(session)) == 2


def test_a_reuse_is_refused_when_the_prompt_version_moved(session, service, monkeypatch):
    """AD-8: a prompt change is a **behaviour** change.

    A BKB built under v1 must not be served for a v2 request, even though the
    site is byte-identical — which is why the version is compared rather than
    assumed.
    """
    first = _run(session, service)
    session.commit()

    repo = KnowledgeRepository(session)
    repo.current(1).prompt_version = 99
    session.commit()

    second = _run(session, service)
    session.commit()
    assert second.reused is False, "a stale prompt version must not be reused"
    assert second.version == first.version + 1


# --------------------------------------------------------------- DI33 / signals


def test_observed_markup_is_passed_through_as_fact(session, service):
    payload = build_local_signals(_signals(markup_seen=True))

    assert payload["competitors"] == ["Segment"]
    assert payload["tech_markers"] == ["HubSpot"]
    assert payload["nav_taxonomy"] == ["Pricing"]
    assert MARKUP_ABSENT_KEY not in payload


def test_unobserved_markup_is_omitted_and_flagged_never_reported_as_empty():
    """**[DI33](../docs/DEFERRED-IMPROVEMENTS.md), closed.**

    On an L1 cache hit ``website_snapshots`` has stored text and no markup, so
    the four markup-derived signals are empty **because nothing was parsed**.
    Emitting them as four empty lists reads identically to *"this site has none
    of these"*, and a model told that records *"this company uses no analytics"*
    as a fact about the business.

    So they are **omitted entirely** and replaced with one flag. The prompt
    carries the matching clause: an omitted signal is unobserved, never absent.
    """
    payload = build_local_signals(_signals(markup_seen=False))

    assert payload[MARKUP_ABSENT_KEY] is True
    for key in ("tech_markers", "structured_data", "social_links", "nav_taxonomy"):
        assert key not in payload, f"{key} must be absent, not empty"


def test_the_two_text_derived_signals_still_arrive_on_a_cache_hit():
    """The degradation is partial, and saying so precisely is the point.

    ``competitors`` and ``pricing`` read text, so a reuse can still compute them.
    Dropping all six would lose signal that is genuinely available.
    """
    payload = build_local_signals(_signals(markup_seen=False))

    assert payload["competitors"] == ["Segment"]
    assert payload["pricing"]["amounts"] == ["$99"]


def test_the_flag_reaches_the_prompt_the_model_actually_sees(session, service):
    """The flag is worthless if it stops at the boundary.

    Asserting on the rendered request is what makes this a test of the
    *behaviour* rather than of the dictionary.
    """
    _run(session, service, signals=_signals(markup_seen=False))

    sent = service.provider.calls[0].messages[-1].content
    assert MARKUP_ABSENT_KEY in sent
    assert "tech_markers" not in sent


def test_the_prompt_tells_the_model_what_an_omitted_signal_means():
    """The flag and the instruction ship together, or the flag means nothing."""
    from src.ai.prompts import PromptManager

    raw = PromptManager().load(STAGE, 1).raw
    assert MARKUP_ABSENT_KEY in raw
    assert "UNOBSERVED, never ABSENT" in raw


# ------------------------------------------------------------- config/rollback


def test_deleting_the_config_block_reproduces_the_default_budget(settings, service):
    """The rollback property every settings block in this repository has.

    ⚠ Asserted **here**, at the AI layer, because that is where the key is read —
    ``src/knowledge/`` may not know what a provider's wire knobs are and
    ``test_no_wire_format_details_outside_ai`` enforces it.
    """
    from src.ai.service import MAX_OUTPUT_CEILING

    assert settings.get("ai.max_tokens.business_intelligence", 12000) == 12000
    assert MAX_OUTPUT_CEILING > 12000, "the escalation ceiling must sit above the default"


def test_the_shipped_config_file_carries_the_key_the_phase_declares():
    """[34 §P14](../docs/34-implementation-plan.md)'s Config row, in the file."""
    import yaml

    from tests.conftest import PROJECT_ROOT

    config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert config["ai"]["max_tokens"]["business_intelligence"] == 12000


def test_the_prompt_has_all_six_mandatory_sections():
    """[34 §P14](../docs/34-implementation-plan.md) task 2, *"all six … incl. `# JSON Shape`"*.

    ``PromptManager.validate`` enforces four across every stage. The other two
    are this template's own, so they are asserted here rather than by widening a
    rule the other three prompts were not written against.
    """
    from src.ai.prompts import PromptManager

    manager = PromptManager()
    assert manager.validate(STAGE, 1) == []

    raw = manager.load(STAGE, 1).raw
    for section in ("# Role", "# Task", "# Rules", "# JSON Shape", "# Constraints", "# User"):
        assert section in raw, section


def test_every_section_key_appears_in_the_prompts_json_shape():
    """A section the prompt never asks for is a section that arrives empty.

    The schema and the template are two halves of one contract, and nothing else
    would notice them drifting apart — the response would simply validate, with a
    silent ``incomplete`` on a section nobody requested.
    """
    from src.ai.prompts import PromptManager
    from src.db.models import BKB_SECTION_KEYS

    raw = PromptManager().load(STAGE, 1).raw
    missing = [key for key in BKB_SECTION_KEYS if f'"{key}"' not in raw]
    assert missing == []


# ---------------------------------------------------------------- idempotence


def test_running_the_same_analysis_twice_writes_no_duplicate_rows(session, service):
    """R9, at the stage level rather than at the repository's.

    A re-claimed lease costs neither a request nor a token nor a BKB version.
    """
    _run(session, service)
    session.commit()
    before = _counts(session)

    _run(session, service)
    session.commit()

    assert _counts(session) == before


def _counts(session):
    from src.db.models import BKB, BKBSection, IntentSignal, PainPoint, Persona

    return tuple(
        session.query(entity).count()
        for entity in (BKB, BKBSection, Persona, PainPoint, IntentSignal, AICall)
    )


def test_the_model_call_happens_before_the_first_write(session, service):
    """The ordering that makes this stage immune to [DI37](../docs/DEFERRED-IMPROVEMENTS.md).

    ``AIService._record_ai_call`` writes through its **own** session, so a caller
    holding an open write transaction stalls that insert for the whole
    ``busy_timeout`` and then loses the row — silently, because recording is not
    permitted to break the call it records. Found in P14's own handler tests,
    measured at 21.6 s per affected test.

    ``analyze`` is safe because it calls **first** and writes **second**. This
    pins that ordering, so a later refactor that hoisted ``create_bkb`` above the
    call would fail here rather than start losing cost data.
    """
    from src.db.models import BKB

    seen = {}

    original = service.provider.chat

    def watching(request):
        seen["bkb_rows_at_call_time"] = session.query(BKB).count()
        return original(request)

    service.provider.chat = watching
    _run(session, service)
    session.commit()

    assert seen["bkb_rows_at_call_time"] == 0, (
        "analyze() must not have written anything before it calls the model"
    )
    assert session.query(BKB).count() == 1


def test_the_result_payload_is_json_serialisable(session, service):
    """It lands in ``run_events.data_json``, which is ``json.dumps``'d."""
    result = _run(session, service)
    assert json.loads(json.dumps(result.to_dict()))["sections"] == 23
