"""The invariants that keep the architecture honest.

These are grep- and behaviour-level tests rather than unit tests. Each one
guards a property that is cheap to hold now and expensive to restore once it has
been broken for a few months.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import DateTime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"


def _python_files(root: Path, exclude: set[str] = frozenset()) -> list[Path]:
    return [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not any(part in exclude for part in p.parts)
    ]


# ------------------------------------------------------------ vendor coupling


def _executable_tokens(path: Path) -> str:
    """Identifiers and non-docstring string literals — i.e. code that *acts*.

    The rule being tested is about *coupling*, not vocabulary. A docstring
    explaining why DeepSeek's cache behaves as it does is documentation and is
    wanted; a literal ``"deepseek"`` in a default argument is coupling and is
    not. Raw text matching cannot tell them apart, and a test that punishes
    commenting gets its comments deleted rather than its coupling fixed.

    Uses ``ast`` rather than ``tokenize``: docstrings are an AST concept, and
    the token-level heuristic for spotting them is subtly wrong (the token
    preceding a docstring is the ``:`` of the enclosing def, not a NEWLINE).
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    pieces: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                pieces.append(node.value)
        elif isinstance(node, ast.Name):
            pieces.append(node.id)
        elif isinstance(node, ast.Attribute):
            pieces.append(node.attr)
        elif isinstance(node, ast.alias):
            pieces.append(node.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            pieces.append(node.module)
    return " ".join(pieces)


def test_no_vendor_coupling_outside_providers():
    """AC8: no module outside providers/ may branch on or default to a vendor.

    ``providers/registry.py`` is the deliberate exception: it exists so the
    Settings dropdown is built from data rather than a hardcoded list in a
    template, and everything else takes its default from ``DEFAULT_PROVIDER``.
    """
    offenders = []
    for path in _python_files(SRC):
        if "providers" in path.parts:
            continue
        if "deepseek" in _executable_tokens(path).lower():
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"vendor coupling outside providers/: {offenders}"


def test_provider_default_comes_from_the_registry():
    """The mechanism that makes the rule above hold rather than being policed."""
    from src.ai.credentials import CredentialStore
    from src.ai.providers.registry import DEFAULT_PROVIDER
    from src.settings import get_settings

    assert CredentialStore(get_settings({})).provider == DEFAULT_PROVIDER


def test_no_wire_format_details_outside_ai():
    """Business logic must not know what a token or a temperature is."""
    pattern = re.compile(r"\b(response_format|max_tokens|temperature)\b")
    offenders = []
    for path in _python_files(SRC, exclude={"ai"}):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"provider wire details leaked: {offenders}"


def test_the_network_layer_has_no_reddit_knowledge():
    """Fence 4 (R5), and the first implementation of it.

    ``docs/35`` §2.1 lists this among the four checks it calls non-negotiable and
    ``docs/12`` §14 ticked it as delivered in P2 -- but no such test existed, and
    writing it in P4 found seven Reddit identifiers in ``src/net/blocks.py``.
    They were moved to ``RedditClient`` rather than deleted; the transport now
    carries generic challenge signatures and the caller supplies target-specific
    ones.

    **Scope is `src/net/` only.** ``docs/testing/P04-testing.md`` T12 instructs a
    tester to plant the word in a file under that tree and watch this fail;
    widening the scope to all of ``src/`` would make that instruction defeat
    itself, and would also fail on ``src/reddit_client.py``, which is *supposed*
    to know about Reddit.

    AST-based, not ``grep -ri``: the rule is about coupling, not vocabulary.
    ``src/net/user_agents.py`` must stay free to explain in its docstring that it
    exists because of ``old.reddit.com`` 403s -- a literal reading of the old
    text would have forced an engineer to delete the comment explaining why the
    boundary exists. See ARCHITECTURE_FREEZE §11.1.
    """
    pattern = re.compile(r"reddit", re.IGNORECASE)
    offenders = []
    for path in _python_files(SRC / "net"):
        hits = sorted({t for t in _executable_tokens(path).split() if pattern.search(t)})
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {hits}")
    assert offenders == [], (
        "src/net/ is a reusable egress layer and must contain no Reddit knowledge "
        f"in executable code (R5). Offenders: {offenders}"
    )


def test_prompts_are_files_not_literals():
    """A literal buried in a function cannot be diffed in a review."""
    offenders = []
    for path in _python_files(SRC):
        text = path.read_text(encoding="utf-8")
        if "You are a" in text or "You are an" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"inline prompt text found in: {offenders}"


# ------------------------------------------------------------------ secrets


def test_no_api_key_in_config_or_repo():
    """AC7 support: the repository must never contain a credential."""
    config = (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "api_key" not in config.lower() or "NOT HERE" in config
    assert not re.search(r"\bsk-[A-Za-z0-9_\-]{16,}", config)

    for path in _python_files(SRC) + [PROJECT_ROOT / "main.py"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bsk-[A-Za-z0-9_\-]{20,}", text), f"key-shaped literal in {path}"


def test_gitignore_covers_secrets():
    ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "data/*.db", "*proxies*.txt"):
        assert pattern in ignore, f"{pattern} is not gitignored"


def test_redaction_catches_credential_shapes():
    from src.obs.logging import REDACTED, redact

    samples = [
        "Authorization: Bearer sk-abc123def456ghi789jkl",
        "using key sk-1234567890abcdefghij now",
        'api_key="sk-supersecretvalue123"',
        "http://user1234:hunter2pass@1.2.3.4:8080",
    ]
    for sample in samples:
        assert REDACTED in redact(sample), f"not redacted: {sample}"

    clean = "nothing sensitive in this line at all"
    assert redact(clean) == clean


def test_key_never_returned_by_any_settings_route(client, settings):
    """There is no reveal endpoint, and no parameter produces one."""
    from src.dashboard.app import get_ai_service

    secret = "sk-neverexposed0123456789"
    get_ai_service().credentials.set_key(secret, validate=False)

    for path in ("/api/settings/ai", "/api/settings/ai/providers", "/api/health", "/api/health/ai"):
        response = client.get(path)
        assert secret not in response.get_data(as_text=True), f"key leaked from {path}"

    page = client.get("/settings/ai").get_data(as_text=True)
    assert secret not in page


# ------------------------------------------------------------------ prompts


def test_every_prompt_has_the_required_sections():
    """AC10."""
    from src.ai.prompts import PromptManager

    manager = PromptManager()
    stages = manager.available()
    assert len(stages) == 4, f"expected 4 templates, found {stages}"

    for stage, version in stages:
        problems = manager.validate(stage, version)
        assert problems == [], f"{stage} v{version}: {problems}"


def test_batched_prompt_carries_a_batch_contract():
    """Without it, a model silently dropping an item looks like success."""
    from src.ai.prompts import PromptManager

    template = PromptManager().load("lead_enrichment")
    system, _user = template.split()
    assert "# Batch Contract" in system
    assert "echo" in system.lower()


def test_prompt_system_half_has_no_variables():
    """The frozen half must be byte-identical on every call.

    A variable in the system half would make the prefix vary per item, which
    silently destroys the ~50x cached-input saving.
    """
    import re as _re

    from src.ai.prompts import PromptManager

    manager = PromptManager()
    for stage, version in manager.available():
        system, _user = manager.load(stage, version).split()
        found = _re.findall(r"\{\{\s*(\w+)\s*\}\}", system)
        assert found == [], f"{stage} v{version} has variables in its frozen half: {found}"


def test_prompt_hashes_are_recorded():
    """A prompt change must be a visible, reviewable event."""
    from src.ai.prompts import PromptManager

    manager = PromptManager()
    hashes = {stage: manager.load(stage, v).content_hash for stage, v in manager.available()}
    assert len(set(hashes.values())) == len(hashes), "two templates have identical content"
    for stage, digest in hashes.items():
        assert len(digest) == 64, f"{stage} hash malformed"


# ------------------------------------------------------------------ context


def test_frozen_prefix_rejects_volatile_data():
    """A timestamp in the prefix is a silent 50x cost increase."""
    from src.ai.context import ContextBuilder, VolatilePrefixError

    builder = ContextBuilder()
    with pytest.raises(VolatilePrefixError):
        builder.build({"run": "started at 2026-07-30T14:22:01"})
    with pytest.raises(VolatilePrefixError):
        builder.build({"id": "550e8400-e29b-41d4-a716-446655440000"})


def test_frozen_prefix_is_order_independent():
    """Dict order follows insertion, which follows whatever the caller did."""
    from src.ai.context import ContextBuilder

    builder = ContextBuilder()
    first = builder.build({"alpha": {"b": 2, "a": 1}, "beta": ["x"]})
    second = builder.build({"beta": ["x"], "alpha": {"a": 1, "b": 2}})
    assert first.prefix_hash == second.prefix_hash


# --------------------------------------------------------------- regression


def test_legacy_dashboard_unchanged(client):
    """AC18: the existing dashboard is the backward-compatibility proof."""
    response = client.get("/")
    assert response.status_code == 200


def test_csv_export_still_thirteen_columns(client):
    response = client.get("/api/leads/export")
    assert response.status_code == 200
    header = response.get_data(as_text=True).lstrip("﻿").splitlines()[0]
    assert len(header.split(",")) == 13


def test_ruff_is_clean():
    """AC19."""
    result = subprocess.run(
        ["python", "-m", "ruff", "check", "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


#: Every route the legacy blueprint has ever exposed: ``GET /`` plus the
#: **17 API endpoints** R20 names. Transcribed from the running app at P3 and
#: frozen here as a literal, because the guarantee is about this exact set —
#: deriving it from the app at test time would assert only that the app equals
#: itself.
LEGACY_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("/", "GET"),
        ("/api/keywords", "GET"),
        ("/api/keywords", "POST"),
        ("/api/keywords/<int:kw_id>", "DELETE"),
        ("/api/leads", "GET"),
        ("/api/leads/<int:lead_id>", "DELETE"),
        ("/api/leads/<int:lead_id>/status", "PUT"),
        ("/api/leads/export", "GET"),
        ("/api/queries", "GET"),
        ("/api/queries", "POST"),
        ("/api/queries/<int:q_id>", "DELETE"),
        ("/api/scrape", "POST"),
        ("/api/settings", "GET"),
        ("/api/settings", "PUT"),
        ("/api/stats", "GET"),
        ("/api/subreddits", "GET"),
        ("/api/subreddits", "POST"),
        ("/api/subreddits/<int:sub_id>", "DELETE"),
    }
)


def test_the_seventeen_legacy_endpoints_are_all_still_there(client):
    """R20's endpoint half, which the recorded replay does not cover.

    ``test_legacy_api_contract_is_frozen`` replays seven **GET** paths — the ones
    whose response shape could be recorded. That leaves the other eleven, and
    every non-GET route, guarded by nothing: a phase could delete
    ``DELETE /api/leads/<id>`` and the suite would stay green.

    This asserts the route table itself. New surfaces go in new blueprints
    (``routes_runs``, ``routes_health``, ``routes_pages``), so this set must not
    grow either — an addition here means someone edited ``routes.py``, which is
    the file the compatibility guarantee is built on not being edited.
    """
    from src.dashboard.app import create_app

    app = create_app(run_migrations=False)
    actual = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith("main.")
        for method in rule.methods
        if method in {"GET", "POST", "PUT", "DELETE"}
    }

    assert actual == LEGACY_ROUTES, (
        f"legacy route table changed:\n"
        f"  removed: {sorted(LEGACY_ROUTES - actual)}\n"
        f"  added:   {sorted(actual - LEGACY_ROUTES)}"
    )
    assert len({rule for rule, _ in LEGACY_ROUTES if rule != "/"}) + 4 == 17, (
        "the count R20 states is 17 API endpoints; four paths carry two methods"
    )


def test_every_legacy_endpoint_still_answers(client):
    """Present in the route table is not the same as working.

    Only the read paths are exercised — a POST or DELETE here would mutate. That
    is the honest limit of this test, and the write paths' shapes are covered by
    their own tests elsewhere.
    """
    for path in (
        "/",
        "/api/leads",
        "/api/leads/export",
        "/api/keywords",
        "/api/queries",
        "/api/settings",
        "/api/stats",
        "/api/subreddits",
    ):
        assert client.get(path).status_code == 200, f"{path} no longer answers"


def test_legacy_api_contract_is_frozen(client):
    """AC18, restated at the level that matters.

    The original guarantee was "GET / renders byte-identically". That was the
    right guard while the dashboard was untouched, but Phase 1 §7 always
    intended the page to gain navigation, and the UX pass added an AI status
    widget and moved configuration to its own page.

    Byte-identity of the *chrome* was never the point. What must not change is
    the **contract**: the response shape of every legacy endpoint, and the CSV
    column order that external importers depend on. That is what this asserts,
    and it is strictly stronger than eyeballing a diff of the HTML.

    The pre-UX HTML is kept at tests/baseline/index_pre_ux.html for reference.
    """
    import json

    baseline_path = PROJECT_ROOT / "tests" / "baseline" / "api_contract.json"
    if not baseline_path.exists():  # pragma: no cover
        pytest.skip("no recorded API contract")

    baseline = json.loads(baseline_path.read_text())

    for path, spec in baseline.items():
        kind, expected = spec["kind"], spec["value"]
        response = client.get(path)
        assert response.status_code == 200, f"{path} regressed to {response.status_code}"

        if kind == "csv_header":
            header = response.get_data(as_text=True).lstrip("\ufeff").splitlines()[0]
            assert header == expected, f"CSV columns changed:\n  was {expected}\n  now {header}"

        elif kind == "dict_keys":
            payload = response.get_json()
            assert isinstance(payload, dict), f"{path} is no longer an object"
            assert sorted(payload) == expected, (
                f"{path} keys changed:\n  was {expected}\n  now {sorted(payload)}"
            )

        elif kind == "list_item_keys":
            payload = response.get_json()
            assert isinstance(payload, list), f"{path} is no longer a list"
            # The test database is empty, so an empty list is expected and
            # proves the endpoint still answers. Item shape is only checkable
            # when there is an item.
            if payload and expected:
                assert sorted(payload[0]) == expected, (
                    f"{path} item keys changed:\n  was {expected}\n  now {sorted(payload[0])}"
                )


# ------------------------------------------------------- naive-UTC timestamps


def _datetime_column_defaults():
    """Every callable ``DateTime`` default/onupdate in the schema.

    Yields ``(label, callable)``. Reflected off ``Base.metadata`` rather than
    listed by hand: a test that enumerates today's columns stops protecting the
    ones added tomorrow, which is exactly when this bug comes back.
    """
    from src.db.models import Base

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, DateTime):
                continue
            for kind in ("default", "onupdate"):
                spec = getattr(column, kind)
                if spec is not None and spec.is_callable:
                    # SQLAlchemy wraps a zero-arg default in ``lambda ctx: fn()``
                    # and copies the original's metadata onto it; ``__wrapped__``
                    # is the function actually written in the model.
                    yield (
                        f"{table.name}.{column.name} {kind}",
                        getattr(spec.arg, "__wrapped__", spec.arg),
                    )


