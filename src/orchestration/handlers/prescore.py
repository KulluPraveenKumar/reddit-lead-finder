"""The P11 stage — score every collected item, group, count the funnel, fetch comments.

**This is not a job type.** It is a function ``handle_finalize_run`` calls, and
that is deliberate: [DI15](../../../docs/DEFERRED-IMPROVEMENTS.md) records that an
eighth job type already shipped unreconciled against
[04 §2.4](../../../docs/04-system-design.md)'s closed list of seven, and adding a
ninth to run a stage that has no independent retry semantics would deepen a debt
P11 does not own. The stage runs inside the finaliser's transaction, retries with
it, and is idempotent for the same reason the finaliser is.

**Why the finaliser and not the scrape handler.** Every quantity here is
*run*-level: the funnel's denominator, the intra-run collapse rate, and the
comment budget ``scraping.max_comment_posts``. ``handle_scrape_subreddit`` runs
**once per subreddit**, so a stage placed there would dedup within a subreddit
rather than within a run, and would spend the whole comment budget on whichever
subreddit finished first. ``finalize_run`` is the one place the run is complete
and still open.

``handle_finalize_run`` already traverses ``ANALYZING`` with the reason *"No AI
analysis runs at this stage"*, and **that stays true**:
[34 §P11](../../../docs/34-implementation-plan.md) requires ``SELECT COUNT(*)
FROM ai_calls WHERE run_id=?`` to be **0**, and nothing below can reach a model —
``src/scoring/`` and ``src/dedupe/`` are both inside R3's fence, which
``tests/test_boundaries.py`` enforces.

The order is fixed by an acceptance criterion, not by taste:

```
    1. score every collected item        -> N distinct pre-scores
    2. group with rank = the pre-score   -> representatives chosen by 06c 4.3
    3. write one prescores row per item  -> admit | reject | grouped
    4. count the funnel                  -> A2, collapse rate, reasons
    5. fetch comments, best first        -> the -5% counterfactual
```

**Scoring precedes grouping**, so a group of N genuinely yields N distinct
pre-scores ([34 §P10](../../../docs/34-implementation-plan.md)'s criterion,
transferred to P11 by [freeze §11.1](../../../docs/ARCHITECTURE_FREEZE.md)) and
so ``DedupItem.rank`` is filled — which is what restores
[06c §4.3](../../../docs/06c-local-first-pipeline.md)'s specified ordering
``(prescore.total, score, created_utc)`` without a signature change. Grouping
after scoring also keeps [06c §4.4](../../../docs/06c-local-first-pipeline.md)'s
rule intact by construction: **group for analysis, score individually** — every
member already has its own number before any group exists.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Lead, Run
from src.db.repositories.discovery import DiscoveryRepository
from src.dedupe import DedupItem, DedupSettings
from src.dedupe.groups import build_groups, persist
from src.obs.events import emit_event
from src.scoring import (
    DECISION_ADMIT,
    DECISION_GROUPED,
    DECISION_REJECT,
    SOURCE_SCRAPE,
    STAGE_FULL,
    PrescoreSettings,
    keyword_tiers_of,
)
from src.scoring.funnel import FUNNEL_EVENT, FunnelReport
from src.scoring.prescore import ScoredItem, prescore

log = logging.getLogger(__name__)


def build_comment_scraper(config: dict[str, Any]):
    """Construct the comment scraper and its transport.

    A named seam, exactly as ``handlers/scrape.py::build_scraper`` is one: this
    is the only line in this stage that opens a network client, so it is the line
    a test needs to replace and the one an operator debugging transport wants to
    find. Kept separate from ``build_scraper`` rather than reusing it, because
    that one returns a ``SubredditScraper`` and reaching through it for its
    client would make a test replace the wrong object.
    """
    from src.reddit_client import RedditClient  # noqa: PLC0415
    from src.scrapers.comment_scraper import CommentScraper  # noqa: PLC0415

    return CommentScraper(RedditClient(config), config)


def run_prescore_stage(session: Session, run_id: int, config: dict[str, Any]) -> dict[str, Any]:
    """Score, group, count and fetch. Returns the funnel payload.

    Returns ``{"skipped": "disabled"}`` when ``pipeline.prescore_enabled`` is
    false — [34 §P11](../../../docs/34-implementation-plan.md)'s Rollback row,
    *"items keep ``intent_score`` only"*. No ``prescores`` row is written, no
    group is formed and no comment request is made, so the run behaves exactly as
    it did at P10. This is the first half of the pair
    ``src.scoring.prescore.prescore`` documents; the second half is inside the
    scorer, so the rollback holds even if this check were removed.
    """
    settings = PrescoreSettings.from_config(config)
    if not settings.enabled:
        log.info("run %s: pre-score stage disabled by pipeline.prescore_enabled", run_id)
        return {"skipped": "disabled"}

    leads = _collected_leads(session, run_id)
    if not leads:
        return {"skipped": "no_leads"}

    report = FunnelReport()
    report.full.collected = len(leads)

    scores = _score_all(leads, settings, config)
    grouping = _group(leads, scores, config)
    _write_prescores(session, run_id, leads, scores, grouping, report)

    # P10's own writer, and the only one permitted: `persist` refuses a result
    # that violates DI22 (no item in two groups) rather than trusting the caller,
    # and it is what makes the guarantee an application-level invariant instead
    # of a comment. `dedup_members` has no `run_id`, so the run is reachable only
    # through `dedup_groups.run_id` -- which is exactly why the check has to
    # happen here, in the writer, and not in the schema.
    persist(
        session,
        grouping["result"],
        run_id=run_id,
        project_id=None,
        settings=DedupSettings.from_config(config),
    )

    report.grouped = grouping["grouped"]
    report.groups = grouping["groups"]

    comments = _fetch_comments(session, leads, scores, grouping, settings, config)

    payload = report.to_dict()
    payload["comments"] = comments

    emit_event(
        session,
        run_id,
        FUNNEL_EVENT,
        message=_summary(report, comments),
        **payload,
    )
    return payload


# ------------------------------------------------------------------ the items


def _collected_leads(session: Session, run_id: int) -> list[Lead]:
    """This run's leads, oldest first.

    ⚠ **``leads`` has no ``run_id``, so this is bounded by time rather than by a
    foreign key.** Every lead scraped at or after the run started belongs to it,
    which is exact under the constraint the system already enforces —
    ``RunService.active_for_project`` permits one active run at a time, so two
    runs cannot interleave writes into this window.

    Adding ``leads.run_id`` would be the direct fix and is **deliberately not
    done**: [34 §P11](../../../docs/34-implementation-plan.md)'s **DB** row is
    ``None``, [freeze §4.1](../../../docs/ARCHITECTURE_FREEZE.md) fixes the chain
    at ten revisions, and a column is a schema change that needs a §11 amendment
    with a failed measurement behind it. Recorded in the handover so a later
    phase that *does* open a revision can consider it, rather than rediscovering
    the constraint.

    ⚠ **Holdout-audit leads are excluded, and that is an A2 correctness fix
    rather than tidiness.** ``_holdout_audit`` stores its 2% sample as real
    leads with ``scraped_at`` inside this run's window, so they would otherwise
    be picked up here — and they are items stage 3 **already rejected**, stored
    *because* they were rejected and already carrying their own full-stage
    ``prescores`` row. Counting them again would put a population selected for
    being rejected into the denominator of the hard-filter rate, biasing
    **A2 upwards** by an amount that grows with the holdout rate. They remain
    real, labellable leads (06c §6.1); they are simply not stage 4's input.
    """
    run = session.get(Run, run_id)
    if run is None or run.started_at is None:
        return []
    return (
        session.query(Lead)
        .filter(Lead.scraped_at >= run.started_at, Lead.source == SOURCE_SCRAPE)
        .order_by(Lead.id)
        .all()
    )


def _score_all(
    leads: list[Lead], settings: PrescoreSettings, config: dict[str, Any]
) -> dict[int, Any]:
    """One :class:`~src.scoring.prescore.PreScore` per lead, keyed by ``leads.id``.

    ``keyword_tiers_of`` reads the ``keywords:`` block as the **mapping it is**,
    which is [DI24](../../../docs/DEFERRED-IMPROVEMENTS.md)'s fix. Before it, the
    tier list was ``('high_intent', 'medium_intent')`` — the tier *names* — and
    the keyword component of every score would have been 0.0 on every real post,
    silently, exactly as it has been in triage since P6.
    """
    tiers = keyword_tiers_of(config)
    negatives = tuple(((config or {}).get("discovery") or {}).get("negative_terms") or ())
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    return {
        lead.id: prescore(
            ScoredItem(
                title=lead.title or "",
                body=lead.body or "",
                author=lead.author,
                subreddit=lead.subreddit,
                score=lead.score,
                num_comments=lead.num_comments,
                created_utc=lead.created_utc,
                row_id=lead.id,
            ),
            settings,
            keyword_tiers=tiers,
            negative_terms=negatives,
            rules=None,
            now=now,
        )
        for lead in leads
    }


# --------------------------------------------------------------- the cascade


def _group(leads: list[Lead], scores: dict[int, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Run P10's cascade with ``rank`` filled in, and report what it collapsed.

    **This is the first call site ``src/dedupe/`` has ever had.** P10 shipped the
    library with no caller; [PHASE-10-HANDOVER §1](../../../docs/PHASE-10-HANDOVER.md)
    says so plainly, and §3.1 hands ``DedupItem.rank`` to P11.

    ⚠ **``jaccard_threshold`` is read from config and is NOT tuned here.**
    [PHASE-10-HANDOVER §4 T1](../../../docs/PHASE-10-HANDOVER.md): P10 measured
    the collapse rate **flat at 5.74% from 0.85 all the way down to 0.60**, so
    loosening finds nothing and *"do not tune ``jaccard_threshold`` to reach a
    number"*. This stage **measures** the intra-run rate and reports it; the
    threshold stays at 06c §4.2's 0.85.
    """
    settings = DedupSettings.from_config(config)
    items = [
        DedupItem(
            key=("lead", lead.id),
            title=lead.title or "",
            body=lead.body or "",
            score=lead.score,
            created_utc=lead.created_utc,
            # 06c 4.3's ordering, restored. P10 fell back to
            # (score, created_utc, row_id) because no pre-score existed.
            rank=scores[lead.id].total if lead.id in scores else None,
        )
        for lead in leads
    ]

    result = build_groups(items, settings)
    grouped_keys = {key for key in result.grouped_keys if key[0] == "lead"}
    representatives = {key for key in result.representatives if key[0] == "lead"}

    return {
        "result": result,
        "items": items,
        # A non-representative member: grouped, and resolved by reusing the
        # representative's analysis. 06c section 8's worked example counts these
        # as "resolved", never as discarded -- all members still appear as leads.
        "collapsed": {key[1] for key in grouped_keys - representatives},
        "grouped": len(grouped_keys - representatives),
        "groups": len(result.groups),
    }


