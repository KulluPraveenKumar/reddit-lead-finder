"""The stage-3 holdout on the live discovery path, plus DI24 and DI25.

freeze R11 — *"a 2% holdout applies to the admission gate AND to metadata
triage"* — and docs/34 §P11 task 6. This is the first mechanism in the project
that can measure the false-positive rate of a gate deciding on titles alone.

The three land together on purpose. DI24 is what makes the keyword component
non-zero; the holdout is what measures the gate; and DI25 is the defect the
holdout was built to catch, fixed **after** it, so the evidence survived.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy.orm import Session

from src.db.models import Job, Lead, Prescore, Run, RunEvent
from src.orchestration.handlers.discover import DISCOVER_JOB, _triage_config, handle_discover
from src.scoring import SOURCE_HOLDOUT_AUDIT, SOURCE_SCRAPE

T0 = datetime.datetime(2026, 8, 8, 12, 0, 0)

CONFIG = {
    "keywords": {
        "high_intent": ["looking for", "any recommendations", "what tool do you use"],
        "medium_intent": ["how do i", "struggling with", "need help with"],
    },
    "pipeline": {"prescore_enabled": True, "prescore_admission_floor": 35},
    "gate": {"metadata_holdout_rate": 1.0},  # audit everything, so the test is exact
}

STRONG_BODY = (
    "We are a five person team and our spreadsheets are falling apart. I have been "
    "struggling with keeping track of who spoke to which customer and I need help with "
    "picking something that does not cost a fortune every single month to operate. "
) * 2


def feed_post(pid, title, body=STRONG_BODY, minutes=30):
    return {
        "id": pid,
        "title": title,
        "url": f"https://www.reddit.com/r/SaaS/comments/{pid}/",
        "author": "example_user_1",
        "subreddit": "SaaS",
        "score": 40,
        "num_comments": 12,
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


def make_job(session, run_id):
    job = Job(
        run_id=run_id,
        job_type=DISCOVER_JOB,
        payload_json=json.dumps({"subreddits": ["SaaS"], "channel": "listing"}),
        state="running",
        available_at=T0,
        created_at=T0,
    )
    session.add(job)
    session.commit()
    return job


@pytest.fixture
def feed(monkeypatch):
    posts: list[dict] = []

    class FakeClient:
        def fetch_feed(self, subreddits, *, sort="new", limit=None, query=None):
            return list(posts)

        def get_new_posts(self, subreddit, limit=100):
            return []

    from src.orchestration.handlers import discover

    monkeypatch.setattr(discover, "_build_client", lambda config: FakeClient())
    monkeypatch.setattr(discover, "_load_config", lambda: CONFIG)
    return posts


# --------------------------------------------------------------------- DI24


def test_the_keywords_block_is_read_as_a_mapping_not_as_its_keys():
    """DI24, fixed.

    `_triage_config` read `config["keywords"]` as a sequence, and iterating a
    mapping yields its KEYS — so `TriageConfig.keywords` was
    `('high_intent', 'medium_intent')` and triage matched a title only if it
    literally contained the string `high_intent`. Measured against the shipped
    config on 2026-08-13; the provisional score has been 0.0 on every real post
    ever triaged.
    """
    cfg = _triage_config(CONFIG)
    assert "high_intent" not in cfg.keywords
    assert "looking for" in cfg.keywords
    assert set(cfg.keywords) == {
        "looking for",
        "any recommendations",
        "what tool do you use",
        "how do i",
        "struggling with",
        "need help with",
    }


def test_the_provisional_triage_score_is_no_longer_always_zero():
    """The consequence DI24 names: "nothing downstream noticed because nothing
    consumed that score. P11 is the first consumer"."""
    from src.discovery.triage import triage

    cfg = _triage_config(CONFIG)
    result = triage({"title": "Looking for a CRM - any recommendations?"}, cfg)
    assert result.components["keyword_hits"]
    assert result.total > 0.0


def test_the_defective_form_would_have_scored_zero():
    """The test that would have failed against the old code, kept as the
    regression rather than as a claim about it."""
    from src.discovery.triage import TriageConfig, triage

    defective = TriageConfig(keywords=tuple(CONFIG["keywords"]))  # iterates the KEYS
    result = triage({"title": "Looking for a CRM - any recommendations?"}, defective)
    assert result.components["keyword_hits"] == []
    assert result.total == 0.0


def test_a_malformed_keywords_block_does_not_raise():
    """A typo in an optional block must not stop discovery."""
    assert _triage_config({"keywords": ["oops", "a list"]}).keywords == ()
    assert _triage_config({}).keywords == ()
    assert _triage_config({"keywords": None}).keywords == ()


