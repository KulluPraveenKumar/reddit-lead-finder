"""Verify a database's shape against the schema the phase specified.

**Why this exists.** ``docs/testing/P01-testing.md`` T5 originally checked the
schema with five ``python -c "import sqlite3; ..."`` one-liners, the longest of
them 350 characters on a single line. They were correct, and they were also
unusable by the non-developer the guide is written for: a mistyped bracket
produced a ``SyntaxError`` about quoting rather than an answer about the
database, and the guide had to carry a paragraph explaining PowerShell's
handling of ``\\"`` to make them survive a copy-paste.

This script replaces them with one command that prints one verdict per check.

**Why stdlib only.** ``sqlite3`` and ``argparse`` ship with Python, so this runs
on Windows, macOS and Linux with the interpreter the project already requires
and nothing else. In particular it does **not** need the ``sqlite3`` *command
line tool*, which is absent from a default Windows install. It also adds no
dependency, which ``docs/ARCHITECTURE_FREEZE.md`` §5 would otherwise forbid.

**What it is not.** Not a test. ``tests/test_orchestration.py`` and
``tests/test_migrations.py`` remain the enforcement; this is the operator-facing
view of the same facts, so a human running the manual guide sees *why* a check
failed rather than a pytest traceback.

Usage::

    python scripts/check_schema.py --db data/p1-test.db
    python scripts/check_schema.py --db data/leads.db --revision 0003 --skip-p1

Exit code is 0 when every check passes and 1 when any fails, so it can also be
used as a gate in a script.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# The specification, transcribed from docs/05-database-plan.md and
# docs/04-system-design.md. Written out here rather than imported from
# src.db.models on purpose: a check that reads the same declaration the
# migration reads would agree with itself no matter what shipped.
# ---------------------------------------------------------------------------

#: Every table present once 0004 is applied. Sorted; compared as a set.
EXPECTED_TABLES_AT_0004 = (
    "ai_cache",
    "ai_calls",
    "ai_provider_state",
    "alembic_version",
    "dashboard_keywords",
    "dashboard_search_queries",
    "dashboard_subreddits",
    "http_cache",
    "jobs",
    "leads",
    "metrics",
    "proxies",
    "run_events",
    "runs",
    "scrape_runs",
    "settings",
    "subreddits",
    "tracked_users",
)

#: What 0005 adds. Kept separate from the 0004 set so `--skip-p6` can check a
#: database that has not been upgraded yet, the same way `--skip-p1` does.
EXPECTED_TABLES_AT_0005 = (
    "discovery_watermarks",
    "prescores",
)

#: What 0006 adds. Same separation, same reason: a database still at 0005 is a
#: legitimate state to verify, not a broken one.
#:
#: ⚠️ **Presence only.** The *shape* of these four tables -- their columns,
#: defaults, indexes and constraints -- is asserted by P8 Stage 4, not here.
#: This entry exists so that the checks which already existed keep meaning what
#: they say once 0006 lands: without it, `no unexpected tables` fails on four
#: tables that are entirely expected, which would be the verifier reporting its
#: own staleness as a schema defect.
EXPECTED_TABLES_AT_0006 = (
    "comments",
    "dedup_groups",
    "dedup_members",
    "minhash_bands",
)

#: What 0007 adds. Twelve, and the same separation for the same reason: a
#: database still at 0006 is a legitimate state to verify (`--skip-p12`), and the
#: live database stays there until an operator runs the upgrade themselves.
EXPECTED_TABLES_AT_0007 = (
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

#: The conditional pair, plus whatever shadow tables ``vec0`` creates beside a
#: virtual table. **Optional, never required**: they exist only where the
#: ``sqlite-vec`` extension loads, which is no host measured so far. Matched by
#: prefix rather than by name because the shadow-table names are the extension's
#: private business, and a verifier that hard-coded them would report a working
#: database as broken the day the extension changed them.
OPTIONAL_TABLE_PREFIX = "bkb_embedding"

#: The six deferred ``project_id`` foreign keys 0007 closes, with the ON DELETE
#: action each ships. The actions are deliberately not uniform:
#:
#: * ``leads`` and ``comments`` are **SET NULL** because [freeze §8] makes
#:   "expiring leads" a permanent non-goal -- *a lead is a historical fact* --
#:   so deleting a project must not delete the corpus collected for it.
#: * ``dedup_groups`` and ``minhash_bands`` are **CASCADE** because both are
#:   derived per-run artefacts that are rebuilt from scratch.
#: * ``ai_calls`` (SET NULL) and ``runs`` (CASCADE) are given literally in
#:   [05 §7.1].
#:
#: If these ever become uniform, one of them is wrong.
EXPECTED_PROJECT_FOREIGN_KEYS = {
    "ai_calls": "SET NULL",
    "runs": "CASCADE",
    "leads": "SET NULL",
    "comments": "SET NULL",
    "dedup_groups": "CASCADE",
    "minhash_bands": "CASCADE",
}

#: The three BKB sections whose content lives in a typed table, so their
#: ``bkb_sections.payload_json`` is NULL and the other twenty are not.
#: ``ideal_customer_profiles`` is **not** one of them -- it has no typed table,
#: so its payload is the only copy of an ICP that exists ([05 §5.1b]).
TYPED_SECTION_KEYS = ("buyer_personas", "pain_points", "buying_signals")

#: Unique indexes 0007 creates. Uniqueness is the point of every one of them:
#: each is the natural key some later phase upserts on, and a non-unique index
#: there would let a regeneration silently double every row it rewrote.
EXPECTED_UNIQUE_INDEXES_AT_0007 = (
    "ux_projects_normalized_url",
    "ux_bkb_sections",
    "ux_personas_project_slug",
    "ux_pain_points_project_slug",
    "ux_intent_signals_project_slug",
    "ux_bkb_entities",
    "ux_bkb_alias_norm",
    "ux_bkb_links",
)

#: Index name -> the column order the query planner needs.
#:
#: Order matters and presence does not. ``ix_jobs_claim`` backs
#: ``WHERE state=? AND available_at<=? ORDER BY priority, id``; with the columns
#: in any other order the index still "exists" and the claim degrades to a table
#: scan under exactly the load it was built for.
EXPECTED_INDEXES = {
    "ix_jobs_claim": ["state", "available_at", "priority", "id"],
    "ix_jobs_run": ["run_id", "state"],
    "ix_jobs_lease": ["state", "lease_expires_at"],
    "ix_run_events_run": ["run_id", "id"],
    "ix_runs_project_state": ["project_id", "state"],
}

#: Table -> (referenced table, referenced column, ON DELETE action).
#:
#: The two actions are deliberately different and the difference is the point:
#: ``SET NULL`` means deleting a run never deletes its spend history or its
#: legacy scrape record; ``CASCADE`` means deleting a run does clean up its own
#: work items. If these ever match each other, one of them is wrong.
EXPECTED_FOREIGN_KEYS = {
    "ai_calls": ("runs", "run_id", "SET NULL"),
    "scrape_runs": ("runs", "run_id", "SET NULL"),
    "jobs": ("runs", "run_id", "CASCADE"),
    "run_events": ("runs", "run_id", "CASCADE"),
}

#: The `runs` columns, in declaration order.
EXPECTED_RUNS_COLUMNS = [
    "id",
    "project_id",
    "state",
    "options_json",
    "stats_json",
    "llm_cost_usd",
    "error",
    "started_at",
    "updated_at",
    "finished_at",
]

#: Column names that would give a human gate an expiry.
#:
#: A gate that expires proceeds without the human it exists to wait for, which
#: defeats the quality mechanism the pipeline is built on (AD-6). There is
#: nothing to assert positively about an absent feature, so the absence itself
#: is the check.
FORBIDDEN_EXPIRY_COLUMNS = frozenset({"expires_at", "timeout_at", "deadline", "ttl", "expiry"})

#: The legacy contract from ARCHITECTURE_FREEZE R20. A migration that changed
#: any of these has destroyed data, whatever else it did correctly.
#:
#: **Scoped to the baseline rows, not the whole table.** R20 protects the leads
#: that existed before the rebuild; it does not freeze the database. From P3
#: onwards the product collects new leads every time it runs, so asserting a
#: total would report normal operation as data loss. `BASELINE_MAX_LEAD_ID` is
#: the boundary: ids at or below it are the original 459.
EXPECTED_LEADS = 459
BASELINE_MAX_LEAD_ID = 459
EXPECTED_INTENT_MAX = 164.28
EXPECTED_INTENT_AVG = 42.29

#: Legal state values, transcribed from `src/orchestration/states.py`. Kept here
#: rather than imported so this script stays runnable against any database with
#: nothing but the standard library.
LEGAL_RUN_STATES = frozenset(
    {
        "pending",
        "profiling",
        "discovering",
        "awaiting_subreddit_review",
        "generating_keywords",
        "awaiting_keyword_review",
        "awaiting_options",
        "scraping",
        "analyzing",
        "complete",
        "failed",
        "cancelled",
    }
)
LEGAL_JOB_STATES = frozenset({"queued", "running", "done", "failed", "cancelled"})


class Report:
    """Collects verdicts so every check runs before anything reports failure.

    Stopping at the first failure would make the operator re-run the script once
    per problem. One pass, one list.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.failures: list[str] = []
        self.checks = 0
        self.verbose = verbose

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        self.checks += 1
        if ok:
            print(f"  PASS  {label}")
            if detail and self.verbose:
                print(f"          {detail}")
        else:
            print(f"  FAIL  {label}")
            if detail:
                print(f"          {detail}")
            self.failures.append(label)
        return ok

    def section(self, title: str) -> None:
        print(f"\n{title}")

    def summary(self) -> int:
        print()
        if self.failures:
            print(f"FAILED — {len(self.failures)} of {self.checks} checks did not pass:")
            for name in self.failures:
                print(f"  - {name}")
            return 1
        print(f"OK — all {self.checks} checks passed.")
        return 0


