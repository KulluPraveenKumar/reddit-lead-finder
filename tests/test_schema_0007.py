"""0007_projects_and_knowledge_base — P12.

Twelve tables, six closed foreign keys, one CHECK, and three nullabilities that
were decided **against** a document rather than inherited from one. Each of
those three has a test here whose failure message says what the decision was,
because the next reader of [34 §P12] will find text asking for the opposite.

⚠️ **What is deliberately NOT tested here: the `vec0` branch executing.**
``sqlite_vec`` is not installed on any host measured for this project (P0
[SPRINT-0-MEASUREMENTS §3.1], re-measured 2026-08-15), so
``CREATE VIRTUAL TABLE bkb_embeddings USING vec0(...)`` cannot run and no test
can honestly claim it does. What *is* tested is everything around it: that a
failure to load is caught, that both tables are skipped together, that the
warning names the cause, that the DDL string is the one that would run, and that
the migration completes either way. The gap is stated rather than papered over
with a fake that would pass while proving nothing.
"""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "0007_projects_and_knowledge_base"
PREVIOUS = "0006_content_and_dedup"
MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / f"{REVISION}.py"


def _migration_module():
    """The revision module, loaded by path.

    ``0007_projects_and_knowledge_base`` is not a Python identifier — it starts
    with a digit — so there is no import statement that reaches it. Alembic
    loads revision files the same way, by path.

    Used only to **read** constants. Nothing here patches this module object:
    alembic loads its own copy through ``ScriptDirectory``, so an attribute
    patched on this one would have no effect on the migration that actually
    runs, while the test went green. The extension tests below inject into
    ``sys.modules`` instead, which both copies see.
    """
    spec = importlib.util.spec_from_file_location("_rev_0007", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sqlite_vec_that_fails_to_load(monkeypatch):
    """A ``sqlite_vec`` that imports and then fails, injected into ``sys.modules``.

    ``sqlite_vec`` is genuinely absent on this host, so the skip branch would be
    taken anyway and a test asserting it would pass **vacuously** — and would
    start failing the day somebody installed the extension. Injecting a module
    whose ``load()`` raises forces the branch for the stated reason on any host.
    """
    fake = types.ModuleType("sqlite_vec")

    def load(_conn):
        raise RuntimeError("dlopen failed")

    fake.load = load
    monkeypatch.setitem(sys.modules, "sqlite_vec", fake)
    return fake


#: The twelve tables 0007 always creates. The vector pair is deliberately not
#: here — it is conditional, and a required-table list containing an optional
#: table is a list that fails on the normal case.
P12_TABLES = (
    "projects",
    "website_snapshots",
    "bkb",
    "bkb_sections",
    "personas",
    "pain_points",
    "intent_signals",
    "bkb_entities",
    "bkb_entity_aliases",
    "bkb_links",
    "bkb_evidence",
    "bkb_suggestions",
)

#: The six deferred `project_id` keys and the ON DELETE each ships.
P12_PROJECT_FOREIGN_KEYS = {
    "ai_calls": "SET NULL",
    "runs": "CASCADE",
    "leads": "SET NULL",
    "comments": "SET NULL",
    "dedup_groups": "CASCADE",
    "minhash_bands": "CASCADE",
}


@pytest.fixture
def at_0007(tmp_path):
    """A fresh database upgraded to 0007. Fast: no live-data copy."""
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "kb.db"
    MigrationRunner(db_path).upgrade(REVISION)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _raw_live_copy(tmp_path: Path) -> Path:
    source = PROJECT_ROOT / "data" / "leads.db"
    if not source.exists():  # pragma: no cover
        pytest.skip("no live database present")
    target = tmp_path / "raw.db"
    shutil.copy(source, target)
    return target


# ---------------------------------------------------------------------------
# The twelve tables, and the six keys M8 deferred to here
# ---------------------------------------------------------------------------


def test_the_twelve_tables_exist(at_0007):
    tables = {r[0] for r in at_0007.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(set(P12_TABLES) - tables)
    assert not missing, f"0007 did not create: {missing}"


def test_all_six_deferred_project_keys_are_closed(at_0007):
    """M8's other half. A deferred key that is never closed is just a bare column.

    [34 §P12] names four of these and [05 §7.1]'s table names six; the two extra
    are ``leads`` and ``comments``, which ``scripts/check_schema.py`` has
    asserted were *"deferred to 0007"* since P8. Six is the union, and closing
    them is what makes those four assertions true rather than permanently
    pending.
    """
    for table, action in P12_PROJECT_FOREIGN_KEYS.items():
        keys = [
            (r[3], r[6])
            for r in at_0007.execute(f"PRAGMA foreign_key_list({table})")
            if r[2] == "projects"
        ]
        assert ("project_id", action) in keys, (
            f"{table}.project_id -> projects ON DELETE {action} is missing; got {keys}. "
            f"M8 deferred this constraint to 0007 and 0007 must close it."
        )


def test_the_deletion_actions_are_not_uniform(at_0007):
    """The four actions differ, and the difference is load-bearing.

    ``leads``/``comments`` are SET NULL because [freeze §8] makes expiring leads
    a permanent non-goal — *a lead is a historical fact* — so deleting a project
    must not delete the corpus collected for it. ``dedup_groups``/
    ``minhash_bands`` are CASCADE because both are derived per-run artefacts.
    If someone ever makes these uniform, one of them becomes wrong silently.
    """
    actions = {}
    for table in P12_PROJECT_FOREIGN_KEYS:
        actions[table] = [
            r[6] for r in at_0007.execute(f"PRAGMA foreign_key_list({table})") if r[2] == "projects"
        ][0]

    assert actions["leads"] == "SET NULL"
    assert actions["comments"] == "SET NULL"
    assert actions["dedup_groups"] == "CASCADE"
    assert len(set(actions.values())) == 2, (
        f"the six actions collapsed to one: {actions}. Deleting a project would "
        f"now either delete the collected leads or orphan the dedup artefacts."
    )


def test_a_lead_and_a_comment_can_still_be_inserted_at_0007(at_0007):
    """The F1 effect test, at the revision that closes the keys rather than
    defers them.

    ``test_no_revision_leaves_a_dangling_foreign_key`` covers 0007 structurally
    because it is parametrised over the chain. This proves the write path, which
    is the thing F1 actually broke: a rebuild that reflected the ``leads`` table
    wrongly would leave a schema that reads fine and rejects every INSERT.
    """
    at_0007.execute(
        "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, scraped_at) "
        "VALUES ('t3_p12', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01')"
    )
    lead_id = at_0007.execute("SELECT id FROM leads WHERE reddit_id='t3_p12'").fetchone()[0]
    at_0007.execute(
        "INSERT INTO comments (lead_id, body, scraped_at, body_hash) "
        "VALUES (?, 'b', '2026-01-01', 'hash-p12')",
        (lead_id,),
    )
    at_0007.commit()

    assert at_0007.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1


def test_the_project_foreign_key_is_enforced_not_merely_present(at_0007):
    """A constraint that is declared but unenforced is decoration.

    ``PRAGMA foreign_keys=ON`` is set by the fixture and by
    ``src/db/database.py`` on every connection, so a bad ``project_id`` must be
    rejected rather than stored.
    """
    with pytest.raises(sqlite3.IntegrityError):
        at_0007.execute(
            "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, "
            "scraped_at, project_id) "
            "VALUES ('t3_bad', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01', 9999)"
        )


# ---------------------------------------------------------------------------
# The three nullabilities decided against a document
# ---------------------------------------------------------------------------


def test_runs_project_id_is_still_nullable(at_0007):
    """⚠️ [34 §P12] asks for ``NOT NULL`` here. It is not buildable and not right.

    **Measured 2026-08-15:** all 11 rows in the live ``runs`` table have
    ``project_id IS NULL``, so the rebuild's ``INSERT ... SELECT`` fails; making
    it pass means backfilling a placeholder project, and **M5** says *no
    migration rewrites a row*. **AD-5** is frozen as *"project scoping is
    additive and nullable"*, and ``RunService.create(project_id: int | None)``
    is the shipped signature.

    Recorded as a [freeze §11.1] reconciliation. This test exists so that a
    later phase re-reading the plan's parenthetical cannot quietly tighten it
    without seeing why it is loose.
    """
    notnull = {r[1]: r[3] for r in at_0007.execute("PRAGMA table_info(runs)")}
    assert notnull["project_id"] == 0, (
        "runs.project_id was tightened to NOT NULL. 11 of 11 live runs have it "
        "NULL, M5 forbids rewriting them, and AD-5 freezes project scoping as "
        "additive and nullable."
    )


def test_a_run_can_still_be_created_without_a_project(at_0007):
    """The behavioural half of the test above. P1-P11 all do exactly this."""
    at_0007.execute(
        "INSERT INTO runs (state, started_at, updated_at) "
        "VALUES ('pending', '2026-01-01', '2026-01-01')"
    )
    at_0007.commit()
    assert at_0007.execute("SELECT COUNT(*) FROM runs WHERE project_id IS NULL").fetchone()[0] == 1


def test_the_dedup_project_ids_are_still_nullable(at_0007):
    """[05 §7.1] left this to P12 explicitly; [05 §5.4b] declares them NOT NULL.

    They stay nullable because P10's cascade and P11's stage write ``None`` into
    both on every run today — there is no project to attribute a run to until
    P16. Tightening them would satisfy a document by breaking shipped code.
    """
    for table in ("dedup_groups", "minhash_bands"):
        notnull = {r[1]: r[3] for r in at_0007.execute(f"PRAGMA table_info({table})")}
        assert notnull["project_id"] == 0, (
            f"{table}.project_id was tightened to NOT NULL; the dedup cascade "
            f"writes None into it on every run."
        )


# ---------------------------------------------------------------------------
# The payload rule — [34 §P12]'s bold acceptance criterion
# ---------------------------------------------------------------------------


def _insert_bkb(conn) -> int:
    """A fresh project and a fresh BKB, returning the new ``bkb.id``.

    Callable more than once: each call makes its own project, so a second BKB is
    a valid foreign-key target rather than a fabricated id.
    """
    n = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (name, website_url, normalized_url, created_at, updated_at) "
        "VALUES (?, ?, ?, '2026-01-01', '2026-01-01')",
        (f"p{n}", f"https://e{n}.com", f"https://e{n}.com"),
    )
    project_id = conn.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO bkb (project_id, model, prompt_version, created_at) "
        "VALUES (?, 'm', 1, '2026-01-01')",
        (project_id,),
    )
    return conn.execute("SELECT id FROM bkb ORDER BY id DESC LIMIT 1").fetchone()[0]