# --------------------------------------------------------------------- DI25


def test_the_bare_hiring_pattern_no_longer_discards_a_textbook_lead():
    """DI25, fixed — and fixed **after** the holdout that measures it.

    "Our hiring process is broken and I need a tool to fix it" is a textbook lead
    for this product, and the bare `\\bhiring\\b` alternative had been discarding
    it live since P6. The loss was invisible by construction.
    """
    from src.discovery.triage import triage

    cfg = _triage_config(CONFIG)
    result = triage({"title": "Our hiring process is broken and I need a tool to fix it"}, cfg)
    assert result.admitted, "DI25's own example must now survive triage"


@pytest.mark.parametrize(
    "title",
    [
        "[HIRING] Senior backend engineer, remote",
        "[For Hire] Freelance designer available",
        "We're hiring a growth lead",
        "Now hiring: two backend roles",
        "Job posting: senior SRE",
    ],
)
def test_real_hiring_posts_are_still_rejected(title):
    """The recall that matters is kept. Fixing a false positive by deleting the
    rule would trade one silent loss for a loud one."""
    from src.discovery.triage import triage

    assert triage({"title": title}, _triage_config(CONFIG)).reason == "hiring"


def test_triage_and_the_rules_engine_now_agree_on_hiring():
    """Half of DI23's divergence closes here: the two modules deliberately
    disagreed on this one pattern, and now they do not."""
    from src.discovery.triage import STRUCTURAL_PATTERNS as TRIAGE_PATTERNS
    from src.rules.structural import STRUCTURAL_PATTERNS as RULES_PATTERNS

    triage_hiring = next(p for p, name in TRIAGE_PATTERNS if name == "hiring")
    rules_hiring = next(p for p, name in RULES_PATTERNS if name == "hiring")
    assert triage_hiring == rules_hiring


# ----------------------------------------------------------- the audit


def test_sampled_rejects_are_stored_as_labellable_leads(session, run, feed):
    """docs/06c §6.1, and operator decision **D3**.

    "Audited items are persisted as real, labellable leads, flagged
    `leads.source='holdout_audit'`. This is not a convenience — it is what stops
    the learning loop degenerating." Storing them is also what makes the
    `prescores` row possible at all: the table's CHECK requires a stored row to
    point at, which is the wall P6 hit and passed to this phase.
    """
    feed.extend(
        [
            feed_post("t3_keep", "Looking for a CRM - any recommendations?"),
            feed_post("t3_bait", "Upvote this if you agree with karma farming"),
        ]
    )

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    audit = session.query(Lead).filter(Lead.source == SOURCE_HOLDOUT_AUDIT).all()
    assert len(audit) == 1
    assert audit[0].reddit_id == "t3_bait"
    assert result["holdout"]["sampled"] == 1
    assert result["holdout"]["stored_as_leads"] == 1


def test_an_audited_lead_carries_a_holdout_flagged_prescore_row(session, run, feed):
    """`holdout_sampled` is the column that separates the audit population — and
    the one P19's yield curve must NOT filter on (docs/06c §6.1)."""
    feed.append(feed_post("t3_bait", "Weekly megathread for questions"))

    handle_discover(session, make_job(session, run.id))
    session.commit()

    row = session.query(Prescore).filter(Prescore.holdout_sampled.is_(True)).one()
    assert row.stage == "full"
    assert json.loads(row.components_json)["_triage"] == "megathread"


def test_the_miss_rate_is_published_on_the_timeline(session, run, feed):
    """docs/34 §P11's bold criterion: "metadata-triage miss rate published"."""
    feed.append(feed_post("t3_bait", "Weekly megathread for questions"))

    handle_discover(session, make_job(session, run.id))
    session.commit()

    event = session.query(RunEvent).filter(RunEvent.event == "discovery.poll.done").one()
    payload = json.loads(event.data_json)
    assert "holdout" in payload
    assert payload["holdout"]["measured"] is True
    assert "gate_miss_rate" in payload["holdout"]


