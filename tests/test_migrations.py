"""Migration foundation. These guard the live 459-row database."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE = PROJECT_ROOT / "tests" / "baseline" / "db_fingerprint.json"

#: The tables that existed before Alembic was introduced, i.e. exactly what
#: 0001_baseline creates. Frozen: this set must never grow.
BASELINE_TABLES = frozenset(
    {
        "leads",
        "subreddits",
        "dashboard_subreddits",
        "dashboard_keywords",
        "dashboard_search_queries",
        "settings",
        "tracked_users",
        "scrape_runs",
    }
)


def _dump_schema(db_path: Path, skip_tables: set[str] | None = None) -> str:
    skip = skip_tables or set()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'alembic%' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return "\n".join(f"{t} {n}\n{s}" for t, n, s in rows if n not in skip)


def test_single_head():
    """A branched history breaks `upgrade head` and is the defect this catches."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from src.db.migrate import MigrationRunner

    with tempfile.TemporaryDirectory() as tmp:
        runner = MigrationRunner(Path(tmp) / "x.db")
        assert runner.head_revision()

    # Assert the *property*, not a pinned revision id. Hardcoding the current
    # head made this test fail on every phase that adds a migration -- a
    # guaranteed false alarm that says nothing about whether the chain branched.
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1, f"migration history has branched: {heads}"


#: Columns added to a *baseline* table by a later revision.
#:
#: Until P1 no migration altered a pre-existing table, so
#: ``test_baseline_matches_create_all`` could compare 0001's DDL against today's
#: models directly. ``0004`` adds ``scrape_runs.run_id`` -- planned since
#: ``docs/05`` 4.2 -- so that comparison can never hold again unmodified.
#:
#: The guard is *not* weakened: the diverging table is excluded from the byte
#: comparison and then asserted exactly, so any *other* change to a baseline
#: table, or any further change to ``scrape_runs``, still fails.
POST_BASELINE_COLUMNS: dict[str, set[str]] = {
    "scrape_runs": {"run_id"},  # 0004_orchestration
    "leads": {  # 0006_content_and_dedup
        "project_id",
        "confidence_score",
        "analysis_status",
        "source",
    },
}

#: Indexes added to a *baseline* table by a later revision.
#:
#: Needed for the same reason as ``POST_BASELINE_COLUMNS``, and discovered the
#: same way -- by a failure. ``_dump_schema`` skips rows by their
#: ``sqlite_master.name``, which for an index is the **index's** name, not its
#: table's. So listing ``leads`` in ``POST_BASELINE_COLUMNS`` excludes the
#: ``CREATE TABLE leads`` row and nothing else; its four new indexes still reach
#: the byte comparison against a 0001 database that has none of them.
#:
#: ``0004`` never exposed this: ``scrape_runs`` gained a column and no index.
#:
#: ⚠️ **Named individually rather than skipping every index on the table**, so
#: ``ix_leads_intent_score`` and ``ix_leads_scraped_at`` -- which *do* date from
#: 0001 -- stay byte-compared. Excluding by table would have retired that check
#: silently, which is the weakening this list exists to avoid.
POST_BASELINE_INDEXES: set[str] = {
    "ix_leads_project_id",  # 0006_content_and_dedup
    "ix_leads_confidence_score",
    "ix_leads_analysis_status",
    "ix_leads_project_conf",
}


def test_baseline_matches_create_all():
    """0001 on empty must equal create_all() on empty, byte for byte.

    If this fails, the migration is wrong, not the test. Hand-derived DDL gets
    details like "unique=True + index=True yields a UNIQUE INDEX" wrong.

    Tables listed in ``POST_BASELINE_COLUMNS`` are compared by
    ``test_post_baseline_columns_are_exactly_as_declared`` instead, and the
    indexes those later revisions added are named in ``POST_BASELINE_INDEXES``.
    """
    from src.db.models import Base

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        via_create_all = tmp_path / "a.db"
        via_alembic = tmp_path / "b.db"

        engine = create_engine(f"sqlite:///{via_create_all}")
        # The eight tables that predate Alembic. Listed explicitly rather than
        # filtered by name prefix: a prefix rule silently swept in every later
        # phase's tables (proxies, http_cache, metrics in Phase 2) and turned a
        # correct migration into a failing test.
        legacy = [t for t in Base.metadata.sorted_tables if t.name in BASELINE_TABLES]
        assert len(legacy) == len(BASELINE_TABLES), "a baseline table is missing from models.py"
        Base.metadata.create_all(engine, tables=legacy)
        engine.dispose()

        import os

        env = dict(os.environ, ALEMBIC_DB_URL=f"sqlite:///{via_alembic}")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0001_baseline"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        skip = set(POST_BASELINE_COLUMNS) | POST_BASELINE_INDEXES
        assert _dump_schema(via_create_all, skip) == _dump_schema(via_alembic, skip)


