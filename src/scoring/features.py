"""Features — the arithmetic half of the pre-score. Every function returns 0.0–1.0.

[06c §2](../../docs/06c-local-first-pipeline.md) puts four things here by name:
*"Age / recency calculation — ``datetime`` arithmetic"*, *"Upvote / comment
scoring — arithmetic"*, and by extension the two shape signals
[06c §3.1](../../docs/06c-local-first-pipeline.md) names inline,
``length_plausibility`` and ``QUESTION_RE``.

**Every function here returns a value in [0.0, 1.0], and that is load-bearing
rather than tidy.** :func:`~src.scoring.prescore.prescore` computes
``100 * sum(w[k] * v[k])`` over weights that normalise to 1.0, so the 0–100 bound
[34 §P11](../../docs/34-implementation-plan.md) asserts holds **only** if no
component can exceed 1.0. ``test_every_feature_is_bounded_in_the_unit_interval``
drives each one with empty, zero, negative, enormous and malformed input and
asserts the range, rather than trusting six separate ``min()`` calls to all be
right.

**Nothing here reads a project, a database or a model.** These are pure
functions of an item's own metadata, which is what makes the pre-score
re-runnable at zero cost and what keeps this module inside R3's fence.
"""

from __future__ import annotations

import datetime
import math
import re
from collections.abc import Mapping, Sequence

#: A title that asks something. [06c §3.1](../../docs/06c-local-first-pipeline.md)
#: names ``QUESTION_RE`` and does not define it, so it is defined here to the
#: narrowest thing that sentence can mean.
#:
#: Two forms, because either alone is wrong on real Reddit titles: an explicit
#: ``?``, **or** an interrogative opener. *"Looking for a CRM recommendation"* is
#: not a question and does not match; *"Any recommendations for a CRM"* is one
#: without punctuation and does. Anchored at the start for the opener form so
#: that *"I know how to do this"* does not match on the ``how``.
QUESTION_RE = re.compile(
    r"\?|^\s*(?:who|what|when|where|why|how|which|is|are|does|do|did|can|could|"
    r"should|would|will|has|have|any|anyone|anybody|looking\s+for\s+advice)\b",
    re.IGNORECASE,
)

#: Below this many characters an item is not worth analysing, and the length
#: component is 0.0. ``rules.min_chars`` (80) is the operator-facing dial and is
#: passed in; this is only the floor for the *shape* of the curve when it is not.
DEFAULT_MIN_CHARS = 80

#: Where the length component saturates. Past this, more text is not more signal
#: — a 6,000-character post is not four times the lead a 1,500-character one is.
#: 1,500 is chosen against measured data rather than felt: the live database's
#: leads have a **mean of 1,333 and a median of 1,060** characters
#: ([PHASE-10-COMPLETION-REPORT §3](../../docs/PHASE-10-COMPLETION-REPORT.md),
#: measured over the real corpus while correcting the A5 benchmark), so the knee
#: sits just above the typical real lead and the tail flattens rather than
#: rewarding length for its own sake.
LENGTH_SATURATION_CHARS = 1_500

#: Engagement saturation. ``src/scoring/legacy.py`` clamps upvotes at **100** and
#: comments at **50**, and those two numbers have governed every one of the 459
#: original leads. Reused rather than re-picked so the pre-score and the legacy
#: ``intent_score`` agree about what "a lot of engagement" means.
UPVOTE_SATURATION = 100
COMMENT_SATURATION = 50


def tier_value(hits: Mapping[str, Sequence[str]], tier_order: Sequence[str], decay: float) -> float:
    """How strong the strongest matched keyword tier is, in [0, 1].

    [06c §3.1](../../docs/06c-local-first-pipeline.md) writes
    ``TIER_VALUE[item.matched_keyword_tier]`` over ``high/med/low`` and **never
    gives the three values**, so they are derived rather than invented:

    * The tiers are ranked by **the order they appear in ``keywords:``**, first
      being strongest. ``src/rules/keywords.py::match_tiers`` deliberately does
      not hard-code tier names — *"Weighting the tiers is P11's problem; naming
      them is the config's"* — and reading the order keeps that true. A third
      tier added to ``config.yaml`` works with no code change.
    * Each step down is worth ``1 / decay`` of the one above, where ``decay`` is
      ``config.yaml``'s own ``scoring.high_intent_multiplier`` (**2**). That is
      the legacy scorer's relative weighting exactly — it scores a high-intent
      hit at ``keyword_weight * high_intent_multiplier`` and a medium one at
      ``keyword_weight`` — so the pre-score agrees with the instrument that
      produced the 459 usable leads instead of quietly disagreeing with it.

    With the shipped two-tier config: ``high_intent`` -> 1.0, ``medium_intent``
    -> 0.5. No match -> 0.0.

    The **strongest** tier wins rather than the sum, because this component
    answers *"how good is the best signal"*; *"how many signals"* is
    :func:`keyword_density`'s question, and adding them here would count the same
    evidence twice.
    """
    best = 0.0
    for rank, tier in enumerate(tier_order):
        if hits.get(tier):
            best = max(best, 1.0 / (decay**rank))
    return _clamp(best)


