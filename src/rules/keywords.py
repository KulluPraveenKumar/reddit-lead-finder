"""Keyword tiers and negative terms — set membership and normalised substring.

[06c §2](../../docs/06c-local-first-pipeline.md) puts both here: *"Keyword
matching | substring / compiled regex"* and *"Negative-term filtering | set
membership"*, both in ``rules/keywords.py``. That is why there is no
``negatives.py`` despite [03 §2](../../docs/03-architecture.md)'s prose listing
"negatives" as a concern.

**A keyword hit is not a decision.** Tier matching returns *what matched*; the
weighting is [06c §3.1](../../docs/06c-local-first-pipeline.md)'s nine-component
pre-score, which is **P11's**. Only the negative-term check rejects.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from . import ADMITTED, NEGATIVE_TERM, RuleResult, reject

#: Anything that is not a letter, a digit or whitespace. Replaced by a space
#: rather than deleted -- see :func:`normalise`.
_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Casefold, turn punctuation into spaces, collapse runs of whitespace.

    Two properties, and the second is the one that is easy to lose:

    * ``"Foo-Bar"``, ``"foo bar"`` and ``"FOO.BAR"`` all normalise to
      ``"foo bar"``, so a negative term written either way matches either way.
      This is the *"case- and punctuation-insensitive"* half of P9's acceptance
      criterion.
    * ``"no tion"`` does **not** become ``"notion"``. Punctuation collapses to a
      **space**, and runs of whitespace collapse to **one** space -- whitespace
      is never removed. Deleting it instead would be a one-character change that
      makes every multi-word term match text that merely contains its letters in
      order, and the acceptance criterion as written does not test for it.
      Mutation M10 is exactly that change, and
      ``test_normalise_does_not_join_separate_words`` is what catches it.

    ``casefold`` rather than ``lower``: it folds ``ß`` to ``ss`` and handles
    scripts ``lower`` does not, and a negative vocabulary is operator-supplied
    text that this project has no reason to assume is ASCII.
    """
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", text.casefold())).strip()


def match_tiers(text: str, keyword_tiers: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Which keywords matched, grouped by the tier they came from.

    ``keyword_tiers`` is the parsed ``keywords:`` block -- a **mapping** of tier
    name to list of phrases, ``{"high_intent": [...], "medium_intent": [...]}``.

    .. warning::

       **It is a mapping, and iterating it yields tier names, not keywords.**
       ``src/orchestration/handlers/discover.py``'s ``_triage_config`` does
       exactly that::

           keywords = tuple(str(k) for k in (config or {}).get("keywords", []) or [])

       and so ``TriageConfig.keywords`` is ``('high_intent', 'medium_intent')``.
       Measured against the shipped ``config.yaml`` on 2026-08-13. P6's keyword
       matching therefore matches a title only if it literally contains the
       string ``high_intent``, and its provisional score is always ``0.0``.
       Nothing downstream noticed because nothing consumes that score until P11.

       That is P6's defect on a path P9 is additive to, and P9 does not fix it
       (**A-2**, and the reasoning that deferred DI13 and DI14). It is registered
       instead. ``test_match_tiers_reads_the_mapping_not_its_keys`` is the test
       that would have failed against the form above.

    The tier *names* are whatever the mapping contains. P9 does not hard-code
    ``high_intent``/``medium_intent``, and does not require a third tier:
    [06c §3.1](../../docs/06c-local-first-pipeline.md) writes ``TIER_VALUE`` over
    ``high/med/low`` while ``config.yaml`` ships two, and a module that named
    them would go stale the moment the operator added one. Weighting the tiers is
    P11's problem; naming them is the config's.
    """
    haystack = normalise(text)
    hits: dict[str, list[str]] = {}
    for tier, phrases in keyword_tiers.items():
        matched = [p for p in phrases if p and normalise(p) in haystack]
        if matched:
            hits[str(tier)] = matched
    return hits


def check_negative_terms(text: str, negative_terms: Iterable[str]) -> RuleResult:
    """Reject if the operator's negative vocabulary appears in ``text``.

    Substring on the normalised text, which is the semantics
    ``src/discovery/triage.py`` already ships (``term.lower() in lowered``) --
    deliberately, so that the two do not disagree about what a negative term
    *is* while DI23's convergence is still outstanding. A word-boundary variant
    would be a behaviour change on a live path, and P9 is additive.

    ``detail`` carries the term that fired, because *"rejected: negative_term"*
    tells an operator nothing about which word in their own vocabulary is doing
    the damage.
    """
    haystack = normalise(text)
    for term in negative_terms:
        if not term:
            continue
        needle = normalise(term)
        if needle and needle in haystack:
            return reject(NEGATIVE_TERM, detail=term)
    return ADMITTED