def test_post_baseline_columns_are_exactly_as_declared():
    """A baseline table may only diverge from 0001 in ways we wrote down.

    This is the half of the guard that ``test_baseline_matches_create_all`` gives
    up by excluding a table. Without it, excluding ``scrape_runs`` would mean any
    future column could appear there unnoticed.
    """
    import sqlite3

    from src.db.models import Base

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline_db = tmp_path / "baseline.db"

        import os

        env = dict(os.environ, ALEMBIC_DB_URL=f"sqlite:///{baseline_db}")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0001_baseline"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        conn = sqlite3.connect(baseline_db)
        try:
            for table, added in POST_BASELINE_COLUMNS.items():
                at_baseline = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                in_model = {c.name for c in Base.metadata.tables[table].columns}
                assert in_model - at_baseline == added, (
                    f"{table} diverges from 0001 by {sorted(in_model - at_baseline)}, "
                    f"but only {sorted(added)} is declared in POST_BASELINE_COLUMNS"
                )
                assert at_baseline - in_model == set(), f"{table} lost a baseline column"
        finally:
            conn.close()


def test_fresh_database_upgrades_to_head(temp_db):
    from src.db.migrate import MigrationRunner

    runner = MigrationRunner(temp_db)
    assert runner.current_revision() == runner.head_revision()

    conn = sqlite3.connect(temp_db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    assert {"leads", "ai_calls", "ai_cache", "ai_provider_state"} <= tables


def test_live_database_preserved(live_db_copy):
    """AC1 / R20: the 459 original leads migrate with every score intact.

    **Scoped to the baseline rows, and that is the contract.** R20 protects the
    leads that existed before the rebuild; it does not freeze the table. The
    product's entire purpose is to add leads, and every manual test run does —
    P3's own testing took the live database from 459 rows to 469.

    This asserts the strong half unchanged: every baseline id still present, and
    the digest over their scores byte-identical. A deleted original drops the
    count; an altered score changes the digest. What it no longer asserts is that
    the database never grew, which was never the guarantee and is now provably
    false in normal operation.
    """
    from src.db.migrate import MigrationRunner

    if not BASELINE.exists():  # pragma: no cover
        pytest.skip("no baseline fingerprint recorded")
    baseline = json.loads(BASELINE.read_text())
    boundary = baseline["baseline_max_lead_id"]

    MigrationRunner(live_db_copy).ensure_current()

    conn = sqlite3.connect(live_db_copy)
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        rows = conn.execute(
            "SELECT id, intent_score FROM leads WHERE id <= ? ORDER BY id", (boundary,)
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == baseline["lead_count"], (
        f"{baseline['lead_count'] - len(rows)} of the original leads are missing"
    )
    digest = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    assert digest == baseline["intent_score_sha256"], "an original intent_score changed"
    assert total >= baseline["lead_count"]


def test_downgrade_round_trip(temp_db):
    from src.db.migrate import MigrationRunner

    runner = MigrationRunner(temp_db)
    runner.downgrade("0001_baseline")
    assert runner.current_revision() == "0001_baseline"

    conn = sqlite3.connect(temp_db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "ai_calls" not in tables
    assert "leads" in tables

    runner.upgrade("head")
    assert runner.current_revision() == runner.head_revision()


def test_backup_uses_sqlite_api(temp_db):
    """A file copy is unsafe under WAL; the backup API accounts for it."""
    from src.db.migrate import MigrationRunner

    backup = MigrationRunner(temp_db).backup()
    assert backup is not None and backup.exists()

    conn = sqlite3.connect(backup)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "leads" in tables


def _dangling_foreign_keys(conn: sqlite3.Connection) -> list[str]:
    """Every FK whose parent table does not exist in this database.

    Shared by the chain guard and the rollback test, so both mean the same thing
    by "dangling". SQLite table names are case-insensitive, so the parent named
    in a REFERENCES clause need not match ``sqlite_master``'s casing.
    """
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    present = {name.lower() for name in tables}

    dangling: list[str] = []
    for table in tables:
        for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
            parent, column = row[2], row[3]
            if parent.lower() not in present:
                dangling.append(f"{table}.{column} -> {parent} (missing)")
    return dangling


def _revisions_oldest_first() -> list[str]:
    """Every revision id in the chain, `0001` first.

    Derived from the script directory rather than hardcoded, for the reason
    ``test_single_head`` gives: a pinned list fails on every phase that adds a
    migration, which is a guaranteed false alarm that says nothing.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


@pytest.mark.parametrize("revision", _revisions_oldest_first())
def test_no_revision_leaves_a_dangling_foreign_key(revision):
    """A ``REFERENCES`` target that does not exist **at that revision**.

    This is the guard for [P8 review F1]. The defect it catches is specific and
    it is invisible to everything else the project runs:

    ``ALTER TABLE leads ADD COLUMN project_id INTEGER REFERENCES projects(id)``
    written at ``0006``, when ``projects`` does not arrive until ``0007``,
    **succeeds**. ``SELECT`` keeps working. ``PRAGMA foreign_key_check`` returns
    ``[]``. The up/down/up round-trip is pure DDL and passes. ``check_schema.py``
    only reads. And yet **every** ``INSERT`` into ``leads`` fails with
    ``no such table: main.projects`` -- including one that sets ``project_id`` to
    ``NULL``, because SQLite resolves the parent table at statement-prepare time,
    not at constraint-check time. There is no value that avoids it.

    So the assertion is made on the *constraint*, not on an insert.
    ``PRAGMA foreign_key_list`` names the parent table directly, at every
    revision, **with no fixture rows at all**. That is what makes this affordable
    to run over the whole chain: the alternative -- inserting into every table at
    every revision -- needs a valid row for ``jobs``, ``run_events``,
    ``prescores`` (an FK *and* the ``(lead_id IS NOT NULL) <> (comment_id IS NOT
    NULL)`` CHECK), ``dedup_members`` and more, at six revisions and growing
    (D5, option B′, rejected on cost).

    ⚠️ ``PRAGMA foreign_key_check`` is **not** a substitute and was measured to
    fail here: it validates *data* against constraints it can resolve, and says
    nothing about a constraint whose parent table is missing.

    Parametrised over every revision so this covers ``0007``–``0010`` as they
    land, not only ``0006``. Same idiom as P5's
    ``test_conditional_get_has_not_been_reintroduced`` and P6's
    ``test_the_density_heuristic_was_not_reintroduced``: prevent the *class*,
    not the instance.
    """
    from src.db.migrate import MigrationRunner

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "chain.db"
        MigrationRunner(db_path).upgrade(revision)

        conn = sqlite3.connect(db_path)
        try:
            dangling = _dangling_foreign_keys(conn)
        finally:
            conn.close()

    assert not dangling, (
        f"revision {revision} leaves a foreign key pointing at a table that does "
        f"not exist yet: {dangling}. Every INSERT into that table already fails "
        f"with 'no such table', even with the column set to NULL -- while "
        f"foreign_key_check, the DDL round-trip and check_schema.py all report "
        f"green. Use a bare column here and close the FK with batch_alter_table "
        f"in the revision that creates the parent (freeze M8)."
    )


# ---------------------------------------------------------------------------
# 0006_content_and_dedup — P8 Stage 4
#
# ⚠️ **What is deliberately NOT tested here: the dedup_members "one group per
# run" invariant.** 05 §5.4b states it, and it is *not expressible in this
# schema* (P8 review F7): there is no `run_id` on `dedup_members`, the run is
# reachable only through `dedup_groups`, and SQLite cannot constrain uniqueness
# across a join. Two groups from the same run can each claim the same lead and
# every index stays satisfied. Writing a test that appeared to check it would be
# worse than the gap, because it would retire the question. It is P10's, to
# uphold in the application and to test there.
# ---------------------------------------------------------------------------

P8_TABLES = ("comments", "dedup_groups", "dedup_members", "minhash_bands")
P8_LEAD_COLUMNS = ("project_id", "confidence_score", "analysis_status", "source")


def _raw_copy(tmp_path: Path) -> Path:
    """A copy of the live database that has **not** been migrated.

    ``live_db_copy`` runs ``init_db``, which upgrades to head — correct for most
    tests and useless for the two that need to observe the *transition*.
    """
    source = PROJECT_ROOT / "data" / "leads.db"
    if not source.exists():  # pragma: no cover
        pytest.skip("no live database present")
    target = tmp_path / "raw.db"
    shutil.copy(source, target)
    return target


def test_a7_a8_a_lead_and_a_comment_can_be_inserted_at_0006(tmp_path):
    """The F1 failure mode, proven end to end rather than by proxy.

    ``test_no_revision_leaves_a_dangling_foreign_key`` asserts on the
    *constraint*, which is what makes it affordable across every revision. This
    asserts on the *effect*, at the one revision P8 owns. Both matter: the guard
    would still pass if SQLite ever changed when it resolves a REFERENCES
    target, and this would not.
    """
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "insert.db"
    MigrationRunner(db_path).upgrade("0006_content_and_dedup")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, scraped_at) "
            "VALUES ('t3_a7', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01')"
        )
        lead_id = conn.execute("SELECT id FROM leads WHERE reddit_id='t3_a7'").fetchone()[0]
        conn.execute(
            "INSERT INTO comments (lead_id, body, scraped_at, body_hash) "
            "VALUES (?, 'b', '2026-01-01', 'hash-a8')",
            (lead_id,),
        )
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_dangling_fk_guard_actually_covers_0006():
    """4.1 — confirm the parametrised guard *picked 0006 up*, not skipped it.

    A parametrised test that silently stops covering a revision reports the same
    green as one that covers it. This asserts the parameter list itself.
    """
    revisions = _revisions_oldest_first()
    assert "0006_content_and_dedup" in revisions, (
        f"the dangling-FK guard is not covering 0006: {revisions}"
    )
    assert revisions[0] == "0001_baseline"


def test_a2_every_existing_lead_gets_the_documented_defaults(live_db_copy):
    """A2 — **every** row, not a sample.

    ⚠️ The count is asserted as *"the number of correctly-defaulted rows equals
    the total"* rather than against a hardcoded 478. That is strictly stronger,
    not weaker: 478 was true on 2026-08-11 and the scraper's whole purpose is to
    change it, so a pinned literal would fail on the first new lead while proving
    nothing extra. What must hold forever is that **no row was left behind by the
    ALTER**, and that is what this asserts. The floor of 459 keeps it honest
    against an empty table trivially satisfying the equality.
    """
    conn = sqlite3.connect(live_db_copy)
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}
        assert set(P8_LEAD_COLUMNS) <= columns, f"0006 columns missing: {columns}"

        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        defaulted = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE project_id IS NULL "
            "AND confidence_score IS NULL "
            "AND analysis_status = 'not_analyzed' "
            "AND source = 'scrape'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert total >= 459, "the live copy lost baseline rows before the assertion could run"
    assert defaulted == total, (
        f"{total - defaulted} of {total} leads did not receive the documented defaults"
    )


def test_a5_the_legacy_intent_score_fingerprint_survives_0006(live_db_copy):
    """A2/A5 — the 459 originals and their scores, after the ALTER.

    ``check_schema.py`` pins these same two numbers; asserting them here as well
    is deliberate, because the two run in different places. The script is what a
    human runs from the manual guide, and it is not in CI.
    """
    if not BASELINE.exists():  # pragma: no cover
        pytest.skip("no baseline fingerprint recorded")
    baseline = json.loads(BASELINE.read_text())
    boundary = baseline["baseline_max_lead_id"]

    conn = sqlite3.connect(live_db_copy)
    try:
        count = conn.execute("SELECT COUNT(*) FROM leads WHERE id <= ?", (boundary,)).fetchone()[0]
        hi, avg = conn.execute(
            "SELECT MAX(intent_score), AVG(intent_score) FROM leads WHERE id <= ?", (boundary,)
        ).fetchone()
        rows = conn.execute(
            "SELECT id, intent_score FROM leads WHERE id <= ? ORDER BY id", (boundary,)
        ).fetchall()
    finally:
        conn.close()

    assert count == baseline["lead_count"]
    assert round(hi, 2) == baseline["baseline_intent_score_max"] == 164.28
    assert round(avg, 2) == baseline["baseline_intent_score_avg"] == 42.29
    digest = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    assert digest == baseline["intent_score_sha256"], "0006 altered an original intent_score"


def test_a3_the_alter_did_not_rewrite_a_single_row(tmp_path):
    """A3 — metadata-only, proven by ``rootpage``, not by a clock.

    A rewritten table gets a **new** root b-tree page; an ``ADD COLUMN`` that
    only edits the table header does not. Comparing ``sqlite_master.rootpage``
    across the upgrade is therefore a direct observation of "no row was
    touched".

    ⚠️ **Deliberately not a wall-clock assertion.** A6's *"< 1 s"* and DI18's
    ``test_parse_speed_stays_inside_the_budget`` are the same species, and DI18
    has already failed three times for machine load rather than for slowness.
    A timing test here would measure the CI runner, not the migration.

    ⚠️ **Pinned to ``0006``, not ``head``, from P12 on.** This asserts a property
    of *this* revision -- that its four ``ADD COLUMN``s are metadata-only. ``0007``
    legitimately **does** rebuild ``leads``, because closing the deferred
    ``project_id`` foreign key needs a create-copy-drop-rename and SQLite has no
    ``ADD CONSTRAINT``. Left as ``head`` this test would have read that correct
    rebuild as a P8 defect. The assertion below is unchanged; only the revision
    it is made at is pinned to the one the docstring is about. ``0007``'s
    equivalent guarantee -- that the rebuild preserved every row, score and index
    -- is asserted by ``tests/test_schema_0007.py::
    test_up_down_up_on_a_copy_of_the_live_database``.
    """
    from src.db.migrate import MigrationRunner

    db_path = _raw_copy(tmp_path)

    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute(
            "SELECT rootpage FROM sqlite_master WHERE type='table' AND name='leads'"
        ).fetchone()[0]
        before_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    finally:
        conn.close()

    MigrationRunner(db_path).upgrade("0006_content_and_dedup")

    conn = sqlite3.connect(db_path)
    try:
        after = conn.execute(
            "SELECT rootpage FROM sqlite_master WHERE type='table' AND name='leads'"
        ).fetchone()[0]
        after_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    finally:
        conn.close()

    assert after == before, (
        f"leads was rewritten: rootpage moved {before} -> {after}. 0006 must be "
        f"metadata-only (M5); a row rewrite over the legacy rows is the one thing "
        f"the ALTER may not do."
    )
    assert after_count == before_count


def test_a9_the_named_check_survives_the_prescores_rebuild(live_db_copy):
    """A9 — ``batch_alter_table`` rebuilds by reflection, and CHECKs are its weak spot.

    Step 2.8 closes ``prescores.comment_id`` with a copy-and-move rebuild. If
    SQLAlchemy's reflection drops the named CHECK on the way through, the
    constraint is gone and **nothing else would notice**: no test inserts a
    prescores row with both targets set, and the FK closure it was rebuilt for
    would still look correct.
    """
    conn = sqlite3.connect(live_db_copy)
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='prescores'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert "ck_prescores_one_target" in sql, (
        f"the named CHECK did not survive the batch rebuild:\n{sql}"
    )


def test_a9_the_prescores_check_is_still_enforced(live_db_copy):
    """The CHECK, asserted by effect rather than by presence.

    A constraint that exists in the DDL text but is not enforced is the failure
    this pairs with the test above to exclude.
    """
    conn = sqlite3.connect(live_db_copy)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO prescores (run_id, lead_id, comment_id, total, components_json, "
                "stage, gate_decision, created_at) "
                "VALUES (NULL, NULL, NULL, 1.0, '{}', 'full', 'admit', '2026-01-01')"
            )
    finally:
        conn.close()


def test_the_deferred_prescores_fk_is_enforced_not_merely_present(tmp_path):
    """4.6 — ``fk_prescores_comment`` bites, asserted by effect.

    ``PRAGMA foreign_key_list`` reporting the constraint proves only that the
    DDL says so. What P8 task 4 owes is a constraint that **rejects a bad
    write**, which is a different claim and the one worth testing.
    """
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "fk.db"
    MigrationRunner(db_path).upgrade("head")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        parents = {(r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(prescores)")}
        assert ("comments", "comment_id") in parents, f"FK absent: {sorted(parents)}"

        conn.execute(
            "INSERT INTO runs (state, started_at, updated_at) "
            "VALUES ('complete', '2026-01-01', '2026-01-01')"
        )
        run_id = conn.execute("SELECT id FROM runs").fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO prescores (run_id, lead_id, comment_id, total, components_json, "
                "stage, gate_decision, created_at) VALUES (?, NULL, 999999, 1.0, '{}', 'full', "
                "'admit', '2026-01-01')",
                (run_id,),
            )
    finally:
        conn.close()


def test_a1_up_down_up_on_a_copy_of_the_live_database(tmp_path):
    """A1 — the rollback, on real data, with the count checked at every stage.

    ⚠️ **The downgraded schema is checked for validity, not only for absence.**
    Row counts, missing tables and missing columns are all satisfied by a
    rollback that leaves ``prescores`` pointing at the ``comments`` table it just
    dropped -- and that database is **broken**: every INSERT into ``prescores``
    fails with ``no such table: main.comments``. It is F1 again, arriving through
    the rollback path rather than the upgrade path.

    ``test_no_revision_leaves_a_dangling_foreign_key`` cannot catch it, because
    it walks the chain *upward* and never observes the post-downgrade state. That
    asymmetry was found by mutation S3, which deleted step 2.9's
    ``drop_constraint`` and survived every assertion this test originally made.

    It also means step 2.9's stated reason is not the real one: SQLite permits
    dropping a referenced parent in every configuration (measured, with
    ``foreign_keys`` both ON and OFF, with the child table both empty and
    populated). The hazard is not the drop failing -- it is the reference left
    behind.
    """
    from src.db.migrate import MigrationRunner

    db_path = _raw_copy(tmp_path)
    runner = MigrationRunner(db_path)

    def leads_and_head() -> tuple[int, str | None]:
        conn = sqlite3.connect(db_path)
        try:
            return (
                conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
                runner.current_revision(),
            )
        finally:
            conn.close()

    # ⚠️ `0006`, not `head`. This test is P8's 0006 round-trip and its three
    # revision assertions say so; once P12 made `head` mean `0007` the literal
    # `head` would have silently retargeted it to a different rollback. Pinned
    # rather than loosened -- the assertions below are unchanged.
    runner.upgrade("0006_content_and_dedup")
    up_count, up_rev = leads_and_head()
    assert up_rev == "0006_content_and_dedup"

    runner.downgrade("0005_discovery")
    down_count, down_rev = leads_and_head()
    assert down_rev == "0005_discovery"

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}

        # (a) The downgraded schema references nothing that is gone.
        dangling = _dangling_foreign_keys(conn)

        # (b) And it is actually writable. A dangling REFERENCES is invisible to
        #     every structural check -- foreign_key_check returns [] -- so the
        #     only thing that proves it is a write.
        conn.execute(
            "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, scraped_at) "
            "VALUES ('t3_rb', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01')"
        )
        lead_id = conn.execute("SELECT id FROM leads WHERE reddit_id='t3_rb'").fetchone()[0]
        conn.execute(
            "INSERT INTO runs (state, started_at, updated_at) "
            "VALUES ('complete', '2026-01-01', '2026-01-01')"
        )
        run_id = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO prescores (run_id, lead_id, comment_id, total, components_json, "
            "stage, gate_decision, created_at) "
            "VALUES (?, ?, NULL, 1.0, '{}', 'full', 'admit', '2026-01-01')",
            (run_id, lead_id),
        )
        conn.rollback()  # leave the copy as the later stages expect to find it

        # (c) PRAGMA integrity/foreign_key_check on the rolled-back schema.
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()

    assert not (set(P8_TABLES) & tables), f"downgrade left P8 tables behind: {tables}"
    assert not (set(P8_LEAD_COLUMNS) & columns), f"downgrade left P8 columns behind: {columns}"
    assert not dangling, (
        f"the downgrade left a dangling foreign key: {dangling}. Every INSERT "
        f"into that table now fails with 'no such table'. 0006's downgrade must "
        f"drop the prescores constraint BEFORE dropping comments (step 2.9)."
    )
    assert not fk_violations, f"downgrade left FK violations: {fk_violations}"
    assert integrity == "ok", f"downgrade corrupted the database: {integrity}"

    runner.upgrade("0006_content_and_dedup")
    re_count, re_rev = leads_and_head()
    assert re_rev == "0006_content_and_dedup"

    assert up_count == down_count == re_count >= 459, (
        f"a lead was lost across the round-trip: {up_count} -> {down_count} -> {re_count}"
    )


def test_the_dedup_members_partial_uniques_behave(tmp_path):
    """4.8 — partial, not plain. The difference is the whole point.

    A plain ``UNIQUE (group_id, lead_id)`` would treat every NULL ``lead_id`` as
    distinct in SQLite and so would *appear* to work — while also constraining
    comment-only rows it has no business constraining. The ``WHERE`` clause is
    what makes each index apply to its own kind of row, and dropping it is a
    mutation nothing else in the suite catches.
    """
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "dedup.db"
    MigrationRunner(db_path).upgrade("head")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, scraped_at) "
            "VALUES ('t3_d', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01')"
        )
        lead_id = conn.execute("SELECT id FROM leads").fetchone()[0]
        conn.execute(
            "INSERT INTO comments (lead_id, body, scraped_at, body_hash) "
            "VALUES (?, 'b', '2026-01-01', 'h-dedup')",
            (lead_id,),
        )
        comment_id = conn.execute("SELECT id FROM comments").fetchone()[0]
        conn.execute("INSERT INTO dedup_groups (method, created_at) VALUES ('exact', '2026-01-01')")
        group_id = conn.execute("SELECT id FROM dedup_groups").fetchone()[0]

        conn.execute(
            "INSERT INTO dedup_members (group_id, lead_id) VALUES (?, ?)", (group_id, lead_id)
        )
        conn.commit()

        # The partial unique bites on a real duplicate.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO dedup_members (group_id, lead_id) VALUES (?, ?)",
                (group_id, lead_id),
            )
        conn.rollback()

        # A comment-only row in the same group does NOT collide with the lead row,
        # which is what the WHERE clause buys.
        conn.execute(
            "INSERT INTO dedup_members (group_id, comment_id) VALUES (?, ?)",
            (group_id, comment_id),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM dedup_members").fetchone()[0] == 2

        # And the CHECK still refuses a row that names both, or neither.
        #
        # ⚠️ **A SECOND, EMPTY GROUP is used deliberately.** Asserting this
        # against `group_id` would prove nothing: that group already holds
        # (group_id, lead_id), so a both-set row violates
        # `ux_dedup_members_lead` whether or not the CHECK exists. A mutation
        # that deleted `ck_dedup_members_one_target` survived against the
        # original form of this test for exactly that reason -- the unique index
        # masked the assertion. Same species as P7's "masked by a second guard".
        conn.execute("INSERT INTO dedup_groups (method, created_at) VALUES ('exact', '2026-01-01')")
        empty_group = conn.execute(
            "SELECT id FROM dedup_groups ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError):  # both targets named
            conn.execute(
                "INSERT INTO dedup_members (group_id, lead_id, comment_id) VALUES (?, ?, ?)",
                (empty_group, lead_id, comment_id),
            )
        conn.rollback()

        with pytest.raises(sqlite3.IntegrityError):  # neither target named
            conn.execute(
                "INSERT INTO dedup_members (group_id, lead_id, comment_id) VALUES (?, NULL, NULL)",
                (empty_group,),
            )
    finally:
        conn.close()


def test_ux_comments_hash_rejects_a_duplicate_body_hash(tmp_path):
    """4.9 — ``body_hash`` is the dedup key, so the index must actually be unique."""
    from src.db.migrate import MigrationRunner

    db_path = tmp_path / "comments.db"
    MigrationRunner(db_path).upgrade("head")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            "INSERT INTO leads (reddit_id, subreddit, author, title, url, created_utc, scraped_at) "
            "VALUES ('t3_c', 's', 'a', 't', 'u', '2026-01-01', '2026-01-01')"
        )
        lead_id = conn.execute("SELECT id FROM leads").fetchone()[0]
        conn.execute(
            "INSERT INTO comments (lead_id, body, scraped_at, body_hash) "
            "VALUES (?, 'first', '2026-01-01', 'same-hash')",
            (lead_id,),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO comments (lead_id, body, scraped_at, body_hash) "
                "VALUES (?, 'second', '2026-01-01', 'same-hash')",
                (lead_id,),
            )
    finally:
        conn.close()


def test_pragmas_applied_on_every_connection(temp_db):
    """foreign_keys is per-connection and OFF by default in SQLite."""
    from sqlalchemy import text

    from src.db.database import ENGINE

    for _ in range(3):
        with ENGINE.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 10000


def test_init_db_does_not_call_create_all(temp_db, monkeypatch):
    """Schema is owned by Alembic.

    A stray create_all() would create whatever is in models.py and then collide
    with the migration meant to create it.
    """
    from src.db import database
    from src.db.models import Base

    called = False

    def boom(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(Base.metadata, "create_all", boom)
    database.init_db(temp_db)
    assert not called
