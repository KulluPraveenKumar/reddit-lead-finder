"""net_infrastructure - proxies, http_cache, metrics

Revision ID: 0003_net_infrastructure
Revises: 0002_ai_infrastructure
Create Date: 2026-07-31

Three new tables. Nothing existing is altered, so the live rows are untouched.

``proxies`` deliberately has **no username or password column**. The credentials
live in the gitignored proxy file and nowhere else, so a copied database cannot
become a compromised proxy account. ``tests/test_net.py`` asserts the column
list, which is what keeps that true rather than merely intended today.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_net_infrastructure"
down_revision: str | None = "0002_ai_infrastructure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proxies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=120), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="untested"),
        sa.Column("exit_ip", sa.String(length=45), nullable=True),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_responses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("blacklisted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_proxies_endpoint", "proxies", ["host", "port"], unique=True)

    op.create_table(
        "http_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index("ix_http_cache_expires", "http_cache", ["expires_at"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metrics_name_time", "metrics", ["name", "recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_metrics_name_time", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_http_cache_expires", table_name="http_cache")
    op.drop_table("http_cache")
    op.drop_index("ux_proxies_endpoint", table_name="proxies")
    op.drop_table("proxies")