def _index_columns(conn: sqlite3.Connection, name: str) -> list[str] | None:
    """Column order for an index, or None when the index does not exist.

    ``PRAGMA index_info`` on a missing index returns an empty result rather than
    raising, so 'absent' and 'present but empty' need distinguishing here or a
    dropped index would read as a column-order mismatch.
    """
    rows = list(
        conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,))
    )
    if not rows:
        return None
    return [r[2] for r in conn.execute(f"PRAGMA index_info({name})")]


def check_integrity(conn: sqlite3.Connection, report: Report) -> None:
    """Is the file itself sound, before anything is asserted about its shape?

    A corrupt page or a violated foreign key makes every later check meaningless,
    so these run first.
    """
    report.section("Database integrity")

    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    report.check(result == "ok", "integrity_check reports ok", f"got: {result}")

    violations = list(conn.execute("PRAGMA foreign_key_check"))
    report.check(
        not violations,
        "no foreign key violations",
        f"{len(violations)} violation(s): {violations[:5]}",
    )


def check_revision(conn: sqlite3.Connection, report: Report, expected: str | None) -> None:
    report.section("Migration version")

    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    actual = row[0] if row else "(none)"

    if expected is None:
        print(f"  INFO  alembic_version is {actual}")
        return

    # Accept the short form ("0003") as well as the full revision id, because
    # that is what `alembic downgrade` takes and what the operator will type.
    ok = actual == expected or actual.startswith(expected)
    report.check(ok, f"alembic_version is {expected}", f"got: {actual}")


