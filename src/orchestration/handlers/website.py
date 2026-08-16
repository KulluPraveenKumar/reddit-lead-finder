"""The P14 stage — a project's website becomes its Business Knowledge Base.

**This is not a job type.** It is a function, exactly as
``handlers/prescore.py::run_prescore_stage`` is one, and for the reason that
module records: [DI15](../../../docs/DEFERRED-IMPROVEMENTS.md) says an eighth job
type already shipped unreconciled against
[04 §2.4](../../../docs/04-system-design.md)'s **closed list of seven**, P11
declined to add a ninth, and P14 declines to add a tenth. A stage with no
independent retry semantics does not need one — ``AIService`` already owns
retry, repair and the budget guard, and the write below is idempotent (R9).

It is also the shape the phase *needs*. The BKB is a **project**-level artefact,
not a run-level one: P16's `project add` will call this with no run in sight,
while a pipeline run will call it with one. So ``run_id`` is optional, and the
timeline event is emitted only when there is a timeline to emit it to —
``run_events.run_id`` is ``NOT NULL``, so a stage that assumed a run would be
unusable from the UI that P16 is about to build.

```
handle_analyze_website(session, project_id, run_id=?, config=?)
   │
   ├─ WebsiteFetcher.fetch      P13's; direct egress (R18), L1 cache, ≤7 pages
   ├─ site_signals.extract      six local signals, zero AI
   ├─ knowledge.bkb.analyze     ONE call → 23 verdicts → 23 rows
   └─ emit_event                only when run_id is not None
```

⚠️ **The 422/502 attributes on P13's exceptions are not turned into HTTP here.**
``InvalidWebsiteURL.status_code == 422`` and
``WebsiteUnreachable.status_code == 502`` exist so that **P16** can map them in
one line ([PHASE-13-HANDOVER §4 T2](../../../docs/PHASE-13-HANDOVER.md)). This
stage lets them propagate unchanged and invents no status of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Project
from src.knowledge.bkb import BKBResult, analyze
from src.obs.events import emit_event

log = logging.getLogger(__name__)

#: The ``run_events`` event this stage appends when it has a run to append to.
BKB_EVENT = "bkb.analyzed"


def build_website_fetcher(config: dict[str, Any] | None):
    """Construct P13's fetcher.

    A named seam, exactly as ``handlers/scrape.py::build_scraper`` and
    ``handlers/prescore.py::build_comment_scraper`` are: this is the only line in
    the stage that can open a network connection, so it is the line a test
    replaces and the line an operator debugging egress looks for.

    ⚠ Imported inside the function rather than at module scope so that importing
    this handler does not drag in ``trafilatura`` and the HTTP stack — the same
    reason the other two seams do it.
    """
    from src.ai.website_fetcher import WebsiteFetcher  # noqa: PLC0415

    return WebsiteFetcher(config=config or {})


def build_ai_service(config: dict[str, Any] | None):
    """Construct the one permitted path to a model (R2).

    The second seam, and the more important one: **``src/knowledge/`` may not
    import ``src.ai``** (R3), so the service is constructed *here*, outside the
    fence, and passed into :func:`~src.knowledge.bkb.analyze` as a parameter.
    """
    from src.ai.service import AIService  # noqa: PLC0415
    from src.settings import get_settings  # noqa: PLC0415

    return AIService(get_settings(config))


def handle_analyze_website(
    session: Session,
    project_id: int,
    *,
    run_id: int | None = None,
    config: dict[str, Any] | None = None,
    fetcher=None,
    service=None,
) -> dict[str, Any]:
    """Fetch the project's site, then build its BKB. Returns the event payload.

    ``fetcher`` and ``service`` are injected by tests and by P16; when omitted
    they are built from ``config`` through the two seams above. Injecting rather
    than patching is what keeps
    [35 §2.3](../../../docs/35-testing-strategy.md) check 6 — the suite makes no
    network call — a property of the design instead of a property of the mocks.

    ⚠ **Idempotent (R9), by two different mechanisms rather than one.** P13's L1
    cache makes a re-run inside the TTL fetch nothing, and
    :func:`~src.knowledge.bkb.analyze`'s L2 reuse makes it call nothing and
    supersede nothing when the fingerprint and prompt version are unchanged. A
    re-claimed lease therefore costs neither a request nor a token nor a BKB
    version.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"no project {project_id}")

    fetcher = fetcher or build_website_fetcher(config)
    service = service or build_ai_service(config)

    site = fetcher.fetch(project.website_url, session=session, project_id=project_id)

    from src.ai.site_signals import extract  # noqa: PLC0415

    signals = extract(site)

    result: BKBResult = analyze(
        session,
        project_id=project_id,
        site=site,
        signals=signals,
        service=service,
        config=config,
    )

    payload = result.to_dict()
    payload["requests"] = site.requests_made
    payload["thin"] = site.thin
    # DI33: whether the four markup signals were observable at all. Recorded on
    # the timeline because "this company uses no analytics" and "we read a cached
    # copy with no markup in it" must never look the same to a later reader.
    payload["markup_seen"] = signals.markup_seen

    if run_id is not None:
        emit_event(session, run_id, BKB_EVENT, message=_summary(project, result), **payload)
    else:
        log.info("project %s: %s", project_id, _summary(project, result))

    return payload


