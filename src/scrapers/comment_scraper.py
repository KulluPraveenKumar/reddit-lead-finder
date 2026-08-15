"""Comment collection — the expensive requests, spent on the best candidates first.

[34 §P11](../../docs/34-implementation-plan.md) task 3: *"``CommentScraper`` —
candidates **ordered by pre-score**, skipping below the admission floor"*, with
the acceptance line *"comment candidates ordered by pre-score; collected comments
fall **≥5%** with **no** reduction in admitted items"*.

**Why ordering is the whole mechanism.** A comment fetch is one HTTP request per
post — by far the most expensive thing in the deterministic pipeline, and the
only place in P11 that touches the network. ``scraping.max_comment_posts`` bounds
how many are made. Ordering decides *which* posts get them, so a fixed budget
buys the best evidence instead of whichever post the scraper reached first.

**The −5% is a within-run counterfactual, not a two-run A/B.** Nothing in this
codebase called ``get_post_comments`` before P11 — grepped 2026-08-15, the only
references are the client's own definition and a signature-freeze assertion in
``tests/test_get_feed.py`` — so there is **no live baseline to compare against**,
and inventing one by running the pipeline twice would measure machine state as
much as behaviour. :class:`CommentPlan` therefore records what
fetch-every-eligible-post would have cost alongside what ordering actually spent,
and the saving is the difference. That is a number computed from the same run's
own data, which is what makes it reproducible.

⚠ **This module is new and IS linted and formatted.** ``pyproject.toml``'s
``src/scrapers/*`` exemption was narrowed to name the three pre-Phase-1 scrapers
in P11, precisely so a rule written about legacy code did not silently swallow
this file. See the comment there.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.db.models import Lead
from src.db.repositories.comments import CommentRepository, CommentWrite

log = logging.getLogger(__name__)

#: [34 §P11](../../docs/34-implementation-plan.md)'s Config row, with the
#: defaults this module assumes when the block is absent — the property every
#: other settings object in this codebase documents, so a rollback by deleting
#: the block behaves identically to a rollback by flag.
DEFAULT_MAX_COMMENTS_PER_POST = 50
DEFAULT_MAX_COMMENT_POSTS = 25
DEFAULT_MIN_POST_COMMENTS = 3


@dataclass(frozen=True)
class ScrapingSettings:
    """The ``scraping:`` block, validated.

    ``max_comments_per_post`` defaults to **50**, which is
    ``RedditClient.get_post_comments``'s own ``limit`` default — cited rather
    than invented, and keeping the two equal means the config key changes
    behaviour rather than merely appearing to.

    ``min_post_comments_for_comment_fetch`` defaults to **3**: fetching a page to
    collect one or two replies spends a full request for almost no evidence.
    """

    max_comments_per_post: int = DEFAULT_MAX_COMMENTS_PER_POST
    max_comment_posts: int = DEFAULT_MAX_COMMENT_POSTS
    min_post_comments_for_comment_fetch: int = DEFAULT_MIN_POST_COMMENTS

    @classmethod
    def from_config(cls, config) -> ScrapingSettings:
        block = (config or {}).get("scraping") or {}
        return cls(
            max_comments_per_post=int(
                block.get("max_comments_per_post", DEFAULT_MAX_COMMENTS_PER_POST)
            ),
            max_comment_posts=int(block.get("max_comment_posts", DEFAULT_MAX_COMMENT_POSTS)),
            min_post_comments_for_comment_fetch=int(
                block.get("min_post_comments_for_comment_fetch", DEFAULT_MIN_POST_COMMENTS)
            ),
        )

    def __post_init__(self) -> None:
        if self.max_comments_per_post < 0:
            raise ValueError(
                f"scraping.max_comments_per_post must be >= 0, got {self.max_comments_per_post}"
            )
        if self.max_comment_posts < 0:
            raise ValueError(
                f"scraping.max_comment_posts must be >= 0 (0 switches comment "
                f"collection off), got {self.max_comment_posts}"
            )
        if self.min_post_comments_for_comment_fetch < 0:
            raise ValueError(
                f"scraping.min_post_comments_for_comment_fetch must be >= 0, "
                f"got {self.min_post_comments_for_comment_fetch}"
            )


@dataclass(frozen=True)
class Candidate:
    """One lead considered for a comment fetch, with the pre-score that ranks it."""

    lead_id: int
    url: str
    prescore: float
    num_comments: int | None
    already_stored: int = 0


@dataclass
class CommentPlan:
    """Which posts to fetch, and what the ordering saved.

    ``eligible`` is the counterfactual denominator: every post that passes the
    floor and the comment-count test, i.e. what a scraper with no budget and no
    ordering would have requested. ``selected`` is what this plan actually
    requests. The gap between them is the −5% acceptance criterion, and it is
    reported rather than asserted here — asserting a percentage inside the
    planner would make the criterion true by construction.
    """

    selected: list[Candidate] = field(default_factory=list)
    eligible: int = 0
    below_floor: int = 0
    too_few_comments: int = 0
    already_covered: int = 0
    unknown_comment_count: int = 0
    #: Columns filled by task 4's back-fill. Counted rather than assumed.
    backfilled: int = 0

    @property
    def requests(self) -> int:
        return len(self.selected)

    @property
    def saved(self) -> int:
        return max(0, self.eligible - self.requests)

    @property
    def saving_rate(self) -> float | None:
        """The measured reduction, or ``None`` when there was nothing to reduce.

        ``None`` and not ``0.0``: a run with no eligible posts has not
        demonstrated a 0% saving, it has demonstrated nothing, and the run page
        renders a blank rather than a zero for exactly this reason.
        """
        if self.eligible <= 0:
            return None
        return self.saved / self.eligible

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "requests": self.requests,
            "saved": self.saved,
            "saving_rate": None if self.saving_rate is None else round(self.saving_rate, 4),
            "below_floor": self.below_floor,
            "too_few_comments": self.too_few_comments,
            "already_covered": self.already_covered,
            "unknown_comment_count": self.unknown_comment_count,
            "backfilled": self.backfilled,
        }


def plan_fetches(
    candidates: Sequence[Candidate],
    settings: ScrapingSettings,
    *,
    admission_floor: float,
) -> CommentPlan:
    """Rank by pre-score, drop what is not worth a request, take the budget.

    The order of the three exclusions matters and is cheapest-first, which is
    also the order that reports most usefully:

    1. **Below the admission floor.** An item the gate will not admit is not
       worth a request, whatever its comment count —
       [34 §P11](../../docs/34-implementation-plan.md) task 3 says *"skipping
       below the admission floor"*.
    2. **Too few comments.** ``min_post_comments_for_comment_fetch``.
    3. **Already covered.** A re-run must not re-request a page whose comments
       are already stored; the savepoint skip would discard the rows anyway, and
       the request would already have been spent.

    ⚠ **``num_comments is None`` is treated as eligible, not as zero** —
    [DI13](../../docs/DEFERRED-IMPROVEMENTS.md)'s trigger, firing exactly where
    the register predicted: *"a consumer treats ``0`` as 'nobody commented' and
    acts on it — most likely the comment-fetch eligibility test in P11, which is
    where the distinction first has a decision hanging off it."*

    An unknown count must not be read as "no comments", because that would make
    every search-sourced lead permanently ineligible for the one enrichment step
    that costs nothing but a request. It is counted separately
    (``unknown_comment_count``) so the share is visible rather than assumed, and
    it is ranked by pre-score like everything else — the budget still bounds the
    cost, so the worst case of admitting an unknown is one wasted request on a
    high-scoring post, against the alternative of never fetching comments for a
    whole collection channel.
    """
    plan = CommentPlan()
    eligible: list[Candidate] = []

    for candidate in candidates:
        if candidate.prescore < admission_floor:
            plan.below_floor += 1
            continue
        if candidate.already_stored > 0:
            plan.already_covered += 1
            continue
        if candidate.num_comments is None:
            plan.unknown_comment_count += 1
        elif candidate.num_comments < settings.min_post_comments_for_comment_fetch:
            plan.too_few_comments += 1
            continue
        eligible.append(candidate)

    plan.eligible = len(eligible)

    # Descending pre-score, then descending comment count, then lead id. The
    # trailing id is the tie-break that keeps selection deterministic when the
    # first two are equal — the same discipline `dedupe.choose_representative`
    # applies, and for the same reason: two identical runs must select the same
    # posts or the -5% measurement is not reproducible.
    eligible.sort(key=lambda c: (-c.prescore, -(c.num_comments or 0), c.lead_id))
    plan.selected = eligible[: settings.max_comment_posts]
    return plan


class CommentScraper:
    """Fetch and store comments for the best-scoring leads of a run.

    Constructed like ``SubredditScraper`` — client and config — so the handler's
    ``build_scraper`` seam pattern applies unchanged, and so a test replaces one
    object rather than patching a module.
    """

    def __init__(self, reddit_client, config=None) -> None:
        self.client = reddit_client
        self.config = config or {}
        self.settings = ScrapingSettings.from_config(self.config)

    def candidates_for(
        self, session: Session, lead_ids: Sequence[int], prescores: dict[int, float]
    ) -> list[Candidate]:
        """Build candidates from stored leads and this run's pre-scores.

        A lead with no pre-score is **skipped**, not defaulted to 0.0: it means
        the scoring stage did not see it, and inventing a score for it would put
        an unmeasured item into a ranking that claims to be by pre-score.
        """
        if not lead_ids:
            return []

        repo = CommentRepository(session)
        stored = repo.counts_for_leads(list(lead_ids))

        rows = (
            session.query(Lead.id, Lead.url, Lead.num_comments)
            .filter(Lead.id.in_(list(lead_ids)))
            .all()
        )
        return [
            Candidate(
                lead_id=lead_id,
                url=url,
                prescore=prescores[lead_id],
                num_comments=num_comments,
                already_stored=stored.get(lead_id, 0),
            )
            for lead_id, url, num_comments in rows
            if lead_id in prescores and url
        ]

    def run(
        self,
        session: Session,
        candidates: Sequence[Candidate],
        *,
        admission_floor: float,
    ) -> tuple[CommentPlan, CommentWrite]:
        """Plan, fetch, store. Returns the plan and the write outcome.

        **The session is committed by the caller, not here.** A comment fetch is
        a multi-second network call per post, and holding SQLite's single write
        lock across it is the defect that returned HTTP 500 when a run was
        cancelled mid-scrape in P3 — recorded in ``handlers/scrape.py`` and
        ``handlers/discover.py`` as the most expensive trap in the project. The
        rows are added inside savepoints and flushed per row; the outer commit
        happens once, after the last fetch.
        """
        plan = plan_fetches(candidates, self.settings, admission_floor=admission_floor)
        repo = CommentRepository(session)
        stored = skipped = 0

        for candidate in plan.selected:
            try:
                detail = self.client.get_post_detail(
                    candidate.url, limit=self.settings.max_comments_per_post
                )
            except Exception as exc:  # noqa: BLE001 - AD-9: fail soft on enrichment
                # AD-9, "fail soft on enrichment, loud on collection". Comments
                # are enrichment: one unreachable thread must not fail a run that
                # collected leads successfully. Logged at warning so the loss is
                # visible rather than silent.
                log.warning("comment fetch failed for lead %s: %s", candidate.lead_id, exc)
                continue

            if not detail:
                continue

            plan.backfilled += _backfill(session, candidate.lead_id, detail)

            outcome = repo.add_many(candidate.lead_id, detail.get("comments") or [])
            stored += outcome.stored
            skipped += outcome.skipped

        return plan, CommentWrite(stored=stored, skipped=skipped)


def _backfill(session: Session, lead_id: int, detail: dict) -> int:
    """Task 4 — fill a search-sourced lead's missing ``score`` from the post page.

    **Only ever fills a NULL.** A stored number is never overwritten, and that is
    the whole design rather than caution: ``leads.score`` is a fact recorded at
    collection time, and replacing it with the value the post has *now* would
    silently re-date every lead the comment stage touched — an item's score would
    change depending on whether it happened to win a comment-fetch slot, which
    makes the column incomparable across leads.

    ``num_comments`` is filled on the same rule, for the same reason and for
    DI13's: a search-sourced lead stores ``None`` there too, and an unknown that
    can be resolved cheaply should be.

    Returns how many columns it filled, so the funnel can report the back-fill
    rather than the operator having to trust it happened.
    """
    lead = session.get(Lead, lead_id)
    if lead is None:
        return 0

    filled = 0
    if lead.score is None and detail.get("score") is not None:
        lead.score = int(detail["score"])
        filled += 1
    if lead.num_comments is None and detail.get("num_comments") is not None:
        lead.num_comments = int(detail["num_comments"])
        filled += 1
    return filled


__all__ = [
    "Candidate",
    "CommentPlan",
    "CommentScraper",
    "ScrapingSettings",
    "plan_fetches",
]