def _insert_section(conn, bkb_id: int, key: str, payload: str | None) -> None:
    conn.execute(
        "INSERT INTO bkb_sections (bkb_id, section_key, payload_json, created_at) "
        "VALUES (?, ?, ?, '2026-01-01')",
        (bkb_id, key, payload),
    )


def _rejected_by_the_payload_check(conn, bkb_id: int, key: str, payload: str | None) -> None:
    """Assert the insert is rejected **by ``ck_bkb_sections_payload_null_rule``**.

    ⚠️ **The constraint name is checked, and that is the whole point.** These
    tests originally inserted into ``bkb_id + 1000`` — an id that does not exist
    — so `sqlite3.IntegrityError` was raised by the **foreign key** and the
    assertion passed no matter what the CHECK said. Mutation testing found it:
    replacing the biconditional `=` with `>=` and with `<=`, which disables one
    direction of the rule each, left both tests green (P12 mutations M6/M6b).

    So the target `bkb_id` is always real, the `(bkb_id, section_key)` pair is
    always fresh, and the error message must name the constraint. Anything else
    — a foreign key, the unique index, a NOT NULL — now fails the test instead of
    satisfying it.
    """
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _insert_section(conn, bkb_id, key, payload)
    assert "ck_bkb_sections_payload_null_rule" in str(excinfo.value), (
        f"{key} was rejected, but not by the payload rule: {excinfo.value}"
    )


