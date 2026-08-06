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
def app(temp_db):
    from src.dashboard.app import create_app, reset_ai_service

    reset_ai_service()
    application = create_app(run_migrations=False)
    application.config["TESTING"] = True
    yield application
    reset_ai_service()


@pytest.fixture
def client(app):
    return app.test_client()