# -------------------------------------------------------------- the funnel


def _write_prescores(
    session: Session,
    run_id: int,
    leads: list[Lead],
    scores: dict[int, Any],
    grouping: dict[str, Any],
    report: FunnelReport,
) -> None:
    """One ``prescores`` row per collected item, admitted or not — the AC1 criterion.

    ``prescore_exists`` guards each write, which is the idempotence R9 requires
    and what makes a re-claimed finaliser safe: a lease expiring mid-stage and
    re-running would otherwise write a second row for every item and **double
    every funnel count**, which is the failure P6's identical guard exists to
    prevent on the metadata stage.

    A **grouped** item is recorded as ``grouped`` rather than ``admit`` even
    though it passed the gate, because that is what ``prescores.gate_decision``'s
    four values mean and because the funnel must be able to say how many items
    the cascade resolved. Its ``total`` is its **own** pre-score, untouched —
    [06c §4.4](../../../docs/06c-local-first-pipeline.md), and P10's G6.
    """
    repo = DiscoveryRepository(session)
    collapsed = grouping["collapsed"]

    for lead in leads:
        result = scores[lead.id]
        if repo.prescore_exists(run_id, lead.id, stage=STAGE_FULL):
            continue

        if result.decision == DECISION_REJECT:
            decision, reason = DECISION_REJECT, result.reason
            report.full.count(result.reason or "unknown", detail=result.detail)
        elif lead.id in collapsed:
            decision, reason = DECISION_GROUPED, None
            report.full.admit()
        else:
            decision, reason = DECISION_ADMIT, None
            report.full.admit()

        repo.add_prescore(
            run_id,
            lead.id,
            total=result.total,
            components=_components_payload(result),
            gate_decision=decision,
            gate_reason=reason,
            stage=STAGE_FULL,
        )


