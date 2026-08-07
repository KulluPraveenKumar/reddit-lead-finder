"""``POST /api/scrape`` — the contract, and the rollback path behind it.

The recorded baseline in ``tests/baseline/api_scrape_contract.json`` was captured
against the pre-P3 build, before the route was touched. That ordering is the
whole point: a contract recorded *after* the change records the change.

``tests/baseline/api_contract.json`` cannot cover this route — its replay issues
``client.get(path)`` and ``/api/scrape`` is a POST — so without this file the
phase's most compatibility-sensitive edit would have no test that could fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.db import database
from src.db.models import Job, Run
from src.orchestration.handlers import REGISTRY
from src.orchestration.job_queue import JobQueue
from src.orchestration.worker import Worker

BASELINE = Path(__file__).parent / "baseline" / "api_scrape_contract.json"


@pytest.fixture
def recorded():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture
def session(app):
    with Session(bind=database.ENGINE, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def worker(app):
    """Driven a tick at a time, so nothing here races a background thread."""
    return Worker(JobQueue(database.ENGINE), REGISTRY, poll_interval=0.0)


@pytest.fixture
def no_network(monkeypatch):
    """The orchestrated path must not reach Reddit when the worker runs it."""
    from src.orchestration.handlers import scrape as scrape_handler

    class _Nothing:
        def run(self, session, subreddits=None, run_id=None):
            return 0

    monkeypatch.setattr(scrape_handler, "build_scraper", lambda config: _Nothing())


# --------------------------------------------------------------- the contract


def test_the_recorded_baseline_is_what_we_think_it_is(recorded):
    """Guards the guard. A baseline edited to match a regression proves nothing."""
    assert recorded["status_code"] == 200
    assert recorded["keys"] == ["message", "ok"]
    assert recorded["values"] == {"ok": True, "message": "Scrape started in background"}


def test_scrape_keeps_every_recorded_key_and_value(client, recorded, no_network):
    """R20. Adding a field is compatible; changing or removing one is not."""
    response = client.post("/api/scrape")
    body = response.get_json()

    assert response.status_code == recorded["status_code"]
    assert response.headers["Content-Type"].startswith("application/json")
    for key, value in recorded["values"].items():
        assert body[key] == value, f"{key} changed from {value!r} to {body[key]!r}"


def test_scrape_adds_run_id_and_nothing_else(client, recorded, no_network):
    """The permitted change, stated exactly, so a fourth key fails here."""
    body = client.post("/api/scrape").get_json()

    assert sorted(body) == sorted([*recorded["keys"], "run_id"])
    assert isinstance(body["run_id"], int)


def test_scrape_creates_a_run_and_queues_a_job_per_subreddit(client, session, no_network):
    """AC1's first half: the response is a shim over real queued work."""
    from src.db.models import DashboardSubreddit

    session.add(DashboardSubreddit(name="alpha"))
    session.add(DashboardSubreddit(name="beta"))
    session.commit()

    run_id = client.post("/api/scrape").get_json()["run_id"]

    session.expire_all()
    run = session.query(Run).filter(Run.id == run_id).one()
    assert run.state == "scraping"

    subs = {
        json.loads(j.payload_json)["subreddit"]
        for j in session.query(Job).filter(Job.run_id == run_id, Job.job_type == "scrape_subreddit")
    }
    assert {"alpha", "beta"} <= subs


def test_scrape_completes_the_run(client, session, worker, no_network):
    """AC1 in full: created *and completed*."""
    run_id = client.post("/api/scrape").get_json()["run_id"]

    for _ in range(30):
        if not worker.tick():
            break

    session.expire_all()
    assert session.query(Run).filter(Run.id == run_id).one().state == "complete"


def test_a_second_scrape_returns_200_with_the_run_already_running(client, no_network):
    """The status code is part of the contract this route has always had.

    The sidebar button does `fetch(...).then(r => r.json())` with no status
    check, so a 409 here would render as "Scrape complete!" to the operator. The
    409 lives on POST /api/runs, where AC7 asserts it.
    """
    first = client.post("/api/scrape")
    second = client.post("/api/scrape")

    assert second.status_code == 200
    assert second.get_json()["run_id"] == first.get_json()["run_id"]
    assert second.get_json()["message"] == "Scrape started in background"


def test_double_click_creates_one_run(client, session, no_network):
    """docs/13 §9.4, the problem this route's rewrite exists to solve."""
    for _ in range(5):
        client.post("/api/scrape")

    session.expire_all()
    assert session.query(Run).count() == 1


