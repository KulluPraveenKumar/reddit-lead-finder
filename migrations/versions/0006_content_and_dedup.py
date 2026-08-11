"""content_and_dedup - comments, dedup_groups, dedup_members, minhash_bands

Revision ID: 0006_content_and_dedup
Revises: 0005_discovery
Create Date: 2026-08-11

Four new tables, four new ``leads`` columns, and the closure of one foreign key
``0005`` deliberately left open. **No row is rewritten** (M5): every ``ALTER`` is
an ``ADD COLUMN``, which SQLite records as a metadata-only change to the table
header, so the 478 live leads -- and the 459 legacy-contract rows among them --
are untouched.

⚠️ **Four ``project_id`` columns are BARE -- no ``REFERENCES`` clause -- and
that is deliberate.** ``projects`` does not exist until ``0007`` (P12).
[freeze M8] mandates the pattern: *"forward references use a bare column plus a
deferred FK added later by ``batch_alter_table``"*, exactly as ``0002`` left
``ai_calls.run_id`` bare for ``0004`` to close.

This is not a stylistic point. Writing ``REFERENCES projects(id)`` here would
make **every INSERT into that table fail** with ``no such table: main.projects``
-- including one that sets ``project_id`` to ``NULL``, because SQLite resolves
the parent table when it prepares the statement, not when it checks the
constraint. And it would do so invisibly: the migration succeeds, ``SELECT``
keeps working, ``PRAGMA foreign_key_check`` returns ``[]``, the up/down/up
round-trip passes and ``check_schema.py`` reports OK. Measured, not assumed --
and now guarded by
``tests/test_migrations.py::test_no_revision_leaves_a_dangling_foreign_key``.

``dedup_groups.project_id`` and ``minhash_bands.project_id`` are additionally
**nullable**, where [05 §5.4b] declares them ``NOT NULL``. ``NOT NULL`` is
unsatisfiable at ``0006`` for the same reason. **Whether they should be tightened
when ``0007`` closes the FK is P12's decision, not this revision's**, and it is
named in P8's handover so P12 answers it deliberately rather than inheriting an
accident.

``prescores`` is **altered here, not created here.** [33 §2.4] moved it into
``0005`` and ``0005_discovery.py`` creates it; what ``0006`` owes it is closing
the ``comment_id`` foreign key that ``0005`` left bare because ``comments`` did
not exist yet. The ``CHECK ((lead_id IS NOT NULL) <> (comment_id IS NOT NULL))``
must survive the ``batch_alter_table`` rebuild -- named-constraint reflection is
that operation's known weak spot, so a test asserts it rather than trusting it.

``leads.source`` is [16 §115]'s DDL, adopted into the frozen schema by decision
D3. Domain ``scrape | holdout_audit``. It is the fix for R27, the
degenerate-learning-loop risk: holdout-audited items must become real, labellable
leads or the yield curve is fitted only on the gate's own admissions.
**Four columns, four indexes** -- there is no index on ``source`` (its only
consumer, P11's holdout, reads by run) and no ``CHECK`` on its domain, because
every other enumerated column in this schema is a bare ``VARCHAR``.

**No ``gate_audits``.** [05 §5.4b] lists it beside the dedup tables; [freeze
§4.1] places it in ``0009`` (P19).

**No rows are written.** P8 creates empty tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_content_and_dedup"
down_revision: str | None = "0005_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. leads gains four columns. All metadata-only; project_id BARE (D1).
    #    The two NOT NULL columns carry defaults, which is what lets SQLite add
    #    them without rewriting the 478 existing rows.
    op.add_column("leads", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column(
        "leads",
        sa.Column(
            "analysis_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_analyzed",
        ),
    )
    op.add_column(
        "leads",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="scrape"),
    )

    op.create_index("ix_leads_project_id", "leads", ["project_id"])
    op.create_index("ix_leads_confidence_score", "leads", ["confidence_score"])
    op.create_index("ix_leads_analysis_status", "leads", ["analysis_status"])
    op.create_index(
        "ix_leads_project_conf",
        "leads",
        ["project_id", sa.text("confidence_score DESC")],
    )

    # 2. comments. project_id BARE (D1); lead_id is in-revision and stays inline.
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("reddit_id", sa.String(length=20), nullable=True),
        sa.Column("author", sa.String(length=100), nullable=False, server_default="[deleted]"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_utc", sa.DateTime(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column(
            "analysis_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_analyzed",
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
    )
    op.create_index("ux_comments_hash", "comments", ["body_hash"], unique=True)
    op.create_index("ix_comments_lead", "comments", ["lead_id"])
    op.create_index(
        "ix_comments_project",
        "comments",
        ["project_id", sa.text("confidence_score DESC")],
    )

    # 3. dedup_groups. project_id BARE and NULLABLE (D1, D4).
    op.create_table(
        "dedup_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "representative_lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "representative_comment_id",
            sa.Integer(),
            sa.ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dedup_groups_project", "dedup_groups", ["project_id", "run_id"])

    # 4. dedup_members. Every FK is in-revision, so all stay inline.
    #
    #    ⚠️ The comment in 05 §5.4b -- "a lead or comment belongs to at most one
    #    group per run" -- is NOT what these indexes enforce, and no test claims
    #    otherwise. They constrain "at most once WITHIN a group". There is no
    #    run_id here; the run is reachable only through dedup_groups, and SQLite
    #    cannot express uniqueness across a join. Two groups from the same run can
    #    each claim the same lead. That invariant is P10's to uphold in the
    #    application and to test there (review F7).
    op.create_table(
        "dedup_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("dedup_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Integer(),
            sa.ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("is_representative", sa.Boolean(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "(lead_id IS NOT NULL) <> (comment_id IS NOT NULL)",
            name="ck_dedup_members_one_target",
        ),
    )
    op.create_index(
        "ux_dedup_members_lead",
        "dedup_members",
        ["group_id", "lead_id"],
        unique=True,
        sqlite_where=sa.text("lead_id IS NOT NULL"),
    )
    op.create_index(
        "ux_dedup_members_comment",
        "dedup_members",
        ["group_id", "comment_id"],
        unique=True,
        sqlite_where=sa.text("comment_id IS NOT NULL"),
    )

    # 5. minhash_bands. project_id BARE and NULLABLE (D1, D4).
    op.create_table(
        "minhash_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("band_index", sa.Integer(), nullable=False),
        sa.Column("band_hash", sa.String(length=32), nullable=False),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Integer(),
            sa.ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_minhash_lookup", "minhash_bands", ["project_id", "band_index", "band_hash"])

    # 6. Close the FK 0005 deferred. `comments` exists as of step 2.
    with op.batch_alter_table("prescores") as batch:
        batch.create_foreign_key(
            "fk_prescores_comment", "comments", ["comment_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    # Exact reverse. The prescores rebuild comes FIRST: it references `comments`,
    # which cannot be dropped while a constraint points at it. Same reason the
    # 0004 downgrade drops its two batch constraints before dropping `runs`.
    with op.batch_alter_table("prescores") as batch:
        batch.drop_constraint("fk_prescores_comment", type_="foreignkey")

    op.drop_index("ix_minhash_lookup", table_name="minhash_bands")
    op.drop_table("minhash_bands")

    op.drop_index("ux_dedup_members_comment", table_name="dedup_members")
    op.drop_index("ux_dedup_members_lead", table_name="dedup_members")
    op.drop_table("dedup_members")

    op.drop_index("ix_dedup_groups_project", table_name="dedup_groups")
    op.drop_table("dedup_groups")

    op.drop_index("ix_comments_project", table_name="comments")
    op.drop_index("ix_comments_lead", table_name="comments")
    op.drop_index("ux_comments_hash", table_name="comments")
    op.drop_table("comments")

    op.drop_index("ix_leads_project_conf", table_name="leads")
    op.drop_index("ix_leads_analysis_status", table_name="leads")
    op.drop_index("ix_leads_confidence_score", table_name="leads")
    op.drop_index("ix_leads_project_id", table_name="leads")

    op.drop_column("leads", "source")
    op.drop_column("leads", "analysis_status")
    op.drop_column("leads", "confidence_score")
    op.drop_column("leads", "project_id")
