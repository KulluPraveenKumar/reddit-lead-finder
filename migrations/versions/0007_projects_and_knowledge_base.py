"""projects_and_knowledge_base - the Business Knowledge Base schema

Revision ID: 0007_projects_and_knowledge_base
Revises: 0006_content_and_dedup
Create Date: 2026-08-15

Twelve tables, two more when ``sqlite-vec`` loads, and the closure of **six**
deferred ``project_id`` foreign keys. The largest revision in the chain
([freeze §4.1]), and the first to touch the live database since ``0006``.

**No row is written and no row is rewritten** (M5). Every table here is new; the
six existing tables are touched only by ``batch_alter_table`` to add a
constraint their column has been waiting for since it was created bare.

---------------------------------------------------------------------------
Three things a reader will expect to find here and will not
---------------------------------------------------------------------------

**1. ``runs.project_id`` is NOT tightened to ``NOT NULL``, and that is
deliberate.** [34 §P12]'s DB row and [05 §7.1a] step 3 both ask for it. It
cannot be done and should not be:

* **Measured, 2026-08-15:** all **11** rows in the live ``runs`` table have
  ``project_id IS NULL``. ``batch_alter_table`` + ``alter_column(nullable=False)``
  rebuilds via ``INSERT INTO _alembic_tmp_runs SELECT ...``, which fails outright
  on those rows. Making it pass means backfilling a placeholder project -- and
  **M5** says *"no migration rewrites a row"*.
* **AD-5 is frozen as "project scoping is additive and nullable."** A run
  created before a project exists has no project to belong to, which is exactly
  what [05 §7.1a] says in the sentence *before* the one asking for ``NOT NULL``.
* ``RunService.create(project_id: int | None, ...)`` is the shipped signature.
  Every run P1-P11 creates passes ``None``.

Recorded as a [freeze §11.1] reconciliation, not a §11 amendment: no technology,
table, decision or dependency changes, and the column keeps the nullability it
already has. The **foreign key is still created** -- that half was always
buildable.

**2. Six foreign keys close here, not four.** [34 §P12] names four
(``ai_calls``, ``runs``, ``dedup_groups``, ``minhash_bands``); [05 §7.1]'s table
names **six**, adding ``leads.project_id`` and ``comments.project_id``; [05 §7]'s
closing prose says three. ``scripts/check_schema.py`` has asserted since P8 that
all four of ``leads``/``comments``/``dedup_groups``/``minhash_bands`` are *"BARE
-- the FK is deferred to 0007"*. Six is the union, it is what M8 exists to
finish, and leaving two bare forever would make ``0007`` the revision that
deferred a foreign key to nowhere. Second [freeze §11.1] reconciliation.

The ``leads`` rebuild was **probed on a copy of the live database before this
file was written**: 492 rows, ``intent_score`` fingerprint ``9327a13dd9ef4185``
unchanged, all nine indexes preserved including the ``reddit_id`` UNIQUE, child
foreign keys on ``comments``/``dedup_members`` intact, ``PRAGMA
foreign_key_check`` empty. **M7 requires a timestamped backup before the
upgrade** regardless -- this is the legacy table R20 pins.

**3. ``bkb_sections.payload_json`` is NULLABLE, where [05 §5.1] declares it
``TEXT NOT NULL``.** [05 §5.1b] -- written later, and the more specific rule --
requires ``payload_json IS NULL`` for exactly ``buyer_personas``, ``pain_points``
and ``buying_signals``, because for those three the typed table is authoritative
and a second copy would rot. The two statements cannot both hold, and [34 §P12]'s
acceptance criterion encodes §5.1b. Third [freeze §11.1] reconciliation.

It ships as a ``CHECK`` rather than as a convention, because this schema already
enforces exactly this shape twice (``ck_prescores_one_target``,
``ck_dedup_members_one_target``) and because a rule enforced only by a test is a
rule the next writer can break in a transaction the test never sees.

---------------------------------------------------------------------------
Deletion semantics for the six closed keys
---------------------------------------------------------------------------

No document states them; P12 chooses, and the choice is not symmetric:

* ``ai_calls`` -> **SET NULL**, ``runs`` -> **CASCADE**. Both are given
  literally in [05 §7.1]'s code block.
* ``leads``, ``comments`` -> **SET NULL**. [freeze §8] lists *"expiring leads"*
  as a permanent non-goal on the grounds that *"a lead is a historical fact"*.
  Cascading a project deletion into the collected corpus would delete real
  research; a comment's lifetime is already tied to its lead, which cascades.
* ``dedup_groups``, ``minhash_bands`` -> **CASCADE**. Both are derived per-run
  artefacts that are rebuilt from scratch, and both already cascade from ``runs``.

``dedup_groups.project_id`` and ``minhash_bands.project_id`` stay **nullable**,
the question [05 §7.1] left explicitly to this revision. P10's cascade and P11's
stage write them as ``None`` on every run today, so ``NOT NULL`` would break
shipped behaviour to satisfy a document. Recorded rather than inherited.

---------------------------------------------------------------------------
The conditional pair
---------------------------------------------------------------------------

``bkb_embeddings`` (a ``vec0`` virtual table) and ``bkb_embedding_meta`` are
created **only if ``sqlite-vec`` loads**. [05 §7.1a]: *"the migration must not
fail when the extension is missing"* -- a hard dependency on a loadable C
extension would make the whole schema un-installable in exchange for a recall
improvement, and embeddings never *reject* anything ([06e §5.3]), so their
absence costs recall, not correctness.

⚠️ **Measured on this host, 2026-08-15: ``sqlite_vec`` is not installed**, which
is P0's finding unchanged ([SPRINT-0-MEASUREMENTS §3.1]) and the same measurement
that had P10 ship its semantic tier off by default. So the *skip* branch is the
one that runs here, and ``/api/health`` reports ``semantic_layer: disabled``
rather than leaving the degradation silent. **No dependency is added** --
[34 §P12]'s Config row is None and [freeze §5] lists the vector stack as
optional.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_projects_and_knowledge_base"
down_revision: str | None = "0006_content_and_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The three BKB sections whose content lives in a typed table instead of in
#: ``payload_json`` ([05 §5.1b]). Spelled literally here rather than imported
#: from ``src.db.models``: a migration is a snapshot of the schema at one point
#: in the chain, and importing a constant that a later phase may edit would make
#: this revision mean something different next year than it meant when it ran.
#: ``tests/test_schema_0007.py`` asserts the two spellings agree.
TYPED_SECTION_KEYS: tuple[str, ...] = ("buyer_personas", "pain_points", "buying_signals")

#: ``payload_json IS NULL`` for exactly those three, NOT NULL for the other
#: twenty -- **including ``ideal_customer_profiles``**, which has no typed table
#: and whose payload is therefore the only copy of an ICP that exists. [05 §5.1b]
#: flags that one specifically as the mistake a reader is likely to make.
_PAYLOAD_NULL_RULE = (
    "(section_key IN ('buyer_personas', 'pain_points', 'buying_signals'))"
    " = (payload_json IS NULL)"
)

#: The vector pair, as literal DDL. Kept as data rather than inline so that
#: ``tests/test_schema_0007.py`` can assert what *would* run on a host that has
#: the extension -- the branch itself cannot execute where ``sqlite_vec`` is
#: absent, which is every host measured so far.
VEC0_DDL = "CREATE VIRTUAL TABLE bkb_embeddings USING vec0(embedding FLOAT[256])"


def _load_sqlite_vec(bind) -> None:
    """Load the ``sqlite-vec`` extension onto Alembic's own connection.

    Onto *this* connection specifically: an extension loaded elsewhere is not
    visible to the statement ``op.execute`` is about to prepare, and the failure
    would be ``no such module: vec0`` at DDL time rather than an ImportError
    here.

    Raises whatever went wrong. The caller decides that a failure is not fatal;
    this function does not, because a helper that swallows its own errors cannot
    be tested for the two outcomes that matter.
    """
    import sqlite_vec

    raw = bind.connection.driver_connection
    raw.enable_load_extension(True)
    try:
        sqlite_vec.load(raw)
    finally:
        # Leave the connection as it was found. The extension stays loaded for
        # this connection's lifetime; the *ability* to load more does not.
        raw.enable_load_extension(False)


def upgrade() -> None:
    # ---- 1. projects. Referenced by everything below and by six existing
    #         tables whose columns have been waiting bare since 0002/0004/0006.
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("website_url", sa.Text(), nullable=False),
        # scheme+host, lowercased, no trailing slash -- the identity of a
        # project, so that two spellings of one site are one project.
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ux_projects_normalized_url", "projects", ["normalized_url"], unique=True)

    # ---- 2-7. The six deferred foreign keys. `projects` exists as of step 1.
    #
    #   ⚠️ Order matters less here than the fact that each is a REBUILD:
    #   SQLite cannot ADD CONSTRAINT, so batch_alter_table does
    #   create-copy-drop-rename on each of these six tables -- including
    #   `leads`, which carries the 459 rows R20 pins. M7's backup is not
    #   optional. (batch_alter_table does NOT rebuild when its only operation is
    #   add_column; alembic emits a plain ALTER there. This is the other case.)
    with op.batch_alter_table("ai_calls") as batch:
        batch.create_foreign_key(
            "fk_ai_calls_project", "projects", ["project_id"], ["id"], ondelete="SET NULL"
        )

    # runs.project_id keeps its nullability. See the module docstring, point 1:
    # 11 of 11 live rows are NULL, M5 forbids rewriting them, and AD-5 freezes
    # project scoping as additive and nullable.
    with op.batch_alter_table("runs") as batch:
        batch.create_foreign_key(
            "fk_runs_project", "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("leads") as batch:
        batch.create_foreign_key(
            "fk_leads_project", "projects", ["project_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("comments") as batch:
        batch.create_foreign_key(
            "fk_comments_project", "projects", ["project_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("dedup_groups") as batch:
        batch.create_foreign_key(
            "fk_dedup_groups_project", "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("minhash_bands") as batch:
        batch.create_foreign_key(
            "fk_minhash_bands_project", "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )

    # ---- 8. website_snapshots. Referenced by bkb_evidence (step 17).
    #         Separate from `projects` so a re-analysis can compare against what
    #         the previous one actually read.
    op.create_table(
        "website_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_website_snapshots_project", "website_snapshots", ["project_id"])

    # ---- 9. bkb. One current row per project; `superseded_at IS NULL` is the
    #         current one, which is why the index leads with the pair.
    op.create_table(
        "bkb",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        # Measured size of the enrichment prefix (06e §6), and the sections the
        # budget dropped from it. Both NULL until P15 builds a prefix.
        sa.Column("prefix_tokens", sa.Integer(), nullable=True),
        sa.Column("dropped_sections_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="complete"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_bkb_current", "bkb", ["project_id", "superseded_at"])

    # ---- 10. bkb_sections. 23 rows per BKB, each versioned independently.
    op.create_table(
        "bkb_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bkb_id", sa.Integer(), sa.ForeignKey("bkb.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("section_key", sa.String(length=40), nullable=False),
        # NULLABLE, against 05 §5.1's `TEXT NOT NULL`. See the module docstring,
        # point 3: §5.1b requires NULL for exactly the three typed sections, and
        # the CHECK below makes that the schema's rule rather than a convention.
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        # Matching surface vs retrieval-only (06e §6).
        sa.Column("in_prefix", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("edited_by_user", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 05 §5.1c, written inline rather than as ALTER: the revision has not
        # shipped, so there is nothing to alter, and writing it as ALTER would
        # be a self-inflicted batch_alter_table on SQLite.
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        # NULL means "never stales". Seeded per section group by P14 from
        # `src.db.models.BKB_STALENESS_DAYS`; Group C is NULL because it
        # accretes from Reddit and is getting fresher, not older.
        sa.Column("staleness_days", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="website"),
        sa.CheckConstraint(_PAYLOAD_NULL_RULE, name="ck_bkb_sections_payload_null_rule"),
    )
    op.create_index("ux_bkb_sections", "bkb_sections", ["bkb_id", "section_key"], unique=True)

    # ---- 11. personas. Referenced by pain_points (step 12).
    #          Carries BOTH project_id and bkb_id (05 §5.1b): without bkb_id,
    #          deleting a superseded BKB would drop the evidence and leave the
    #          persona behind, unevidenced but still displayed.
    op.create_table(
        "personas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bkb_id", sa.Integer(), sa.ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True
        ),
        # The join key the LLM emits: stable, human-readable, and something the
        # model has a chance of getting right, unlike a database integer.
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("job_title", sa.String(length=160), nullable=True),
        sa.Column("seniority", sa.String(length=60), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("goals_json", sa.Text(), nullable=True),
        sa.Column("tools_json", sa.Text(), nullable=True),
        sa.Column("subreddits_json", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="website"),
    )
    op.create_index("ux_personas_project_slug", "personas", ["project_id", "slug"], unique=True)

    # ---- 12. pain_points. References personas.
    op.create_table(
        "pain_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bkb_id", sa.Integer(), sa.ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="3"),  # 1..5
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="3"),  # 1..5
        # How a person phrases this complaint. This is the column the pre-score's
        # `pain_phrase` component will read -- it is created empty here and
        # populated by P14's analyze_business.
        sa.Column("phrases_json", sa.Text(), nullable=True),
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("personas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="website"),
    )
    op.create_index(
        "ux_pain_points_project_slug", "pain_points", ["project_id", "slug"], unique=True
    )

    # ---- 13. intent_signals. Feeds ConfidenceScorer (P21) via `weight`.
    op.create_table(
        "intent_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bkb_id", sa.Integer(), sa.ForeignKey("bkb.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("tier", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="website"),
    )
    op.create_index(
        "ux_intent_signals_project_slug", "intent_signals", ["project_id", "slug"], unique=True
    )

    # ---- 14. bkb_entities. Covers ONLY the entity kinds with no typed table --
    #          competitor, product, feature, tool, alternative (05 §5.1a). The
    #          three tables above already are typed entity tables with slugs;
    #          nothing appears in both, or there would be two registries for one
    #          thing.
    op.create_table(
        "bkb_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 05 §5.1c: entities drift, and aliases alone do not capture it. The
        # self-reference is created inline -- the table exists by the time
        # SQLite resolves it, because it is the table being created.
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "merged_into_id", sa.Integer(), sa.ForeignKey("bkb_entities.id"), nullable=True
        ),
    )
    op.create_index("ux_bkb_entities", "bkb_entities", ["project_id", "kind", "slug"], unique=True)

    # ---- 15. bkb_entity_aliases. Resolution tiers 1-3 are pure lookups over
    #          this table (06e §4), which is why alias_norm carries its own
    #          non-unique index as well as the composite unique.
    op.create_table(
        "bkb_entity_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("bkb_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(length=160), nullable=False),
        # casefolded, punctuation and spacing stripped
        sa.Column("alias_norm", sa.String(length=160), nullable=False),
        # site | casing | misspelling | acronym | domain | confirmed
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ux_bkb_alias_norm", "bkb_entity_aliases", ["entity_id", "alias_norm"], unique=True
    )
    op.create_index("ix_bkb_alias_lookup", "bkb_entity_aliases", ["alias_norm"])

    # ---- 16. bkb_links. Endpoints are (kind, row id) pairs so an edge can span
    #          the typed tables and bkb_entities without five nullable FK
    #          columns. Polymorphic by design, so there is no FK ordering
    #          requirement and no referential integrity on the endpoints --
    #          the cost of the shape, paid knowingly.
    op.create_table(
        "bkb_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(length=40), nullable=False),
        sa.Column("src_kind", sa.String(length=30), nullable=False),
        sa.Column("src_id", sa.Integer(), nullable=False),
        sa.Column("dst_kind", sa.String(length=30), nullable=False),
        sa.Column("dst_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ux_bkb_links",
        "bkb_links",
        ["project_id", "relation", "src_kind", "src_id", "dst_kind", "dst_id"],
        unique=True,
    )
    op.create_index("ix_bkb_links_src", "bkb_links", ["src_kind", "src_id"])

    # ---- 17. bkb_evidence. References bkb and website_snapshots, plus leads
    #          and comments -- which is what makes Reddit-sourced knowledge
    #          auditable: "why does the BKB think this objection exists?"
    #          resolves to real threads rather than to a count.
    op.create_table(
        "bkb_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bkb_id", sa.Integer(), sa.ForeignKey("bkb.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("subject_kind", sa.String(length=30), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        # Must be a literal substring of the snapshot text. NULLABLE, because
        # 05 §5.1c requires a source_type='ai_inference' row to carry no quote:
        # there is nothing to point at, and a quote there would be a fabrication.
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("website_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # website | reddit_post | reddit_comment | operator | ai_inference
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="website"),
        sa.Column(
            "lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "comment_id",
            sa.Integer(),
            sa.ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_by", sa.String(length=80), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_bkb_evidence_subject", "bkb_evidence", ["subject_kind", "subject_id"])
    op.create_index("ix_bkb_evidence_source", "bkb_evidence", ["source_type"])

    # ---- 18. bkb_suggestions. Learned proposals awaiting operator review
    #          (06e §7). Never auto-applied.
    op.create_table(
        "bkb_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),  # alias|pain_phrase|entity
        sa.Column("payload_json", sa.Text(), nullable=False),
        # The lead ids and spans that produced the proposal.
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        # 05 §5.1c: aggregate evidence, so the 06e §4.2 threshold is checkable.
        sa.Column("pattern_kind", sa.String(length=30), nullable=True),
        sa.Column("distinct_groups", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_bkb_suggestions_pending", "bkb_suggestions", ["project_id", "status"])

    # ---- 19. The conditional pair. A missing extension logs a warning and
    #          skips BOTH tables -- meta without embeddings would be a table of
    #          pointers into nothing.
    bind = op.get_bind()
    try:
        _load_sqlite_vec(bind)
        op.execute(VEC0_DDL)
        op.create_table(
            "bkb_embedding_meta",
            # Matches bkb_embeddings.rowid. Named `rowid` per 05 §5.1a; in
            # SQLite an INTEGER PRIMARY KEY column *is* the rowid, so the two
            # tables share a key without a join table.
            sa.Column("rowid", sa.Integer(), primary_key=True),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subject_kind", sa.String(length=30), nullable=False),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            # Invalidation key: a model change invalidates every vector written
            # under the old one.
            sa.Column("model_name", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_bkb_emb_meta",
            "bkb_embedding_meta",
            ["project_id", "subject_kind", "subject_id"],
        )
    except Exception as exc:  # noqa: BLE001 - the extension is optional by design
        # Deliberately broad: a sqlite_vec that imports but cannot load, a
        # SQLite built without extension support, and a plain ImportError are
        # the same outcome here -- no vector tables, and a platform that still
        # works. `/api/health` reports `semantic_layer: disabled` so this is
        # visible rather than silent.
        _log_skip(exc)


def _log_skip(exc: Exception) -> None:
    """Warn that the semantic layer was skipped, on alembic's own logger.

    Its own function so the skip can be asserted without capturing the whole
    migration's output, and so the message has one spelling.
    """
    import logging

    logging.getLogger("alembic.runtime.migration").warning(
        "sqlite-vec unavailable (%s); semantic layer disabled, bkb_embeddings "
        "and bkb_embedding_meta were not created",
        exc,
    )


def downgrade() -> None:
    # Exact reverse of upgrade(). The six batch constraints are dropped BEFORE
    # `projects`, for the reason 0006's downgrade drops the prescores constraint
    # first: a table cannot be dropped while a foreign key points at it.
    #
    # The vector pair is dropped first of all and conditionally -- on a host
    # without the extension it was never created, and `DROP TABLE IF EXISTS` is
    # the honest statement of "if this ran, undo it".
    op.execute("DROP TABLE IF EXISTS bkb_embedding_meta")
    op.execute("DROP TABLE IF EXISTS bkb_embeddings")

    op.drop_index("ix_bkb_suggestions_pending", table_name="bkb_suggestions")
    op.drop_table("bkb_suggestions")

    op.drop_index("ix_bkb_evidence_source", table_name="bkb_evidence")
    op.drop_index("ix_bkb_evidence_subject", table_name="bkb_evidence")
    op.drop_table("bkb_evidence")

    op.drop_index("ix_bkb_links_src", table_name="bkb_links")
    op.drop_index("ux_bkb_links", table_name="bkb_links")
    op.drop_table("bkb_links")

    op.drop_index("ix_bkb_alias_lookup", table_name="bkb_entity_aliases")
    op.drop_index("ux_bkb_alias_norm", table_name="bkb_entity_aliases")
    op.drop_table("bkb_entity_aliases")

    op.drop_index("ux_bkb_entities", table_name="bkb_entities")
    op.drop_table("bkb_entities")

    op.drop_index("ux_intent_signals_project_slug", table_name="intent_signals")
    op.drop_table("intent_signals")

    op.drop_index("ux_pain_points_project_slug", table_name="pain_points")
    op.drop_table("pain_points")

    op.drop_index("ux_personas_project_slug", table_name="personas")
    op.drop_table("personas")

    op.drop_index("ux_bkb_sections", table_name="bkb_sections")
    op.drop_table("bkb_sections")

    op.drop_index("ix_bkb_current", table_name="bkb")
    op.drop_table("bkb")

    op.drop_index("ix_website_snapshots_project", table_name="website_snapshots")
    op.drop_table("website_snapshots")

    with op.batch_alter_table("minhash_bands") as batch:
        batch.drop_constraint("fk_minhash_bands_project", type_="foreignkey")
    with op.batch_alter_table("dedup_groups") as batch:
        batch.drop_constraint("fk_dedup_groups_project", type_="foreignkey")
    with op.batch_alter_table("comments") as batch:
        batch.drop_constraint("fk_comments_project", type_="foreignkey")
    with op.batch_alter_table("leads") as batch:
        batch.drop_constraint("fk_leads_project", type_="foreignkey")
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("fk_runs_project", type_="foreignkey")
    with op.batch_alter_table("ai_calls") as batch:
        batch.drop_constraint("fk_ai_calls_project", type_="foreignkey")

    op.drop_index("ux_projects_normalized_url", table_name="projects")
    op.drop_table("projects")