def test_the_three_typed_sections_must_have_a_null_payload(at_0007):
    """For those three the typed table is authoritative; a payload here would be
    a second copy that rots (05 §5.1b)."""
    from src.db.models import BKB_TYPED_SECTION_KEYS

    bkb_id = _insert_bkb(at_0007)
    for key in BKB_TYPED_SECTION_KEYS:
        _insert_section(at_0007, bkb_id, key, None)
    at_0007.commit()

    other_bkb = _insert_bkb(at_0007)
    for key in BKB_TYPED_SECTION_KEYS:
        _rejected_by_the_payload_check(at_0007, other_bkb, key, '{"a": 1}')


def test_the_other_twenty_sections_must_have_a_payload(at_0007):
    """Both directions, because only asserting the NULL half would let all 23 be
    NULL — a knowledge base with no knowledge in it, passing its own test."""
    from src.db.models import BKB_SECTION_KEYS, BKB_TYPED_SECTION_KEYS

    others = [k for k in BKB_SECTION_KEYS if k not in BKB_TYPED_SECTION_KEYS]
    assert len(others) == 20

    bkb_id = _insert_bkb(at_0007)
    for key in others:
        _insert_section(at_0007, bkb_id, key, '{"a": 1}')
    at_0007.commit()

    other_bkb = _insert_bkb(at_0007)
    for key in others:
        _rejected_by_the_payload_check(at_0007, other_bkb, key, None)