def check_tables(
    conn: sqlite3.Connection,
    report: Report,
    *,
    with_p6: bool = True,
    with_p8: bool = True,
    with_p12: bool = True,
) -> None:
    report.section("Tables")

    actual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    actual = {t for t in actual if not t.startswith("sqlite_")}
    expected = set(EXPECTED_TABLES_AT_0004)
    if with_p6:
        expected |= set(EXPECTED_TABLES_AT_0005)
    if with_p8:
        expected |= set(EXPECTED_TABLES_AT_0006)
    if with_p12:
        expected |= set(EXPECTED_TABLES_AT_0007)

    missing = sorted(expected - actual)
    # The vector tables are expected-if-present and never expected-if-absent, so
    # they are excluded from `extra` rather than added to `expected`. Listing
    # them as expected would turn "this host has no sqlite-vec" -- the normal
    # case -- into a missing-table failure.
    extra = sorted(t for t in actual - expected if not t.startswith(OPTIONAL_TABLE_PREFIX))

    report.check(not missing, f"all {len(expected)} expected tables present", f"missing: {missing}")
    report.check(not extra, "no unexpected tables", f"unexpected: {extra}")


def check_discovery_shape(
    conn: sqlite3.Connection, report: Report, *, with_p8: bool = True
) -> None:
    """The 0005 constraints that are easy to get wrong and silent when wrong."""
    report.section("Discovery (0005)")

    # The partial uniques. A plain (subreddit, channel, query) unique index does
    # NOT constrain listing rows, because SQLite treats NULLs as distinct — so
    # the check that matters is behavioural, not "an index exists".
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(discovery_watermarks)")}
    report.check(
        "ux_watermarks_listing" in indexes,
        "ux_watermarks_listing exists — listing rows are actually unique",
        f"got: {sorted(indexes)}",
    )
    report.check(
        "ux_watermarks_search" in indexes,
        "ux_watermarks_search exists",
        f"got: {sorted(indexes)}",
    )

    columns = {r[1] for r in conn.execute("PRAGMA table_info(discovery_watermarks)")}
    report.check(
        not ({"last_etag", "last_modified"} & columns),
        "discovery_watermarks has no last_etag/last_modified — U4 was refuted",
        f"got: {sorted(columns)}",
    )

    prescore_columns = {r[1] for r in conn.execute("PRAGMA table_info(prescores)")}
    report.check(
        "stage" in prescore_columns,
        "prescores.stage exists — metadata triage is auditable (R11)",
        f"got: {sorted(prescore_columns)}",
    )

    # comment_id was bare from 0005 until 0006, which creates `comments` and
    # closes the FK with batch_alter_table (M8). The check is INVERTED rather
    # than deleted: "the deferral was honoured" and "the deferral was closed"
    # are both real properties, and the second is the one that is true now.
    # Deleting it would retire the only assertion that P8 task 4 happened.
    prescore_fks = {(r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(prescores)")}
    if with_p8:
        report.check(
            ("comments", "comment_id") in prescore_fks,
            "prescores.comment_id -> comments — the FK 0005 deferred is now closed (M8)",
            f"got: {sorted(prescore_fks)}",
        )
    else:
        report.check(
            ("comments", "comment_id") not in prescore_fks,
            "prescores.comment_id has no FK yet — deferred to 0006 (M8)",
            f"got: {sorted(prescore_fks)}",
        )
    report.check(
        ("runs", "run_id") in prescore_fks,
        "prescores -> runs.run_id",
        f"got: {sorted(prescore_fks)}",
    )


def check_content_and_dedup_shape(
    conn: sqlite3.Connection, report: Report, *, with_p12: bool = True
) -> None:
    """The 0006 constraints that are easy to get wrong and silent when wrong.

    Every check here is one a passing migration could still fail. The four
    ``project_id`` columns in particular: a ``REFERENCES projects(id)`` written
    at this revision leaves the schema *looking* correct -- the DDL applies,
    ``foreign_key_check`` returns ``[]`` -- while every INSERT into that table
    fails. That is P8 review F1, and it is asserted here as well as in the test
    suite because this script is what a human runs from the manual guide.

    ⚠️ **That assertion inverts at 0007**, which is why it takes a flag rather
    than being a constant. Before 0007 the four columns must be bare or every
    INSERT is broken; after 0007 they must reference ``projects`` or M8 deferred
    a foreign key to nowhere. Both are real failures and they are exact
    opposites, so a verifier that checked only one of them would pass a database
    in precisely the state the other check exists to catch.
    """
    report.section("Content and dedup (0006)")

    lead_columns = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}
    for column in ("project_id", "confidence_score", "analysis_status", "source"):
        report.check(
            column in lead_columns,
            f"leads.{column} exists",
            f"got: {sorted(lead_columns)}",
        )

    # The defaults are what let the ALTER stay metadata-only over 478 rows.
    lead_defaults = {r[1]: r[4] for r in conn.execute("PRAGMA table_info(leads)")}
    report.check(
        (lead_defaults.get("analysis_status") or "").strip("'\"") == "not_analyzed",
        "leads.analysis_status defaults to 'not_analyzed'",
        f"got: {lead_defaults.get('analysis_status')!r}",
    )
    report.check(
        (lead_defaults.get("source") or "").strip("'\"") == "scrape",
        "leads.source defaults to 'scrape'",
        f"got: {lead_defaults.get('source')!r}",
    )

    # ⚠️ F1. Four columns must reference `projects`, which arrives in 0007 —
    #    and must NOT reference it before then. See the docstring.
    for table in ("leads", "comments", "dedup_groups", "minhash_bands"):
        parents = {r[2].lower() for r in conn.execute(f"PRAGMA foreign_key_list({table})")}
        if with_p12:
            report.check(
                "projects" in parents,
                f"{table}.project_id references projects — the FK 0006 deferred is closed (M8)",
                f"still bare: {sorted(parents)}. M8 deferred this constraint to 0007 "
                f"and 0007 did not add it",
            )
        else:
            report.check(
                "projects" not in parents,
                f"{table}.project_id is BARE — the FK is deferred to 0007 (M8)",
                f"got a REFERENCES projects: {sorted(parents)}. Every INSERT into "
                f"{table} is already broken",
            )

    # 4 columns, 4 indexes. `source` deliberately has none (D3).
    lead_indexes = {r[1] for r in conn.execute("PRAGMA index_list(leads)")}
    for name in (
        "ix_leads_project_id",
        "ix_leads_confidence_score",
        "ix_leads_analysis_status",
        "ix_leads_project_conf",
    ):
        report.check(name in lead_indexes, f"{name} exists", f"got: {sorted(lead_indexes)}")
    report.check(
        "ix_leads_source" not in lead_indexes,
        "leads.source has NO index — 4 columns, 4 indexes (D3)",
        f"got: {sorted(lead_indexes)}",
    )

    # `body_hash` is the real dedup key, so its index must actually be unique.
    comment_indexes = {r[1]: r[2] for r in conn.execute("PRAGMA index_list(comments)")}
    report.check(
        comment_indexes.get("ux_comments_hash") == 1,
        "ux_comments_hash is UNIQUE — body_hash is the dedup key",
        f"got: {comment_indexes}",
    )

    # Partial, not plain. A plain unique would constrain comment-only rows too.
    dedup_index_sql = {
        r[0]: (r[1] or "")
        for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='dedup_members'"
        )
    }
    for name, column in (
        ("ux_dedup_members_lead", "lead_id"),
        ("ux_dedup_members_comment", "comment_id"),
    ):
        sql = dedup_index_sql.get(name, "")
        report.check(
            "WHERE" in sql.upper() and column in sql,
            f"{name} is PARTIAL (WHERE {column} IS NOT NULL)",
            f"got: {sql or 'the index is missing entirely'}",
        )

    # The CHECK that batch_alter_table's reflection is most likely to drop.
    for table, constraint in (
        ("prescores", "ck_prescores_one_target"),
        ("dedup_members", "ck_dedup_members_one_target"),
    ):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        report.check(
            bool(row) and constraint in (row[0] or ""),
            f"{constraint} is present on {table}",
            "the named CHECK is missing",
        )