def test_the_audit_catches_di25s_own_example_as_a_miss(session, run, feed, monkeypatch):
    """**The measurement that justified fixing DI25**, reproduced against the
    pre-fix pattern.

    With the bare `\\bhiring\\b` restored, the audit re-scores the reject with its
    body, the full-stage gate ADMITS it, and the miss is counted with `hiring` as
    the worst reason — which is exactly the signal an operator needed and never
    had. This is the test that shows the holdout would have found the defect.
    """
    import importlib
    import re

    # `from src.discovery import triage` binds the re-exported FUNCTION, not the
    # module, so the module is fetched by name.
    triage_module = importlib.import_module("src.discovery.triage")

    broken = tuple(
        (re.compile(r"\bhiring\b", re.IGNORECASE), "hiring") if name == "hiring" else (p, name)
        for p, name in triage_module._COMPILED
    )
    monkeypatch.setattr(triage_module, "_COMPILED", broken)

    feed.append(
        feed_post(
            "t3_lead",
            "Our hiring process is broken and I need a tool to fix it",
            body="I am looking for any recommendations. " + STRONG_BODY,
        )
    )
    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    holdout = result["holdout"]
    assert holdout["sampled"] == 1
    assert holdout["would_have_qualified"] == 1
    assert holdout["gate_miss_rate"] == 1.0
    assert holdout["worst_reason"] == "hiring"


def test_provably_correct_rejections_are_not_audited(session, run, feed):
    """docs/06c §6: auditing them would waste effort proving arithmetic works.
    `no_title` is P11's addition — it would bias the rate downwards."""
    feed.append(feed_post("t3_none", ""))

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["rejected_by_reason"] == {"no_title": 1}
    assert result["holdout"]["sampled"] == 0
    assert session.query(Lead).filter(Lead.source == SOURCE_HOLDOUT_AUDIT).count() == 0


def test_admitted_posts_are_never_audited(session, run, feed):
    """The audit samples REJECTS. Sampling an admission would measure nothing and
    would store a duplicate of a post the pipeline already keeps."""
    feed.append(feed_post("t3_keep", "Looking for a CRM - any recommendations?"))

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["admitted"] == 1
    assert result["holdout"]["sampled"] == 0
    assert session.query(Lead).count() == 0


def test_a_zero_rate_switches_the_audit_off(session, run, feed, monkeypatch):
    """The documented rollback, and its cost: the gate keeps filtering and stops
    being measurable, which AD-10b names as worse than no filter at all."""
    from src.orchestration.handlers import discover

    monkeypatch.setattr(
        discover, "_load_config", lambda: {**CONFIG, "gate": {"metadata_holdout_rate": 0.0}}
    )
    feed.append(feed_post("t3_bait", "Weekly megathread for questions"))

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["holdout"]["sampled"] == 0
    assert session.query(Lead).count() == 0


def test_an_already_collected_reject_counts_but_is_not_stored_twice(session, run, feed):
    """Dropping it would silently shrink the sample toward whichever posts
    happened to be new, which is not the 2% the rate claims."""
    session.add(
        Lead(
            reddit_id="t3_bait",
            subreddit="SaaS",
            author="example_user_1",
            title="Weekly megathread for questions",
            url="https://www.reddit.com/r/SaaS/comments/t3_bait/",
            created_utc=T0,
            source=SOURCE_SCRAPE,
        )
    )
    session.commit()
    feed.append(feed_post("t3_bait", "Weekly megathread for questions"))

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    # Already known, so the diff drops it before triage; nothing is stored twice.
    assert session.query(Lead).filter(Lead.reddit_id == "t3_bait").count() == 1
    assert session.query(Lead).filter(Lead.source == SOURCE_HOLDOUT_AUDIT).count() == 0
    assert result["holdout"]["sampled"] == 0


def test_a_failing_audit_does_not_fail_the_poll(session, run, feed, monkeypatch):
    """An audit exists to measure quality; a measurement failure that discarded
    the thing being measured would be worse than no measurement."""
    from src.orchestration.handlers import discover

    monkeypatch.setattr(
        discover, "_run_holdout", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    feed.append(feed_post("t3_keep", "Looking for a CRM - any recommendations?"))

    result = handle_discover(session, make_job(session, run.id))
    session.commit()

    assert result["holdout"] == {"error": "boom"}
    assert result["admitted"] == 1


def test_an_audited_lead_does_not_claim_an_intent_score_it_did_not_earn(session, run, feed):
    """It is stored BECAUSE it was rejected. Writing a keyword score that implies
    it passed would make the two populations indistinguishable in the one column
    an operator sorts by."""
    feed.append(feed_post("t3_bait", "Weekly megathread for questions"))

    handle_discover(session, make_job(session, run.id))
    session.commit()

    lead = session.query(Lead).filter(Lead.source == SOURCE_HOLDOUT_AUDIT).one()
    assert lead.intent_score == 0.0
    assert lead.matched_keywords == ""