def _summary(project: Project, result: BKBResult) -> str:
    """One human sentence, for the run timeline and the log."""
    if result.reused:
        return (
            f"Reused BKB v{result.version} for {project.name} — "
            "the site is unchanged, so no AI call was made."
        )
    incomplete = (
        ""
        if not result.incomplete
        else f" ({len(result.incomplete)} incomplete: {', '.join(result.incomplete)})"
    )
    return (
        f"Built BKB v{result.version} for {project.name}: "
        f"{result.complete_count}/{len(result.sections)} sections complete{incomplete}, "
        f"{result.calls_made} AI call(s), ${result.cost_usd:.4f}."
    )


# ------------------------------------------------------------------- the CLI
#
# ``python -m src.orchestration.handlers.website``
#
# Every phase since P5 has shipped one so that a **non-developer can execute the
# manual guide** — P5's `feed`, P6's `triage.py`, P9's `python -m src.rules`,
# P10's `__main__.py`, P11's wiring, P13's fetcher CLI. Same basis, and
# [34 §P12](../../../docs/34-implementation-plan.md)'s note records that a file
# needed for that purpose is not scope creep.
#
# ⚠ **It lives here rather than in ``src/knowledge/__main__.py``** because it
# needs *both* sides of the R3 fence — the fetcher and the service are
# ``src.ai``, and the knowledge package may not import them. That is also why
# P10's `src/dedupe/__main__.py` could stay inside its own fence and this cannot.


def render_report(payload: dict[str, Any], *, url: str, dry_run: bool) -> str:
    """The CLI's output, as a string.

    Factored out for the reason P13's ``render_report`` was: it is the half that
    can be tested **without a network call or an API key**, which is what keeps
    [35 §2.3](../../../docs/35-testing-strategy.md) check 6 intact while still
    covering what the operator actually reads.
    """
    lines = [f"URL              {url}"]
    if dry_run:
        lines += [
            "MODE             dry run — nothing was sent to a model, nothing was written",
            f"pages fetched    {payload['pages']}",
            f"characters       {payload['chars']}",
            f"thin content     {payload['thin']}",
            f"markup observed  {payload['markup_seen']}",
            "",
            "Local signals that would be sent as FACTS:",
            payload["local_signals"],
        ]
        if not payload["markup_seen"]:
            lines += [
                "",
                "NOTE  markup_not_observed is set, so tech_markers, structured_data,",
                "      social_links and nav_taxonomy are OMITTED rather than sent empty.",
                "      An omitted signal is unobserved, never absent (DI33).",
            ]
        return "\n".join(lines)

    lines += [
        f"BKB              v{payload['version']}  (id {payload['bkb_id']})",
        f"sections         {payload['complete']}/{payload['sections']} complete",
        f"incomplete       {', '.join(payload['incomplete']) or 'none'}",
        f"AI calls         {payload['calls']}",
        f"cost             ${payload['cost_usd']:.4f}",
        f"http requests    {payload['requests']}",
        f"markup observed  {payload['markup_seen']}",
        f"reused           {payload['reused']}",
    ]
    return "\n".join(lines)