def check_knowledge_base_shape(conn: sqlite3.Connection, report: Report) -> None:
    """The 0007 constraints that a passing migration could still get wrong.

    Presence of the twelve tables is `check_tables`' job. This is the shape:
    the six ON DELETE actions, the payload rule, and the three nullabilities
    that were decided against a document rather than inherited from one.
    """
    report.section("Projects and knowledge base (0007)")

    # The six closed keys, each with its action. `foreign_key_list` gives
    # (id, seq, table, from, to, on_update, on_delete, match).
    for table, action in EXPECTED_PROJECT_FOREIGN_KEYS.items():
        actual = [
            (r[3], r[6])
            for r in conn.execute(f"PRAGMA foreign_key_list({table})")
            if r[2] == "projects"
        ]
        report.check(
            ("project_id", action) in actual,
            f"{table}.project_id -> projects ON DELETE {action}",
            f"got: {actual or 'no foreign key to projects at all'}",
        )

    # ⚠️ runs.project_id stays NULLABLE. [34 §P12] asks for NOT NULL; all 11
    #    live rows are NULL, M5 forbids rewriting them to satisfy it, and AD-5
    #    freezes project scoping as "additive and nullable". Asserted positively
    #    so that a later phase re-reading the plan cannot quietly tighten it.
    runs_columns = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(runs)")}
    report.check(
        runs_columns.get("project_id") == 0,
        "runs.project_id is still NULLABLE — AD-5, and 11 of 11 live rows are NULL",
        f"notnull flag: {runs_columns.get('project_id')}",
    )

    # The same decision for the two P8 left open, and for the same kind of
    # reason: P10's cascade and P11's stage write both as None on every run.
    for table in ("dedup_groups", "minhash_bands"):
        columns = {r[1]: r[3] for r in conn.execute(f"PRAGMA table_info({table})")}
        report.check(
            columns.get("project_id") == 0,
            f"{table}.project_id is still NULLABLE — the dedup cascade writes None",
            f"notnull flag: {columns.get('project_id')}",
        )

    # The payload rule, as a CHECK rather than as a convention.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bkb_sections'"
    ).fetchone()
    sections_sql = (row[0] if row else "") or ""
    report.check(
        "ck_bkb_sections_payload_null_rule" in sections_sql,
        "ck_bkb_sections_payload_null_rule is present on bkb_sections",
        "the named CHECK is missing — the payload rule is a convention again",
    )
    report.check(
        all(key in sections_sql for key in TYPED_SECTION_KEYS),
        f"the CHECK names exactly the three typed sections {list(TYPED_SECTION_KEYS)}",
        f"got: {sections_sql[:300]}",
    )
    report.check(
        "ideal_customer_profiles" not in sections_sql,
        "ideal_customer_profiles is NOT exempt — it has no typed table (05 §5.1b)",
        "the CHECK exempts a section whose payload is the only copy of an ICP",
    )

    section_columns = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(bkb_sections)")}
    report.check(
        section_columns.get("payload_json") == 0,
        "bkb_sections.payload_json is NULLABLE — 05 §5.1b overrides §5.1's NOT NULL",
        f"notnull flag: {section_columns.get('payload_json')}. The three typed "
        f"sections cannot be stored",
    )

    # A source_type='ai_inference' row has nothing to quote, and a quote there
    # would be a fabrication (05 §5.1c).
    evidence_columns = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(bkb_evidence)")}
    report.check(
        evidence_columns.get("quote") == 0,
        "bkb_evidence.quote is NULLABLE — an ai_inference row has nothing to quote",
        f"notnull flag: {evidence_columns.get('quote')}",
    )

    # The three typed tables carry bkb_id as well as project_id, without which
    # deleting a superseded BKB drops the evidence and leaves the claim behind,
    # unevidenced but still displayed (05 §5.1b).
    for table in ("personas", "pain_points", "intent_signals"):
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        report.check(
            "bkb_id" in columns and "project_id" in columns,
            f"{table} carries both bkb_id and project_id — evidence cascades correctly",
            f"got: {sorted(columns)}",
        )

    # Uniqueness is the point of each of these; a plain index would let a
    # regeneration double every row it rewrote.
    for name in EXPECTED_UNIQUE_INDEXES_AT_0007:
        row = conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone()
        if row is None:
            report.check(False, f"{name} exists and is UNIQUE", "the index is missing entirely")
            continue
        unique = {r[1]: r[2] for r in conn.execute(f"PRAGMA index_list({row[0]})")}
        report.check(unique.get(name) == 1, f"{name} exists and is UNIQUE", f"got: {unique}")

    # Reported, never asserted. Absent is the normal case and is not a failure;
    # what would be a failure is not knowing which state the host is in.
    vector = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='bkb_embeddings'"
    ).fetchone()[0]
    state = "enabled" if vector else "disabled"
    presence = "present" if vector else "absent"
    print(f"  INFO  semantic_layer is {state} (bkb_embeddings {presence}; sqlite-vec is optional)")