def test_ideal_customer_profiles_is_not_exempt(at_0007):
    """⚠️ The specific mistake 05 §5.1b flags.

    An ICP feels structurally like a persona, so it is easy to assume there is an
    ``icps`` table behind it. There is not — ``payload_json`` is the **only**
    copy of an ICP that exists, and exempting the section would lose it entirely
    while every other test still passed.
    """
    bkb_id = _insert_bkb(at_0007)
    _rejected_by_the_payload_check(at_0007, bkb_id, "ideal_customer_profiles", None)


def test_the_migrations_check_and_the_models_constant_agree(at_0007):
    """The migration spells the three keys literally; ``models.py`` spells them
    again. Two spellings of one rule is how they drift.

    Same pairing as ``tests/test_rules_vocabulary.py``: one file is permitted to
    import both sides and assert the agreement.
    """
    from src.db.models import BKB_TYPED_SECTION_KEYS

    migration = _migration_module()
    assert tuple(migration.TYPED_SECTION_KEYS) == tuple(BKB_TYPED_SECTION_KEYS)
    for key in BKB_TYPED_SECTION_KEYS:
        assert key in migration._PAYLOAD_NULL_RULE


def test_every_section_key_has_a_staleness_policy():
    """23 sections, 23 entries, and Group C is the seven that never stale.

    ``staleness_days`` is seeded by P14; P12 ships the policy as data so P14 has
    one place to read it rather than a table in a document to re-transcribe.
    """
    from src.db.models import BKB_SECTION_KEYS, BKB_STALENESS_DAYS

    assert len(BKB_SECTION_KEYS) == 23
    assert set(BKB_STALENESS_DAYS) == set(BKB_SECTION_KEYS)

    never = {k for k, v in BKB_STALENESS_DAYS.items() if v is None}
    assert never == {
        "competitor_references",
        "alternative_solutions",
        "customer_language",
        "reddit_terminology",
        "search_intent",
        "buying_signals",
        "common_objections",
    }, (
        f"Group C is the seven sections that accrete from Reddit and are "
        f"therefore getting fresher, not older (06h §5.1). Got: {sorted(never)}"
    )
    assert BKB_STALENESS_DAYS["ideal_customer_profiles"] == 90
    assert BKB_STALENESS_DAYS["company_overview"] == 180


# ---------------------------------------------------------------------------
# The conditional pair — [34 §P12]'s other bold criterion
# ---------------------------------------------------------------------------


def test_the_migration_completes_with_sqlite_vec_unavailable(
    tmp_path, sqlite_vec_that_fails_to_load
):
    """**The bold criterion.** A missing extension must cost recall, not the
    schema.

    Forced rather than assumed — see the fixture. On this host the branch would
    be taken anyway, and a test that relied on that would prove nothing the day
    the extension arrived.
    """
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "novec.db"
    MigrationRunner(db_path).upgrade(REVISION)

    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    assert set(P12_TABLES) <= tables, "the twelve unconditional tables must still be created"
    assert "bkb_embeddings" not in tables
    assert "bkb_embedding_meta" not in tables, (
        "the meta table was created without the vectors it indexes — a table of "
        "pointers into nothing. Both are skipped or neither is."
    )


