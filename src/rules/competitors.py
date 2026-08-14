"""Competitor detection — a dictionary lookup, and the interface P15 will fill.

[06c §2](../../docs/06c-local-first-pipeline.md) is blunt about why this is not
an AI task:

    Once the business profile names competitors, finding them in a Reddit post
    is a dictionary lookup with alias and misspelling variants -- not a reasoning
    task. Asking a model to do it would be paying for ``in``.

**A competitor mention is a positive signal, not a rejection.** Nothing here
returns a :class:`~src.rules.RuleResult` and nothing is added to
``REASONS``: [06c §3.1](../../docs/06c-local-first-pipeline.md) makes
``competitor`` one of the nine pre-score *components*, and the pre-score is
**P11's**. A post naming a competitor is usually a better lead, not a worse one.

⚠️ **This module is inert in production, deliberately, until P15.** Its data
comes from the ``EntityRegistry`` that [34 §P15](../../docs/34-implementation-plan.md)
builds over ``bkb_entities`` / ``bkb_entity_aliases``, and those tables arrive in
``0007`` (**P12**). [34 §P9](../../docs/34-implementation-plan.md)'s Config row
names no competitor key, so there is nothing for a caller to construct a registry
*from* yet -- and that is the point rather than an oversight.

``tests/test_boundaries.py::test_the_competitor_registry_was_not_wired_before_p15``
fails if anyone wires it early. The failure mode being guarded is specific: a
competitor rule that quietly matches nothing looks exactly like a business with
no competitors, and nothing in this system would ever report the difference.
Deleting that test is how P15 turns this on, and it must be a deliberate act --
the same discipline [PHASE-08-HANDOVER §4 T1](../../docs/PHASE-08-HANDOVER.md)
demands for ``notify.min_confidence_alert``: *"delete that fence deliberately
when P21 ships the kind, do not discover it failing."*
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, runtime_checkable

from .keywords import normalise


@runtime_checkable
class EntityRegistry(Protocol):
    """Resolves free text to the canonical names of entities it mentions.

    ``typing.Protocol`` rather than an ABC, and **not** an import from
    ``src/knowledge/`` -- that package does not exist until P15. Structural
    typing means P15's ``EntityRegistry`` satisfies this without inheriting from
    it, and without this module ever learning that P15 happened.

    [34 §P15](../../docs/34-implementation-plan.md) specifies the real resolver
    as four tiers: exact, normalised, fuzzy (Levenshtein <=2 on tokens longer
    than five), then embedding (>=0.82). :class:`DictionaryEntityRegistry` below
    implements the **first two only**, on purpose -- see its docstring.
    """

    def resolve(self, text: str) -> list[str]:
        """Canonical names mentioned in ``text``. Empty when there are none."""
        ...


class DictionaryEntityRegistry:
    """The fallback: normalised exact matching over canonical names and aliases.

    ⚠️ **Tiers 3 and 4 -- fuzzy and embedding -- are deliberately absent.**
    [34 §P15](../../docs/34-implementation-plan.md) owns the four-tier resolver
    and its five alias generators, and building a second fuzzy matcher here would
    be work done twice that then has to be reconciled. P9's task 4 asks for a
    *"dictionary fallback"*, and a dictionary lookup is what this is.

    So a misspelling is matched **only if the operator supplied it as an alias.**
    That is a real limitation and it is stated rather than implied.

    Matching is on **token boundaries**, not substrings, which is a considered
    departure from :func:`~src.rules.keywords.check_negative_terms`. A negative
    term is operator vocabulary where over-matching merely costs a lead nobody
    wanted; an entity name is a *name*, and ``notional`` is not ``Notion``.
    """

    def __init__(self, entities: Mapping[str, Sequence[str]] | None = None) -> None:
        """``{canonical name: [aliases]}``. The canonical name matches itself."""
        self._patterns: list[tuple[re.Pattern[str], str]] = []
        for canonical, aliases in (entities or {}).items():
            for surface in (canonical, *(aliases or ())):
                needle = normalise(surface)
                if not needle:
                    continue
                # (?<!\w) / (?!\w) rather than \b: the needle is already
                # normalised, so it may begin or end with a non-word character
                # that \b would anchor against the wrong side.
                self._patterns.append(
                    (re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)"), str(canonical))
                )

    def resolve(self, text: str) -> list[str]:
        """Canonical names mentioned in ``text``, in first-registered order, deduped."""
        haystack = normalise(text or "")
        found: list[str] = []
        for pattern, canonical in self._patterns:
            if canonical not in found and pattern.search(haystack):
                found.append(canonical)
        return found


#: The registry used when a caller supplies none: it knows nothing and finds
#: nothing. Not ``None``, so callers need no null check and a missing registry
#: behaves identically to a business with no competitors recorded yet.
EMPTY_REGISTRY = DictionaryEntityRegistry()


def competitor_mentions(text: str, registry: EntityRegistry | None = None) -> list[str]:
    """Canonical competitor names mentioned in ``text``.

    The signal [06c §3.1](../../docs/06c-local-first-pipeline.md) feeds to the
    pre-score as ``"competitor": 1.0 if competitor_mentions(...) else 0.0``.
    Returning the names rather than a bool is what lets P11 explain *which*
    competitor was seen, which is the difference between a score and an
    explanation ([R7](../../docs/ARCHITECTURE_FREEZE.md)).

    Never raises. A ``None`` text and a missing registry both yield ``[]``.
    """
    return (registry or EMPTY_REGISTRY).resolve(text or "")


def mentions_any(text: str, registry: EntityRegistry | None = None) -> bool:
    """:func:`competitor_mentions` as the boolean the pre-score component wants."""
    return bool(competitor_mentions(text, registry))


def registry_from_mapping(entities: Mapping[str, Iterable[str]]) -> DictionaryEntityRegistry:
    """Build a registry from ``{canonical: aliases}``.

    A named constructor because P15 replaces the *implementation* and not the
    call sites: a caller that builds registries through this function changes by
    one line when the BKB-backed resolver arrives.
    """
    return DictionaryEntityRegistry({k: list(v) for k, v in entities.items()})
