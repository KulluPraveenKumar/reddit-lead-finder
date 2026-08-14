"""Structural noise, and the length floor — posts that are not a person with a problem.

[34 §P9](../../docs/34-implementation-plan.md) task 2: *"Structural regex:
hiring, giveaway, megathread, AMA, promo"*. These are the cheap, high-volume
rejections [06c](../../docs/06c-local-first-pipeline.md) exists to make before
paying for anything.

**Every rejection here reports ``structural_noise`` with the pattern name in
``detail``** (operator decision **D3**). One counted reason keeps P9's vocabulary
a subset of P19's eleven; the ``detail`` keeps the measurement
[AD-10b](../../docs/ARCHITECTURE_FREEZE.md) requires.

⚠️ **The risk in this module is not missing junk. It is discarding leads.**
A structural regex that is a little too wide throws away real customers who
happen to use a common word, and **nothing in this system would ever report
it** -- there is no page showing the posts you never collected. The 2% holdout
that would measure it is P11's. Until then, every pattern here ships with a
*near-miss* fixture: a post that contains the pattern's vocabulary and must be
**admitted**.
"""

from __future__ import annotations

import re

from . import ADMITTED, STRUCTURAL_NOISE, TOO_SHORT, RuleResult, reject

#: ``(compiled pattern, detail)``. Ordered, and the order is only cosmetic --
#: the first match wins and no post is expected to hit two.
STRUCTURAL_PATTERNS: tuple[tuple[str, str], ...] = (
    # ⚠️ NO bare `\bhiring\b`. `src/discovery/triage.py` has one, and it rejects
    # "Our hiring process is broken and I need a tool to fix it" -- which is a
    # textbook lead for this product. Found while writing this module's
    # near-miss fixture; see the P9 Stage 2 report. The tag form and the
    # explicit phrases carry the recall that matters without the false positive.
    (
        r"^\s*\[\s*(?:hiring|for\s+hire)\s*\]|\bwe(?:'|’)?re hiring\b|\bnow hiring\b"
        r"|\bjob (?:opening|posting)\b",
        "hiring",
    ),
    (r"\bgiveaway\b|\bfree (?:copy|licen[sc]e|key)s?\b|\braffle\b", "giveaway"),
    (
        r"\bmegathread\b|\bweekly (?:thread|discussion)\b|\bmonthly thread\b"
        r"|\bdaily (?:thread|discussion)\b",
        "megathread",
    ),
    # `\bama\b` and not `ama` -- "Amazon" begins with the same three letters, and
    # a word boundary is the whole defence. The optional brackets sit inside the
    # anchor so "[AMA]" and "AMA:" both match while "Amazon FBA tools" does not.
    #
    # ⚠️ The bracket and the space after it are ONE optional group -- `(?:\[\s*)?`
    # and **not** `\[?\s*`. The second form has two `\s*` quantifiers separated by
    # an optional, so on a whitespace-only prefix the engine tries every way of
    # splitting that run between them: quadratic, and `re` has no timeout, so a
    # long enough title wedges the worker rather than raising. Measured
    # 2026-08-14 on the old form -- 2,000 spaces 0.031s, 4,000 spaces 0.063s,
    # 8,000 spaces 0.266s (doubling the input quadrupled the time), and a
    # 100,000-space title burned **67.8 seconds** of CPU inside `evaluate`.
    # Post titles are attacker-supplied. Found by the A5 property test in P9
    # Stage 5, on its first run.
    (r"^\s*(?:\[\s*)?ama\b\s*\]?|\bask me anything\b", "ama"),
    (
        r"\bpromo(?:tional)? code\b|\bdiscount code\b|\buse code\s+\w+"
        r"|\baffiliate link\b|\bupvote (?:this )?if\b",
        "promo",
    ),
)

_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), detail) for pattern, detail in STRUCTURAL_PATTERNS
)

#: The pattern names, so a test can assert the set rather than a string literal.
DETAILS = frozenset(detail for _, detail in STRUCTURAL_PATTERNS)


def check_structural(title: str) -> RuleResult:
    """Judge a title's *shape*. Never raises: a missing title is not an exception.

    Applied to the **title**, which is all
    [28 §3](../../docs/28-discovery-redesign.md)'s metadata stage has. A body
    would only add false positives here -- a comment quoting a megathread
    announcement is not a megathread.
    """
    text = title or ""
    for pattern, detail in _COMPILED:
        if pattern.search(text):
            return reject(STRUCTURAL_NOISE, detail=detail)
    return ADMITTED


def is_too_short(text: str, min_chars: int) -> bool:
    """``True`` when ``text`` is too short to be worth analysing.

    ⚠️ **Text-agnostic on purpose, and nothing binds it to a body in P9.**
    [06b](../../docs/06b-deepseek-optimization.md) specifies ``min_chars: 80``
    inside a prefilter that runs immediately before an AI call -- i.e. after a
    body has been fetched -- and
    [06c §3.2](../../docs/06c-local-first-pipeline.md) writes it
    ``len(text) < min_chars``. **P9's rules see titles and authors only**; the
    body arrives with P11's comment and full-scoring work, and P11 is what binds
    this predicate to it.

    Shipping the predicate now rather than deferring it costs four lines and
    makes ``rules.min_chars`` -- which is in P9's Config row -- mean something.
    Operator decision **D2**: four predicates implemented, three production-wired.

    ``None`` and ``""`` are short, not errors.
    """
    return len(text or "") < min_chars


def check_length(text: str, min_chars: int) -> RuleResult:
    """:func:`is_too_short` as a :class:`RuleResult`, for uniformity at call sites."""
    if is_too_short(text, min_chars):
        return reject(TOO_SHORT, detail=f"{len(text or '')} < {min_chars}")
    return ADMITTED