def test_the_skip_is_logged_with_its_cause(tmp_path, capfd, sqlite_vec_that_fails_to_load):
    """A silent skip is the failure 05 §7.1a is guarding against.

    ⚠️ **Captured at the file descriptor, not with ``caplog`` and not with a
    handler.** Two approaches were tried and both observed nothing while the
    warning was plainly on stderr:

    * ``caplog`` installs on the **root** logger, and ``migrations/env.py`` runs
      ``fileConfig``, which leaves the ``alembic`` logger not propagating.
    * A handler attached to ``alembic.runtime.migration`` before the upgrade is
      **removed by that same ``fileConfig``**, which reconfigures logging when
      ``env.py`` is executed — i.e. after the handler is attached and before the
      message is emitted.

    ``capfd`` reads the descriptor, so it is indifferent to how logging was
    configured and to when. What is asserted is what an operator running
    ``alembic upgrade head`` would actually see.
    """
    from src.db.migrate import MigrationRunner

    MigrationRunner(tmp_path / "logged.db").upgrade(REVISION)

    err = capfd.readouterr().err
    assert "sqlite-vec unavailable" in err and "dlopen failed" in err, (
        f"the skip must name its cause; stderr was: {err[-500:]}"
    )
    assert "semantic layer disabled" in err
    assert "bkb_embeddings" in err, "the message must name what was not created"


def test_the_vector_ddl_is_the_one_that_would_run():
    """The branch cannot execute where ``sqlite-vec`` is absent, so what the DDL
    *says* is pinned instead.

    This is not a substitute for running it and does not pretend to be. It
    catches the cheap regression — a dimension or a table name edited by hand —
    and leaves the expensive one (does ``vec0`` accept this?) honestly untested.
    """
    assert _migration_module().VEC0_DDL == (
        "CREATE VIRTUAL TABLE bkb_embeddings USING vec0(embedding FLOAT[256])"
    )


def test_sqlite_vec_is_not_a_declared_dependency():
    """[34 §P12]'s Config row is None and [freeze §5] lists the vector stack as
    optional. Adding it to requirements would be a dependency change needing an
    amendment — and would contradict the try/except that exists because it is
    absent.

    ⚠️ **Comment lines are stripped first, and that is the point rather than a
    loophole.** P10 documented the optional install in ``requirements.txt`` as a
    comment — *"pip install model2vec sqlite-vec"* — precisely so an operator who
    wants the tier knows how to get it. A naive substring search would read that
    explanation as a declaration and fail; what must be asserted is that no
    *installable* line names either package.
    """
    lines = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    declared = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    for package in ("sqlite-vec", "sqlite_vec", "model2vec"):
        offenders = [ln for ln in declared if package in ln]
        assert not offenders, (
            f"{package} became a required dependency: {offenders}. The semantic "
            f"tier is optional (AD-16, freeze §5); making it required would be a "
            f"dependency change needing a §11 amendment."
        )

    # And the comment that tells an operator how to opt in is still there — the
    # thing the strip above is protecting.
    assert any("pip install model2vec sqlite-vec" in ln for ln in lines)


def test_neither_vector_table_is_declared_on_the_orm_base():
    """``create_all()`` must not be able to produce a schema the migration
    cannot. Declaring ``bkb_embeddings`` on ``Base`` would emit a plain
    ``CREATE TABLE`` for a ``vec0`` virtual table on every host."""
    from src.db.models import Base

    names = set(Base.metadata.tables)
    assert "bkb_embeddings" not in names
    assert "bkb_embedding_meta" not in names


# ---------------------------------------------------------------------------
# The round-trip, on real data
# ---------------------------------------------------------------------------


