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


def test_discovery_makes_no_ai_calls():
    """P6 makes this an acceptance criterion; P5 establishes it while it is free.

    Discovery decides *what to look at*. Deciding what a post is *worth* is the
    enrichment pipeline's job, behind a budget and a gate. The moment discovery
    can call a model, the per-run cost stops being predictable from the number
    of subreddits -- and the cheapest time to hold that line is when the package
    has one file in it.
    """
    discovery = SRC / "discovery"
    if not discovery.exists():  # pragma: no cover - P5 creates it
        pytest.skip("src/discovery/ does not exist yet")

    offenders = []
    for path in _python_files(discovery):
        tokens = _executable_tokens(path)
        if re.search(r"\bsrc\.ai\b|\bfrom \.\.ai\b", tokens) or "src.ai" in tokens:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"src/discovery/ imports the AI layer: {offenders}"


def test_the_policy_module_exists_and_is_inside_the_ai_fence():
    """A5 names `discovery/policy.py` specifically, so its absence must fail.

    `test_discovery_makes_no_ai_calls` walks whatever files exist, which means a
    deleted or renamed `policy.py` would leave it passing over the remaining
    files while the criterion it enforces silently stopped being about anything.
    P5's F3 -- a guard that cannot fail is documentation.
    """
    policy = SRC / "discovery" / "policy.py"
    assert policy.exists(), "R3 and P6's A5 both name src/discovery/policy.py by path"
    assert "src.ai" not in _executable_tokens(policy)


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, resolved to absolute. Imports only.

    Not identifiers, not string literals -- and that distinction is load-bearing
    for R4. Transport T2 is specified as a ``subprocess`` call to the ``hermes``
    binary (``docs/21`` §7.1), so the literal string ``"hermes"`` must stay legal
    in an argv list while ``import hermes`` must not. A token- or text-based fence
    cannot tell those apart, and would therefore fail on the one implementation
    the architecture actually asked for -- the same trap ARCHITECTURE_FREEZE §11.1
    already recorded for fences 1 and 4, where a literal ``grep -ri`` would have
    forced an engineer to delete the comment explaining why the boundary exists.

    Relative imports are resolved against the file's own package, so
    ``from ..ai import service`` inside ``src/notify/`` is reported as ``src.ai``
    and cannot slip past a check written for the absolute form.

    Dynamic imports are covered for the two spellings that appear in real code:
    ``importlib.import_module("x")`` and ``__import__("x")``.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = path.relative_to(PROJECT_ROOT).parts[:-1]

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if not node.level:
                modules.add(node.module)
            else:
                # level 1 is the containing package, 2 its parent, and so on.
                base = package[: len(package) - (node.level - 1)]
                modules.add(".".join((*base, node.module)))
        elif isinstance(node, ast.Call):
            called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if called in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    modules.add(first.value)
    return modules


def _imports_any(path: Path, roots: set[str]) -> list[str]:
    """The members of ``roots`` this file imports, matching whole packages only.

    ``hermes`` matches ``hermes`` and ``hermes.client``; it must not match a
    hypothetical ``hermesutils``, which is a different distribution.
    """
    found = set()
    for module in _imported_modules(path):
        for root in roots:
            if module == root or module.startswith(root + "."):
                found.add(root)
    return sorted(found)


def test_the_platform_never_imports_hermes():
    """Grep fence 3 (R4) -- and the first implementation of it.

    ``docs/34`` §1.2 lists *"all four grep fences pass (R2-R5)"* as a **universal**
    acceptance criterion, for every phase without exception. Fence 3 did not
    exist: before P7, ``grep -i hermes tests/`` matched no file at all, so six
    phases ticked a line nobody could have checked. Exactly the defect P4 found
    for fence 4, which ``docs/12`` §14 had also ticked as delivered while it was
    absent, and which failed on seven identifiers the moment it was written.

    **R4 is a one-way dependency, not a vocabulary ban.** The platform is the data
    plane; Hermes is the control plane above it (``ARCHITECTURE_FREEZE`` §1). The
    platform must keep working with Hermes uninstalled -- which is the state of
    this machine, and remains so until P23. So this fence is about *imports*: see
    :func:`_imported_modules` for why a text match would break transport T2.

    Scope is all of ``src/``, deliberately wider than fence 4's ``src/net/``:
    there is no module anywhere in the platform that is supposed to know about the
    agent runtime.
    """
    scanned = 0
    offenders = []
    for path in _python_files(SRC):
        scanned += 1
        hits = _imports_any(path, {"hermes"})
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {hits}")

    # A fence that walked nothing would report no violations while checking
    # nothing -- P6's F3, and the reason every fence here counts its own inputs.
    assert scanned > 0, "fence 3 scanned no files; SRC is wrong or the tree is empty"
    assert offenders == [], (
        "R4: src/ never imports Hermes -- the platform does not depend on the "
        "control plane, and must run with Hermes uninstalled. Transport T2 reaches "
        "it as a subprocess, which needs no import. Offenders: " + str(offenders)
    )