def check_indexes(conn: sqlite3.Connection, report: Report) -> None:
    report.section("Indexes (column order matters)")

    for name, expected in EXPECTED_INDEXES.items():
        actual = _index_columns(conn, name)
        if actual is None:
            report.check(False, f"{name} exists", "the index is missing entirely")
            continue
        report.check(
            actual == expected,
            f"{name} = {expected}",
            f"got: {actual}",
        )


def check_foreign_keys(conn: sqlite3.Connection, report: Report, *, with_p12: bool = True) -> None:
    report.section("Foreign keys (ON DELETE action matters)")

    for table, expected in EXPECTED_FOREIGN_KEYS.items():
        actual = [(r[2], r[3], r[6]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")]
        report.check(
            expected in actual,
            f"{table} -> {expected[0]}.{expected[1]} ON DELETE {expected[2]}",
            f"got: {actual}",
        )

    # `runs.project_id` stays a bare column until 0007 creates `projects`.
    # A REFERENCES clause before then would name a table that does not exist;
    # afterwards its absence would mean M8 deferred a key to nowhere. Same
    # inversion as the four columns in `check_content_and_dedup_shape`.
    runs_fks = [r[2] for r in conn.execute("PRAGMA foreign_key_list(runs)")]
    if with_p12:
        report.check(
            runs_fks == ["projects"],
            "runs -> projects.project_id — the FK 0004 deferred is closed (M8)",
            f"got: {runs_fks}",
        )
    else:
        report.check(
            runs_fks == [],
            "runs has no foreign keys yet (projects arrives in 0007)",
            f"got: {runs_fks}",
        )


def check_constraints(conn: sqlite3.Connection, report: Report) -> None:
    """Column-level guarantees that a table-existence check would not catch."""
    report.section("Constraints")

    runs_info = list(conn.execute("PRAGMA table_info(runs)"))
    columns = [r[1] for r in runs_info]

    report.check(
        columns == EXPECTED_RUNS_COLUMNS,
        "runs columns are exactly as specified, in order",
        f"got: {columns}",
    )

    present = FORBIDDEN_EXPIRY_COLUMNS & set(columns)
    report.check(
        not present,
        "runs has no expiry column — gates never time out (AD-6)",
        f"found: {sorted(present)}",
    )

    nullable = {r[1]: not r[3] for r in runs_info}
    report.check(
        nullable.get("project_id") is True,
        "runs.project_id is nullable until 0007",
        f"got notnull={not nullable.get('project_id')}",
    )

    # The two `run_id` columns differ on purpose, per docs/05 §7.3:
    # a job may be standalone (maintenance, canary) and so is nullable; an event
    # is always an event *about a run* and so is not.
    jobs_notnull = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(jobs)")}
    report.check(
        jobs_notnull.get("run_id") == 0,
        "jobs.run_id is nullable — a job need not belong to a run",
        f"got notnull={jobs_notnull.get('run_id')}",
    )

    events_notnull = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(run_events)")}
    report.check(
        events_notnull.get("run_id") == 1,
        "run_events.run_id is NOT NULL — an event always belongs to a run",
        f"got notnull={events_notnull.get('run_id')}",
    )


def check_row_counts(conn: sqlite3.Connection, report: Report) -> None:
    """The orchestration tables, and whether what is in them is legal.

    Until P3 this asserted the three tables were **empty** — true while nothing
    enqueued anything, and false the moment the product was used. Emptiness was
    never the property worth protecting; it was a stand-in for "P1 ships shape,
    not behaviour". What matters now that rows exist is that every one of them
    holds a state the state machine defines: a value outside the enum is a row no
    code can ever move again, and it would sit there silently.
    """
    report.section("Orchestration rows")

    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("runs", "jobs", "run_events")
    }
    print(f"  INFO  runs={counts['runs']} jobs={counts['jobs']} run_events={counts['run_events']}")

    for table, column, legal in (
        ("runs", "state", LEGAL_RUN_STATES),
        ("jobs", "state", LEGAL_JOB_STATES),
    ):
        found = {r[0] for r in conn.execute(f"SELECT DISTINCT {column} FROM {table}")}
        illegal = sorted(found - legal)
        report.check(
            not illegal,
            f"every {table}.{column} is a state the machine defines",
            f"illegal: {illegal}",
        )

    orphans = conn.execute(
        "SELECT COUNT(*) FROM run_events WHERE run_id NOT IN (SELECT id FROM runs)"
    ).fetchone()[0]
    report.check(orphans == 0, "no run_events orphaned from their run", f"got: {orphans}")


def check_legacy_fingerprint(conn: sqlite3.Connection, report: Report, expect_leads: bool) -> None:
    """The legacy contract: 459 leads with an unchanged score fingerprint (R20).

    Only meaningful against the production database or a copy of it, so it is
    skippable — but skipping is announced rather than silent, because a check
    that quietly did not run reads exactly like a check that passed.
    """
    report.section("Legacy fingerprint")

    leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    if not expect_leads:
        print(f"  INFO  leads = {leads} (not checked; --no-leads-check was passed)")
        return

    if leads == 0:
        print("  INFO  empty database — skipping the intent_score fingerprint")
        return

    baseline = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE id <= ?", (BASELINE_MAX_LEAD_ID,)
    ).fetchone()[0]
    collected = leads - baseline
    print(f"  INFO  leads = {leads} ({baseline} baseline + {collected} collected since)")

    # The originals: every one still present, and none rescored. Growth above the
    # boundary is the product working and is reported, not asserted.
    report.check(
        baseline == EXPECTED_LEADS,
        f"the {EXPECTED_LEADS} original leads are all still present",
        f"got: {baseline} — {EXPECTED_LEADS - baseline} missing",
    )

    hi, avg = conn.execute(
        "SELECT MAX(intent_score), AVG(intent_score) FROM leads WHERE id <= ?",
        (BASELINE_MAX_LEAD_ID,),
    ).fetchone()
    report.check(
        round(hi, 2) == EXPECTED_INTENT_MAX,
        f"max(intent_score) over the original leads = {EXPECTED_INTENT_MAX}",
        f"got: {round(hi, 2)}",
    )
    report.check(
        round(avg, 2) == EXPECTED_INTENT_AVG,
        f"avg(intent_score) over the original leads = {EXPECTED_INTENT_AVG}",
        f"got: {round(avg, 2)}",
    )