def test_up_down_up_on_a_copy_of_the_live_database(tmp_path):
    """M9, for the largest revision in the chain and the first to rebuild ``leads``.

    The fingerprint is the assertion that matters. A ``batch_alter_table`` over
    ``leads`` is a genuine create-copy-drop-rename, so a reflection that dropped
    the ``reddit_id`` UNIQUE, reordered a column or lost a row would leave a
    database that passes every structural check and has quietly changed the 459
    rows R20 pins.
    """
    from src.db.migrate import MigrationRunner

    db_path = _raw_live_copy(tmp_path)
    runner = MigrationRunner(db_path)

    def snapshot() -> tuple[int, list, list]:
        conn = sqlite3.connect(db_path)
        try:
            leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            scores = conn.execute(
                "SELECT id, intent_score FROM leads WHERE id <= 459 ORDER BY id"
            ).fetchall()
            indexes = sorted((r[1], r[2]) for r in conn.execute("PRAGMA index_list(leads)"))
            return leads, scores, indexes
        finally:
            conn.close()

    # ⚠️ `_move_to`, not `upgrade`. `upgrade` only moves forward, so once
    # `data/leads.db` reached 0007 this took its `before` snapshot at 0007 and
    # compared the revision with itself. Same root cause as the regression the
    # operator's T9 caught in `test_a1_...`; see `_move_to`'s docstring.
    from tests.test_migrations import _move_to

    _move_to(runner, PREVIOUS)
    assert runner.current_revision() == PREVIOUS
    before = snapshot()

    runner.upgrade(REVISION)
    assert runner.current_revision() == REVISION
    after_up = snapshot()

    runner.downgrade(PREVIOUS)
    assert runner.current_revision() == PREVIOUS
    after_down = snapshot()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        parents = {
            table: {r[2] for r in conn.execute(f"PRAGMA foreign_key_list({table})")}
            for table in P12_PROJECT_FOREIGN_KEYS
        }
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    assert not (set(P12_TABLES) & tables), f"the downgrade left 0007 tables behind: {tables}"
    for table, names in parents.items():
        assert "projects" not in names, (
            f"the downgrade left {table}.project_id referencing a dropped "
            f"projects table. Every INSERT into {table} now fails with 'no such "
            f"table' while foreign_key_check still returns []."
        )
    assert integrity == "ok"
    assert not violations

    runner.upgrade(REVISION)
    after_re = snapshot()

    assert before == after_up == after_down == after_re, (
        "the round-trip changed the leads table: count, the 459 baseline "
        "intent_scores, or the index set differs across up/down/up."
    )
    assert before[0] >= 459


def test_the_downgrade_is_clean_on_a_host_without_the_extension(
    tmp_path, sqlite_vec_that_fails_to_load
):
    """``DROP TABLE IF EXISTS`` for the pair, because on this host they were
    never created — and a downgrade that raised there would make the rollback
    unavailable exactly where the upgrade had already degraded."""
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "rollback.db"
    runner = MigrationRunner(db_path)
    runner.upgrade(REVISION)
    runner.downgrade(PREVIOUS)

    assert runner.current_revision() == PREVIOUS


def test_check_schema_verifies_the_0007_shape(tmp_path, capsys):
    """``scripts/check_schema.py`` is what the manual guide runs, and its four
    *"is BARE — deferred to 0007"* assertions **invert** at this revision.

    ⚠️ **Added because mutation M16 survived.** Disabling the inversion — so the
    verifier keeps asserting the four columns are bare at `0007` — was caught by
    nothing in the suite: the script's new section was exercised only by a
    throwaway drill. A verifier nobody tests is a verifier that can rot into
    reporting a correct schema as broken, or worse, the reverse.
    """
    from scripts.check_schema import main
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "verified.db"
    MigrationRunner(db_path).upgrade(REVISION)

    code = main(["--db", str(db_path), "--revision", "0007", "--no-leads-check"])
    out = capsys.readouterr().out

    assert code == 0, out
    assert "FAIL" not in out
    for table in P12_PROJECT_FOREIGN_KEYS:
        assert f"{table}.project_id" in out, f"{table} is not verified at all: {out}"
    assert "semantic_layer is disabled" in out


