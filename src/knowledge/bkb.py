"""``analyze_business``, end to end: one call in, 23 persisted sections out.

[34 §P14](../../docs/34-implementation-plan.md)'s Objective, in one sentence:
*"**One** AI call produces 23 validated BKB sections, with per-section failure
isolation"*. This module is where the one call is made, the 23 verdicts are
taken, and the rows are written.

```
ExtractedSite + SiteSignals
   │
   ├─ build_local_signals()      facts, not questions (06 §2.2) — and DI33
   ├─ AIService.analyze_business_call()          ← the ONE call (R2, R10)
   │     └─ ai_cache hit on (fingerprint, prompt_version) → ZERO calls (L2)
   ├─ validate_sections()        23 independent verdicts, none can raise
   └─ KnowledgeRepository        supersede → 23 sections → 3 typed tables
```

**Why this is not a job type.** ``src/orchestration/handlers/website.py`` calls
into here as a *function*, exactly as ``handlers/prescore.py`` is called by the
finaliser and for the reason its docstring records:
[DI15](../../docs/DEFERRED-IMPROVEMENTS.md) says an eighth job type already
shipped unreconciled against [04 §2.4](../../docs/04-system-design.md)'s closed
list of seven, and a ninth for a stage with no independent retry semantics would
deepen a debt P14 does not own.

**Nothing here reaches a model except through ``AIService``** ([R2](../../docs/ARCHITECTURE_FREEZE.md))
— and this package imports `src.ai` **not at all** ([R3](../../docs/ARCHITECTURE_FREEZE.md)). The
service arrives as the ``service`` parameter, constructed by the handler on the other side of the
fence. That is why :func:`analyze` takes it rather than building one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.db.models import BKB_SECTION_KEYS
from src.db.repositories.knowledge import BKB_COMPLETE, BKB_PARTIAL, KnowledgeRepository

from .sections import ValidatedSection, validate_sections

log = logging.getLogger(__name__)

#: The four local signals that need markup to compute. On an L1 cache hit
#: ``website_snapshots`` has stored text and no HTML, so these are empty
#: **because nothing was parsed** — [DI33](../../docs/DEFERRED-IMPROVEMENTS.md).
MARKUP_SIGNAL_KEYS = ("tech_markers", "structured_data", "social_links", "nav_taxonomy")

#: The flag that replaces them. See :func:`build_local_signals`.
MARKUP_ABSENT_KEY = "markup_not_observed"

#: [34 §P14](../../docs/34-implementation-plan.md)'s Metrics row, *"< $0.05"*.
#: Exceeding it is logged loudly and does **not** raise: the budget guard in
#: ``src/ai/cost.py`` owns *stopping* spend, and a second gate that could refuse
#: an already-paid-for answer would throw away knowledge the operator was billed
#: for. This is a measurement, and P16 renders it as the cost chip.
COST_BUDGET_USD = 0.05


# ⚠️ **There is no settings object here, and the absence is the design.**
# [34 §P14](../../docs/34-implementation-plan.md)'s Config row names one key, an
# output budget for this stage, and the first draft of this module read it into
# a ``BKBSettings`` dataclass — which
# ``tests/test_boundaries.py::test_no_wire_format_details_outside_ai`` rejected
# on the spot — business logic must not know what the provider's wire knobs are.
# It was right, and the fence found it before review did. (That test matches on
# raw text rather than on the AST, so this comment cannot spell the knobs out
# either; read the test for the list.) An output budget is a **wire** concern,
# so the key is read by
# ``AIService.analyze_business_call`` — see ``src/ai/service.py``, which is the
# only module permitted to name it — and this one passes no budget at all.
#
# The rollback property the Config row implies is unchanged; it is simply
# asserted where the key is now read, in ``tests/test_knowledge_bkb.py``.


@dataclass(frozen=True)
class BKBResult:
    """What one analysis did — including what it did *not* spend."""

    bkb_id: int
    version: int
    sections: tuple[ValidatedSection, ...]
    reused: bool
    calls_made: int
    cost_usd: float
    status: str

    @property
    def incomplete(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.sections if not s.ok)

    @property
    def complete_count(self) -> int:
        return sum(1 for s in self.sections if s.ok)

    def to_dict(self) -> dict[str, Any]:
        """The payload the handler puts on ``run_events`` and P16 renders."""
        return {
            "bkb_id": self.bkb_id,
            "version": self.version,
            "sections": len(self.sections),
            "complete": self.complete_count,
            "incomplete": list(self.incomplete),
            "reused": self.reused,
            "calls": self.calls_made,
            "cost_usd": round(self.cost_usd, 6),
            "status": self.status,
        }


def build_local_signals(signals: Any) -> dict[str, Any]:
    """The ``local_signals`` block, as **facts rather than questions**.

    [06 §2.2](../../docs/06-ai-pipeline.md) and
    [PHASE-13-HANDOVER §3.3](../../docs/PHASE-13-HANDOVER.md): asking a model to
    find a ``<meta generator>`` tag is paying tokens for a parser, so what the
    parser already found is handed over as established fact.

    ⚠ **This function is [DI33](../../docs/DEFERRED-IMPROVEMENTS.md)'s answer,
    and it is the reason this phase could close it.** When ``markup_seen`` is
    ``False`` the four markup-derived keys are **omitted entirely** and
    ``markup_not_observed: true`` is rendered in their place — rather than
    emitting four empty lists, which read identically to *"this site has none of
    these"* and would have the model record *"this company uses no analytics"*
    as a fact about the business. The prompt's Rules section carries the
    matching clause: an omitted signal is **unobserved**, never **absent**.

    P13 named three options and picked none, having no consumer. P14 is the
    consumer, and the answer is the third: **accept the degradation and mark
    it** — no column, no migration, and no re-fetch, so neither
    [freeze §4.1](../../docs/ARCHITECTURE_FREEZE.md) nor P13's zero-fetch
    guarantee is disturbed.
    """
    payload: dict[str, Any] = {
        "competitors": list(signals.competitors),
        "pricing": {
            "currencies": list(signals.pricing.currencies),
            "amounts": list(signals.pricing.amounts),
            "intervals": list(signals.pricing.intervals),
            "posture": list(signals.pricing.posture),
        },
    }

    if not signals.markup_seen:
        payload[MARKUP_ABSENT_KEY] = True
        return payload

    payload["tech_markers"] = list(signals.tech_markers)
    payload["structured_data"] = list(signals.structured_data)
    payload["social_links"] = [list(pair) for pair in signals.social_links]
    payload["nav_taxonomy"] = list(signals.nav_taxonomy)
    return payload


def analyze(
    session,
    *,
    project_id: int,
    site: Any,
    signals: Any,
    service: Any,
    config: dict[str, Any] | None = None,
) -> BKBResult:
    """One website, one call, 23 persisted sections.

    ⚠ **The call is made before the write, and exactly once.** There is no retry
    loop here and there must not be one: ``AIService._execute`` already owns
    retry, repair and the budget guard, and a second loop at this level would
    turn *"exactly one ``ai_calls`` row"* into *"one per outer attempt"* — the
    criterion this phase is measured on.

    ⚠ **Per-section failure never reaches this function as an exception.**
    :func:`~src.knowledge.sections.validate_sections` returns 23 verdicts and
    raises for none of them, so a malformed persona costs its own section's
    ``status`` and nothing else. If it could raise, the other 22 would be lost
    with it — which is the failure task 3 exists to prevent.
    """
    repo = KnowledgeRepository(session)

    result = service.analyze_business_call(
        url=site.url,
        site_text=site.text,
        local_signals=build_local_signals(signals),
        project_id=project_id,
    )

    sections = validate_sections(result.value.model_dump())
    status = BKB_COMPLETE if all(s.ok for s in sections) else BKB_PARTIAL

    existing = repo.current(project_id)
    prompt_version = _prompt_version(service)

    # ---- L2: an unchanged fingerprint makes zero calls AND zero churn -------
    # `AIService` already answered from `ai_cache`, keyed on the content hash of
    # the site text plus the stage and prompt version -- so no `ai_calls` row was
    # written and the acceptance criterion is met the moment `from_cache` is
    # True. Superseding a BKB on top of that would still be wrong: it would burn
    # a version number and re-point every typed row for an analysis that learned
    # nothing new, and "BKB v7" would stop meaning "the seventh thing we thought".
    if result.from_cache and existing is not None and existing.prompt_version == prompt_version:
        log.info(
            "project %s: BKB v%s reused — the site fingerprint and prompt v%s are unchanged, "
            "so no model call was made",
            project_id,
            existing.version,
            prompt_version,
        )
        return BKBResult(
            bkb_id=existing.id,
            version=existing.version,
            sections=sections,
            reused=True,
            calls_made=0,
            cost_usd=0.0,
            status=existing.status,
        )

    bkb = repo.create_bkb(
        project_id,
        model=_model_name(service),
        prompt_version=prompt_version,
        status=status,
    )

    for section in sections:
        repo.upsert_section(bkb.id, section)

    _persist_typed(repo, project_id, bkb.id, sections)

    calls = 0 if result.from_cache else 1
    if result.cost_usd > COST_BUDGET_USD:
        # Loud, not fatal. See COST_BUDGET_USD.
        log.warning(
            "project %s: BKB v%s cost $%.4f, over the $%.2f budget in 34 §P14",
            project_id,
            bkb.version,
            result.cost_usd,
            COST_BUDGET_USD,
        )

    log.info(
        "project %s: BKB v%s persisted — %d/%d sections complete, %d call(s), $%.4f",
        project_id,
        bkb.version,
        sum(1 for s in sections if s.ok),
        len(BKB_SECTION_KEYS),
        calls,
        result.cost_usd,
    )

    return BKBResult(
        bkb_id=bkb.id,
        version=bkb.version,
        sections=sections,
        reused=False,
        calls_made=calls,
        cost_usd=result.cost_usd,
        status=status,
    )


# ------------------------------------------------------------------- support


def _persist_typed(
    repo: KnowledgeRepository,
    project_id: int,
    bkb_id: int,
    sections: tuple[ValidatedSection, ...],
) -> None:
    """The three sections a typed table owns.

    Their ``bkb_sections.payload_json`` is ``NULL`` and the table is
    authoritative for the content (05 §5.1b) — so this is not a second copy, it
    is *the* copy, and the section row above it carries metadata only.
    """
    by_key = {section.key: section for section in sections}
    repo.upsert_personas(project_id, bkb_id, by_key["buyer_personas"].items)
    repo.upsert_pain_points(project_id, bkb_id, by_key["pain_points"].items)
    repo.upsert_intent_signals(project_id, bkb_id, by_key["buying_signals"].items)


def _prompt_version(service: Any) -> int:
    """Which template answered. Half of the L2 cache key, and pinned on the row.

    A prompt change is a behaviour change (``src/ai/prompts.py``), so a BKB built
    under v1 must not be reused for a v2 request — which is why this is compared
    rather than assumed.
    """
    return int(service.prompts.latest_version("business_intelligence"))


def _model_name(service: Any) -> str:
    """``bkb.model`` is NOT NULL, so this never returns an empty string."""
    return getattr(getattr(service, "provider", None), "model", "") or "unknown"


__all__ = [
    "COST_BUDGET_USD",
    "MARKUP_ABSENT_KEY",
    "MARKUP_SIGNAL_KEYS",
    "BKBResult",
    "analyze",
    "build_local_signals",
]