# ------------------------------------------------------------ the rollback path


def test_rollback_switch_uses_the_legacy_thread_and_all_three_scrapers(client, monkeypatch):
    """C1's test, written so it cannot pass for the wrong reason.

    Asserting `status_code == 200` would prove nothing: the route returns before
    the thread does anything, and the socket blocker's NetworkCallBlocked dies
    silently inside that thread. So this asserts the three scrapers were
    **constructed**, which only the legacy branch does.
    """
    constructed = _patch_scrapers(monkeypatch)
    monkeypatch.setattr(
        "src.orchestration.run_service.orchestration_enabled", lambda: False, raising=True
    )

    response = client.post("/api/scrape")
    _join_scrape_threads()

    assert response.status_code == 200
    assert "run_id" not in response.get_json(), "the legacy path has no run"
    assert constructed == {"subreddit", "keyword", "user"}


def test_the_switch_is_what_selects_the_path(client, monkeypatch):
    """Break the branch condition and this goes red -- the F4 discipline.

    With orchestration enabled, the legacy scrapers must NOT be constructed. If
    the switch is ignored and the legacy path always runs, this fails; if the
    switch is ignored the other way, the test above fails.
    """
    constructed = _patch_scrapers(monkeypatch)
    monkeypatch.setattr(
        "src.orchestration.run_service.orchestration_enabled", lambda: True, raising=True
    )
    from src.orchestration.handlers import scrape as scrape_handler

    monkeypatch.setattr(scrape_handler, "build_scraper", lambda config: None)

    body = client.post("/api/scrape").get_json()
    _join_scrape_threads()

    assert "run_id" in body
    assert constructed == set(), "the orchestrated path must not start the legacy thread"


def test_orchestration_defaults_to_enabled_when_config_is_unreadable(monkeypatch):
    """An unreadable config must not silently downgrade to the path being replaced."""
    import src.config
    from src.orchestration.run_service import orchestration_enabled

    monkeypatch.setattr(src.config, "load_config", _explode)
    assert orchestration_enabled() is True


def test_orchestration_switch_reads_the_config_value(monkeypatch):
    import src.config
    from src.orchestration.run_service import orchestration_enabled

    monkeypatch.setattr(src.config, "load_config", lambda: {"orchestration": {"enabled": False}})
    assert orchestration_enabled() is False

    monkeypatch.setattr(src.config, "load_config", lambda: {})
    assert orchestration_enabled() is True


def test_config_is_read_as_utf8_regardless_of_locale(tmp_path):
    """Found by this phase: one non-ASCII character broke every command.

    `open(path, "r")` uses the locale default, which is cp1252 on Windows, so a
    warning sign in a comment raised UnicodeDecodeError from `load_config` --
    and therefore from the dashboard, the scraper and the worker. YAML is UTF-8
    by specification.
    """
    from src.config import load_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "# ⚠️ a warning sign, an em dash — and a bullet •\n"
        "subreddits:\n  - saas\n"
        "keywords:\n  high_intent:\n    - looking for\n"
        "scoring:\n  keyword_weight: 3\n",
        encoding="utf-8",
    )

    assert load_config(config_file)["subreddits"] == ["saas"]


def test_the_shipped_config_has_the_switch_on():
    """The rollback is off by default; shipping it on would ship the rollback."""
    from src.config import load_config

    assert load_config().get("orchestration", {}).get("enabled") is True


# ------------------------------------------------------------------- helpers


def _patch_scrapers(monkeypatch) -> set[str]:
    """Replace the three legacy scrapers with recorders. Returns the record."""
    constructed: set[str] = set()

    def recorder(name):
        class _Recorder:
            def __init__(self, *args, **kwargs):
                constructed.add(name)

            def run(self, session, *args, **kwargs):
                return 0

        return _Recorder

    import src.scrapers.keyword_scraper as ks
    import src.scrapers.subreddit_scraper as ss
    import src.scrapers.user_scraper as us

    monkeypatch.setattr(ss, "SubredditScraper", recorder("subreddit"))
    monkeypatch.setattr(ks, "KeywordScraper", recorder("keyword"))
    monkeypatch.setattr(us, "UserScraper", recorder("user"))
    return constructed


def _join_scrape_threads(timeout: float = 5.0) -> None:
    """Wait for the legacy daemon thread. F5: anything that could hang gets a deadline."""
    import threading

    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.name.startswith("Thread-"):
            thread.join(timeout=timeout)


def _explode(*_args, **_kwargs):
    raise FileNotFoundError("config.yaml is missing")