def test_no_datetime_column_defaults_to_a_deprecated_or_local_clock():
    """The bug this pass fixed, made permanent.

    ``datetime.utcnow`` is deprecated in 3.12 and *raises* under
    ``-W error::DeprecationWarning``. Because SQLAlchemy evaluates column
    defaults inside statement execution, that raise arrives as a
    ``StatementError`` on INSERT — an error that names neither the column nor
    the datetime, and which cost this project six mysterious test failures.

    ``datetime.now`` without a ``tz`` is the trap on the other side: it silences
    the warning and returns *local* time, which is wrong by hours on a
    developer's machine and right by accident in a UTC CI container.
    """
    # Keyed by ``__qualname__`` rather than identity: ``datetime.datetime.utcnow``
    # hands back a fresh bound-builtin object on every attribute access, so ``is``
    # would never match and the test would pass no matter what the model did.
    banned = {
        "datetime.utcnow": "datetime.utcnow, which is deprecated and raises under -W error",
        "datetime.now": "a bare datetime.now, which returns local time, not UTC",
    }
    for label, fn in _datetime_column_defaults():
        reason = banned.get(getattr(fn, "__qualname__", ""))
        assert reason is None, f"{label} uses {reason}; use models._utcnow instead"


def test_every_datetime_default_produces_naive_utc():
    """Naive in, naive out — and actually UTC, not the local wall clock.

    The ``replace(tzinfo=None)`` in ``models._utcnow`` is load-bearing:
    ``JobQueue.claim`` compares timestamps as formatted SQLite strings, so an
    aware value would serialize with a ``+00:00`` suffix and the ``<=`` would
    silently stop matching — a queue that claims nothing and reports no error.
    """
    import datetime as _dt

    reference = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    for label, fn in _datetime_column_defaults():
        value = fn()
        assert value.tzinfo is None, (
            f"{label} returned an aware datetime; the schema stores naive UTC"
        )
        assert abs((value - reference).total_seconds()) < 60, (
            f"{label} is not on a UTC clock (returned {value}, expected ~{reference})"
        )


