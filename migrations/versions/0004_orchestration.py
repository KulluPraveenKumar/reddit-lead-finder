"""orchestration - runs, jobs, run_events

Revision ID: 0004_orchestration
Revises: 0003_net_infrastructure
Create Date: 2026-08-05

Three new tables plus one nullable column on ``scrape_runs``. That column is the
**only** change to anything that predates this revision, which is what keeps the
459 live leads and their scores untouched.

Two deferred foreign keys are closed here, both using ``batch_alter_table``
because SQLite cannot ``ADD CONSTRAINT``:

* ``ai_calls.run_id`` -> ``runs.id`` — the column was created bare in 0002
  because ``runs`` did not exist yet (docs/05 §7.1).
* ``scrape_runs.run_id`` -> ``runs.id`` — added and constrained in one batch.

``runs.project_id`` is deliberately **left bare**. ``projects`` does not exist
until 0007, which adds the constraint and tightens the column to NOT NULL. The
tightening is safe there because no run can exist before a project can.

Table creation order is a real constraint, not a formality: ``jobs`` and
``run_events`` both reference ``runs``, and ``downgrade`` drops them in exactly
the reverse order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_orchestration"
down_revision: str | None = "0003_net_infrastructure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. runs — referenced by everything below.
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        # No REFERENCES: `projects` arrives in 0007.
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("stats_json", sa.Text(), nullable=True),
        sa.Column("llm_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_project_state", "runs", ["project_id", "state"])

    # 2. jobs — the claim index column order matches the claim query exactly.
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(length=60), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("worker_id", sa.String(length=80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_claim", "jobs", ["state", "available_at", "priority", "id"])
    op.create_index("ix_jobs_run", "jobs", ["run_id", "state"])
    op.create_index("ix_jobs_lease", "jobs", ["state", "lease_expires_at"])

    # 3. run_events — the operator-facing timeline.
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False, server_default="info"),
        sa.Column("event", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_events_run", "run_events", ["run_id", "id"])

    # 4. scrape_runs gains run_id. The 10 existing rows keep NULL, which is
    #    semantically correct: they predate orchestration.
    with op.batch_alter_table("scrape_runs") as batch:
        batch.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_scrape_runs_run", "runs", ["run_id"], ["id"], ondelete="SET NULL"
        )

    # 5. Close the deferred FK left open by 0002.
    with op.batch_alter_table("ai_calls") as batch:
        batch.create_foreign_key("fk_ai_calls_run", "runs", ["run_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # Reverse order. The two batch rebuilds come first because they reference
    # `runs`, which cannot be dropped while a constraint points at it.
    with op.batch_alter_table("ai_calls") as batch:
        batch.drop_constraint("fk_ai_calls_run", type_="foreignkey")

    with op.batch_alter_table("scrape_runs") as batch:
        batch.drop_constraint("fk_scrape_runs_run", type_="foreignkey")
        batch.drop_column("run_id")

    op.drop_index("ix_run_events_run", table_name="run_events")
    op.drop_table("run_events")

    op.drop_index("ix_jobs_lease", table_name="jobs")
    op.drop_index("ix_jobs_run", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_runs_project_state", table_name="runs")
    op.drop_table("runs")
