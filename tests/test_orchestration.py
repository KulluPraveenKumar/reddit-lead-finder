"""P1 — the run state machine and its schema.

Two things are being guarded here, and they fail in different ways:

* **The transition table.** A wrong edge does not crash; it lets a run reach a
  state nobody designed for, days later, in production. So the table is asserted
  against the specification edge by edge rather than spot-checked.
* **The migration.** ``0004`` is the first revision to touch a pre-existing
  table (``scrape_runs``), and there are 459 real leads on the other side of it.

Everything here is offline.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.orchestration import (
    GATE_STATES,
    JOB_TRANSITIONS,
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalTransition,
    JobState,
    RunState,
    assert_job_transition,
    assert_transition,
    can_transition,
    is_gate,
    is_terminal,
)

#: The recorded shape of the pre-rebuild database. Read rather than hardcoded so
#: the legacy contract has exactly one definition, in one file, shared with
#: `tests/test_migrations.py`.
_BASELINE_PATH = Path(__file__).parent / "baseline" / "db_fingerprint.json"


def _baseline() -> dict:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The specification, transcribed from docs/04 §1.1-1.2.
#
# Written out again rather than imported: a test that reads the same dict the
# code reads asserts nothing. This is the independent copy.
# ---------------------------------------------------------------------------

SPEC_STATES = {
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

SPEC_TRANSITIONS = {
    "pending": {"profiling", "cancelled", "failed"},
    "profiling": {"discovering", "failed", "cancelled"},
    "discovering": {"awaiting_subreddit_review", "failed", "cancelled"},
    "awaiting_subreddit_review": {"generating_keywords", "discovering", "cancelled"},
    "generating_keywords": {"awaiting_keyword_review", "failed", "cancelled"},
    "awaiting_keyword_review": {"awaiting_options", "generating_keywords", "cancelled"},
    "awaiting_options": {"scraping", "cancelled"},
    "scraping": {"analyzing", "failed", "cancelled"},
    "analyzing": {"complete", "failed", "cancelled"},
    "complete": {"analyzing"},
    "failed": {"pending"},
    "cancelled": set(),
}

#: The job table, transcribed independently for the same reason as above.
#:
#: ``TRANSITIONS`` had this second copy from the start and ``JOB_TRANSITIONS``
#: did not, so the job table was only ever spot-checked. A wrong job edge fails
#: the same way a wrong run edge does — silently, in production, days later.
SPEC_JOB_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"done", "failed", "queued", "cancelled"},
    "done": set(),
    "failed": {"queued"},
    "cancelled": set(),
}


class TestRunStates:
    def test_twelve_states_exactly_as_specified(self):
        """docs/34 §P1 says eleven; docs/04 §1.1 lists twelve and is the spec."""
        assert {s.value for s in RunState} == SPEC_STATES
        assert len(RunState) == 12

    def test_transition_table_matches_specification_edge_by_edge(self):
        actual = {state.value: {t.value for t in targets} for state, targets in TRANSITIONS.items()}
        assert actual == SPEC_TRANSITIONS

    def test_every_state_appears_in_the_table(self):
        """A state with no entry would raise KeyError on first use, in production."""
        assert set(TRANSITIONS) == set(RunState)

    def test_cancelled_is_final(self):
        """Cancel must not mean pause. They need different guarantees."""
        assert TRANSITIONS[RunState.CANCELLED] == frozenset()
        assert not can_transition(RunState.CANCELLED, RunState.PENDING)

    def test_backward_edges_exist(self):
        """'Regenerate these, I don't like them' must not require starting over."""
        assert can_transition(RunState.AWAITING_SUBREDDIT_REVIEW, RunState.DISCOVERING)
        assert can_transition(RunState.AWAITING_KEYWORD_REVIEW, RunState.GENERATING_KEYWORDS)

    def test_complete_can_reanalyse_and_failed_can_retry(self):
        assert can_transition(RunState.COMPLETE, RunState.ANALYZING)
        assert can_transition(RunState.FAILED, RunState.PENDING)

    def test_complete_cannot_go_backwards_into_scraping(self):
        assert not can_transition(RunState.COMPLETE, RunState.SCRAPING)

    def test_every_unspecified_edge_is_rejected(self):
        """All 144 ordered pairs, not the three that were spot-checked.

        The edges above assert that the *allowed* set is right. This asserts the
        complement: of the 12x12 pairs, exactly those in the specification are
        accepted and every one of the other 110 raises. An extra edge added by
        mistake passes every other test in this class.
        """
        accepted, rejected = set(), set()
        for source in RunState:
            for target in RunState:
                (accepted if can_transition(source, target) else rejected).add(
                    (source.value, target.value)
                )

        expected = {(s, t) for s, targets in SPEC_TRANSITIONS.items() for t in targets}
        assert accepted == expected
        assert len(accepted) + len(rejected) == len(RunState) ** 2

        # And the rejection must raise, not merely return False.
        for source, target in sorted(rejected):
            with pytest.raises(IllegalTransition):
                assert_transition(source, target)