def test_notify_imports_no_model():
    """R17 / AD-28: notifications never invoke a model.

    ``docs/21`` §7.1 states it without qualification -- *"No model is involved in
    a notification, ever"* -- and ``docs/34`` §P7's acceptance criterion is *"zero
    tokens consumed"*. ``docs/22`` §4.12 describes a ``notify-policy`` skill that
    would classify the *"~5%"* of events its deterministic table cannot, but R17
    admits no five per cent and that skill is not in the three-skill first
    delivery (``ARCHITECTURE_FREEZE`` §7). No ambiguity path is built: the table
    covers every kind, and anything unrecognised is suppressed.

    An import fence cannot see a subprocess, so this is necessarily one half of
    the guard. The other half is the token assertion -- zero ``ai_calls`` rows for
    a run that sent a message -- which is the criterion that actually matters and
    which arrives with the dispatcher in Stage 5.
    """
    notify = SRC / "notify"
    assert notify.exists(), "src/notify/ is P7's package; its absence is a failure, not a skip"

    scanned = 0
    offenders = []
    for path in _python_files(notify):
        scanned += 1
        hits = _imports_any(path, {"src.ai", "hermes"})
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {hits}")

    assert scanned > 0, "the R17 fence scanned no files under src/notify/"
    assert offenders == [], (
        "R17/AD-28: src/notify/ imports neither the AI layer nor an agent runtime. "
        "A notification that cost a model call would make the most frequent message "
        "in the system the most expensive one. Offenders: " + str(offenders)
    )


def test_notify_confines_the_http_client_to_transport():
    """``docs/34`` §P7: *"renderers.py imports neither src.ai nor an HTTP client."*

    The rule generalises usefully, so it is enforced as one: **exactly one module
    in this package may speak to the network**, and it is ``transport.py``. A
    renderer that could make a request would be able to enrich a message body from
    somewhere other than the database, and "rendered from SQL" would stop being
    checkable. Confining egress to one file also means the R15 redaction argument
    has one place to hold.

    ``transport.py`` is allowed ``requests`` -- already a dependency, so P7 adds
    none (``ARCHITECTURE_FREEZE`` §5 is untouched).
    """
    notify = SRC / "notify"
    assert notify.exists(), "src/notify/ is P7's package; its absence is a failure, not a skip"

    clients = {"requests", "httpx", "aiohttp", "urllib3", "urllib.request", "http.client"}
    allowed = {"transport.py"}

    scanned = 0
    offenders = []
    for path in _python_files(notify):
        scanned += 1
        if path.name in allowed:
            continue
        hits = _imports_any(path, clients)
        if hits:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {hits}")

    assert scanned > 0, "the HTTP-confinement fence scanned no files under src/notify/"
    assert offenders == [], (
        "only src/notify/transport.py may import an HTTP client; a renderer builds "
        "its body from SQL. Offenders: " + str(offenders)
    )


def test_the_notify_package_exists():
    """The two fences above walk whatever is there, so absence must fail loudly.

    P6's G1 pairs its AI fence with an existence check for the same reason: *"a
    fence that walks whatever files are there passes vacuously if the file it was
    written for is deleted."* P5's F3, third occurrence -- a guard that cannot
    fail is documentation. Deleting or renaming this package should break a test,
    not quietly reduce two fences to no-ops over an empty directory.
    """
    package = SRC / "notify" / "__init__.py"
    assert package.exists(), "R17 and docs/34 §P7 both name src/notify/ by path"

    from src.notify import Kind

    # Five, not six or seven. ARCHITECTURE_FREEZE §7 caps first delivery at five
    # and the three documents naming them disagree (docs/22 §4.12 lists six,
    # docs/21 §7.1 seven); expansion to nine "requires operator request", so a
    # sixth appearing here without one is a scope change to catch now.
    assert len(Kind) == 5, f"freeze §7 fixes first delivery at five kinds, found {len(Kind)}"

    # min_confidence_alert configures leads.confidence_score, which does not exist
    # until 0006. P6's density_threshold note is the precedent: a key nothing reads
    # is a documented capability that does not exist.
    assert "lead.high_confidence" not in {k.value for k in Kind}