def test_check_schema_still_verifies_a_database_left_at_0006(tmp_path, capsys):
    """The other half of the inversion, and the reason it is a flag.

    A database still at `0006` is a **legitimate** state — the operator's live
    one is exactly that until they run the upgrade themselves — and there the
    four columns must be bare, because a `REFERENCES projects` clause written
    before `0007` breaks every INSERT into that table silently.
    """
    from scripts.check_schema import main
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "still-0006.db"
    MigrationRunner(db_path).upgrade(PREVIOUS)

    code = main(["--db", str(db_path), "--revision", "0006", "--no-leads-check", "--skip-p12"])
    out = capsys.readouterr().out

    assert code == 0, out
    assert "is BARE" in out, "the pre-0007 assertion stopped running entirely"

    # And without the flag it must FAIL rather than quietly pass: the twelve
    # tables really are missing at 0006.
    failing = main(["--db", str(db_path), "--revision", "0006", "--no-leads-check"])
    assert failing == 1, "check_schema passed a 0006 database while expecting 0007"


def test_the_dangling_fk_guard_covers_0007():
    """The parametrised guard is only a guard if it picked this revision up."""
    from tests.test_migrations import _revisions_oldest_first

    assert REVISION in _revisions_oldest_first()


def test_the_head_is_0007_and_there_is_still_one_of_them():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    assert script.get_heads() == [REVISION]


def test_the_chain_is_still_ten_revisions_or_fewer():
    """[freeze §4.1]: *"Ten revisions. No eleventh without an amendment."*
    0007 is the seventh; three remain for P17, P19 and P25."""
    from tests.test_migrations import _revisions_oldest_first

    revisions = _revisions_oldest_first()
    assert len(revisions) == 7
    assert revisions[-1] == REVISION


# ---------------------------------------------------------------------------
# What P12 deliberately did not do
# ---------------------------------------------------------------------------


def test_leads_has_no_run_id(at_0007):
    """DI28, declined deliberately while ``0007`` was open.

    P11's handover named this the cheap moment. It was still declined: DI28's own
    entry records that ``scraped_at >= run.started_at`` is **exact** under the
    one-active-run constraint, so there is no failed measurement — and
    [lock §8] allows a mid-phase improvement only when it relates to the current
    phase. Pinned so the decision is visible rather than looking like an
    oversight; the next phase to open a revision may reverse it.
    """
    columns = {r[1] for r in at_0007.execute("PRAGMA table_info(leads)")}
    assert "run_id" not in columns


def test_the_three_absent_pre_score_components_are_still_absent():
    """⚠️ [PHASE-11-HANDOVER §6] hands this test's premise to P12, and P12 keeps
    all three absent — with the labels corrected.

    ``0007`` creates ``projects``, ``pain_points`` and ``bkb_entities``
    **empty**. A component reading an empty table scores 0.0 for every item,
    which is [DI24] verbatim and the thing ``ABSENT_COMPONENTS`` exists to
    prevent; and [PHASE-11-HANDOVER §4] T2 records that adding a seventh weight
    rescales every stored ``total``, invalidating the admission floor measured
    against six. Rescaling every score for components that can only be zero is
    strictly worse than waiting.

    What P12 *did* change is the labels: each now names the phase that supplies
    the **data** rather than the phase that supplies the column.
    """
    from src.scoring import ABSENT_COMPONENTS

    assert set(ABSENT_COMPONENTS) == {"pain_phrase", "competitor", "subreddit_fit"}
    assert ABSENT_COMPONENTS["pain_phrase"].startswith("P14")
    assert ABSENT_COMPONENTS["competitor"].startswith("P15")
    assert ABSENT_COMPONENTS["subreddit_fit"].startswith("P16")
    assert not any(label.startswith("P12") for label in ABSENT_COMPONENTS.values()), (
        "a component still names P12 as its supplier. 0007 creates the tables "
        "empty; the phase that writes the rows is the one that can score from them."
    )


def test_p12_wrote_no_row(at_0007):
    """Twelve empty tables. P16 writes the first project, P14 the first BKB."""
    for table in P12_TABLES:
        count = at_0007.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0, f"0007 seeded {count} rows into {table}"


def test_p12_makes_no_ai_call(at_0007):
    """A schema revision has no business calling a model. P11's G7, restated for
    a phase whose Deliverables mention none — which is exactly when nobody
    checks."""
    assert at_0007.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0


# The `/api/health` reporting of `semantic_layer` is tested in
# tests/test_schedule_and_health.py, where the app and client fixtures already
# live — a second app fixture here would be a second source of truth for how
# this application is started.