class TestGatesHaveNoTimeout:
    """AC: 'the two AWAITING_*_REVIEW states have no timeout'.

    A gate that expires proceeds without the human it exists to wait for. There
    is nothing to assert *positively* about an absent feature, so this asserts
    the two things that would have to be true if a timeout were ever added:
    the gate set is exactly those two states, and no run column stores an expiry.
    """

    def test_gate_states_are_exactly_the_two_reviews(self):
        assert {
            RunState.AWAITING_SUBREDDIT_REVIEW,
            RunState.AWAITING_KEYWORD_REVIEW,
        } == GATE_STATES
        assert is_gate(RunState.AWAITING_SUBREDDIT_REVIEW)
        assert is_gate("awaiting_keyword_review")
        assert not is_gate(RunState.SCRAPING)

    #: Names that would give a gate an expiry. None may exist, in either place.
    FORBIDDEN = frozenset({"expires_at", "timeout_at", "deadline", "ttl", "expiry"})

    def test_runs_schema_has_no_expiry_column(self, temp_db):
        """The absence is the feature. If someone adds one, this fails."""
        conn = sqlite3.connect(temp_db)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
        finally:
            conn.close()
        assert not (cols & self.FORBIDDEN), (
            f"a gate timeout column appeared: {cols & self.FORBIDDEN}"
        )

    def test_runs_model_has_no_expiry_column(self):
        """The model, not just the migrated schema.

        Mutation testing found this gap: adding ``expires_at`` to ``Run`` passed
        the schema check, because the schema comes from the migration and the
        migration had not changed. The column would have appeared the moment
        anyone autogenerated a revision -- long after the decision was made.
        Both halves are now guarded.
        """
        from src.db.models import Run

        cols = {c.name for c in Run.__table__.columns}
        assert not (cols & self.FORBIDDEN), (
            f"a gate timeout column appeared: {cols & self.FORBIDDEN}"
        )

    def test_a_gate_is_not_terminal(self):
        """A gate is waiting, not finished — the worker must not treat it as done."""
        for gate in GATE_STATES:
            assert not is_terminal(gate)


class TestTransitionErrors:
    def test_illegal_transition_names_both_states(self):
        """AC: the error names both states. 'Illegal transition' alone is unactionable."""
        with pytest.raises(IllegalTransition) as exc:
            assert_transition(RunState.PENDING, RunState.COMPLETE)
        msg = str(exc.value)
        assert "pending" in msg
        assert "complete" in msg

    def test_illegal_transition_lists_what_was_allowed(self):
        with pytest.raises(IllegalTransition) as exc:
            assert_transition(RunState.PENDING, RunState.SCRAPING)
        assert "profiling" in str(exc.value)

    def test_terminal_error_says_terminal(self):
        with pytest.raises(IllegalTransition, match="terminal"):
            assert_transition(RunState.CANCELLED, RunState.PENDING)

    def test_accepts_raw_strings_from_the_database(self):
        """The column is a VARCHAR; forgetting to coerce must not skip the guard."""
        assert_transition("pending", "profiling")
        with pytest.raises(IllegalTransition):
            assert_transition("pending", "complete")

    def test_unknown_state_lists_the_valid_ones(self):
        with pytest.raises(IllegalTransition) as exc:
            assert_transition("awaiting_review", "profiling")
        assert "awaiting_review" in str(exc.value)
        assert "awaiting_subreddit_review" in str(exc.value)

    def test_legal_transition_is_silent(self):
        assert assert_transition(RunState.SCRAPING, RunState.ANALYZING) is None


