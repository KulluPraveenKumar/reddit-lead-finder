"""BKB persistence — supersede, upsert, and the origin guard's near half.

Repositories exist so query logic does not sprawl into handlers (AD-6). This one
owns every statement ``analyze_business`` issues against the five tables
[34 §P14](../../../docs/34-implementation-plan.md)'s **DB** row names: ``bkb``,
``bkb_sections``, ``personas``, ``pain_points`` and ``intent_signals``.

**It creates no table and opens no revision.** `0007` created all five
([PHASE-12-COMPLETION-REPORT](../../../docs/PHASE-12-COMPLETION-REPORT.md)); the
head stays `0007`, seven revisions of ten, and
`test_the_chain_is_still_ten_revisions_or_fewer` is still **P17's** to change.

## Supersede, never overwrite

``BKB.superseded_at IS NULL`` is the current version, which is why
``ix_bkb_current`` leads with ``(project_id, superseded_at)``. A re-analysis
stamps the old row and inserts a new one at ``version + 1``. Keeping the old
version is what makes *"what did we think last month, and on what evidence?"*
answerable, and it is what ``bkb_evidence``'s CASCADE hangs off.

## What a "soft delete" is here, exactly

⚠ **``personas``, ``pain_points`` and ``intent_signals`` have no ``status`` and
no ``deleted_at`` column**, and `0007` is shipped, so adding one would be a
[freeze §4.1](../../../docs/ARCHITECTURE_FREEZE.md) amendment needing a failed
measurement. The soft delete is therefore expressed in the columns that exist:

    a typed row is CURRENT iff its `bkb_id` is the current BKB's id.

A slug that vanishes from a re-analysis is simply **not re-pointed** — it keeps
the ``bkb_id`` of the superseded BKB, stays queryable, stays labellable, and
falls out of the current knowledge base without a row being deleted. That is
[34 §P14](../../../docs/34-implementation-plan.md) task 4's *"vanished slugs
soft-deleted"* with no schema change. It is also the only reading consistent
with [freeze §8](../../../docs/ARCHITECTURE_FREEZE.md)'s *"a lead is a historical
fact"* posture toward deletion.

## The origin guard, and what of it belongs to P14

[R12](../../../docs/ARCHITECTURE_FREEZE.md) — *knowledge accretes; regeneration
deletes only ``origin='website'`` rows* — and its enforcement,
``lifecycle.regenerate_section``, are **P15's**
([34 §P15](../../../docs/34-implementation-plan.md) task 4). P14 must not
pre-empt it and must not *break* it. So this module takes the narrow half it
cannot avoid taking: **a row whose ``origin`` is not ``'website'`` has its
``bkb_id`` re-pointed and its content left alone.** An operator's edit and a
Reddit-learned row survive a re-analysis; a website-derived row is refreshed
from the site. Nothing is deleted here by any path.
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Deferred deliberately. ``src.knowledge.bkb`` imports this module, so a
    # runtime import back into ``src.knowledge`` would close a cycle through
    # ``src/knowledge/__init__.py`` and leave one of the two packages
    # half-initialised depending on which was imported first.
    from src.knowledge.sections import ValidatedSection

from ..models import (
    BKB,
    BKB_STALENESS_DAYS,
    BKBSection,
    IntentSignal,
    PainPoint,
    Persona,
)

log = logging.getLogger(__name__)

#: ``origin`` values. Only the first is P14's to write or refresh; the other two
#: are re-pointed and never touched. `05 §5.1` fixes the vocabulary.
ORIGIN_WEBSITE = "website"

#: ``bkb.status``. The column's comment says ``complete | partial | failed``.
BKB_COMPLETE = "complete"
BKB_PARTIAL = "partial"

#: ``intent_signals.weight`` per tier. The column defaults to 0.2 and P21's
#: ``ConfidenceScorer`` reads it as **arithmetic over a stored value, never a
#: model call** (R6) — so the tier the model emits is mapped to a number *here*,
#: deterministically, rather than the model being asked for the number.
TIER_WEIGHTS: dict[str, float] = {"high": 0.5, "medium": 0.3, "low": 0.15}


def _utcnow() -> datetime.datetime:
    """Naive UTC, matching every ``default=_utcnow`` column in ``models.py``.

    ⚠ Naive, deliberately. [DI36](../../../docs/DEFERRED-IMPROVEMENTS.md) is the
    record of what mixing the two costs: an aware value compared against a naive
    column raises, and a *local*-time value compares fine and is silently wrong.
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class KnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- the BKB

    def current(self, project_id: int) -> BKB | None:
        """The live BKB for a project, or ``None`` before the first analysis."""
        return (
            self.session.query(BKB)
            .filter(BKB.project_id == project_id, BKB.superseded_at.is_(None))
            .order_by(BKB.version.desc())
            .first()
        )

    def supersede_current(self, project_id: int, *, at: datetime.datetime | None = None) -> int:
        """Stamp every live BKB for this project. Returns how many were stamped.

        Written as *every* rather than *the* on purpose: the invariant is one
        live row per project, and a writer that assumes an invariant it does not
        enforce is how the invariant stops being true. If a previous crash left
        two, this closes both instead of leaving one live behind the new one.
        """
        stamped = at or _utcnow()
        rows = (
            self.session.query(BKB)
            .filter(BKB.project_id == project_id, BKB.superseded_at.is_(None))
            .all()
        )
        for row in rows:
            row.superseded_at = stamped
        return len(rows)

    def create_bkb(
        self,
        project_id: int,
        *,
        model: str,
        prompt_version: int,
        status: str = BKB_COMPLETE,
    ) -> BKB:
        """Supersede whatever is live, then insert the next version.

        ``version`` counts from the highest that has *ever* existed for the
        project, not from the live one — otherwise a superseded row and a new
        one could collide on a number, and *"BKB v3"* would name two things.
        """
        highest = (
            self.session.query(BKB.version)
            .filter(BKB.project_id == project_id)
            .order_by(BKB.version.desc())
            .first()
        )
        self.supersede_current(project_id)

        row = BKB(
            project_id=project_id,
            version=(highest[0] if highest else 0) + 1,
            model=model,
            prompt_version=prompt_version,
            status=status,
        )
        self.session.add(row)
        self.session.flush()  # the id is the parent of everything below
        return row

    def set_status(self, bkb: BKB, status: str) -> None:
        bkb.status = status

    # ----------------------------------------------------------- the sections

    def upsert_section(self, bkb_id: int, section: ValidatedSection) -> BKBSection:
        """One of the 23 rows, keyed by ``ux_bkb_sections`` on ``(bkb_id, key)``.

        ``payload_json`` is taken from the verdict rather than decided here, so
        ``ck_bkb_sections_payload_null_rule`` is satisfied by construction:
        :class:`~src.knowledge.sections.ValidatedSection` already carries
        ``None`` for exactly the three typed sections.

        ``staleness_days`` is seeded from ``BKB_STALENESS_DAYS`` — **P12 shipped
        that policy as data specifically so P14 would have one place to read it
        from** rather than a table in a document to re-transcribe
        (`src/db/models.py:819`). Group C is ``NULL``: those seven accrete from
        Reddit and are getting fresher, not older.
        """
        row = (
            self.session.query(BKBSection)
            .filter(BKBSection.bkb_id == bkb_id, BKBSection.section_key == section.key)
            .one_or_none()
        )
        if row is None:
            row = BKBSection(bkb_id=bkb_id, section_key=section.key)
            self.session.add(row)

        row.payload_json = (
            None if section.payload is None else json.dumps(section.payload, sort_keys=True)
        )
        row.confidence = section.confidence
        row.status = section.status
        row.staleness_days = BKB_STALENESS_DAYS[section.key]
        row.origin = ORIGIN_WEBSITE
        row.last_verified_at = _utcnow()
        return row

    def sections_for(self, bkb_id: int) -> list[BKBSection]:
        return (
            self.session.query(BKBSection)
            .filter(BKBSection.bkb_id == bkb_id)
            .order_by(BKBSection.id)
            .all()
        )

    # -------------------------------------------------------- the typed tables

    def upsert_personas(self, project_id: int, bkb_id: int, items: Sequence[Any]) -> list[Persona]:
        """``personas``, upserted on ``ux_personas_project_slug``."""

        def apply(row: Persona, item: Any, order: int) -> None:
            row.name = item.name
            row.job_title = item.job_title or None
            row.seniority = item.seniority or None
            row.description = None
            row.goals_json = _dump(item.responsibilities, item.metrics)
            row.tools_json = _dump(item.tools)
            row.subreddits_json = _dump(item.where_they_ask)
            row.display_order = order

        return self._upsert_typed(Persona, project_id, bkb_id, items, apply)

    def upsert_pain_points(
        self, project_id: int, bkb_id: int, items: Sequence[Any]
    ) -> list[PainPoint]:
        """``pain_points``, upserted on ``ux_pain_points_project_slug``.

        ⚠ **``phrases_json`` is the column the pre-score's ``pain_phrase``
        component reads**, and writing it is this phase's obligation to
        `src.scoring.ABSENT_COMPONENTS`. **The component itself is NOT wired
        here** — operator decision D2,
        [P14-DECISION-ANALYSIS](../../../docs/P14-DECISION-ANALYSIS.md): the
        first ``projects`` row is P16's, so a component wired now would
        contribute a structural zero to every real lead until then, which is
        [DI24](../../../docs/DEFERRED-IMPROVEMENTS.md) exactly. P14 supplies the
        data; P16 supplies the reader, and ``WEIGHTS`` rescales **once**.
        """

        def apply(row: PainPoint, item: Any, order: int) -> None:
            row.title = item.title
            row.description = item.description or None
            row.severity = item.severity
            row.frequency = item.frequency
            row.phrases_json = _dump(item.how_people_phrase_it)

        return self._upsert_typed(PainPoint, project_id, bkb_id, items, apply)

    def upsert_intent_signals(
        self, project_id: int, bkb_id: int, items: Sequence[Any]
    ) -> list[IntentSignal]:
        """``intent_signals``, upserted on ``ux_intent_signals_project_slug``."""

        def apply(row: IntentSignal, item: Any, order: int) -> None:
            row.label = item.label
            row.description = None
            row.tier = item.tier
            # R6: the number is arithmetic over the categorical the model emits,
            # never a number the model was asked for.
            row.weight = TIER_WEIGHTS.get(item.tier, 0.2)

        return self._upsert_typed(IntentSignal, project_id, bkb_id, items, apply)

    def _upsert_typed(
        self,
        entity: type,
        project_id: int,
        bkb_id: int,
        items: Sequence[Any],
        apply,
    ) -> list:
        """The shared body of the three upserts above.

        Two properties matter more than the field copying:

        1. **Idempotence (R9).** Every field is *assigned*, never incremented or
           appended, so replaying the same analysis lands on the same rows with
           the same values rather than accumulating duplicates.
        2. **The origin guard's near half.** A row whose ``origin`` is not
           ``'website'`` — an operator edit, or something P15 learned from Reddit
           — has its ``bkb_id`` re-pointed so it stays *current*, and its content
           is **left exactly as it is**. See this module's docstring.
        """
        written = []
        for order, item in enumerate(items):
            row = (
                self.session.query(entity)
                .filter(entity.project_id == project_id, entity.slug == item.slug)
                .one_or_none()
            )
            if row is None:
                row = entity(project_id=project_id, slug=item.slug, origin=ORIGIN_WEBSITE)
                self.session.add(row)

            # Re-point first: a non-website row is still part of THIS BKB, it is
            # simply not rewritten by it.
            row.bkb_id = bkb_id
            if row.origin == ORIGIN_WEBSITE:
                apply(row, item, order)
            else:
                log.info(
                    "%s %r kept its %s content across a re-analysis",
                    entity.__tablename__,
                    item.slug,
                    row.origin,
                )
            written.append(row)

        self.session.flush()
        return written

    # ------------------------------------------------------------- the reads

    def personas_for(self, bkb_id: int) -> list[Persona]:
        return self._current(Persona, bkb_id)

    def pain_points_for(self, bkb_id: int) -> list[PainPoint]:
        return self._current(PainPoint, bkb_id)

    def intent_signals_for(self, bkb_id: int) -> list[IntentSignal]:
        return self._current(IntentSignal, bkb_id)

    def _current(self, entity: type, bkb_id: int) -> list:
        return self.session.query(entity).filter(entity.bkb_id == bkb_id).order_by(entity.id).all()

    def orphaned_slugs(self, entity: type, project_id: int, bkb_id: int) -> list[str]:
        """Slugs this project has that the current BKB does **not** claim.

        The soft delete, made observable. Without a query that names them, *"the
        vanished slug is still there but is no longer current"* is a claim about
        a row rather than something a test or an operator can see.
        """
        return [
            slug
            for (slug,) in self.session.query(entity.slug)
            .filter(entity.project_id == project_id, entity.bkb_id != bkb_id)
            .order_by(entity.slug)
        ]


def _dump(*values: Iterable[Any]) -> str | None:
    """JSON for a ``*_json`` column, or ``NULL`` when there is nothing to say.

    ``NULL`` rather than ``"[]"`` so a reader can tell *"the model said none"*
    from *"this column was never written"* — the same distinction
    ``SiteSignals.markup_seen`` exists to preserve one layer up
    ([DI33](../../../docs/DEFERRED-IMPROVEMENTS.md)).
    """
    merged: list[Any] = []
    for value in values:
        merged.extend(value or ())
    return json.dumps(merged, sort_keys=False) if merged else None


__all__ = [
    "BKB_COMPLETE",
    "BKB_PARTIAL",
    "ORIGIN_WEBSITE",
    "TIER_WEIGHTS",
    "KnowledgeRepository",
]
