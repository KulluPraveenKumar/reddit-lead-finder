"""ai_infrastructure - ai_calls, ai_cache, ai_provider_state

Revision ID: 0002_ai_infrastructure
Revises: 0001_baseline
Create Date: 2026-07-30

All three tables are new, so nothing existing is altered and the live 459 rows
are untouched.

``ai_calls.run_id`` and ``.project_id`` are created **without** a REFERENCES
clause because ``runs`` and ``projects`` do not exist yet. The constraints are
added in 0004 and 0005 via ``batch_alter_table`` (docs/05 §7.1).

The API key is deliberately absent: its Fernet ciphertext goes into the
pre-existing ``settings`` table, so storing it needs no schema change at all.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_infrastructure"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prefix_hash", sa.String(length=64), nullable=True),
        sa.Column("input_tokens_cached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens_uncached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("surcharge_multiplier", sa.Float(), nullable=False, server_default="1"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_calls_run", "ai_calls", ["run_id", "created_at"])
    op.create_index("ix_ai_calls_project", "ai_calls", ["project_id", "created_at"])
    op.create_index("ix_ai_calls_stage", "ai_calls", ["stage", "outcome"])
    op.create_index("ix_ai_calls_day", "ai_calls", ["created_at"])

    op.create_table(
        "ai_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index("ix_ai_cache_content", "ai_cache", ["content_hash", "stage", "prompt_version"])
    op.create_index("ix_ai_cache_stage", "ai_cache", ["stage", "prompt_version"])

    op.create_table(
        "ai_provider_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unconfigured"),
        sa.Column("key_fingerprint", sa.String(length=20), nullable=True),
        sa.Column("key_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=60), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("last_validation_ms", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )


def downgrade() -> None:
    op.drop_table("ai_provider_state")
    op.drop_index("ix_ai_cache_stage", table_name="ai_cache")
    op.drop_index("ix_ai_cache_content", table_name="ai_cache")
    op.drop_table("ai_cache")
    for ix in ("ix_ai_calls_day", "ix_ai_calls_stage", "ix_ai_calls_project", "ix_ai_calls_run"):
        op.drop_index(ix, table_name="ai_calls")
    op.drop_table("ai_calls")
