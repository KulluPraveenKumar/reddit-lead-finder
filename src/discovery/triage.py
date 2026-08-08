"""Stage 3 - metadata triage. Title, author and timestamp only.

[28 §3](../../docs/28-discovery-redesign.md) stage 3. **Every rejection here is
made without a body**, which is the redesign's central move and its central
risk: the funnel decides earlier, on less information, and
[AD-10b](../../docs/03-architecture.md) says an aggressive filter that is not
measured is worse than no filter at all.

So this module does one thing beyond deciding: it produces a *reason* for every
decision, and the caller stores a ``prescores`` row for rejections as well as
admissions (R11). The 2% holdout audit that re-scores a sample of these
rejections with their bodies is **P11's** -- it needs full scoring and the
``gate_audits`` table, neither of which exists yet. P6's obligation is to make
that audit possible rather than to run it.

This is a **provisional** score. It is deliberately not the nine-component
pre-score of [06c §3](../../docs/06c-local-first-pipeline.md), which is P11's
and which sees a body. Rows written here carry ``stage='metadata'`` so the two
populations are never confused.

> **File-row note.** [34 §P6](../../docs/34-implementation-plan.md)'s Files row
> does not name this module; it lists the handler, the two discovery modules and
> the repository. The Files row is documented as "a guide, not a contract"
> ([34 §1.1](../../docs/34-implementation-plan.md)) and P5 took the same
> decision for its ``feed`` CLI. Triage is put in its own file rather than
> inlined into the handler because it is pure, and a pure function is testable
> from literals while a handler needs a session and a job.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

#: Authors whose posts are never leads. ``[deleted]`` is the literal string both
#: collection paths produce for a removed account.
BOT_AUTHORS = frozenset(
    {
        "[deleted]",
        "automoderator",
        "autotldr",
        "remindmebot",
        "sneakpeekbot",
        "totesmessenger",
        "wikitextbot",
    }
)

#: Titles that are structurally not a person describing a problem. These are the
#: cheap, high-volume rejections the redesign exists to make before paying for a
#: body: hiring threads, giveaways and the weekly megathreads.
STRUCTURAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^\[hiring\]|^\[for hire\]|\bhiring\b|\bwe'?re hiring\b", "hiring"),
    (r"\bgiveaway\b|\bfree (?:copy|license|licence)s?\b", "giveaway"),
    (r"\bmegathread\b|\bweekly (?:thread|discussion)\b|\bmonthly thread\b", "megathread"),
    (r"^\[?ama\]?\b|\bask me anything\b", "ama"),
    (r"\bupvote\b.*\bif\b|\bkarma\b", "engagement_bait"),
)

_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in STRUCTURAL_PATTERNS
)

#: Rejection reasons this module can produce. Named so a test can assert the set
#: rather than a string literal, and so the funnel has a closed vocabulary.
REASONS = frozenset(
    {
        "no_title",
        "bot_author",
        "hiring",
        "giveaway",
        "megathread",
        "ama",
        "engagement_bait",
        "out_of_window",
        "negative_term",
    }
)


@dataclass(frozen=True)
class TriageConfig:
    """Tuning for :func:`triage`.

    ``window_days`` is the age beyond which a post is not worth enriching. A
    lead is a historical fact and is never expired once collected
    ([freeze §8](../../docs/ARCHITECTURE_FREEZE.md)) -- this is about what to
    *spend* on, not about what to keep.
    """

    window_days: int = 30
    keywords: tuple[str, ...] = ()
    negative_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriageResult:
    """A provisional judgement, and why."""

    decision: str  # admit | reject
    reason: str | None
    total: float
    components: dict = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.decision == "admit"


def triage(post: dict, cfg: TriageConfig, *, now: datetime.datetime | None = None) -> TriageResult:
    """Judge one post from its metadata alone.

    Never raises on a malformed post: a missing title is a rejection with a
    reason, not an exception. A poll that dies on one bad entry loses the other
    ninety-nine.
    """
    now = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    title = (post.get("title") or "").strip()
    author = (post.get("author") or "").strip().lower()

    components: dict = {}

    if not title:
        return TriageResult("reject", "no_title", 0.0, components)

    if author in BOT_AUTHORS:
        return TriageResult("reject", "bot_author", 0.0, components)

    for pattern, reason in _COMPILED:
        if pattern.search(title):
            return TriageResult("reject", reason, 0.0, components)

    created = post.get("created_utc")
    if created is not None:
        age_days = (now - created).total_seconds() / 86_400
        components["age_days"] = round(age_days, 3)
        if age_days > cfg.window_days:
            return TriageResult("reject", "out_of_window", 0.0, components)

    lowered = title.lower()
    for term in cfg.negative_terms:
        if term and term.lower() in lowered:
            components["negative_term"] = term
            return TriageResult("reject", "negative_term", 0.0, components)

    hits = [kw for kw in cfg.keywords if kw and kw.lower() in lowered]
    components["keyword_hits"] = hits

    # A provisional score, not the pre-score. It orders what stage 4 and P11
    # look at first; it is not a confidence and it never reaches a lead.
    total = float(min(len(hits), 5) * 20)
    components["title_length"] = len(title)

    return TriageResult("admit", None, total, components)