class TestJobStates:
    def test_five_states(self):
        assert {s.value for s in JobState} == {"queued", "running", "done", "failed", "cancelled"}

    def test_lease_reclamation_is_legal(self):
        """A worker died holding the job; the queue takes it back."""
        assert_job_transition(JobState.RUNNING, JobState.QUEUED)

    def test_retry_after_failure_is_legal(self):
        assert_job_transition(JobState.FAILED, JobState.QUEUED)

    def test_done_is_final(self):
        assert JOB_TRANSITIONS[JobState.DONE] == frozenset()
        with pytest.raises(IllegalTransition, match="terminal"):
            assert_job_transition(JobState.DONE, JobState.QUEUED)

    def test_cannot_skip_running(self):
        with pytest.raises(IllegalTransition):
            assert_job_transition(JobState.QUEUED, JobState.DONE)

    def test_job_transition_table_matches_specification_edge_by_edge(self):
        """The independent copy the run table always had and this one did not."""
        actual = {
            state.value: {t.value for t in targets} for state, targets in JOB_TRANSITIONS.items()
        }
        assert actual == SPEC_JOB_TRANSITIONS

    def test_every_state_appears_in_the_job_table(self):
        assert set(JOB_TRANSITIONS) == set(JobState)

    def test_every_unspecified_job_edge_is_rejected(self):
        """All 25 ordered pairs. See the run-state equivalent for why."""
        accepted = {
            (s.value, t.value)
            for s in JobState
            for t in JobState
            if t.value in SPEC_JOB_TRANSITIONS[s.value]
        }
        for source in JobState:
            for target in JobState:
                pair = (source.value, target.value)
                if pair in accepted:
                    assert assert_job_transition(source, target) is None
                else:
                    with pytest.raises(IllegalTransition):
                        assert_job_transition(source, target)

    def test_job_states_never_reach_a_run_gate(self):
        """A job has no human in it — no job state may be a run gate name.

        Cheap, but it catches the copy-paste that gives the queue a review state
        and quietly reintroduces a timeout-able gate outside GATE_STATES.
        """
        assert not ({s.value for s in JobState} & {s.value for s in GATE_STATES})


class TestTerminalStates:
    def test_terminal_set(self):
        assert {RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED} == TERMINAL_STATES

    def test_is_terminal_accepts_strings(self):
        assert is_terminal("complete")
        assert not is_terminal("scraping")


# ---------------------------------------------------------------------------
# Schema — migration 0004
# ---------------------------------------------------------------------------