def render_stored(session: Session, project_id: int) -> str:
    """What is actually in the database for this project. **Read-only.**

    The manual guide's inspection step. It exists so a non-developer can verify
    *"all 23 sections persist"*, *"1–5 personas, 3–12 pains, 3–12 signals"* and
    *"one `ai_calls` row"* with **one command** rather than a multi-line Python
    snippet — which on Windows PowerShell is not a cosmetic difference: a bash
    heredoc pasted into PowerShell does not run, and the failure is quiet enough
    to read as a passing step.
    """
    from src.db.models import AICall  # noqa: PLC0415
    from src.db.repositories.knowledge import KnowledgeRepository  # noqa: PLC0415

    repo = KnowledgeRepository(session)
    bkb = repo.current(project_id)
    if bkb is None:
        return f"project {project_id} has no BKB yet — run without --show to build one"

    sections = repo.sections_for(bkb.id)
    incomplete = [row.section_key for row in sections if row.status != "ok"]
    calls = (
        session.query(AICall)
        .filter(AICall.stage == "business_intelligence", AICall.project_id == project_id)
        .all()
    )

    lines = [
        f"BKB version      v{bkb.version}  (id {bkb.id})   status: {bkb.status}",
        f"sections         {len(sections) - len(incomplete)}/{len(sections)} complete",
        f"incomplete       {', '.join(incomplete) or 'none'}",
        f"personas         {len(repo.personas_for(bkb.id))}   (expected 1-5)",
        f"pain points      {len(repo.pain_points_for(bkb.id))}   (expected 3-12)",
        f"buying signals   {len(repo.intent_signals_for(bkb.id))}   (expected 3-12)",
        f"ai_calls rows    {len(calls)}   (expected exactly 1)",
        f"total cost       ${sum(c.cost_usd for c in calls):.6f}   (budget $0.05)",
    ]
    for call in calls:
        lines.append(
            f"  - project={call.project_id} outcome={call.outcome} "
            f"attempt={call.attempt} cost=${call.cost_usd:.6f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exercised by hand
    """Analyse one project's website, or dry-run the inputs without a model.

    ⚠ **``--dry-run`` needs no API key and writes nothing.** It exists because
    V-1 is still deferred under [SPRINT-0 B1](../../../docs/SPRINT-0-MEASUREMENTS.md)
    — there is no ``DEEPSEEK_API_KEY`` on this host — so the manual guide needs a
    step that verifies the fetch, the signals and the DI33 flag without one.

    ⚠ **This is the only thing in the phase that reaches a live website**, and no
    test invokes it over the wire; ``render_report`` is factored out precisely so
    the output can be tested without one. Same shape as P13's CLI and its trap
    T7.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Build a project's Business Knowledge Base.")
    parser.add_argument("--project-id", type=int, help="an existing projects.id")
    parser.add_argument("--url", help="dry-run this URL instead, without touching the database")
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and report; never call a model"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="report the stored BKB and exit; read-only, no fetch, no model",
    )
    args = parser.parse_args(argv)

    if args.show:
        if args.project_id is None:
            parser.error("--show needs --project-id")
        from src.db.database import get_session  # noqa: PLC0415

        session = get_session()
        try:
            print(render_stored(session, args.project_id))
        finally:
            session.close()
        return 0

    from src.config import load_config  # noqa: PLC0415

    config = load_config()

    if args.dry_run or args.project_id is None:
        if not args.url:
            parser.error("--dry-run needs --url, and a real run needs --project-id")
        from src.ai.site_signals import extract  # noqa: PLC0415

        site = build_website_fetcher(config).fetch(args.url)
        signals = extract(site)
        from src.knowledge.bkb import build_local_signals  # noqa: PLC0415

        print(
            render_report(
                {
                    "pages": site.pages_fetched,
                    "chars": len(site.text),
                    "thin": site.thin,
                    "markup_seen": signals.markup_seen,
                    "local_signals": _json.dumps(build_local_signals(signals), indent=2),
                },
                url=args.url,
                dry_run=True,
            )
        )
        return 0

    from src.db.database import session_scope  # noqa: PLC0415

    with session_scope() as session:
        project = session.get(Project, args.project_id)
        if project is None:
            print(f"no project {args.project_id}; P16's `project add` is what creates one")
            return 2
        url = project.website_url
        payload = handle_analyze_website(session, args.project_id, config=config)

    print(render_report(payload, url=url, dry_run=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BKB_EVENT",
    "build_ai_service",
    "build_website_fetcher",
    "handle_analyze_website",
    "main",
    "render_report",
    "render_stored",
]