def test_the_density_heuristic_was_not_reintroduced():
    """P6 removed it; this stops a later reader rebuilding it from the plan.

    [34 §P6] task 5 specified a density-adaptive body fetch -- "listing >=25%,
    permalink <25%, hysteresis 30/20" -- choosing between an HTML listing page
    and a permalink when many posts need bodies. P5 measured that an old-Reddit
    listing page renders its expandos lazily and carries **no selftext at all**:
    0 of 25 live, 0 of 25 in the shipped P0 capture (ARCHITECTURE_FREEZE §11,
    2026-08-08). The listing branch spent a request and returned nothing at any
    density, so the heuristic had one reachable arm and was deleted.

    The same shape of defect as conditional GET above: the *plan* still
    describes it, so someone following the plan would build it.
    """
    # Executable tokens only. The modules that removed the heuristic explain
    # why in their docstrings, and a check that matched prose would fail on the
    # very comment recording the decision -- while still passing if someone
    # reintroduced the key under a different name in a comment-free file.
    pattern = re.compile(r"density_threshold|density_adaptive")
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in _python_files(SRC)
        if pattern.search(_executable_tokens(path))
    ]

    config = PROJECT_ROOT / "config.yaml"
    config_text = config.read_text(encoding="utf-8")
    # The explanatory comment names the key; a *setting* would be `key:` at the
    # start of a line. Matching the comment would make this untestable.
    if re.search(r"^\s*density_threshold\s*:", config_text, re.MULTILINE):
        offenders.append("config.yaml")

    assert offenders == [], (
        "the density-adaptive body fetch was removed in P6 because an HTML "
        "listing page carries no selftext (freeze §11). The feed already "
        f"supplies bodies. Found in: {offenders}"
    )


def test_conditional_get_has_not_been_reintroduced():
    """P0's U4 refuted it; ARCHITECTURE_FREEZE §11 deleted the layer.

    This exists because the *plan* still described it. [34 §P5] listed
    `if_none_match` / `if_modified_since` / 304 handling as deliverables, and a
    later reader following that row would reasonably build it. Reddit sends
    neither `ETag` nor `Last-Modified` on `.rss` -- measured on four feeds and
    two hosts in P0, and re-observed on 2026-08-08 -- so the branch could never
    be taken and no test could ever prove it worked.

    See docs/P5-DECISION-ANALYSIS.md §D1.
    """
    pattern = re.compile(r"if_none_match|if_modified_since|If-None-Match|If-Modified-Since")
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in _python_files(SRC)
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "conditional GET does not exist on Reddit's feeds (U4, refuted in P0) and "
        f"the layer was deleted from the architecture. Found in: {offenders}"
    )


def test_atom_fixtures_carry_no_real_identities():
    """[lock §5.1 H2]: this repository is public.

    The Atom fixtures are modelled on a live capture, and a live capture is full
    of real usernames and real permalinks. The invented ones follow one shape,
    asserted here so a future fixture cannot be pasted in raw.
    """
    fixtures = sorted((PROJECT_ROOT / "tests" / "fixtures" / "atom").glob("*.xml"))
    assert fixtures, "the Atom fixtures are missing"

    allowed_author = re.compile(r"^/u/redditor_\d+$")
    offenders = []
    for path in fixtures:
        text = path.read_text(encoding="utf-8")
        for author in re.findall(r"<name>([^<]*)</name>", text):
            if not allowed_author.match(author.strip()):
                offenders.append(f"{path.name}: author {author!r}")
        # Every permalink id must be an invented one: a000nnn or b000nnn.
        for link in re.findall(r"/comments/([A-Za-z0-9]+)/", text):
            if not re.match(r"^[ab]\d{6}$", link):
                offenders.append(f"{path.name}: permalink id {link!r}")
    assert offenders == [], f"real-looking identities in public fixtures: {offenders}"


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