def _components_payload(result: Any) -> dict[str, Any]:
    """What lands in ``prescores.components_json``.

    The raw component values, plus the three that did **not** run and the phase
    that supplies each. Storing the absences is the difference between a P12
    reader seeing *"``subreddit_fit`` scored 0.0"* and *"``subreddit_fit`` did not
    exist yet"* — and a row that cannot tell those apart is a row that will be
    misread, because by then the component *will* exist.
    """
    payload: dict[str, Any] = dict(result.components)
    if result.absent:
        payload["_absent"] = dict(result.absent)
    if result.detail:
        payload["_detail"] = result.detail
    return payload


# -------------------------------------------------------------- the comments


def _fetch_comments(
    session: Session,
    leads: list[Lead],
    scores: dict[int, Any],
    grouping: dict[str, Any],
    settings: PrescoreSettings,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Comments for the best-scoring admitted representatives.

    **Collapsed members are excluded, and that is a saving rather than a loss.**
    A near-duplicate thread's comments are evidence about the *same* discussion
    the representative already covers, and the group shares one analysis — so
    fetching them would spend the most expensive request in the pipeline to
    collect a second copy of what we have.

    ⚠ **The session is committed before the first fetch.** Everything above
    leaves it dirty, and SQLite has one write lock which a pending write holds
    until commit — a multi-second comment fetch under that lock is the defect
    that returned HTTP 500 when a run was cancelled mid-scrape in P3, named as
    trap T0 in three handovers and re-proved clear by P4, P5 and P6 in turn.
    """
    collapsed = grouping["collapsed"]
    admitted = [lead.id for lead in leads if scores[lead.id].admitted and lead.id not in collapsed]
    if not admitted:
        return {"eligible": 0, "requests": 0, "stored": 0, "skipped": 0}

    prescores = {lead_id: scores[lead_id].total for lead_id in admitted}

    # See the docstring: never hold the write lock across the network.
    session.commit()

    scraper = build_comment_scraper(config)
    candidates = scraper.candidates_for(session, admitted, prescores)
    plan, write = scraper.run(session, candidates, admission_floor=settings.admission_floor)

    payload = plan.to_dict()
    payload["stored"] = write.stored
    payload["skipped"] = write.skipped
    return payload


def _summary(report: FunnelReport, comments: dict[str, Any]) -> str:
    """One human sentence for the run's timeline."""
    rate = report.hard_filter_rate
    filtered = "—" if rate is None else f"{rate:.1%}"
    return (
        f"Pre-scored {report.full.collected} item(s): "
        f"{report.full.admitted} admitted, {report.full.rejected} rejected "
        f"({filtered} by hard filters), {report.grouped} grouped into "
        f"{report.groups} group(s). "
        f"{comments.get('stored', 0)} comment(s) from "
        f"{comments.get('requests', 0)} request(s)."
    )


__all__ = ["FUNNEL_EVENT", "run_prescore_stage"]