def run_checks(
    db_path: Path,
    revision: str | None,
    skip_p1: bool,
    expect_leads: bool,
    verbose: bool,
    skip_p6: bool = False,
    skip_p8: bool = False,
    skip_p12: bool = False,
) -> int:
    if not db_path.exists():
        print(f"ERROR: no such database: {db_path}")
        print("Create it first — see P01-testing.md T4 Step 1.")
        return 2

    # `--skip-p8` implies `--skip-p12`. A database without `comments` cannot
    # have had 0007 applied, so requiring 0007's twelve tables there would
    # report a legitimate revision as a broken one.
    skip_p12 = skip_p12 or skip_p8

    report = Report(verbose=verbose)
    print(f"Checking {db_path}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        check_integrity(conn, report)
        check_revision(conn, report, revision)

        if skip_p1:
            print("\n(--skip-p1: the 0004 shape and row-count checks were not run)")
        else:
            check_tables(
                conn,
                report,
                with_p6=not skip_p6,
                with_p8=not skip_p8,
                with_p12=not skip_p12,
            )
            check_indexes(conn, report)
            check_foreign_keys(conn, report, with_p12=not skip_p12)
            check_constraints(conn, report)
            check_row_counts(conn, report)
            if skip_p6:
                print("\n(--skip-p6: the 0005 discovery checks were not run)")
            else:
                check_discovery_shape(conn, report, with_p8=not skip_p8)
            if skip_p8:
                print("\n(--skip-p8: the 0006 content and dedup checks were not run)")
            else:
                check_content_and_dedup_shape(conn, report, with_p12=not skip_p12)
            # `--skip-p8` implies `--skip-p12`: a database without `comments`
            # cannot have had 0007 applied, and the 0007 section would then fail
            # on twelve tables that are correctly absent.
            if skip_p12:
                print("\n(--skip-p12: the 0007 knowledge-base checks were not run)")
            else:
                check_knowledge_base_shape(conn, report)

        check_legacy_fingerprint(conn, report, expect_leads)
    finally:
        conn.close()

    return report.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a SQLite database against the P1 schema specification.",
        epilog="Needs only Python. The sqlite3 command line tool is not required.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/leads.db"),
        help="path to the database file (default: data/leads.db)",
    )
    parser.add_argument(
        "--revision",
        help="alembic revision the database should be at, e.g. 0004 or 0003",
    )
    parser.add_argument(
        "--skip-p1",
        action="store_true",
        help="skip the 0004 shape checks — use on a database still at 0003",
    )
    parser.add_argument(
        "--skip-p6",
        action="store_true",
        help="skip the 0005 discovery checks — use on a database still at 0004",
    )
    parser.add_argument(
        "--skip-p8",
        action="store_true",
        help="skip the 0006 content/dedup checks — use on a database still at 0005",
    )
    parser.add_argument(
        "--skip-p12",
        action="store_true",
        help="skip the 0007 knowledge-base checks — use on a database still at 0006",
    )
    parser.add_argument(
        "--no-leads-check",
        action="store_true",
        help="report the lead count without asserting the 459-lead legacy contract",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print detail for passes too")
    args = parser.parse_args(argv)

    return run_checks(
        db_path=args.db,
        revision=args.revision,
        skip_p1=args.skip_p1,
        expect_leads=not args.no_leads_check,
        verbose=args.verbose,
        skip_p6=args.skip_p6,
        skip_p8=args.skip_p8,
        skip_p12=args.skip_p12,
    )


if __name__ == "__main__":
    sys.exit(main())
