"""Shared fixtures. Every test runs offline against a temporary database.

No test in this suite makes a network call. ``FakeProvider`` covers the whole
AI surface; anything requiring a real key is marked ``live`` and deselected by
default.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Set before any src import so the credential store has a stable data key and
# tests never depend on the developer's real .env.
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-the-suite-only-0123456789")


class NetworkCallBlocked(RuntimeError):
    """A test tried to open a socket. See ``block_network`` below."""


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Machine-enforce the offline guarantee — ``docs/35`` §2.3 check 6.

    Until P2 this was a convention: the suite made no network calls because
    nobody wrote one. A convention is not a guarantee, and the failure it
    permits is silent — a test that quietly reaches Reddit passes on the
    developer's machine and fails in CI for reasons nobody connects to it.

    ``connect`` is patched rather than the ``socket`` constructor: ``responses``,
    ``requests`` and ``urllib3`` all *build* sockets and sessions while doing
    nothing over the wire, and a fixture that broke object construction would be
    telling correct tests they are wrong.

    Loopback stays open. It carries no traffic off the machine, and closing it
    would break any future test that binds a local port.
    """
    import socket

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guard(original):
        def wrapper(self, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else address
            if isinstance(host, str) and host in _LOOPBACK:
                return original(self, address, *args, **kwargs)
            raise NetworkCallBlocked(
                f"the test suite runs offline; a socket to {address!r} was blocked. "
                "Use a fixture or a fake instead of a live call."
            )

        return wrapper

    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A migrated, empty database, isolated per test."""
    from src.db import database

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    monkeypatch.setenv("ALEMBIC_DB_URL", f"sqlite:///{db_file}")

    database.init_db(db_file)
    yield db_file

    if database.ENGINE is not None:
        database.ENGINE.dispose()


@pytest.fixture
def live_db_copy(tmp_path, monkeypatch):
    """A copy of the real database, for regression tests against real data."""
    source = PROJECT_ROOT / "data" / "leads.db"
    if not source.exists():
        pytest.skip("no live database present")

    from src.db import database

    db_file = tmp_path / "leads.db"
    shutil.copy(source, db_file)
    monkeypatch.setattr(database, "DB_PATH", db_file)
    monkeypatch.setenv("ALEMBIC_DB_URL", f"sqlite:///{db_file}")

    database.init_db(db_file)
    yield db_file

    if database.ENGINE is not None:
        database.ENGINE.dispose()


def ensure_project(session, project_id: int):
    """A real ``projects`` row with this id, created once per id.

    ⚠️ **Needed from `0007` (P12) onward.** ``runs.project_id``,
    ``leads.project_id``, ``comments.project_id``, ``dedup_groups.project_id``
    and ``minhash_bands.project_id`` were **bare columns** until `0007` closed
    their foreign keys (M8), so a test could attach a run to project 4 on a
    database that had no projects table at all. It cannot now, and that is the
    constraint working: `PRAGMA foreign_keys=ON` is set on every connection, so
    an id that names no row is rejected.

    The fix is a real parent row, not a relaxed constraint — a test that needs
    referential integrity switched off is testing a database the application
    never runs against.
    """
    from src.db.models import Project

    existing = session.get(Project, project_id)
    if existing is not None:
        return existing

    project = Project(
        id=project_id,
        name=f"test-project-{project_id}",
        website_url=f"https://example{project_id}.com",
        normalized_url=f"https://example{project_id}.com",
    )
    session.add(project)
    session.flush()
    return project


@pytest.fixture
def settings(temp_db):
    from src.settings import get_settings, reset_settings

    reset_settings()
    resolver = get_settings({})
    yield resolver
    reset_settings()


@pytest.fixture
def fake_provider():
    from src.ai.providers import FakeProvider

    return FakeProvider(default_payload={"ok": True})


@pytest.fixture
def ai_service(settings, fake_provider):
    from src.ai.service import AIService

    service = AIService(settings, provider=fake_provider)
    service.credentials.set_key("sk-test0123456789abcdef", validate=False)
    return service


@pytest.fixture
def enrichment_payload():
    return {
        "results": [
            {
                "id": "item-1",
                "is_lead": True,
                "summary": "Looking to replace their attribution tool",
                "buying_intent": "evaluating",
                "urgency": "high",
                "icp_match": "strong",
                "sentiment": "frustrated",
                "opportunity_score": 8,
                "recommended_priority": "high",
                "matched_pain_slugs": ["attribution-gap"],
                "matched_signal_slugs": ["evaluating-alternatives"],
                "competitor_mentions": ["segment"],
                "persona_slug": "growth-lead",
                "evidence_quote": "we are actively looking to replace Segment",
                "why_relevant": "Named incumbent plus a stated timeline.",
                "disqualifiers": [],
            }
        ]
    }


@pytest.fixture
def bkb_payload():
    """A well-formed 23-section ``analyze_business`` response.

    The counterpart to ``enrichment_payload``, and the input every P14 test
    starts from. It is deliberately **valid in every section and inside every
    bound** — 1–3 ICPs, 1–5 personas, 3–12 pains, 3–12 signals — so that a test
    which breaks one section is testing exactly the break it made. A fixture that
    started out slightly wrong would make every isolation test ambiguous.
    """
    return {
        "company_overview": {
            "summary": "Attribution software for B2B SaaS marketing teams.",
            "founded_context": "Founded 2021 by two ex-agency analysts.",
            "confidence": 0.8,
        },
        "products_services": [
            {"name": "Attribution Cloud", "description": "Multi-touch attribution model."}
        ],
        "features": [{"product": "Attribution Cloud", "capabilities": ["multi-touch", "reports"]}],
        "pricing_positioning": {
            "model": "tiered",
            "posture": "Mid-market, published pricing.",
            "price_points": ["$99/mo", "$499/mo"],
        },
        "industry": {"primary": "Marketing analytics", "adjacent": ["Sales enablement"]},
        "target_market": {
            "segment": "B2B",
            "company_sizes": ["50-200"],
            "stages": ["Series A"],
            "geographies": ["US", "EU"],
        },
        "ideal_customer_profiles": [
            {
                "slug": "series-a-saas",
                "name": "Series A B2B SaaS",
                "firmographics": {"headcount": "50-200"},
                "trigger_events": ["hired a demand gen lead"],
                "disqualifiers": ["ecommerce"],
            }
        ],
        "buyer_personas": [
            {
                "slug": "growth-lead",
                "name": "Growth Lead",
                "job_title": "Head of Growth",
                "seniority": "manager",
                "responsibilities": ["pipeline"],
                "metrics": ["CAC"],
                "tools": ["HubSpot"],
                "where_they_ask": ["r/marketing"],
            }
        ],
        "pain_points": [
            {
                "slug": "attribution-gap",
                "title": "Cannot attribute pipeline to channel",
                "description": "Spend decisions are made blind.",
                "severity": 4,
                "frequency": 4,
                "how_people_phrase_it": ["no idea which channel actually works"],
            },
            {
                "slug": "manual-reporting",
                "title": "Reporting eats a day a week",
                "severity": 3,
                "frequency": 5,
                "how_people_phrase_it": ["stuck in spreadsheets every Monday"],
            },
            {
                "slug": "tool-sprawl",
                "title": "Too many overlapping tools",
                "severity": 2,
                "frequency": 3,
                "how_people_phrase_it": ["we pay for four things that do the same job"],
            },
        ],
        "jobs_to_be_done": [{"type": "functional", "statement": "Prove which channel works."}],
        "value_propositions": [
            {"claim": "See pipeline by channel in a day.", "answers_pain": "attribution-gap"}
        ],
        "competitor_references": [
            {
                "slug": "segment",
                "name": "Segment",
                "aliases": ["Twilio Segment"],
                "context": "Named on the comparison page.",
            }
        ],
        "alternative_solutions": [
            {"name": "Spreadsheets", "why_people_use_it": "Free and already there."}
        ],
        "customer_language": ["which channel actually works", "our numbers never match"],
        "reddit_terminology": ["attribution", "UTM"],
        "search_intent": [{"shape": "comparison", "examples": ["segment alternative"]}],
        "buying_signals": [
            {
                "slug": "evaluating-alternatives",
                "label": "Evaluating alternatives",
                "tier": "high",
                "example_phrases": ["looking to replace"],
            },
            {
                "slug": "reporting-pain",
                "label": "Complaining about reporting",
                "tier": "medium",
                "example_phrases": ["reporting is a nightmare"],
            },
            {
                "slug": "new-hire",
                "label": "Just hired a growth lead",
                "tier": "low",
                "example_phrases": ["just joined as head of growth"],
            },
        ],
        "common_objections": [
            {"objection": "Too expensive", "typical_phrasing": "not at that price"}
        ],
        "outreach_angles": [
            {
                "persona": "growth-lead",
                "pain": "attribution-gap",
                "angle": "Lead with the day-one report.",
            }
        ],
        "content_themes": ["attribution", "reporting"],
        "seo_entities": ["multi-touch attribution"],
        "geo_entities": ["United States"],
        "negative_signals": ["hiring post"],
        "evidence": [
            {
                "quote": "See which channel actually works.",
                "source_url": "https://example.com",
                "section": "company_overview",
            }
        ],
        "thin_content": False,
    }


@pytest.fixture
def app(temp_db, monkeypatch):
    """The dashboard, with **no in-process worker**.

    P3 made ``create_app()`` start a worker thread, which is right for the
    operator and wrong for a test: a background thread claiming jobs turns every
    queue assertion into a race with itself, and a test that sometimes finds the
    job already done is worse than one that never runs it. Tests that need work
    executed drive ``Worker.tick()`` explicitly, which is deterministic.

    The environment variable is set **before** ``create_app`` runs, because that
    is when the decision is made and reading it afterwards would be too late.
    """
    monkeypatch.setenv("WORKER_INPROCESS", "false")

    from src.dashboard.app import create_app, reset_ai_service, stop_worker

    stop_worker()
    reset_ai_service()
    application = create_app(run_migrations=False)
    application.config["TESTING"] = True
    yield application
    stop_worker()
    reset_ai_service()


@pytest.fixture
def client(app):
    return app.test_client()
