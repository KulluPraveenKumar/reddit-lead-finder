"""baseline - the 8 tables that already exist

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-30

This revision reproduces exactly what ``Base.metadata.create_all()`` produced
for the eight pre-existing tables. It is **stamped, not applied**, on a database
that already has them (see ``src/db/migrate.py``).

``tests/test_migrations.py::test_baseline_matches_create_all`` asserts that
running this revision on an empty database yields byte-identical DDL to
``create_all()`` on an empty database. If that test fails, this file is wrong —
not the test.

Note two details that are easy to get wrong by hand and were verified against
generated DDL rather than reasoned about:

* ``leads.reddit_id`` and ``tracked_users.username`` are declared
  ``unique=True, index=True``, which SQLAlchemy renders as a **UNIQUE INDEX**,
  not as a table-level UNIQUE constraint.
* Python-side defaults (``datetime.utcnow``) never appear in DDL at all.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reddit_id", sa.String(length=20), nullable=False),
        sa.Column("subreddit", sa.String(length=100), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("post_type", sa.String(length=20), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("num_comments", sa.Integer(), nullable=True),
        sa.Column("intent_score", sa.Float(), nullable=True),
        sa.Column("matched_keywords", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("created_utc", sa.DateTime(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_intent_score", "leads", ["intent_score"], unique=False)
    op.create_index("ix_leads_reddit_id", "leads", ["reddit_id"], unique=True)
    op.create_index("ix_leads_scraped_at", "leads", ["scraped_at"], unique=False)
    op.create_index("ix_leads_status", "leads", ["status"], unique=False)
    op.create_index("ix_leads_subreddit", "leads", ["subreddit"], unique=False)

    op.create_table(
        "subreddits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("last_scraped", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "dashboard_subreddits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "dashboard_keywords",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dashboard_search_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(length=300), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    op.create_table(
        "tracked_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=True),
        sa.Column("lead_count", sa.Integer(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tracked_users_username", "tracked_users", ["username"], unique=True)

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraper_type", sa.String(length=50), nullable=False),
        sa.Column("subreddit", sa.String(length=100), nullable=True),
        sa.Column("posts_found", sa.Integer(), nullable=True),
        sa.Column("leads_found", sa.Integer(), nullable=True),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Reverse creation order. This drops the live product's data, so it exists
    # for test symmetry and is never something to run against a real database.
    op.drop_table("scrape_runs")
    op.drop_index("ix_tracked_users_username", table_name="tracked_users")
    op.drop_table("tracked_users")
    op.drop_table("settings")
    op.drop_table("dashboard_search_queries")
    op.drop_table("dashboard_keywords")
    op.drop_table("dashboard_subreddits")
    op.drop_table("subreddits")
    for ix in (
        "ix_leads_subreddit",
        "ix_leads_status",
        "ix_leads_scraped_at",
        "ix_leads_reddit_id",
        "ix_leads_intent_score",
    ):
        op.drop_index(ix, table_name="leads")
    op.drop_table("leads")