class TestOrchestrationSchema:
    def test_three_tables_created(self, temp_db):
        conn = sqlite3.connect(temp_db)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert {"runs", "jobs", "run_events"} <= tables

    def test_claim_index_column_order_matches_the_claim_query(self, temp_db):
        """The index the queue lives or dies on.

        The claim is ``WHERE state=? AND available_at<=? ORDER BY priority, id``.
        A different column order silently degrades it to a scan under load.
        """
        conn = sqlite3.connect(temp_db)
        try:
            cols = [r[2] for r in conn.execute("PRAGMA index_info(ix_jobs_claim)")]
        finally:
            conn.close()
        assert cols == ["state", "available_at", "priority", "id"]

    def test_all_three_job_indexes_present(self, temp_db):
        conn = sqlite3.connect(temp_db)
        try:
            idx = {r[1] for r in conn.execute("PRAGMA index_list(jobs)")}
        finally:
            conn.close()
        assert {"ix_jobs_claim", "ix_jobs_run", "ix_jobs_lease"} <= idx

    def test_deferred_ai_calls_fk_is_closed(self, temp_db):
        """AC: PRAGMA foreign_key_list(ai_calls) reports the run FK.

        The column was created bare in 0002 because `runs` did not exist.
        """
        conn = sqlite3.connect(temp_db)
        try:
            fks = [
                (r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list(ai_calls)")
            ]
        finally:
            conn.close()
        assert ("runs", "run_id", "id", "SET NULL") in fks

    def test_scrape_runs_gained_run_id_with_set_null(self, temp_db):
        conn = sqlite3.connect(temp_db)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(scrape_runs)")]
            fks = [
                (r[2], r[3], r[4], r[6])
                for r in conn.execute("PRAGMA foreign_key_list(scrape_runs)")
            ]
        finally:
            conn.close()
        assert "run_id" in cols
        assert ("runs", "run_id", "id", "SET NULL") in fks

    def test_jobs_and_events_cascade_from_runs(self, temp_db):
        """Deleting a run must not orphan its jobs or its timeline."""
        conn = sqlite3.connect(temp_db)
        try:
            for table in ("jobs", "run_events"):
                fks = [
                    (r[2], r[3], r[6]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")
                ]
                assert ("runs", "run_id", "CASCADE") in fks, table
        finally:
            conn.close()

    def test_runs_project_id_is_bare_until_0007(self, temp_db):
        """`projects` does not exist yet; a REFERENCES clause here would be a lie."""
        conn = sqlite3.connect(temp_db)
        try:
            fks = [r[2] for r in conn.execute("PRAGMA foreign_key_list(runs)")]
            cols = {r[1]: r for r in conn.execute("PRAGMA table_info(runs)")}
        finally:
            conn.close()
        assert fks == []
        assert cols["project_id"][3] == 0, "project_id must stay nullable until 0007"

    def test_cascade_actually_deletes(self, temp_db):
        """PRAGMA foreign_keys is per-connection and OFF by default in SQLite.

        Asserting the constraint exists is not the same as asserting it fires.
        """
        conn = sqlite3.connect(temp_db)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                "INSERT INTO runs (id, state, llm_cost_usd, started_at, updated_at) "
                "VALUES (1, 'pending', 0, '2026-01-01', '2026-01-01')"
            )
            conn.execute(
                "INSERT INTO jobs (id, run_id, job_type, payload_json, state, priority, "
                "attempts, max_attempts, available_at, created_at) "
                "VALUES (1, 1, 'x', '{}', 'queued', 100, 0, 3, '2026-01-01', '2026-01-01')"
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, level, event, created_at) "
                "VALUES (1, 1, 'info', 'run.created', '2026-01-01')"
            )
            conn.commit()
            conn.execute("DELETE FROM runs WHERE id=1")
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] == 0
        finally:
            conn.close()


