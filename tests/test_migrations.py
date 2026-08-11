"""Migration foundation. These guard the live 459-row database."""

from __future__ import annotations

import hashlib
import json
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
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            # SQLite table names are case-insensitive, so the parent named in a
            # REFERENCES clause need not match sqlite_master's casing.
            present = {name.lower() for name in tables}

            dangling: list[str] = []
            for table in tables:
                for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
                    parent, column = row[2], row[3]
                    if parent.lower() not in present:
                        dangling.append(f"{table}.{column} -> {parent} (missing)")
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