def test_stored_timestamp_defaults_round_trip_as_naive_utc(temp_db):
    """The same guarantee end-to-end, through a real INSERT and SELECT.

    Both tables named here failed under ``-W error::DeprecationWarning``:
    ``leads.scraped_at`` broke the repository tests and ``scrape_runs.run_at``
    broke the worker's reclaim test, where the rolled-back INSERT looked like a
    duplicate-row bug.
    """
    import datetime as _dt

    from sqlalchemy.orm import Session

    from src.db import database
    from src.db.models import Lead, ScrapeRun

    reference = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    with Session(bind=database.ENGINE) as session:
        session.add(
            Lead(
                reddit_id="t3_utc",
                subreddit="test",
                author="tester",
                title="timestamp defaults",
                url="https://example.invalid/t3_utc",
                created_utc=reference,
            )
        )
        session.add(ScrapeRun(scraper_type="subreddit", posts_found=1))
        session.commit()

    with Session(bind=database.ENGINE) as session:
        stamps = {
            "leads.scraped_at": session.query(Lead).one().scraped_at,
            "scrape_runs.run_at": session.query(ScrapeRun).one().run_at,
        }

    for label, stored in stamps.items():
        assert stored is not None, f"{label} was not populated by its default"
        assert stored.tzinfo is None, f"{label} came back aware; the schema stores naive UTC"
        assert abs((stored - reference).total_seconds()) < 60, f"{label} is not on a UTC clock"