def keyword_density(hits: Mapping[str, Sequence[str]]) -> float:
    """``min(1.0, total_hits / 3)`` — [06c §3.1](../../docs/06c-local-first-pipeline.md), literally.

    Counted across **every** tier, because the component is about how densely the
    item is talking about our subject, not about which tier it talked in — that
    is :func:`tier_value`'s question.
    """
    total = sum(len(matched) for matched in hits.values())
    return _clamp(total / 3.0)


def question_form(title: str) -> float:
    """1.0 if the title asks something, else 0.0. :data:`QUESTION_RE`."""
    return 1.0 if QUESTION_RE.search(title or "") else 0.0


def recency_decay(
    created_utc: datetime.datetime | None,
    *,
    window_days: int = 30,
    now: datetime.datetime | None = None,
) -> float:
    """Exponential decay over the run's window. 1.0 at posting, ~0.5 at half the window.

    Exponential rather than linear because the value of a lead does not fall at a
    constant rate: a thread that is two days old is nearly as actionable as a
    fresh one, and one that is twenty days old is nearly as stale as one that is
    thirty. A linear ramp gets both ends wrong.

    ⚠ **Naive UTC on both sides.** ``created_utc`` comes off Reddit already
    stripped to naive UTC on every path in this codebase, and subtracting an
    aware value would raise — the same note ``legacy.py::score_post`` carries,
    for the same reason.

    A missing timestamp returns **0.0, not 1.0**. Unknown age is not freshness,
    and defaulting it to full marks would let every item with a parse failure
    outrank real recent posts. An item *ahead* of ``now`` — clock skew, or a
    fixture — clamps to 1.0 rather than exceeding it.
    """
    if created_utc is None:
        return 0.0
    now = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    age_days = (now - created_utc).total_seconds() / 86_400.0
    if age_days <= 0:
        return 1.0
    if window_days <= 0:
        return 0.0
    # Half-life at half the window: 0.5 ** (age / (window/2)).
    return _clamp(math.pow(0.5, age_days / (window_days / 2.0)))


def engagement(score: int | None, num_comments: int | None) -> float:
    """Upvotes and comments, each saturating, averaged. **None-safe.**

    ⚠ **``None`` and ``0`` are different facts and are treated as such** — this
    is [DI13](../../docs/DEFERRED-IMPROVEMENTS.md)'s trigger firing. A search
    result carries no score in the HTML, and ``_extract_post`` reports
    ``num_comments = 0`` when the count is absent where the honest value is
    ``None``. Here, an **unknown** count contributes nothing to the average and
    is **not counted as a zero measurement**: an item with 40 upvotes and an
    unknown comment count scores on its upvotes alone rather than being halved
    for a fact nobody established.

    Both unknown returns 0.0 — there is no evidence of engagement, which is
    different from evidence of none, but the pre-score has no third value and
    0.0 is the conservative reading for a recall instrument that is about to be
    ranked against items whose numbers *are* known.
    """
    parts: list[float] = []
    if score is not None:
        parts.append(_clamp(max(0, int(score)) / UPVOTE_SATURATION))
    if num_comments is not None:
        parts.append(_clamp(max(0, int(num_comments)) / COMMENT_SATURATION))
    if not parts:
        return 0.0
    return _clamp(sum(parts) / len(parts))


def length_plausibility(length: int, *, min_chars: int = DEFAULT_MIN_CHARS) -> float:
    """0.0 below ``min_chars``, then rising to 1.0 at :data:`LENGTH_SATURATION_CHARS`.

    A hard zero below the floor rather than a gentle ramp, because
    ``rules.min_chars`` is a *rejection* threshold elsewhere in the pipeline
    (``src/rules/structural.py::check_length``) and a component that gave partial
    credit to text the rule engine would reject outright would put the two in
    open disagreement on the same page.

    ⚠ **This is the first thing in the project to bind ``rules.min_chars`` to a
    body.** ``config.yaml`` has carried the note since P9: *"80 comes from
    docs/06b, where it sits in a prefilter that runs after a body has been
    fetched — so it measures a BODY … nothing binds this key to a body until
    P11."* This is that binding, and the before/after count is recorded in the
    completion report as required.
    """
    if length < max(0, min_chars):
        return 0.0
    if min_chars >= LENGTH_SATURATION_CHARS:
        return 1.0
    span = LENGTH_SATURATION_CHARS - min_chars
    return _clamp((length - min_chars) / span)


def _clamp(value: float) -> float:
    """Into [0.0, 1.0]. NaN clamps to 0.0 rather than propagating.

    ``NaN`` fails every comparison, so a bare ``min(1.0, max(0.0, x))`` returns
    it unchanged and one malformed value would poison a whole run's ranking with
    a total that is neither high nor low but incomparable. Checked explicitly.
    """
    if value != value:  # NaN
        return 0.0
    return min(1.0, max(0.0, float(value)))


__all__ = [
    "COMMENT_SATURATION",
    "DEFAULT_MIN_CHARS",
    "LENGTH_SATURATION_CHARS",
    "QUESTION_RE",
    "UPVOTE_SATURATION",
    "engagement",
    "keyword_density",
    "length_plausibility",
    "question_form",
    "recency_decay",
    "tier_value",
]