class TestMigrationSafety:
    def test_live_database_migrates_with_leads_intact(self, live_db_copy):
        """The 459 real leads survive the first revision that touches an old table.

        Scoped to the baseline rows for the reason given in
        ``tests/test_migrations.py::test_live_database_preserved``: the live
        database legitimately grows every time the product is used, and pinning
        its total would make normal operation look like a regression.
        """
        from src.db.migrate import MigrationRunner

        baseline = _baseline()
        lead_boundary = baseline["baseline_max_lead_id"]
        run_boundary = baseline["baseline_scrape_run_count"]

        MigrationRunner(live_db_copy).ensure_current()

        conn = sqlite3.connect(live_db_copy)
        try:
            leads = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE id <= ?", (lead_boundary,)
            ).fetchone()[0]
            stats = conn.execute(
                "SELECT MIN(intent_score), MAX(intent_score), ROUND(AVG(intent_score),2) "
                "FROM leads WHERE id <= ?",
                (lead_boundary,),
            ).fetchone()
            legacy_runs, legacy_with_run = conn.execute(
                "SELECT COUNT(*), COUNT(run_id) FROM scrape_runs WHERE id <= ?", (run_boundary,)
            ).fetchone()
        finally:
            conn.close()

        assert leads == baseline["lead_count"]
        assert stats == (
            baseline["baseline_intent_score_min"],
            baseline["baseline_intent_score_max"],
            baseline["baseline_intent_score_avg"],
        )
        assert legacy_runs == run_boundary
        # The pre-existing audit rows predate orchestration and belong to no run.
        # `src/db/models.py` says NULL "forever"; this is where forever is checked.
        # Rows created from P3 onwards do carry a run_id, and are outside this scope.
        assert legacy_with_run == 0

    def test_downgrade_removes_everything_and_restores_scrape_runs(self, live_db_copy):
        from src.db.migrate import MigrationRunner

        runner = MigrationRunner(live_db_copy)
        runner.ensure_current()
        runner.downgrade("0003_net_infrastructure")

        conn = sqlite3.connect(live_db_copy)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            cols = {r[1] for r in conn.execute("PRAGMA table_info(scrape_runs)")}
            fks = [r[2] for r in conn.execute("PRAGMA foreign_key_list(ai_calls)")]
            baseline_leads = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE id <= ?",
                (_baseline()["baseline_max_lead_id"],),
            ).fetchone()[0]
        finally:
            conn.close()

        assert not ({"runs", "jobs", "run_events"} & tables)
        assert "run_id" not in cols
        assert fks == []
        # Counted over the baseline ids, not the whole table: a downgrade must
        # not lose an original lead, and counting everything would let a loss be
        # masked by leads collected since.
        assert baseline_leads == _baseline()["lead_count"]

        # ...and back up again, which is where a broken downgrade usually shows.
        runner.upgrade("head")
        assert runner.current_revision() == runner.head_revision()

    def test_ai_calls_rows_survive_the_batch_rebuild(self, temp_db):
        """batch_alter_table rebuilds the table. Data must come with it."""
        from src.db.migrate import MigrationRunner

        conn = sqlite3.connect(temp_db)
        try:
            conn.execute(
                "INSERT INTO ai_calls (provider, model, stage, prompt_version, outcome, "
                "input_tokens_cached, input_tokens_uncached, output_tokens, cost_usd, "
                "surcharge_multiplier, attempt, created_at) "
                "VALUES ('fake','m','test',1,'ok',0,0,0,0,1,1,'2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        runner = MigrationRunner(temp_db)
        runner.downgrade("0003_net_infrastructure")
        runner.upgrade("head")

        conn = sqlite3.connect(temp_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
        finally:
            conn.close()


class TestSchemaCheckScript:
    """``scripts/check_schema.py`` is what the manual guide runs.

    A verifier that passes on a broken database is worse than no verifier, so
    the negative case is tested too: the guide's whole value is that a FAIL
    means something.
    """

    def test_passes_on_a_correctly_migrated_database(self, temp_db, capsys):
        """``temp_db`` is at head, so the expected revision follows the head.

        Both the revision and the count were pinned to 0004's values, then to
        0005's, and are now 0006's -- because the head genuinely moved each
        time. **Neither assertion is weakened:** the revision is still asserted
        exactly and the count is still asserted exactly, so a check that
        silently stops running still fails this test.

        The count stays at **29** across the 0006 move, and that is correct
        rather than suspicious: P8's Stage 2 adds no new *check*. It adds four
        table names to an existing set-comparison and inverts one existing
        assertion about ``prescores.comment_id``. The checks that assert P8's
        new columns, indexes and constraints arrive in Stage 4 and will move
        this number then.
        """
        from scripts.check_schema import main

        code = main(["--db", str(temp_db), "--revision", "0006", "--no-leads-check"])
        out = capsys.readouterr().out

        assert code == 0, out
        assert "FAIL" not in out
        assert "all 29 checks passed" in out

    def test_detects_a_wrong_claim_index_column_order(self, temp_db, capsys):
        """The defect the guide exists to catch, injected deliberately.

        A claim index in the wrong order still "exists". Only the order check
        distinguishes it, so that check is the one worth proving fires.
        """
        from scripts.check_schema import main

        conn = sqlite3.connect(temp_db)
        try:
            conn.execute("DROP INDEX ix_jobs_claim")
            conn.execute("CREATE INDEX ix_jobs_claim ON jobs (id, priority, available_at, state)")
            conn.commit()
        finally:
            conn.close()

        code = main(["--db", str(temp_db), "--no-leads-check"])
        out = capsys.readouterr().out

        assert code == 1
        assert "FAIL  ix_jobs_claim" in out

    def test_reports_a_missing_database_without_a_traceback(self, tmp_path, capsys):
        """A non-developer must get a sentence, not a stack trace."""
        from scripts.check_schema import main

        code = main(["--db", str(tmp_path / "absent.db")])
        out = capsys.readouterr().out

        assert code == 2
        assert "no such database" in out

    def test_does_not_write_to_the_database_it_checks(self, temp_db):
        """It opens read-only. Running a check must never be the thing that
        changes the fingerprint the check is verifying."""
        from scripts.check_schema import main

        before = temp_db.stat().st_mtime_ns
        main(["--db", str(temp_db), "--no-leads-check"])
        assert temp_db.stat().st_mtime_ns == before
