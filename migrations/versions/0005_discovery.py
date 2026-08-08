"""discovery - discovery_watermarks, prescores

Revision ID: 0005_discovery
Revises: 0004_orchestration
Create Date: 2026-08-08

Two new tables. Nothing that predates this revision is altered, so the 459 live
leads and their scores are untouched (M5).

``prescores`` is **created here, not altered here.** docs/28 §10 says
``ALTER TABLE prescores ADD COLUMN stage``, which predates docs/33 §2.4 moving
the table into this revision — there is no table to alter, and the ``ALTER``
could never have executed. The freeze (§4.1) is the authority and it says 0005
creates ``prescores`` including ``stage``. Recorded as a §11.1 reconciliation.

``prescores.comment_id`` is deliberately **left bare**, exactly as 0002 left
``ai_calls.run_id``: ``comments`` does not exist until 0006, which closes the
foreign key with ``batch_alter_table`` (M8). The CHECK constraint still holds
without it — it constrains which column is populated, not what it points at.

``last_etag`` / ``last_modified`` are **absent by amendment**, not by oversight:
Reddit sends neither header on ``.rss`` (P0 U4, re-observed 2026-08-08), so
there is nothing to store or replay.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_discovery"
down_revision: str | None = "0004_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. discovery_watermarks — one row per (subreddit, channel, query).
    #    This is the incremental-sync primitive: it turns "scrape the last four
    #    pages every time" into "fetch what changed".
    op.create_table(
        "discovery_watermarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subreddit", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),  # listing | search
        sa.Column("query", sa.String(length=300), nullable=True),  # NULL for listing
        sa.Column("last_seen_fullname", sa.String(length=20), nullable=True),
        sa.Column("last_seen_utc", sa.DateTime(), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_empty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_rate_per_hour", sa.Float(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Uniqueness is enforced by TWO partial indexes, not by the single
    # `(subreddit, channel, query)` index docs/28 §3.1 shows.
    #
    # In SQLite, NULLs are DISTINCT in a UNIQUE index, so a plain three-column
    # unique index does not constrain listing rows at all — `query` is NULL for
    # every one of them, and any number of duplicates would insert cleanly. A
    # duplicated listing watermark is watermark poisoning (docs/28 D2) arriving
    # through the schema: two rows advance independently and each hides posts
    # from the other.
    #
    # The column semantics docs/28 specifies are unchanged. Only the enforcement
    # is corrected, so that the constraint the design assumes actually holds.
    op.create_index(
        "ux_watermarks_listing",
        "discovery_watermarks",
        ["subreddit", "channel"],
        unique=True,
        sqlite_where=sa.text("query IS NULL"),
    )
    op.create_index(
        "ux_watermarks_search",
        "discovery_watermarks",
        ["subreddit", "channel", "query"],
        unique=True,
        sqlite_where=sa.text("query IS NOT NULL"),
    )
    # The due-queue reads this on every scheduler tick.
    op.create_index("ix_watermarks_due", "discovery_watermarks", ["next_poll_at"])

    # 2. prescores — one row per collected item, admitted OR rejected.
    #    Storing the rejections is what makes the funnel auditable: without
    #    them the run page could report *that* items were filtered but never
    #    *which*, and the gate would be untunable (R11, AD-10b).
    op.create_table(
        "prescores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        # No REFERENCES: `comments` arrives in 0006, which closes this FK.
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("components_json", sa.Text(), nullable=False),
        # metadata | full. Stage 3 writes 'metadata' from title+snippet alone;
        # P11 writes 'full' once a body exists.
        sa.Column("stage", sa.String(length=20), nullable=False, server_default="full"),
        sa.Column("gate_decision", sa.String(length=20), nullable=False),
        sa.Column("gate_reason", sa.String(length=30), nullable=True),
        sa.Column("holdout_sampled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(lead_id IS NOT NULL) <> (comment_id IS NOT NULL)",
            name="ck_prescores_one_target",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescores_run", "prescores", ["run_id", "gate_decision"])
    op.create_index("ix_prescores_reason", "prescores", ["run_id", "gate_reason"])
    # Candidate selection orders by this.
    op.create_index("ix_prescores_total", "prescores", ["run_id", sa.text("total DESC")])


def downgrade() -> None:
    op.drop_index("ix_prescores_total", table_name="prescores")
    op.drop_index("ix_prescores_reason", table_name="prescores")
    op.drop_index("ix_prescores_run", table_name="prescores")
    op.drop_table("prescores")

    op.drop_index("ix_watermarks_due", table_name="discovery_watermarks")
    op.drop_index("ux_watermarks_search", table_name="discovery_watermarks")
    op.drop_index("ux_watermarks_listing", table_name="discovery_watermarks")
    op.drop_table("discovery_watermarks")
